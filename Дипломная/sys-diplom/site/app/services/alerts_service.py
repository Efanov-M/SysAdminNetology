from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AlertEvent, AlertRule, AlertSettings, EmergencyEvent, MatrixProfile, Observation, Patient, PatientCheckin, User
from app.services.inbox_service import create_inbox_event
from app.services.notifications import send_matrix_target_message


def user_local_now(user: User, now_utc: datetime) -> datetime:
    try:
        timezone = ZoneInfo(user.timezone or "UTC")
    except Exception:
        timezone = ZoneInfo("UTC")
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(timezone)


def is_in_quiet_hours(start: time | None, end: time | None, current: time) -> bool:
    if not start or not end:
        return False
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def linked_matrix_users(patient: Patient) -> list[User]:
    users: list[User] = []
    for family_user in patient.family.users:
        profile = getattr(family_user, "matrix_profile", None)
        if profile and profile.is_linked and profile.matrix_user_id:
            users.append(family_user)
    return users


def dispatch_matrix_to_linked_users(patient: Patient, text: str) -> list[dict]:
    from app.services import care as care_module

    results: list[dict] = []
    for recipient in linked_matrix_users(patient):
        result = care_module.send_matrix_message(recipient, text)
        results.append({"user_id": recipient.id, "email": recipient.email, **result})
    return results


def rule_owner_local_now(patient: Patient, now_utc: datetime) -> datetime:
    owner = patient.family.owner
    if owner:
        return user_local_now(owner, now_utc)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=UTC)
    return now_utc


def normalize_rule_targets(raw_targets: list | None) -> list[str]:
    targets: list[str] = []
    for item in raw_targets or []:
        candidate = str(item or "").strip()
        if candidate and candidate not in targets:
            targets.append(candidate)
    return targets


def dispatch_alert_rule_signal(patient: Patient, rule: AlertRule, text: str, alert_type: str) -> list[dict]:
    local_now = rule_owner_local_now(patient, datetime.now(UTC))
    if is_in_quiet_hours(rule.quiet_hours_start, rule.quiet_hours_end, local_now.time()):
        return [{"patient_id": patient.id, "rule_id": rule.id, "alert_type": alert_type, "status": "skipped", "reason": "quiet_hours"}]

    targets = normalize_rule_targets(rule.escalation_targets)
    if not targets:
        results = dispatch_matrix_to_linked_users(patient, text)
        for item in results:
            item["rule_id"] = rule.id
            item["alert_type"] = alert_type
        return results

    results: list[dict] = []
    for target in targets:
        result = send_matrix_target_message(target, text)
        results.append({"patient_id": patient.id, "rule_id": rule.id, "alert_type": alert_type, "target": target, **result})
    return results


def list_patient_alert_rules(db: Session, patient: Patient) -> list[AlertRule]:
    return db.scalars(
        select(AlertRule).where(AlertRule.patient_id == patient.id).order_by(AlertRule.type, AlertRule.id)
    ).all()


def get_or_create_alert_rule(db: Session, patient: Patient, rule_type: str) -> AlertRule:
    rule = db.scalar(
        select(AlertRule).where(AlertRule.patient_id == patient.id, AlertRule.type == rule_type).limit(1)
    )
    if rule:
        return rule
    rule = AlertRule(patient_id=patient.id, type=rule_type, enabled=False)
    db.add(rule)
    db.flush()
    return rule


def categorize_extra_recipients(setting: AlertSettings, alert_type: str) -> list[str]:
    direct_targets = []
    fallback_targets = []
    for raw_item in setting.extra_recipients or []:
        candidate = (raw_item or "").strip()
        if not candidate:
            continue
        if ":" not in candidate:
            fallback_targets.append(candidate)
            continue
        prefix, value = candidate.split(":", 1)
        prefix = prefix.strip().lower()
        value = value.strip()
        if not value:
            continue
        if prefix in {alert_type, "all", "default", "general"}:
            direct_targets.append(value)
    return direct_targets or fallback_targets


def alert_targets_for_type(setting: AlertSettings, alert_type: str) -> list[str]:
    targets: list[str] = []
    for item in [setting.matrix_room_id, setting.matrix_user_id, *categorize_extra_recipients(setting, alert_type)]:
        candidate = (item or "").strip()
        if candidate and candidate not in targets:
            targets.append(candidate)
    return targets


def list_user_alert_settings(db: Session, user: User) -> list[AlertSettings]:
    return db.scalars(
        select(AlertSettings)
        .where(AlertSettings.user_id == user.id)
        .order_by(AlertSettings.patient_id, AlertSettings.id)
    ).all()


