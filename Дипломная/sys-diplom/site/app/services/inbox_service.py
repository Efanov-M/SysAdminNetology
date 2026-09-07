from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertEvent, EmergencyEvent, InboxEvent, ReminderEvent, User


def create_inbox_event(db: Session, patient, source_type: str, source_id: int, created_at: datetime | None = None) -> InboxEvent:
    item = InboxEvent(
        patient_id=patient.id,
        source_type=source_type,
        source_id=source_id,
        status="new",
        created_at=created_at or datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(item)
    db.flush()
    return item


def list_relative_inbox_items(db: Session, user: User, limit: int = 30) -> list[InboxEvent]:
    patient_ids = [item.id for item in user.family.patients]
    if user.role != "owner":
        patient_ids = [link.patient_id for link in user.patient_links]
    if not patient_ids:
        return []
    items = db.scalars(
        select(InboxEvent)
        .where(
            InboxEvent.patient_id.in_(patient_ids),
            InboxEvent.status == "new",
        )
        .order_by(InboxEvent.created_at.desc(), InboxEvent.id.desc())
        .limit(limit)
    ).all()
    for item in items:
        source = None
        if item.source_type == "emergency":
            source = db.get(EmergencyEvent, item.source_id)
        elif item.source_type == "alert":
            source = db.get(AlertEvent, item.source_id)
        elif item.source_type == "reminder":
            source = db.get(ReminderEvent, item.source_id)
        item.source = source
    return items


def acknowledge_inbox_item(db: Session, user: User, item: InboxEvent, note: str | None = None) -> InboxEvent:
    item.status = "acknowledged"
    if item.source_type == "emergency":
        source = db.get(EmergencyEvent, item.source_id)
        if source:
            source.status = "acknowledged"
            source.acknowledged_at = datetime.now(UTC).replace(tzinfo=None)
            source.acknowledged_by = user.email
            source.comment = (note or "").strip() or None
            db.add(source)
    elif item.source_type == "alert":
        source = db.get(AlertEvent, item.source_id)
        if source:
            source.status = "acknowledged"
            db.add(source)
    elif item.source_type == "reminder":
        source = db.get(ReminderEvent, item.source_id)
        if source and source.status == "pending":
            source.status = "skipped"
            db.add(source)
    db.add(item)
    db.commit()
    return item


def describe_inbox_item(item: InboxEvent) -> str:
    source = getattr(item, "source", None)
    if item.source_type == "emergency":
        return f"Экстренный сигнал: {(source.message if source else 'Мне плохо')}"
    if item.source_type == "alert":
        return f"Тревожный показатель: {(source.value if source else '')}".strip()
    if item.source_type == "reminder":
        reminder_event = source
        reminder = reminder_event.reminder if reminder_event else None
        if reminder:
            return f"Напоминание: {reminder.title}"
        return "Напоминание"
    return item.source_type


def summarize_inbox_by_patient(items: list[InboxEvent]) -> list[dict]:
    grouped: dict[int, dict] = {}
    for item in items:
        bucket = grouped.setdefault(
            item.patient_id,
            {"patient": item.patient, "items": [], "latest_at": item.created_at},
        )
        bucket["items"].append(item)
        if item.created_at > bucket["latest_at"]:
            bucket["latest_at"] = item.created_at
    result = list(grouped.values())
    result.sort(key=lambda item: item["latest_at"], reverse=True)
    return result
