from __future__ import annotations

import asyncio
import smtplib
from datetime import UTC, datetime, time, timedelta
from urllib.error import URLError
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import AuditLog, Medication, Patient, User
from app.services.matrix_delivery import process_matrix_bot_updates, send_matrix_message
from app.services.notification_delivery import (
    build_medication_reminder_matrix_message,
    build_medication_reminder_message,
    send_notification,
    send_single_channel,
)
from app.services.notification_queue import (
    claim_queue_item,
    list_notification_queue_items,
    record_incident,
    release_queue_processing_marker,
    remove_queue_item,
    save_queue_item,
)


def process_notification_queue(db: Session | None = None) -> list[dict]:
    now = datetime.now(UTC)
    processed = []
    for queued_item in list_notification_queue_items(limit=200):
        item_id = str(queued_item.get("id") or "").strip()
        if not item_id:
            continue
        item = claim_queue_item(item_id)
        if not item:
            continue
        next_retry_at = item.get("next_retry_at")
        try:
            if next_retry_at and datetime.fromisoformat(next_retry_at) > now:
                continue
            channel = item.get("channel", "log")
            is_stale = False
            if next_retry_at:
                try:
                    is_stale = datetime.fromisoformat(next_retry_at) < now - timedelta(minutes=15)
                except ValueError:
                    is_stale = True
            if is_stale:
                record_incident(
                    "stale_retry_item",
                    {
                        "queue_id": item.get("id"),
                        "channel": channel,
                        "recipient_email": item.get("recipient_email"),
                        "recipient_target": item.get("recipient_target"),
                        "attempts": item.get("attempts", 0),
                        "next_retry_at": next_retry_at,
                    },
                )
            result = send_single_channel(
                item.get("title", ""),
                item.get("message", ""),
                channel,
                item.get("recipient_email"),
                item.get("recipient_target"),
            )
        except (smtplib.SMTPException, OSError, URLError) as exc:
            result = {"channel": channel, "status": "failed", "error": str(exc)}
        try:
            if result.get("status") in {"sent", "prepared"}:
                remove_queue_item(item["id"])
                record_incident(
                    "retry_processed_recovered",
                    {
                        "queue_id": item.get("id"),
                        "channel": channel,
                        "recipient_email": item.get("recipient_email"),
                        "recipient_target": item.get("recipient_target"),
                        "attempts": item.get("attempts", 0),
                        "status": result.get("status"),
                    },
                )
                if db is not None:
                    db.add(
                        AuditLog(
                            user_id=None,
                            action="notification_retry_processed",
                            details={
                                "channel": channel,
                                "recipient_email": item.get("recipient_email"),
                                "recipient_target": item.get("recipient_target"),
                                "attempts": item.get("attempts", 0),
                                "status": result.get("status"),
                            },
                        )
                    )
                processed.append({**item, "result": result, "status": "processed"})
                continue
            attempts = int(item.get("attempts", 0)) + 1
            item["attempts"] = attempts
            item["error"] = result.get("error", item.get("error"))
            item["next_retry_at"] = (now + timedelta(minutes=min(5 * attempts, 60))).isoformat()
            item["status"] = "queued"
            save_queue_item(item)
            record_incident(
                "retry_rescheduled_failed_delivery",
                {
                    "queue_id": item.get("id"),
                    "channel": channel,
                    "recipient_email": item.get("recipient_email"),
                    "recipient_target": item.get("recipient_target"),
                    "attempts": attempts,
                    "error": item.get("error"),
                    "next_retry_at": item["next_retry_at"],
                },
            )
            if db is not None:
                db.add(
                    AuditLog(
                        user_id=None,
                        action="notification_retry_scheduled",
                        details={
                            "channel": channel,
                            "recipient_email": item.get("recipient_email"),
                            "recipient_target": item.get("recipient_target"),
                            "attempts": attempts,
                            "next_retry_at": item["next_retry_at"],
                            "error": item.get("error"),
                        },
                    )
                )
            processed.append({**item, "result": result, "status": "retry_scheduled"})
        finally:
            release_queue_processing_marker(item["id"])
    if db is not None and processed:
        db.commit()
    return processed