def get_or_create_alert_settings(db: Session, user: User, patient: Patient) -> AlertSettings:
    setting = db.scalar(
        select(AlertSettings).where(
            AlertSettings.user_id == user.id,
            AlertSettings.patient_id == patient.id,
        )
    )
    if setting:
        return setting
    setting = AlertSettings(user_id=user.id, patient_id=patient.id, enabled=False)
    db.add(setting)
    db.flush()
    return setting


def get_recent_bad_signal(db: Session, patient: Patient, minutes: int = 5) -> PatientCheckin | None:
    threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
    return db.scalar(
        select(PatientCheckin)
        .where(
            PatientCheckin.patient_id == patient.id,
            PatientCheckin.checkin_type == "feeling_bad",
            PatientCheckin.created_at >= threshold,
        )
        .order_by(PatientCheckin.created_at.desc(), PatientCheckin.id.desc())
        .limit(1)
    )


def send_patient_alert_signal(db: Session, patient: Patient, text: str, alert_type: str = "general") -> tuple[list[dict], bool]:
    linked_results = dispatch_matrix_to_linked_users(patient, text)
    if linked_results:
        return linked_results, True
    settings_items = db.scalars(
        select(AlertSettings)
        .where(AlertSettings.patient_id == patient.id, AlertSettings.enabled.is_(True))
        .order_by(AlertSettings.id.asc())
    ).all()

    results: list[dict] = []
    for item in settings_items:
        targets = alert_targets_for_type(item, alert_type)
        if not targets:
            continue
        local_now = user_local_now(item.user, datetime.now(UTC))
        if is_in_quiet_hours(item.quiet_hours_start, item.quiet_hours_end, local_now.time()):
            results.append(
                {
                    "user_id": item.user_id,
                    "patient_id": item.patient_id,
                    "status": "skipped",
                    "reason": "quiet_hours",
                    "alert_type": alert_type,
                }
            )
            continue
        for target in targets:
            result = send_matrix_target_message(target, text)
            results.append(
                {
                    "user_id": item.user_id,
                    "patient_id": item.patient_id,
                    "target": target,
                    "alert_type": alert_type,
                    **result,
                }
            )
    return results, bool(results)


def build_threshold_alert_message(patient_name: str, alert_type: str, value_label: str, created_at: datetime) -> str:
    return "\n".join(
        [
            f"Тревожный показатель: {alert_type}",
            f"Пациент: {patient_name}",
            value_label,
            f"Время: {created_at.strftime('%d.%m.%Y %H:%M')}",
        ]
    )


def check_threshold_alerts(db: Session, patient: Patient, observation_type: str, value: dict, created_at: datetime) -> list[dict]:
    rules = [item for item in patient.alert_rules if item.enabled]
    if observation_type == "blood_pressure":
        sys_value = int(value.get("sys") or 0)
        dia_value = int(value.get("dia") or 0)
        matched_rule = next(
            (
                item
                for item in rules
                if item.type == "blood_pressure"
                and (
                    sys_value >= (item.systolic_max or settings.blood_pressure_sys_alert_threshold)
                    or dia_value >= (item.diastolic_max or settings.blood_pressure_dia_alert_threshold)
                )
            ),
            None,
        )
        if matched_rule:
            message = build_threshold_alert_message(
                patient.name,
                "Высокое давление",
                f"Давление: {sys_value}/{dia_value}",
                created_at,
            )
            alert_event = AlertEvent(
                patient_id=patient.id,
                rule_id=matched_rule.id,
                value=f"{sys_value}/{dia_value}",
                message=message,
                status="new",
                created_at=created_at,
            )
            db.add(alert_event)
            db.flush()
            create_inbox_event(db, patient, "alert", alert_event.id, created_at=created_at)
            results = dispatch_alert_rule_signal(patient, matched_rule, message, "blood_pressure")
            db.commit()
            return results
    if observation_type == "blood_sugar":
        sugar = float(value.get("value") or 0)
        matched_rule = next(
            (
                item
                for item in rules
                if item.type == "glucose"
                and sugar >= (item.glucose_max or settings.blood_sugar_alert_threshold)
            ),
            None,
        )
        if matched_rule:
            message = build_threshold_alert_message(
                patient.name,
                "Высокий сахар",
                f"Сахар: {sugar} {value.get('unit') or 'ммоль/л'}",
                created_at,
            )
            alert_event = AlertEvent(
                patient_id=patient.id,
                rule_id=matched_rule.id,
                value=f"{sugar} {value.get('unit') or 'ммоль/л'}",
                message=message,
                status="new",
                created_at=created_at,
            )
            db.add(alert_event)
            db.flush()
            create_inbox_event(db, patient, "alert", alert_event.id, created_at=created_at)
            results = dispatch_alert_rule_signal(patient, matched_rule, message, "glucose")
            db.commit()
            return results
    return []
