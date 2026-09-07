from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmergencyEvent, Patient, PatientCheckin
from app.services.alerts_service import dispatch_matrix_to_linked_users, send_patient_alert_signal
from app.services.inbox_service import create_inbox_event


def build_emergency_message(patient_name: str, status_label: str, created_at: datetime) -> str:
    return "\n".join(
        [
            f"Сигнал состояния: {status_label}",
            f"Пациент: {patient_name}",
            f"Время: {created_at.strftime('%d.%m.%Y %H:%M')}",
        ]
    )


def get_recent_emergency_event(db: Session, patient: Patient, minutes: int = 5) -> EmergencyEvent | None:
    threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
    return db.scalar(
        select(EmergencyEvent)
        .where(
            EmergencyEvent.patient_id == patient.id,
            EmergencyEvent.created_at >= threshold,
        )
        .order_by(EmergencyEvent.created_at.desc(), EmergencyEvent.id.desc())
        .limit(1)
    )


def build_emergency_notification_message(patient: Patient, message: str, created_at: datetime) -> str:
    return "\n".join(
        [
            "Экстренный сигнал",
            f"Пациент: {patient.name}",
            message,
            f"Время: {created_at.strftime('%d.%m.%Y %H:%M')}",
        ]
    )


def create_emergency_signal(db: Session, patient: Patient, message: str = "Мне плохо") -> tuple[EmergencyEvent, list[dict]]:
    created_at = datetime.now(UTC).replace(tzinfo=None)
    event = EmergencyEvent(
        patient_id=patient.id,
        type="panic",
        message=message,
        status="new",
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    create_inbox_event(db, patient, "emergency", event.id, created_at=created_at)
    notification_message = build_emergency_notification_message(patient, message, created_at)
    results = dispatch_matrix_to_linked_users(patient, notification_message)
    if not any(item.get("status") == "sent" for item in results):
        results, _ = send_patient_alert_signal(db, patient, notification_message, alert_type="general")
    db.commit()
    db.refresh(event)
    return event, results
