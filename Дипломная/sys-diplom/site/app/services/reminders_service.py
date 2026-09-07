from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, CareEvent, Medication, Observation, Patient, PatientCheckin, PatientReminder, Reminder, ReminderEvent, User
from app.services.alerts_service import dispatch_matrix_to_linked_users, send_patient_alert_signal, user_local_now
from app.services.inbox_service import create_inbox_event
from app.services.notification_delivery import build_patient_reminder_matrix_message


def list_patient_reminders(db: Session, patient: Patient) -> list[Reminder]:
    return db.scalars(
        select(Reminder).where(Reminder.patient_id == patient.id).order_by(Reminder.time, Reminder.id)
    ).all()


def list_patient_events(db: Session, patient: Patient) -> list[CareEvent]:
    return db.scalars(
        select(CareEvent)
        .where(CareEvent.patient_id == patient.id, CareEvent.status != "completed")
        .order_by(CareEvent.scheduled_at, CareEvent.id)
    ).all()


def reminder_is_due_on(reminder: Reminder, target_date: date) -> bool:
    if reminder.repeat_type == "once":
        return reminder.created_at.date() == target_date
    if reminder.repeat_type == "weekly":
        return reminder.created_at.date().weekday() == target_date.weekday()
    return True


def get_pending_reminder_event(db: Session, reminder: Reminder, target_date: date) -> ReminderEvent | None:
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    return db.scalar(
        select(ReminderEvent)
        .where(
            ReminderEvent.reminder_id == reminder.id,
            ReminderEvent.status == "pending",
            ReminderEvent.scheduled_at >= day_start,
            ReminderEvent.scheduled_at <= day_end,
        )
        .order_by(ReminderEvent.scheduled_at.desc(), ReminderEvent.id.desc())
        .limit(1)
    )


def get_or_create_reminder_event(db: Session, reminder: Reminder, target_dt: datetime) -> ReminderEvent:
    existing = db.scalar(
        select(ReminderEvent)
        .where(
            ReminderEvent.reminder_id == reminder.id,
            ReminderEvent.scheduled_at == target_dt,
        )
        .limit(1)
    )
    if existing:
        return existing
    event = ReminderEvent(
        reminder_id=reminder.id,
        patient_id=reminder.patient_id,
        status="pending",
        scheduled_at=target_dt,
    )
    db.add(event)
    db.flush()
    return event


def recipient_users(patient: Patient, reminder: PatientReminder | None = None) -> list[User]:
    users: list[User] = []
    owner = patient.family.owner
    if reminder and reminder.recipient_mode == "user" and reminder.recipient_user:
        return [reminder.recipient_user]
    if owner:
        users.append(owner)
    for link in patient.user_links:
        if link.user and link.user not in users:
            users.append(link.user)
    for share in patient.shares:
        if share.receive_reminders and share.viewer not in users:
            users.append(share.viewer)
    return users


def send_matrix_to_recipients(patient: Patient, text: str, reminder: PatientReminder | None = None) -> list[dict]:
    from app.services import care as care_module

    results = []
    for recipient in recipient_users(patient, reminder):
        result = care_module.send_matrix_message(recipient, text)
        results.append({"email": recipient.email, **result})
    return results


def dispatch_due_patient_reminders(db: Session, now: datetime | None = None) -> list[dict]:
    now_utc = now or datetime.now(UTC)
    reminders = db.scalars(select(Reminder).join(Patient).where(Reminder.enabled.is_(True))).all()
    sent: list[dict] = []
    for reminder in reminders:
        owner = reminder.patient.family.owner
        if not owner:
            continue
        local_now = user_local_now(owner, now_utc)
        if not reminder_is_due_on(reminder, local_now.date()):
            continue
        trigger_time = datetime.combine(local_now.date(), reminder.time)
        if trigger_time.strftime("%H:%M") != local_now.strftime("%H:%M"):
            continue
        reminder_event = get_or_create_reminder_event(db, reminder, trigger_time)
        if reminder_event.status == "done":
            continue
        marker = f"{local_now.date().isoformat()} {reminder.time.strftime('%H:%M')}"
        exists = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "patient_reminder_auto",
                AuditLog.created_at >= datetime.combine(local_now.date(), time.min),
            )
        )
        if exists and (exists.details or {}).get("reminder_id") == reminder.id and (exists.details or {}).get("marker") == marker:
            continue
        text = build_patient_reminder_matrix_message(reminder.patient.name, reminder)
        create_inbox_event(db, reminder.patient, "reminder", reminder_event.id, created_at=trigger_time)
        results = dispatch_matrix_to_linked_users(reminder.patient, text)
        db.add(
            AuditLog(
                user_id=owner.id,
                action="patient_reminder_auto",
                details={"patient_id": reminder.patient_id, "reminder_id": reminder.id, "reminder_event_id": reminder_event.id, "marker": marker, "channels": results},
            )
        )
        sent.append({"reminder_id": reminder.id, "reminder_event_id": reminder_event.id, "channels": results})
    if sent:
        db.commit()
    return sent


