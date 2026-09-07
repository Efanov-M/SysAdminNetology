from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.services.backup import (
    _find_existing_medication,
    _find_existing_patient,
    _has_duplicate_document,
    _load_backup_payload,
    build_document_conflict_key,
    build_medication_conflict_key,
    build_patient_conflict_key,
    restore_backup_archive,
)


def _find_similar_observation(existing_patient, observation_payload: dict) -> dict | None:
    incoming_type = observation_payload.get("type")
    incoming_value = observation_payload.get("value", {})
    for item in existing_patient.observations:
        if item.type == incoming_type:
            return {"type": item.type, "value": item.value, "created_at": item.created_at.isoformat()}
    return None


def _find_similar_lab_result(existing_patient, lab_payload: dict) -> dict | None:
    incoming_value = lab_payload.get("value", {})
    incoming_test_name = incoming_value.get("test_name")
    for item in existing_patient.lab_results:
        if item.test_name == incoming_test_name:
            return {
                "test_name": item.test_name,
                "value": item.value,
                "unit": item.unit,
                "panel_name": item.panel_name,
                "created_at": item.created_at.isoformat(),
            }
    return None


def _wizard_dir() -> Path:
    path = settings.backup_path / "restore_wizard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wizard_meta_path(preview_id: str) -> Path:
    return _wizard_dir() / f"{preview_id}.json"


def _wizard_zip_path(preview_id: str) -> Path:
    return _wizard_dir() / f"{preview_id}.zip"


