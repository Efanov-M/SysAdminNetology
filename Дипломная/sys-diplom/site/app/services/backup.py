from __future__ import annotations

import json
from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models import ChildMedication, Document, GrowthRecord, HealthEvent, LabResult, Medication, Observation, Patient, User, VaccineRecord
from app.services.document_processing import build_uploaded_document, cleanup_document_files
from app.utils import delete_upload_file, save_pdf_bytes


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_time(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


def _load_backup_payload(file: UploadFile) -> tuple[dict, ZipFile]:
    filename = file.filename or "backup.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужен ZIP файл резервной копии")

    try:
        content = file.file.read()
        archive = ZipFile(BytesIO(content))
    except BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл не похож на корректный ZIP") from exc

    if "family-export.json" not in archive.namelist():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В архиве нет файла family-export.json",
        )

    payload = json.loads(archive.read("family-export.json").decode("utf-8"))
    if not isinstance(payload, dict) or "patients" not in payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный формат резервной копии")

    return payload, archive


def _delete_existing_user_data(db: Session, user: User) -> None:
    patients = db.query(Patient).filter(Patient.family_id == user.family_id).all()
    for patient in patients:
        for document in patient.documents:
            for path in cleanup_document_files(document):
                delete_upload_file(path)
        db.delete(patient)
    db.flush()


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _find_existing_patient(db: Session, user: User, patient_payload: dict) -> Patient | None:
    patient_name = _normalize_text(patient_payload.get("name"))
    patient_dob = _parse_date(patient_payload.get("date_of_birth"))
    patients = db.query(Patient).filter(Patient.family_id == user.family_id).all()
    for patient in patients:
        if _normalize_text(patient.name) == patient_name and patient.date_of_birth == patient_dob:
            return patient
    return None


def build_patient_conflict_key(patient_payload: dict) -> str:
    return f"{_normalize_text(patient_payload.get('name'))}|{patient_payload.get('date_of_birth') or ''}"


def _find_existing_medication(patient: Patient, medication_payload: dict) -> Medication | None:
    med_key = (
        _normalize_text(medication_payload.get("name")),
        _normalize_text(medication_payload.get("dosage")),
        _normalize_text(medication_payload.get("schedule")),
    )
    for item in patient.medications:
        existing_key = (_normalize_text(item.name), _normalize_text(item.dosage), _normalize_text(item.schedule))
        if existing_key == med_key:
            return item
    return None


def build_medication_conflict_key(patient_payload: dict, medication_payload: dict) -> str:
    return "|".join(
        [
            build_patient_conflict_key(patient_payload),
            _normalize_text(medication_payload.get("name")),
            _normalize_text(medication_payload.get("dosage")),
            _normalize_text(medication_payload.get("schedule")),
        ]
    )


def _has_duplicate_document(patient: Patient, document_payload: dict) -> bool:
    doc_key = (
        _normalize_text(document_payload.get("original_filename")),
        _normalize_text(document_payload.get("description")),
    )
    for item in patient.documents:
        existing_key = (_normalize_text(item.original_filename), _normalize_text(item.description))
        if existing_key == doc_key:
            return True
    return False


def build_document_conflict_key(patient_payload: dict, document_payload: dict) -> str:
    return "|".join(
        [
            build_patient_conflict_key(patient_payload),
            _normalize_text(document_payload.get("original_filename")),
            _normalize_text(document_payload.get("description")),
        ]
    )


