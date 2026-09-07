from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def log_audit_event(db: Session, action: str, user: User | None = None, details: dict | None = None) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        action=action,
        details=details or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


ACTION_LABELS = {
    "family_export": "Экспорт всей семьи",
    "family_export_api": "Экспорт всей семьи через API",
    "patient_export": "Экспорт пациента",
    "patient_export_api": "Экспорт пациента через API",
    "reminders_export": "Экспорт напоминаний",
    "backup_download": "Скачивание резервной копии",
    "backup_restore": "Восстановление из резервной копии",
    "chart_pdf_export": "Экспорт графика в PDF",
    "password_change": "Смена пароля",
    "notification_test": "Тестовое уведомление",
    "patient_notification_send": "Отправка напоминания пациенту",
    "medication_reminder_auto": "Автоматическое напоминание по лекарствам",
    "account_preferences_update": "Обновление настроек аккаунта",
    "comment_journal_export": "Экспорт журнала комментариев",
    "comment_journal_export_pdf": "Экспорт журнала комментариев в PDF",
    "patient_comment_pin": "Закрепление важной заметки",
    "patient_comment_unpin": "Снятие закрепления заметки",
    "pdf_import_review_apply": "Сохранение значений из review PDF",
    "notification_retry_processed": "Повторная доставка уведомления выполнена",
    "notification_retry_scheduled": "Повторная доставка уведомления запланирована",
    "patient_reminder_auto": "Автоматическое напоминание пациенту",
    "care_event_reminder_auto": "Автоматическое напоминание о визите",
    "patient_missed_check_auto": "Автоматическое уведомление о пропуске",
    "patient_emergency_signal": "Сигнал состояния пациента",
    "alert_settings_update": "Настройки сигналов пациента",
}


def format_duration(duration_ms: int | None) -> str:
    if not duration_ms:
        return "меньше секунды"
    seconds = duration_ms / 1000
    if seconds < 1:
        return f"{duration_ms} мс"
    return f"{seconds:.1f} сек"


def describe_audit_event(action: str, details: dict[str, Any] | None = None) -> str:
    payload = details or {}
    label = ACTION_LABELS.get(action, action.replace("_", " "))

    if action.startswith("family_export"):
        patients = payload.get("patients")
        return f"{label}: пациентов в выгрузке {patients}" if patients is not None else label
    if action.startswith("patient_export"):
        patient_id = payload.get("patient_id")
        return f"{label}: пациент #{patient_id}" if patient_id else label
    if action == "reminders_export":
        patient_id = payload.get("patient_id")
        return f"{label}: пациент #{patient_id}" if patient_id else label
    if action == "backup_download":
        patients = payload.get("patients", 0)
        size_bytes = payload.get("archive_size_bytes")
        size_label = f", размер {round(size_bytes / 1024, 1)} KB" if size_bytes else ""
        return f"{label}: семейных профилей {patients}{size_label}"
    if action == "backup_restore":
        mode = payload.get("mode", "merge")
        parts = [
            f"режим {mode}",
            f"пациентов {payload.get('patients', 0)}",
            f"показателей {payload.get('observations', 0)}",
            f"анализов {payload.get('lab_results', 0)}",
            f"лекарств {payload.get('medications', 0)}",
            f"документов {payload.get('documents', 0)}",
        ]
        return f"{label}: " + ", ".join(parts)
    if action == "chart_pdf_export":
        patient_id = payload.get("patient_id")
        chart_type = payload.get("chart_type")
        lab_test_name = payload.get("lab_test_name")
        suffix = f", показатель {lab_test_name}" if lab_test_name else ""
        return f"{label}: пациент #{patient_id}, тип {chart_type}{suffix}"
    if action == "password_change":
        return "Пароль аккаунта был обновлён"
    if action == "notification_test":
        channels = ", ".join(item.get("channel", "log") for item in payload.get("channels", [])) or "log"
        return f"Тест уведомлений: каналы {channels}"
    if action == "patient_notification_send":
        channels = ", ".join(item.get("channel", "log") for item in payload.get("channels", [])) or "log"
        return f"Напоминание пациенту #{payload.get('patient_id')}: каналы {channels}"
    if action == "medication_reminder_auto":
        return f"Автонапоминание пациенту #{payload.get('patient_id')}: {payload.get('reminder_time')}"
    if action == "account_preferences_update":
        return f"Настройки аккаунта обновлены: timezone {payload.get('timezone')}"
    if action == "comment_journal_export":
        return f"Экспорт журнала комментариев: записей {payload.get('entries', 0)}"
    if action == "comment_journal_export_pdf":
        return f"Экспорт журнала комментариев в PDF: записей {payload.get('entries', 0)}"
    if action in {"patient_comment_pin", "patient_comment_unpin"}:
        return f"{label}: пациент #{payload.get('patient_id')}, комментарий #{payload.get('comment_id')}"
    if action == "pdf_import_review_apply":
        return (
            f"Импорт из review PDF: пациент #{payload.get('patient_id')}, "
            f"показателей {payload.get('observations', 0)}, анализов {payload.get('lab_results', 0)}"
        )
    if action == "notification_retry_processed":
        return f"Повторная доставка уведомления: {payload.get('channel')} -> {payload.get('recipient_email')}"
    if action == "notification_retry_scheduled":
        return f"Повтор доставки запланирован: {payload.get('channel')} -> {payload.get('recipient_email')}"
    if action == "patient_reminder_auto":
        return f"Напоминание пациенту #{payload.get('patient_id')}: reminder #{payload.get('reminder_id')}"
    if action == "care_event_reminder_auto":
        return f"Напоминание о визите пациенту #{payload.get('patient_id')}: событие #{payload.get('event_id')}"
    if action == "patient_missed_check_auto":
        return f"Пропуск у пациента #{payload.get('patient_id')}: {payload.get('reason')}"
    if action == "patient_emergency_signal":
        return f"Сигнал состояния пациента #{payload.get('patient_id')}"
    if action == "alert_settings_update":
        return f"Настройки сигналов для пациента #{payload.get('patient_id')}"
    return label
