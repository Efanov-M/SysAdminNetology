from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CareEvent, Medication, Patient, PatientCheckin
from app.services.reminders_service import get_or_create_reminder_event, reminder_is_due_on
from app.utils import escape_ics_text, to_ics_datetime


def build_today_items(
    db: Session,
    patient: Patient,
    reminders: list,
    events: list[CareEvent],
    now: datetime | None = None,
    snooze_hours: int = 1,
) -> list[dict]:
    del patient, snooze_hours
    current = now or datetime.now()
    today = current.date()
    items: list[dict] = []

    for reminder in reminders:
        if not reminder.enabled or not reminder_is_due_on(reminder, today):
            continue
        due_at = datetime.combine(today, reminder.time)
        reminder_event = get_or_create_reminder_event(db, reminder, due_at)
        if reminder_event.status == "done":
            continue
        items.append(
            {
                "kind": "reminder",
                "id": reminder_event.id,
                "reminder_id": reminder.id,
                "title": reminder.title,
                "time_label": reminder_event.scheduled_at.strftime("%H:%M"),
                "is_overdue": reminder_event.scheduled_at < current,
            }
        )

    for event in events:
        if event.status == "completed" or event.completed_at:
            continue
        due_at = event.snoozed_until or event.scheduled_at
        if due_at.date() == today or due_at < current:
            items.append(
                {
                    "kind": "event",
                    "id": event.id,
                    "title": event.title,
                    "time_label": due_at.strftime("%H:%M"),
                    "is_overdue": due_at < current,
                }
            )

    db.flush()
    items.sort(key=lambda item: (not item["is_overdue"], item["time_label"], item["title"]))
    return items[:6]


def list_recent_checkins(db: Session, patient: Patient, limit: int = 20) -> list[PatientCheckin]:
    return db.scalars(
        select(PatientCheckin).where(PatientCheckin.patient_id == patient.id).order_by(PatientCheckin.created_at.desc(), PatientCheckin.id.desc()).limit(limit)
    ).all()


def build_simple_insights(patient: Patient, observations: list[dict], medications: list[Medication], checkins: list[PatientCheckin]) -> list[str]:
    insights: list[str] = []
    today = date.today()
    today_obs = [item for item in observations if item.get("created_at") and item["created_at"].date() == today]
    if not today_obs:
        insights.append("Нет записей за сегодня")

    bp_items = [item for item in observations if item.get("type") == "blood_pressure"][:3]
    if len(bp_items) >= 3:
        sys_values = [int(item.get("value", {}).get("sys", 0)) for item in bp_items]
        if sys_values[0] > sys_values[1] > sys_values[2]:
            insights.append("Давление повышается последние 3 дня")

    weight_items = [item for item in observations if item.get("type") == "weight"][:2]
    if len(weight_items) >= 2:
        latest_weight = float(weight_items[0].get("value", {}).get("value", 0) or 0)
        previous_weight = float(weight_items[1].get("value", {}).get("value", 0) or 0)
        weight_delta = round(latest_weight - previous_weight, 1)
        date_delta = (weight_items[0]["created_at"].date() - weight_items[1]["created_at"].date()).days
        if weight_delta >= 2 and date_delta <= 14:
            insights.append("Вес быстро увеличился. Возможна задержка жидкости")

    active_medications = [item for item in medications if item.is_active]
    if active_medications and not any(item.checkin_type == "medication_taken" and item.created_at.date() == today for item in checkins):
        insights.append("Приём лекарств сегодня ещё не отмечен")

    if not insights:
        insights.append("Сегодня всё выглядит спокойно")
    return insights[:3]


def build_care_event_ics(patient_name: str, events: list[CareEvent]) -> str:
    now = datetime.now().astimezone()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Family PHR MVP//RU"]
    for event in events:
        description_parts = [f"Пациент: {patient_name}"]
        if event.doctor:
            description_parts.append(f"Врач: {event.doctor}")
        if event.place:
            description_parts.append(f"Место: {event.place}")
        if event.comment:
            description_parts.append(f"Комментарий: {event.comment}")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:event-{event.id}@family-phr",
                f"DTSTAMP:{to_ics_datetime(now)}",
                f"DTSTART:{to_ics_datetime(event.scheduled_at.replace(tzinfo=now.tzinfo) if event.scheduled_at.tzinfo is None else event.scheduled_at)}",
                f"SUMMARY:{escape_ics_text(event.title)}",
                f"DESCRIPTION:{escape_ics_text(' | '.join(description_parts))}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