def _build_preview_payload(db: Session, user: User, upload_file: UploadFile) -> tuple[dict, bytes]:
    raw_bytes = upload_file.file.read()
    upload_file.file.seek(0)
    payload, archive = _load_backup_payload(upload_file)
    patients_preview = []
    summary = {
        "incoming_patients": 0,
        "new_patients": 0,
        "matched_patients": 0,
        "new_medications": 0,
        "updated_medications": 0,
        "new_documents": 0,
        "duplicate_documents": 0,
        "observations": 0,
        "lab_results": 0,
    }

    for patient_record in payload.get("patients", []):
        patient_payload = patient_record.get("patient", {})
        summary["incoming_patients"] += 1
        existing_patient = _find_existing_patient(db, user, patient_payload)
        is_matched = existing_patient is not None
        patient_key = build_patient_conflict_key(patient_payload)
        if is_matched:
            summary["matched_patients"] += 1
        else:
            summary["new_patients"] += 1

        patient_info = {
            "key": patient_key,
            "name": patient_payload.get("name"),
            "date_of_birth": patient_payload.get("date_of_birth"),
            "status": "matched" if is_matched else "new",
            "default_action": "merge" if is_matched else "restore",
            "available_actions": ["restore", "skip"] if not is_matched else ["merge", "restore", "skip"],
            "medications": [],
            "documents": [],
            "observations": len(patient_record.get("observations", [])),
            "lab_results": len(patient_record.get("lab_results", [])),
            "comparison_note": "Новый пациент будет создан" if not is_matched else "Найден похожий пациент, можно слить данные",
            "observation_conflicts": [],
            "lab_conflicts": [],
        }
        summary["observations"] += patient_info["observations"]
        summary["lab_results"] += patient_info["lab_results"]

        for observation_payload in patient_record.get("observations", []):
            if not existing_patient:
                continue
            similar = _find_similar_observation(existing_patient, observation_payload)
            if not similar:
                continue
            patient_info["observation_conflicts"].append(
                {
                    "type": observation_payload.get("type"),
                    "incoming": observation_payload.get("value", {}),
                    "current": similar.get("value", {}),
                    "comparison_note": "У пациента уже есть похожий показатель этого типа",
                }
            )

        for lab_payload in patient_record.get("lab_results", []):
            if not existing_patient:
                continue
            similar = _find_similar_lab_result(existing_patient, lab_payload)
            if not similar:
                continue
            patient_info["lab_conflicts"].append(
                {
                    "test_name": lab_payload.get("value", {}).get("test_name"),
                    "incoming": lab_payload.get("value", {}),
                    "current": similar,
                    "comparison_note": "У пациента уже есть похожий анализ по этому показателю",
                }
            )

        for medication_payload in patient_record.get("medications", []):
            state = "new"
            existing_medication = None
            if existing_patient and _find_existing_medication(existing_patient, medication_payload):
                state = "update"
                existing_medication = _find_existing_medication(existing_patient, medication_payload)
                summary["updated_medications"] += 1
            else:
                summary["new_medications"] += 1
            patient_info["medications"].append(
                {
                    "key": build_medication_conflict_key(patient_payload, medication_payload),
                    "name": medication_payload.get("name"),
                    "dosage": medication_payload.get("dosage"),
                    "schedule": medication_payload.get("schedule"),
                    "status": state,
                    "default_action": "update" if state == "update" else "restore",
                    "available_actions": ["update", "restore", "skip"] if state == "update" else ["restore", "skip"],
                    "incoming": {
                        "name": medication_payload.get("name"),
                        "dosage": medication_payload.get("dosage"),
                        "schedule": medication_payload.get("schedule"),
                        "instructions": medication_payload.get("instructions"),
                        "start_date": medication_payload.get("start_date"),
                        "end_date": medication_payload.get("end_date"),
                        "is_active": medication_payload.get("is_active", True),
                        "notes": medication_payload.get("notes"),
                    },
                    "current": (
                        {
                            "name": existing_medication.name,
                            "dosage": existing_medication.dosage,
                            "schedule": existing_medication.schedule,
                            "instructions": existing_medication.instructions,
                            "start_date": existing_medication.start_date.isoformat() if existing_medication.start_date else None,
                            "end_date": existing_medication.end_date.isoformat() if existing_medication.end_date else None,
                            "is_active": existing_medication.is_active,
                            "notes": existing_medication.notes,
                        }
                        if existing_medication
                        else None
                    ),
                    "comparison_note": (
                        "Совпадает по базовым полям, можно обновить заметки и напоминания"
                        if existing_medication
                        else "Такого лекарства ещё нет у пациента"
                    ),
                }
            )

        for document_payload in patient_record.get("documents", []):
            duplicate = bool(existing_patient and _has_duplicate_document(existing_patient, document_payload))
            current_document = None
            if duplicate and existing_patient:
                for item in existing_patient.documents:
                    if (
                        (item.original_filename or "").strip().lower() == (document_payload.get("original_filename") or "").strip().lower()
                        and (item.description or "").strip().lower() == (document_payload.get("description") or "").strip().lower()
                    ):
                        current_document = item
                        break
            if duplicate:
                summary["duplicate_documents"] += 1
            else:
                summary["new_documents"] += 1
            patient_info["documents"].append(
                {
                    "key": build_document_conflict_key(patient_payload, document_payload),
                    "description": document_payload.get("description"),
                    "original_filename": document_payload.get("original_filename"),
                    "document_type": document_payload.get("document_type") or "lab",
                    "doctor_type": document_payload.get("doctor_type"),
                    "status": "duplicate" if duplicate else "new",
                    "default_action": "skip" if duplicate else "restore",
                    "available_actions": ["restore", "skip"],
                    "incoming": {
                        "description": document_payload.get("description"),
                        "original_filename": document_payload.get("original_filename"),
                        "document_type": document_payload.get("document_type") or "lab",
                        "doctor_type": document_payload.get("doctor_type"),
                    },
                    "current": (
                        {
                            "description": current_document.description,
                            "original_filename": current_document.original_filename,
                            "document_type": current_document.document_type,
                            "doctor_type": current_document.doctor_type,
                        }
                        if current_document
                        else None
                    ),
                    "comparison_note": "Похожий документ уже есть, по умолчанию он будет пропущен" if duplicate else "Документ будет добавлен как новый",
                }
            )

        patients_preview.append(patient_info)

    archive.close()
    return {"summary": summary, "patients": patients_preview}, raw_bytes


def create_restore_wizard_preview(db: Session, user: User, upload_file: UploadFile) -> dict:
    preview, raw_bytes = _build_preview_payload(db, user, upload_file)
    preview_id = uuid4().hex
    _wizard_zip_path(preview_id).write_bytes(raw_bytes)
    _wizard_meta_path(preview_id).write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"preview_id": preview_id, **preview}


def get_restore_wizard_preview(preview_id: str) -> dict:
    return json.loads(_wizard_meta_path(preview_id).read_text(encoding="utf-8"))


def apply_restore_wizard_preview(db: Session, user: User, preview_id: str, mode: str, decisions: dict | None = None) -> dict:
    zip_path = _wizard_zip_path(preview_id)
    class StoredUploadFile:
        filename = "restore-preview.zip"

        def __init__(self, content: bytes):
            from io import BytesIO

            self.file = BytesIO(content)

    file = StoredUploadFile(zip_path.read_bytes())
    result = restore_backup_archive(db, user, file, mode=mode, decisions=decisions)
    return result
