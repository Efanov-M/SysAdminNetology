from __future__ import annotations

import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings
from app.models import Medication, Reminder
from app.services.matrix_delivery import MatrixBotService
from app.services.notification_queue import enqueue_notification_retry, save_queue_item


def normalize_channels(channels: list[str] | None = None) -> list[str]:
    normalized = []
    for channel in channels or settings.notification_channels:
        value = channel.strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return normalized or ["log"]


def send_single_channel(
    title: str,
    message: str,
    channel: str,
    recipient_email: str | None = None,
    recipient_target: str | None = None,
) -> dict:
    if channel == "telegram" and settings.telegram_bot_token and settings.telegram_chat_id:
        payload = {"chat_id": settings.telegram_chat_id, "text": f"{title}\n\n{message}"}
        request = Request(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("ok", False):
            return {"channel": "telegram", "status": "sent", "response": True}
        return {"channel": "telegram", "status": "failed", "error": "telegram api returned ok=false"}

    target_email = recipient_email or settings.notification_to_email
    if channel == "email" and settings.smtp_host and target_email and settings.notification_from_email:
        email = EmailMessage()
        email["Subject"] = title
        email["From"] = settings.notification_from_email
        email["To"] = target_email
        email.set_content(message)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(email)
        return {"channel": "email", "status": "sent", "recipient": target_email}

    if channel == "matrix":
        target = (recipient_target or settings.matrix_room_id or "").strip()
        if not target:
            return {"channel": "matrix", "status": "failed", "error": "matrix target is not configured"}
        return MatrixBotService().send_message(target, f"{title}\n\n{message}".strip())

    if channel in {"email", "telegram"}:
        return {"channel": channel, "status": "failed", "error": "channel is not configured"}
    return {"channel": "log", "status": "prepared", "message": message}


def build_blood_pressure_message(
    patient_name: str,
    sys: int,
    dia: int,
    pulse: int | None,
    created_at: datetime | None = None,
) -> str:
    return "\n".join(
        [
            f"Пациент: {patient_name}",
            f"Давление: {sys}/{dia}",
            f"Пульс: {pulse if pulse is not None else 'не указан'}",
            f"Дата: {(created_at or datetime.now()).strftime('%d.%m.%Y %H:%M')}",
        ]
    )


def build_lab_result_message(
    patient_name: str,
    test_name: str,
    value: float,
    unit: str | None,
    created_at: datetime | None = None,
    panel_name: str | None = None,
) -> str:
    lines = [f"Пациент: {patient_name}"]
    if panel_name:
        lines.append(f"Панель: {panel_name}")
    lines.extend(
        [
            f"Анализ: {test_name}",
            f"Значение: {value}{f' {unit}' if unit else ''}",
            f"Дата: {(created_at or datetime.now()).strftime('%d.%m.%Y %H:%M')}",
        ]
    )
    return "\n".join(lines)


def build_medication_created_message(
    patient_name: str,
    medication_name: str,
    dosage: str | None,
    schedule: str | None,
    instructions: str | None = None,
    created_at: datetime | None = None,
) -> str:
    lines = [f"Пациент: {patient_name}", f"Препарат: {medication_name}"]
    if dosage:
        lines.append(f"Дозировка: {dosage}")
    if schedule:
        lines.append(f"Режим: {schedule}")
    if instructions:
        lines.extend(["Как принимать:", instructions])
    lines.append(f"Дата: {(created_at or datetime.now()).strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(lines)


def build_medication_reminder_matrix_message(patient_name: str, medications: list[Medication]) -> str:
    reminder_time = next(
        (medication.reminder_time.strftime("%H:%M") for medication in medications if medication.reminder_time),
        "не указано",
    )
    lines = [
        "Напоминание Family PHR",
        f"Пациент: {patient_name}",
        f"Препарат: {', '.join(item.name for item in medications)}",
        f"Время: {reminder_time}",
    ]
    for medication in medications:
        lines.append(f"Примите лекарство: {medication.name}")
        if medication.dosage:
            lines.append(f"Дозировка: {medication.dosage}")
        instruction_text = (medication.instructions or medication.notes or "").strip()
        if instruction_text:
            lines.extend(["Как принимать:", instruction_text])
    return "\n".join(lines)


def build_patient_reminder_matrix_message(patient_name: str, reminder: Reminder) -> str:
    lines = [
        "Напоминание Family PHR",
        f"Пациент: {patient_name}",
        f"Задача: {reminder.title}",
        f"Тип: {reminder.type}",
        f"Время: {reminder.time.strftime('%H:%M')}",
    ]
    return "\n".join(lines)


def build_medication_reminder_message(patient_name: str, medications: list) -> tuple[str, str]:
    title = f"Напоминания по лекарствам: {patient_name}"
    lines = []
    for medication in medications:
        if not medication.reminder_enabled or not medication.is_active:
            continue
        time_label = medication.reminder_time.strftime("%H:%M") if medication.reminder_time else "время не указано"
        lines.append(f"Примите лекарство: {medication.name}")
        if medication.dosage:
            lines.append(f"Дозировка: {medication.dosage}")
        if medication.schedule:
            lines.append(f"Когда принимать: {medication.schedule}")
        lines.append(f"Время: {time_label}")
        instruction_text = (medication.instructions or medication.notes or "").strip()
        if instruction_text:
            lines.extend(["Как принимать:", instruction_text])
        lines.append("")
    if not lines:
        lines.append("- Нет активных ежедневных напоминаний")
    return title, "\n".join(line for line in lines if line != "" or len(lines) == 1)


def send_notification(
    title: str,
    message: str,
    channels: list[str] | None = None,
    recipient_email: str | None = None,
    recipient_target: str | None = None,
) -> dict:
    deliveries = []
    for channel in normalize_channels(channels):
        attempts = 0
        last_result = None
        while attempts <= max(settings.notification_retry_count, 0):
            attempts += 1
            try:
                last_result = send_single_channel(title, message, channel, recipient_email, recipient_target)
            except (smtplib.SMTPException, OSError, URLError) as exc:
                last_result = {"channel": channel, "status": "failed", "error": str(exc)}
            if last_result.get("status") in {"sent", "prepared"}:
                break
        if (last_result or {}).get("status") == "failed":
            backoff_minutes = min(5 * attempts, 60)
            queue_item = enqueue_notification_retry(
                title,
                message,
                channel,
                recipient_email,
                last_result.get("error", "unknown"),
                attempts,
                recipient_target=recipient_target,
            )
            queue_item["next_retry_at"] = (datetime.now(UTC) + timedelta(minutes=backoff_minutes)).isoformat()
            save_queue_item(queue_item)
            last_result = {**last_result, "queued_retry": True, "queue_id": queue_item["id"], "next_retry_at": queue_item["next_retry_at"]}
        deliveries.append({**(last_result or {"channel": channel, "status": "failed"}), "attempts": attempts})
    overall_status = "sent" if any(item["status"] == "sent" for item in deliveries) else "prepared"
    if deliveries and all(item["status"] == "failed" for item in deliveries):
        overall_status = "failed"
    return {
        "channels": deliveries,
        "status": overall_status,
        "failed_channels": [item["channel"] for item in deliveries if item["status"] == "failed"],
    }