def dispatch_due_event_reminders(db: Session, now: datetime | None = None) -> list[dict]:
    now_utc = now or datetime.now(UTC)
    items = db.scalars(select(CareEvent).join(Patient)).all()
    sent: list[dict] = []
    for event in items:
        if event.status == "completed" or event.completed_at:
            continue
        patient = event.patient
        stages: list[tuple[str, datetime]] = []
        target_time = event.snoozed_until or event.scheduled_at
        if event.remind_day_before:
            stages.append(("day_before", target_time - timedelta(days=1)))
        if event.remind_hours_before:
            stages.append(("hours_before", target_time - timedelta(hours=event.remind_hours_before)))
        for stage_name, trigger_at in stages:
            if abs((trigger_at - now_utc.replace(tzinfo=None)).total_seconds()) > 60:
                continue
            exists = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "care_event_reminder_auto",
                    AuditLog.created_at >= trigger_at - timedelta(hours=1),
                )
            )
            marker = f"{event.id}:{stage_name}:{trigger_at.isoformat()}"
            if exists and (exists.details or {}).get("marker") == marker:
                continue
            text = "\n".join(
                [
                    f"Напоминание о визите: {event.title}",
                    f"Пациент: {patient.name}",
                    f"Дата: {event.scheduled_at.strftime('%d.%m.%Y %H:%M')}",
                    f"Врач: {event.doctor or 'не указан'}",
                    f"Место: {event.place or 'не указано'}",
                ]
            )
            results = send_patient_alert_signal(db, patient, text, alert_type="missed")[0]
            db.add(
                AuditLog(
                    user_id=patient.family.owner.id if patient.family.owner else None,
                    action="care_event_reminder_auto",
                    details={"patient_id": patient.id, "event_id": event.id, "marker": marker, "channels": results},
                )
            )
            sent.append({"event_id": event.id, "stage": stage_name, "channels": results})
    if sent:
        db.commit()
    return sent


def dispatch_missed_care_alerts(db: Session, now: datetime | None = None) -> list[dict]:
    now_utc = now or datetime.now(UTC)
    sent: list[dict] = []
    patients = db.scalars(select(Patient)).all()
    for patient in patients:
        owner = patient.family.owner
        if not owner:
            continue
        local_now = user_local_now(owner, now_utc)
        if local_now.hour < settings.missed_data_check_hour:
            continue
        day_start = datetime.combine(local_now.date(), time.min)
        day_end = datetime.combine(local_now.date(), time.max)
        observation_today = db.scalar(
            select(Observation).where(
                Observation.patient_id == patient.id,
                Observation.created_at >= day_start,
                Observation.created_at <= day_end,
            )
        )
        medication_marked = db.scalar(
            select(PatientCheckin).where(
                PatientCheckin.patient_id == patient.id,
                PatientCheckin.checkin_type == "medication_taken",
                PatientCheckin.created_at >= day_start,
                PatientCheckin.created_at <= day_end,
            )
        )
        missing_types = []
        if observation_today is None:
            missing_types.append("нет показателей за сегодня")
        has_active_medications = any(med.reminder_enabled and med.is_active for med in patient.medications)
        if has_active_medications and medication_marked is None:
            missing_types.append("приём лекарств не отмечен")
        for missing_type in missing_types:
            marker = f"{patient.id}:{local_now.date().isoformat()}:{missing_type}"
            already_sent = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "patient_missed_check_auto",
                    AuditLog.created_at >= day_start,
                    AuditLog.created_at <= day_end,
                )
            )
            if already_sent and (already_sent.details or {}).get("marker") == marker:
                continue
            text = f"Пациент {patient.name}: {missing_type}"
            results = dispatch_matrix_to_linked_users(patient, text)
            checkin_type = "missed_medication" if "лекарств" in missing_type else "missed_data"
            existing_checkin = db.scalar(
                select(PatientCheckin).where(
                    PatientCheckin.patient_id == patient.id,
                    PatientCheckin.checkin_type == checkin_type,
                    PatientCheckin.created_at >= day_start,
                    PatientCheckin.created_at <= day_end,
                )
            )
            if existing_checkin is None:
                db.add(
                    PatientCheckin(
                        patient_id=patient.id,
                        user_id=owner.id,
                        checkin_type=checkin_type,
                        details={"reason": missing_type, "alert_results": results, "inbox": True},
                    )
                )
            db.add(
                AuditLog(
                    user_id=owner.id,
                    action="patient_missed_check_auto",
                    details={"patient_id": patient.id, "marker": marker, "reason": missing_type, "channels": results},
                )
            )
            sent.append({"patient_id": patient.id, "reason": missing_type, "channels": results})
    if sent:
        db.commit()
    return sent
