from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings
from app.models import Document, LabResult, Medication, Observation, Patient, User
from app.services.labs import serialize_lab_result


def serialize_patient_record(
    patient: Patient,
    observations: list[Observation],
    lab_results: list[LabResult],
    medications: list[Medication],
    documents: list[Document],
    emergency_info: dict | None = None,
) -> dict:
    return {
        "patient": {
            "id": patient.id,
            "name": patient.name,
            "patient_type": patient.patient_type,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "notes": patient.notes,
        },
        "emergency_info": {
            "blood_type": emergency_info.get("blood_type") if emergency_info else None,
            "allergies": emergency_info.get("allergies") if emergency_info else None,
            "diagnoses": emergency_info.get("diagnoses") if emergency_info else None,
            "permanent_medications": emergency_info.get("permanent_medications") if emergency_info else None,
            "emergency_contacts": emergency_info.get("emergency_contacts") if emergency_info else None,
        },
        "observations": [
            {
                "id": item.id,
                "type": item.type,
                "value": item.value,
                "created_at": item.created_at.isoformat(),
            }
            for item in observations
        ],
        "lab_results": [
            {
                "id": item["id"],
                "type": item["type"],
                "value": item["value"],
                "created_at": item["created_at"].isoformat(),
            }
            for item in [serialize_lab_result(result) for result in lab_results]
        ],
        "medications": [
            {
                "id": item.id,
                "name": item.name,
                "dosage": item.dosage,
                "schedule": item.schedule,
                "instructions": item.instructions,
                "start_date": item.start_date.isoformat() if item.start_date else None,
                "end_date": item.end_date.isoformat() if item.end_date else None,
                "is_active": item.is_active,
                "reminder_enabled": item.reminder_enabled,
                "reminder_time": item.reminder_time.isoformat() if item.reminder_time else None,
                "notes": item.notes,
                "created_at": item.created_at.isoformat(),
            }
            for item in medications
        ],
        "documents": [
            {
                "id": item.id,
                "description": item.description,
                "original_filename": item.original_filename,
                "file_path": item.file_path,
                "original_file_path": item.original_file_path,
                "processed_file_path": item.processed_file_path,
                "extracted_text": item.extracted_text,
                "processing_status": item.processing_status,
                "document_type": item.document_type,
                "doctor_type": item.doctor_type,
                "created_at": item.created_at.isoformat(),
            }
            for item in documents
        ],
        "growth_records": [
            {"id": item.id, "height": item.height, "weight": item.weight, "date": item.date.isoformat(), "created_at": item.created_at.isoformat()}
            for item in patient.growth_records
        ],
        "vaccine_records": [
            {"id": item.id, "name": item.name, "date": item.date.isoformat() if item.date else None, "status": item.status, "comment": item.comment, "created_at": item.created_at.isoformat()}
            for item in patient.vaccine_records
        ],
        "health_events": [
            {"id": item.id, "temperature": item.temperature, "symptoms": item.symptoms, "comment": item.comment, "date": item.date.isoformat(), "created_at": item.created_at.isoformat()}
            for item in patient.health_events
        ],
        "child_medications": [
            {"id": item.id, "name": item.name, "dosage": item.dosage, "comment": item.comment, "date": item.date.isoformat(), "created_at": item.created_at.isoformat()}
            for item in patient.child_medications
        ],
    }


def serialize_family_record(records: list[dict], user: User) -> dict:
    return {
        "owner_login": user.account_name,
        "owner_email": user.email,
        "patients": records,
    }


def build_backup_archive(payload: dict) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("family-export.json", json.dumps(payload, ensure_ascii=False, indent=2))

        for patient_record in payload["patients"]:
            patient = patient_record["patient"]
            patient_id = patient["id"]
            for document in patient_record["documents"]:
                relative_path = document.get("original_file_path") or document.get("file_path")
                file_path = settings.upload_path.parent / relative_path
                if not file_path.exists():
                    continue
                archive_name = Path("uploads") / str(patient_id) / file_path.name
                archive.write(file_path, arcname=str(archive_name))

    return buffer.getvalue()