def local_now_for_user(user: User, now_utc: datetime) -> datetime:
    try:
        timezone = ZoneInfo(user.timezone or "UTC")
    except Exception:
        timezone = ZoneInfo("UTC")
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(timezone)


def is_quiet_hours(user: User, local_now: datetime) -> bool:
    start = user.quiet_hours_start
    end = user.quiet_hours_end
    if not start or not end:
        return False
    now_time = local_now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= now_time < end
    return now_time >= start or now_time < end


def dispatch_due_medication_reminders(db: Session, now: datetime | None = None) -> list[dict]:
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)

    medications = db.scalars(
        select(Medication)
        .join(Patient)
        .where(Medication.reminder_enabled.is_(True), Medication.reminder_time.is_not(None), Medication.is_active.is_(True))
    ).all()

    recent_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "medication_reminder_auto",
            AuditLog.created_at >= datetime.combine(now_utc.date(), time.min),
        )
    ).all()
    already_sent: set[tuple[int, str]] = set()
    for item in recent_logs:
        details = item.details or {}
        if details.get("patient_id") and details.get("reminder_time"):
            already_sent.add((details["patient_id"], f"{details['day']} {details['reminder_time']}"))

    grouped: dict[int, dict] = {}
    for medication in medications:
        patient = medication.patient
        user = patient.family.owner
        if not user:
            continue
        local_now = local_now_for_user(user, now_utc)
        if is_quiet_hours(user, local_now):
            continue
        reminder_time_key = medication.reminder_time.strftime("%H:%M")
        day_key = local_now.date().isoformat()
        if reminder_time_key != local_now.strftime("%H:%M"):
            continue
        if (patient.id, f"{day_key} {reminder_time_key}") in already_sent:
            continue
        grouped.setdefault(
            patient.id,
            {
                "patient": patient,
                "medications": [],
                "user_id": user.id,
                "day": day_key,
                "time": reminder_time_key,
                "timezone": user.timezone,
            },
        )
        grouped[patient.id]["medications"].append(medication)

    results = []
    for payload in grouped.values():
        title, message = build_medication_reminder_message(payload["patient"].name, payload["medications"])
        recipients: list[tuple[User, str]] = [(payload["patient"].family.owner, "owner")] if payload["patient"].family.owner else []
        for link in payload["patient"].user_links:
            recipients.append((link.user, "member"))

        for recipient, recipient_role in recipients:
            recipient_local_now = local_now_for_user(recipient, now_utc)
            if is_quiet_hours(recipient, recipient_local_now):
                continue
            result = send_notification(
                title,
                message,
                channels=recipient.notification_channels,
                recipient_email=recipient.email,
            )
            matrix_result = send_matrix_message(
                recipient,
                build_medication_reminder_matrix_message(payload["patient"].name, payload["medications"]),
            )
            result["channels"] = [*result.get("channels", []), matrix_result]
            if result.get("status") != "sent" and matrix_result.get("status") == "sent":
                result["status"] = "sent"
            audit_entry = AuditLog(
                user_id=recipient.id,
                action="medication_reminder_auto",
                details={
                    "status": result.get("status", "prepared"),
                    "channels": result.get("channels", []),
                    "patient_id": payload["patient"].id,
                    "medication_ids": [item.id for item in payload["medications"]],
                    "reminder_time": payload["time"],
                    "day": payload["day"],
                    "timezone": recipient.timezone,
                    "recipient_role": recipient_role,
                },
            )
            db.add(audit_entry)
            results.append(audit_entry.details)

    if results:
        db.commit()
    return results


async def scheduled_reminder_loop(session_factory: sessionmaker) -> None:
    interval_seconds = max(settings.reminder_scheduler_poll_seconds, 30)
    while True:
        db = session_factory()
        try:
            from app.services.care import dispatch_due_event_reminders, dispatch_due_patient_reminders, dispatch_missed_care_alerts

            dispatch_due_medication_reminders(db)
            dispatch_due_patient_reminders(db)
            dispatch_due_event_reminders(db)
            dispatch_missed_care_alerts(db)
            process_notification_queue(db)
            process_matrix_bot_updates(db)
        finally:
            db.close()
        await asyncio.sleep(interval_seconds)