def restore_backup_archive(
    db: Session,
    user: User,
    file: UploadFile,
    mode: str = "merge",
    decisions: dict | None = None,
) -> dict:
    payload, archive = _load_backup_payload(file)
    decisions = decisions or {}
    patient_actions = decisions.get("patient_actions", {})
    medication_actions = decisions.get("medication_actions", {})
    document_actions = decisions.get("document_actions", {})
    skip_patients = set(decisions.get("skip_patients", [])) | {
        key for key, value in patient_actions.items() if value == "skip"
    }
    skip_medications = set(decisions.get("skip_medications", [])) | {
        key for key, value in medication_actions.items() if value == "skip"
    }
    skip_documents = set(decisions.get("skip_documents", [])) | {
        key for key, value in document_actions.items() if value == "skip"
    }
    if mode not in {"merge", "replace"}:
        archive.close()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Режим restore должен быть merge или replace")

    if mode == "replace":
        _delete_existing_user_data(db, user)

    restored_patients = 0
    restored_documents = 0
    restored_observations = 0
    restored_lab_results = 0
    restored_medications = 0
    merged_patients = 0
    updated_medications = 0
    skipped_documents = 0

    for patient_record in payload.get("patients", []):
        patient_payload = patient_record.get("patient", {})
        patient_key = build_patient_conflict_key(patient_payload)
        if patient_key in skip_patients:
            continue
        patient = _find_existing_patient(db, user, patient_payload) if mode == "merge" else None
        if patient:
            merged_patients += 1
        else:
            patient = Patient(
                user_id=user.id,
                family_id=user.family_id,
                created_by_user_id=user.id,
                name=patient_payload.get("name", "Пациент из резервной копии"),
                patient_type=patient_payload.get("patient_type", "elderly"),
                date_of_birth=_parse_date(patient_payload.get("date_of_birth")),
                notes=patient_payload.get("notes"),
                created_at=_parse_datetime(patient_payload.get("created_at")) or datetime.now(),
            )
            db.add(patient)
            db.flush()
            restored_patients += 1

        emergency_payload = patient_record.get("emergency_info") or {}
        if emergency_payload:
            patient.blood_type = emergency_payload.get("blood_type")
            patient.allergies = emergency_payload.get("allergies")
            patient.chronic_diseases = emergency_payload.get("diagnoses")
            patient.permanent_medications = emergency_payload.get("permanent_medications")
            patient.emergency_contacts = emergency_payload.get("emergency_contacts")

        for observation_payload in patient_record.get("observations", []):
            if observation_payload.get("type") == "lab_result":
                continue
            observation = Observation(
                patient_id=patient.id,
                type=observation_payload.get("type", "unknown"),
                value=observation_payload.get("value", {}),
                created_at=_parse_datetime(observation_payload.get("created_at")) or datetime.now(),
            )
            db.add(observation)
            restored_observations += 1

        for lab_payload in patient_record.get("lab_results", []):
            value = lab_payload.get("value", {})
            db.add(
                LabResult(
                    patient_id=patient.id,
                    panel_name=value.get("panel_name"),
                    test_name=value.get("test_name", "Анализ"),
                    value=float(value.get("value", 0)),
                    unit=value.get("unit"),
                    reference_low=value.get("reference_low"),
                    reference_high=value.get("reference_high"),
                    reference_text=value.get("reference_text"),
                    created_at=_parse_datetime(lab_payload.get("created_at")) or datetime.now(),
                )
            )
            restored_lab_results += 1

        for observation_payload in patient_record.get("observations", []):
            if observation_payload.get("type") != "lab_result":
                continue
            value = observation_payload.get("value", {})
            db.add(
                LabResult(
                    patient_id=patient.id,
                    panel_name=value.get("panel"),
                    test_name=value.get("test_name", "Анализ"),
                    value=float(value.get("value", 0)),
                    unit=value.get("unit"),
                    created_at=_parse_datetime(observation_payload.get("created_at")) or datetime.now(),
                )
            )
            restored_lab_results += 1

        for medication_payload in patient_record.get("medications", []):
            medication_key = build_medication_conflict_key(patient_payload, medication_payload)
            if medication_key in skip_medications:
                continue
            existing_medication = _find_existing_medication(patient, medication_payload) if mode == "merge" else None
            if existing_medication:
                existing_medication.dosage = medication_payload.get("dosage", existing_medication.dosage)
                existing_medication.schedule = medication_payload.get("schedule", existing_medication.schedule)
                existing_medication.instructions = medication_payload.get("instructions", existing_medication.instructions)
                existing_medication.start_date = _parse_date(medication_payload.get("start_date"))
                existing_medication.end_date = _parse_date(medication_payload.get("end_date"))
                existing_medication.is_active = bool(medication_payload.get("is_active", existing_medication.is_active))
                existing_medication.notes = medication_payload.get("notes")
                existing_medication.reminder_enabled = bool(
                    medication_payload.get("reminder_enabled", existing_medication.reminder_enabled)
                )
                existing_medication.reminder_time = _parse_time(medication_payload.get("reminder_time"))
                updated_medications += 1
                continue

            medication = Medication(
                patient_id=patient.id,
                name=medication_payload.get("name", "Лекарство из резервной копии"),
                dosage=medication_payload.get("dosage"),
                schedule=medication_payload.get("schedule"),
                instructions=medication_payload.get("instructions"),
                start_date=_parse_date(medication_payload.get("start_date")),
                end_date=_parse_date(medication_payload.get("end_date")),
                is_active=bool(medication_payload.get("is_active", True)),
                reminder_enabled=bool(medication_payload.get("reminder_enabled", False)),
                reminder_time=_parse_time(medication_payload.get("reminder_time")),
                notes=medication_payload.get("notes"),
                created_at=_parse_datetime(medication_payload.get("created_at")) or datetime.now(),
            )
            db.add(medication)
            restored_medications += 1

        for document_payload in patient_record.get("documents", []):
            document_key = build_document_conflict_key(patient_payload, document_payload)
            if document_key in skip_documents:
                continue
            if mode == "merge" and _has_duplicate_document(patient, document_payload):
                skipped_documents += 1
                continue
            relative_path = document_payload.get("original_file_path") or document_payload.get("file_path")
            original_filename = document_payload.get("original_filename") or "document.pdf"
            archived_path = relative_path
            if archived_path not in archive.namelist():
                archived_path = str(Path("uploads") / Path(relative_path or "").name)
            if archived_path not in archive.namelist() and relative_path:
                archived_path = str(Path("uploads") / str(patient_payload.get("id", "")) / Path(relative_path).name)
            if archived_path not in archive.namelist():
                continue

            pdf_bytes = archive.read(archived_path)
            stored_path = save_pdf_bytes(original_filename, pdf_bytes, patient.id)
            document = build_uploaded_document(
                patient_id=patient.id,
                stored_path=stored_path,
                original_filename=original_filename,
                document_type=document_payload.get("document_type") or "lab",
                doctor_type=document_payload.get("doctor_type"),
                description=document_payload.get("description"),
            )
            document.processed_file_path = document_payload.get("processed_file_path")
            document.extracted_text = document_payload.get("extracted_text")
            document.processing_status = document_payload.get("processing_status") or "uploaded"
            document.created_at = _parse_datetime(document_payload.get("created_at")) or datetime.now()
            db.add(document)
            restored_documents += 1

        for growth_payload in patient_record.get("growth_records", []):
            db.add(
                GrowthRecord(
                    patient_id=patient.id,
                    height=growth_payload.get("height"),
                    weight=growth_payload.get("weight"),
                    date=_parse_date(growth_payload.get("date")) or date.today(),
                    created_at=_parse_datetime(growth_payload.get("created_at")) or datetime.now(),
                )
            )

        for vaccine_payload in patient_record.get("vaccine_records", []):
            db.add(
                VaccineRecord(
                    patient_id=patient.id,
                    name=vaccine_payload.get("name", "Прививка"),
                    date=_parse_date(vaccine_payload.get("date")),
                    status=vaccine_payload.get("status", "planned"),
                    comment=vaccine_payload.get("comment"),
                    created_at=_parse_datetime(vaccine_payload.get("created_at")) or datetime.now(),
                )
            )

        for event_payload in patient_record.get("health_events", []):
            db.add(
                HealthEvent(
                    patient_id=patient.id,
                    temperature=event_payload.get("temperature"),
                    symptoms=event_payload.get("symptoms"),
                    comment=event_payload.get("comment"),
                    date=_parse_date(event_payload.get("date")) or date.today(),
                    created_at=_parse_datetime(event_payload.get("created_at")) or datetime.now(),
                )
            )

        for child_med_payload in patient_record.get("child_medications", []):
            db.add(
                ChildMedication(
                    patient_id=patient.id,
                    name=child_med_payload.get("name", "Лекарство"),
                    dosage=child_med_payload.get("dosage"),
                    comment=child_med_payload.get("comment"),
                    date=_parse_date(child_med_payload.get("date")) or date.today(),
                    created_at=_parse_datetime(child_med_payload.get("created_at")) or datetime.now(),
                )
            )

    db.commit()
    archive.close()

    return {
        "mode": mode,
        "patients": restored_patients,
        "merged_patients": merged_patients,
        "observations": restored_observations,
        "lab_results": restored_lab_results,
        "medications": restored_medications,
        "updated_medications": updated_medications,
        "documents": restored_documents,
        "skipped_documents": skipped_documents,
    }
