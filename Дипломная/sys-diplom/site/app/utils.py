from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.config import settings

ALLOWED_IMPORT_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
DOCUMENT_PROCESSING_STATUSES = ("uploaded", "processed", "parsed", "failed")
DOCTOR_TYPE_OPTIONS = ("therapist", "cardiologist", "neurologist", "endocrinologist", "other")
DOCTOR_TYPE_LABELS = {
    "therapist": "Терапевт",
    "cardiologist": "Кардиолог",
    "neurologist": "Невролог",
    "endocrinologist": "Эндокринолог",
    "other": "Другой врач",
}


def save_upload_file(file: UploadFile, patient_id: int) -> tuple[str, str]:
    original_name = file.filename or "document.pdf"
    content = file.file.read()
    stored_path = save_pdf_bytes(original_name, content, patient_id)
    return stored_path, original_name


def save_pdf_bytes(original_name: str, content: bytes, patient_id: int) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_IMPORT_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Можно загружать PDF, JPG и PNG")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Файл слишком большой. Максимум {settings.max_upload_mb} МБ",
        )

    patient_dir = settings.upload_path / str(patient_id)
    patient_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{suffix}"
    stored_path = patient_dir / filename
    stored_path.write_bytes(content)
    return str(Path(settings.upload_dir) / str(patient_id) / filename)


def save_import_source_bytes(original_name: str, content: bytes, patient_id: int) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_IMPORT_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для импорта подходят PDF, JPG и PNG")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Файл слишком большой. Максимум {settings.max_upload_mb} МБ",
        )

    patient_dir = settings.upload_path / str(patient_id)
    patient_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{suffix}"
    stored_path = patient_dir / filename
    stored_path.write_bytes(content)
    return str(Path(settings.upload_dir) / str(patient_id) / filename)


def delete_upload_file(relative_path: str) -> None:
    file_path = settings.upload_path.parent / relative_path
    if file_path.exists():
        file_path.unlink()


def to_ics_datetime(dt: datetime) -> str:
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def escape_ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def build_medication_reminder_ics(patient_name: str, medications: list) -> str:
    now = datetime.now().astimezone()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Family PHR MVP//RU"]

    for medication in medications:
        if not medication.is_active or not medication.reminder_enabled or not medication.reminder_time:
            continue

        start_local = datetime.combine(now.date(), medication.reminder_time, tzinfo=now.tzinfo)
        if start_local <= now:
            start_local = start_local + timedelta(days=1)

        title = f"Лекарство: {medication.name}"
        description_parts = [f"Пациент: {patient_name}"]
        if medication.dosage:
            description_parts.append(f"Дозировка: {medication.dosage}")
        if medication.schedule:
            description_parts.append(f"Как принимать: {medication.schedule}")
        if medication.instructions:
            description_parts.append(f"Инструкция: {medication.instructions}")
        if medication.notes:
            description_parts.append(f"Заметки: {medication.notes}")

        uid = f"medication-{medication.id}@family-phr"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{to_ics_datetime(now)}",
                f"DTSTART:{to_ics_datetime(start_local)}",
                "RRULE:FREQ=DAILY",
                f"SUMMARY:{escape_ics_text(title)}",
                f"DESCRIPTION:{escape_ics_text(' | '.join(description_parts))}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
