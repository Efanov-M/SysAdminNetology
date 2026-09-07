from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import (
    can_comment_patient,
    can_write_patient,
    get_current_user,
    get_patient_for_user,
    get_writable_patient_for_user,
)
from app.db import get_db
from app.models import Document, LabResult, Medication, Observation, Patient, PatientComment, PatientShare, User
from app.models import Invite, UserPatient
from app.schemas import (
    BloodPressureCreate,
    DocumentRead,
    EmergencyInfoRead,
    EmergencyInfoUpdate,
    InviteCreate,
    InviteRead,
    LabObservationCreate,
    LabResultRead,
    MedicationCreate,
    MedicationRead,
    NumericObservationCreate,
    ObservationRead,
    PatientCreate,
    PatientCommentCreate,
    PatientCommentRead,
    PatientRead,
    ShareReminderSettingsUpdate,
    UserPreferencesUpdate,
    UserRead,
)
from app.services.audit import log_audit_event
from app.services.charts import build_chart_pdf
from app.services.document_processing import build_uploaded_document, cleanup_document_files, queue_document_processing
from app.services.labs import list_patient_lab_results
from app.services.lab_panels import LAB_PANEL_TEMPLATES
from app.services.medications import check_local_medication_interactions, fetch_medication_info, lookup_drug_cache, suggest_drug_cache
from app.services.notifications import (
    build_blood_pressure_message,
    build_lab_result_message,
    build_medication_created_message,
    dispatch_due_medication_reminders,
    send_matrix_message,
)
from app.services.pdf_import import import_medical_pdf
from app.services.records import (
    collect_family_record,
    collect_patient_record,
    get_owned_patient_record,
    list_audit_logs,
    list_comment_journal,
    list_family_invites,
    list_family_users,
    list_patient_comments_filtered,
    list_patient_documents,
    list_patient_history,
    list_patient_lab_test_names,
    list_patient_medications,
    list_patient_observations,
    list_user_patients,
)
from app.services.restore_preview import (
    apply_restore_wizard_preview,
    create_restore_wizard_preview,
    get_restore_wizard_preview,
)
from app.utils import DOCTOR_TYPE_OPTIONS, delete_upload_file, save_upload_file


router = APIRouter(prefix="/api", tags=["api"])


@router.get("/family/export")
def export_family_record(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = collect_family_record(db, user)
    log_audit_event(db, "family_export_api", user, {"patients": len(payload["patients"])})
    return payload


@router.get("/patients", response_model=list[PatientRead])
def list_patients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_user_patients(db, user)


@router.post("/patients", response_model=PatientRead)
def create_patient(payload: PatientCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только владелец семьи может создавать пациентов")
    if payload.patient_type not in {"elderly", "child"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный тип пациента")
    patient = Patient(user_id=user.id, family_id=user.family_id, created_by_user_id=user.id, **payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/patients/{patient_id}", response_model=PatientRead)
def get_patient(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_patient_for_user(patient_id, user, db)
    return patient


@router.delete("/patients/{patient_id}", status_code=204)
def delete_patient(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только владелец семьи может удалять пациентов")
    patient = get_patient_for_user(patient_id, user, db)
    for document in patient.documents:
        for path in cleanup_document_files(document):
            delete_upload_file(path)
    db.delete(patient)
    db.commit()


@router.get("/family/users", response_model=list[UserRead])
def family_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только владелец семьи может смотреть состав семьи")
    return list_family_users(db, user)


@router.get("/family/invites", response_model=list[InviteRead])
def family_invites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только владелец семьи может смотреть приглашения")
    return list_family_invites(db, user)


@router.post("/invite", response_model=InviteRead)
def create_invite(payload: InviteCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только владелец семьи может приглашать пользователей")
    normalized_login = payload.login.strip().lower()
    existing_user = db.scalar(select(User).where(User.login == normalized_login))
    if not existing_user:
        existing_user = db.scalar(select(User).where(User.email == normalized_login))
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пользователь с таким логином уже существует")
    if payload.patient_id is not None:
        patient = db.scalar(select(Patient).where(Patient.id == payload.patient_id, Patient.family_id == user.family_id))
        if not patient:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пациент не найден")
    invite = Invite(
        login=normalized_login,
        email=normalized_login,
        family_id=user.family_id,
        role="member",
        patient_id=payload.patient_id,
        token=token_urlsafe(24),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        used=False,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/patients/{patient_id}/observations", response_model=list[ObservationRead])
def list_observations(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_patient_for_user(patient_id, user, db)
    return list_patient_history(db, patient)


@router.get("/patients/{patient_id}/history", response_model=list[ObservationRead])
def list_history(
    patient_id: int,
    observation_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    return list_patient_history(db, patient, observation_type, date_from, date_to)


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.put("/me/preferences", response_model=UserRead)
def update_preferences(
    payload: UserPreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.timezone = payload.timezone
    user.quiet_hours_start = payload.quiet_hours_start
    user.quiet_hours_end = payload.quiet_hours_end
    user.notification_channels = sorted({item.strip().lower() for item in payload.notification_channels if item.strip()}) or ["log"]
    if payload.matrix_user_id is not None:
        normalized_matrix_user_id = payload.matrix_user_id.strip() or None
        user.matrix_user_id = normalized_matrix_user_id
        user.matrix_id = normalized_matrix_user_id
    elif payload.matrix_id is not None:
        normalized_matrix_user_id = payload.matrix_id.strip() or None
        user.matrix_user_id = normalized_matrix_user_id
        user.matrix_id = normalized_matrix_user_id
    user.matrix_notifications_enabled = payload.matrix_notifications_enabled
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/blood-pressure", response_model=ObservationRead)
def create_blood_pressure(
    payload: BloodPressureCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    patient = get_writable_patient_for_user(payload.patient_id, user, db)
    if payload.client_id:
        existing = db.scalar(select(Observation).where(Observation.client_id == payload.client_id))
        if existing:
            return existing
    observation = Observation(
        patient_id=patient.id,
        client_id=payload.client_id,
        type="blood_pressure",
        value={"sys": payload.sys, "dia": payload.dia, "pulse": payload.pulse},
    )
    db.add(observation)
    db.commit()
    db.refresh(observation)
    send_matrix_message(user, build_blood_pressure_message(patient.name, payload.sys, payload.dia, payload.pulse, observation.created_at))
    return observation


@router.post("/observations/numeric", response_model=ObservationRead)
def create_numeric_observation(
    payload: NumericObservationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    patient = get_writable_patient_for_user(payload.patient_id, user, db)
    if payload.client_id:
        existing = db.scalar(select(Observation).where(Observation.client_id == payload.client_id))
        if existing:
            return existing
    observation = Observation(
        patient_id=patient.id,
        client_id=payload.client_id,
        type=payload.type,
        value={"value": payload.value, "unit": payload.unit, "label": payload.label},
    )
    db.add(observation)
    if payload.type == "weight":
        patient.weight = payload.value
        db.add(patient)
    db.commit()
    db.refresh(observation)
    return observation


@router.post("/observations/lab", response_model=LabResultRead)
def create_lab_observation(
    payload: LabObservationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    patient = get_writable_patient_for_user(payload.patient_id, user, db)
    lab_result = LabResult(
        patient_id=patient.id,
        panel_name=payload.panel_name,
        test_name=payload.test_name,
        value=payload.value,
        unit=payload.unit,
        reference_low=payload.reference_low,
        reference_high=payload.reference_high,
        reference_text=payload.reference_text,
    )
    db.add(lab_result)
    db.commit()
    db.refresh(lab_result)
    send_matrix_message(
        user,
        build_lab_result_message(
            patient.name,
            lab_result.test_name,
            lab_result.value,
            lab_result.unit,
            lab_result.created_at,
            lab_result.panel_name,
        ),
    )
    return lab_result


@router.post("/medications", response_model=MedicationRead)
def create_medication(
    payload: MedicationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    patient = get_writable_patient_for_user(payload.patient_id, user, db)
    if payload.client_id:
        existing = db.scalar(select(Medication).where(Medication.client_id == payload.client_id))
        if existing:
            return existing
    cached_drug = next(iter(lookup_drug_cache(db, payload.name, limit=1)), None)
    medication_payload = payload.model_dump(exclude={"patient_id"})
    if cached_drug:
        medication_payload["name"] = cached_drug.get("brand_name") or medication_payload["name"]
        medication_payload["instructions"] = medication_payload.get("instructions") or cached_drug.get("instructions")
        medication_payload["notes"] = medication_payload.get("notes") or cached_drug.get("purpose") or cached_drug.get("indications")
    medication = Medication(patient_id=patient.id, **medication_payload)
    db.add(medication)
    db.commit()
    db.refresh(medication)
    send_matrix_message(
        user,
        build_medication_created_message(
            patient.name,
            medication.name,
            medication.dosage,
            medication.schedule,
            medication.instructions,
            medication.created_at,
        ),
    )
    return medication


@router.get("/patients/{patient_id}/medications", response_model=list[MedicationRead])
def list_medications(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_patient_for_user(patient_id, user, db)
    return list_patient_medications(db, patient)


@router.get("/patients/{patient_id}/emergency-info", response_model=EmergencyInfoRead | None)
def get_emergency_info(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_patient_for_user(patient_id, user, db)
    return {
        "patient_id": patient.id,
        "blood_type": patient.blood_type,
        "allergies": patient.allergies,
        "diagnoses": patient.chronic_diseases,
        "permanent_medications": patient.permanent_medications,
        "emergency_contacts": patient.emergency_contacts,
        "emergency_contact_name": patient.emergency_contact_name,
        "emergency_contact_phone": patient.emergency_contact_phone,
    }


@router.put("/patients/{patient_id}/emergency-info", response_model=EmergencyInfoRead)
def update_emergency_info(
    patient_id: int,
    payload: EmergencyInfoUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    patient.blood_type = payload.blood_type
    patient.allergies = payload.allergies
    patient.chronic_diseases = payload.diagnoses
    patient.permanent_medications = payload.permanent_medications
    patient.emergency_contacts = payload.emergency_contacts
    patient.emergency_contact_name = payload.emergency_contact_name
    patient.emergency_contact_phone = payload.emergency_contact_phone
    db.commit()
    db.refresh(patient)
    return {
        "patient_id": patient.id,
        "blood_type": patient.blood_type,
        "allergies": patient.allergies,
        "diagnoses": patient.chronic_diseases,
        "permanent_medications": patient.permanent_medications,
        "emergency_contacts": patient.emergency_contacts,
        "emergency_contact_name": patient.emergency_contact_name,
        "emergency_contact_phone": patient.emergency_contact_phone,
    }


@router.get("/patients/{patient_id}/export")
def export_patient_record(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient, record = get_owned_patient_record(db, patient_id, user)
    log_audit_event(db, "patient_export_api", user, {"patient_id": patient.id})
    return record


@router.post("/documents", response_model=DocumentRead)
def upload_document(
    patient_id: int = Form(...),
    document_type: str = Form(...),
    doctor_type: str | None = Form(default=None),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    if document_type not in {"lab", "report"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный тип документа")
    normalized_doctor_type = (doctor_type or "").strip().lower() or None
    if document_type == "report" and normalized_doctor_type not in DOCTOR_TYPE_OPTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Выберите тип врача для выписки")
    stored_path, original_name = save_upload_file(file, patient.id)
    document = build_uploaded_document(
        patient_id=patient.id,
        stored_path=stored_path,
        original_filename=original_name,
        document_type=document_type,
        doctor_type=normalized_doctor_type if document_type == "report" else None,
        description=description,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    queue_document_processing(document)
    return document


@router.get("/patients/{patient_id}/documents", response_model=list[DocumentRead])
def list_documents(
    patient_id: int,
    document_type: str | None = Query(default=None),
    doctor_type: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    normalized_doctor_type = (doctor_type or "").strip().lower() or None
    if normalized_doctor_type and normalized_doctor_type not in DOCTOR_TYPE_OPTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный тип врача")
    return list_patient_documents(db, patient, document_type=document_type, doctor_type=normalized_doctor_type)


@router.delete("/observations/{observation_id}", status_code=204)
def delete_observation(observation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    observation = db.scalar(
        select(Observation)
        .join(Patient)
        .where(Observation.id == observation_id, Patient.family_id == user.family_id)
    )
    if not observation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись не найдена")
    get_writable_patient_for_user(observation.patient_id, user, db)
    db.delete(observation)
    db.commit()


@router.delete("/medications/{medication_id}", status_code=204)
def delete_medication(medication_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    medication = db.scalar(
        select(Medication).join(Patient).where(Medication.id == medication_id, Patient.family_id == user.family_id)
    )
    if not medication:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Назначение не найдено")
    get_writable_patient_for_user(medication.patient_id, user, db)
    db.delete(medication)
    db.commit()


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = db.scalar(select(Document).join(Patient).where(Document.id == document_id, Patient.family_id == user.family_id))
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    get_writable_patient_for_user(document.patient_id, user, db)
    for path in cleanup_document_files(document):
        delete_upload_file(path)
    db.delete(document)
    db.commit()


@router.get("/medications/search")
def search_medication_info(
    query: str = Query(..., min_length=2),
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del user
    try:
        return {"items": fetch_medication_info(query, db, force_refresh=refresh)}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Не удалось получить данные по препарату") from exc


@router.get("/drugs/suggest")
def suggest_drugs(
    q: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del user
    return {"items": suggest_drug_cache(db, q)}


@router.get("/drugs/autofill")
def drug_autofill(
    q: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del user
    items = lookup_drug_cache(db, q, limit=1)
    if not items:
        return {"item": None}
    item = items[0]
    return {
        "item": {
            "name": item.get("brand_name") or q.strip(),
            "instructions": item.get("instructions"),
            "description": item.get("purpose") or item.get("indications"),
            "dosage_forms": item.get("dosage_forms") or [],
            "source": item.get("source"),
        }
    }


@router.post("/medications/interactions")
def check_interactions(names: list[str], user: User = Depends(get_current_user)):
    del user
    return {"items": check_local_medication_interactions(names)}


@router.get("/audit")
def get_audit_log(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "action": item.action,
            "details": item.details,
            "created_at": item.created_at.isoformat(),
        }
        for item in list_audit_logs(db, user)
    ]


@router.get("/comments/journal")
def get_comments_journal(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    pinned_only: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "items": list_comment_journal(
            db,
            user,
            search=search,
            category=category,
            pinned_only=pinned_only,
            limit=limit,
        )
    }


@router.get("/patients/{patient_id}/comments", response_model=list[PatientCommentRead])
def list_comments(
    patient_id: int,
    pinned_only: bool = Query(default=False),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    comments = list_patient_comments_filtered(db, patient, pinned_only=pinned_only, search=search)
    if category:
        comments = [item for item in comments if item.category == category]
    return comments


@router.post("/patients/{patient_id}/comments", response_model=PatientCommentRead)
def create_comment(
    patient_id: int,
    payload: PatientCommentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    if not can_comment_patient(patient, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Комментарии недоступны")
    comment = PatientComment(
        patient_id=patient.id,
        user_id=user.id,
        category=payload.category,
        text=payload.text.strip(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.put("/patients/{patient_id}/shares/{share_id}/rules")
def update_share_rules(
    patient_id: int,
    share_id: int,
    payload: ShareReminderSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    share = db.scalar(select(PatientShare).where(PatientShare.id == share_id, PatientShare.patient_id == patient.id))
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило доступа не найдено")
    share.receive_reminders = payload.receive_reminders
    db.add(share)
    db.commit()
    db.refresh(share)
    return {"id": share.id, "receive_reminders": share.receive_reminders, "role": share.role}


@router.post("/comments/{comment_id}/pin", response_model=PatientCommentRead)
def pin_comment(
    comment_id: int,
    pinned: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.scalar(select(PatientComment).join(Patient).where(PatientComment.id == comment_id))
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден")
    if not can_write_patient(comment.patient, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Закреплять комментарии может только владелец")
    comment.pinned = pinned
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    comment = db.scalar(select(PatientComment).join(Patient).where(PatientComment.id == comment_id))
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден")
    if not (can_write_patient(comment.patient, user) or comment.user_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав для удаления комментария")
    db.delete(comment)
    db.commit()


@router.post("/backup/preview")
def preview_restore(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_restore_wizard_preview(db, user, file)


@router.get("/backup/wizard/{preview_id}")
def get_restore_preview(preview_id: str, user: User = Depends(get_current_user)):
    del user
    return get_restore_wizard_preview(preview_id)


@router.post("/backup/wizard/{preview_id}/apply")
def apply_restore_preview(
    preview_id: str,
    mode: str = Query(default="merge"),
    decisions: dict | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return apply_restore_wizard_preview(db, user, preview_id, mode=mode, decisions=decisions)


@router.post("/patients/{patient_id}/import/pdf")
def import_observations_from_pdf(
    patient_id: int,
    file: UploadFile = File(...),
    save: bool = Query(default=False),
    store_document: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    pdf_bytes = file.file.read()
    result = import_medical_pdf(
        db=db,
        patient=patient,
        pdf_bytes=pdf_bytes,
        original_filename=file.filename or "medical.pdf",
        save_results=save,
        store_document=store_document,
    )
    return result


@router.post("/jobs/reminders/run")
def run_reminders_job(
    at_time: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del user
    now = None
    if at_time:
        parsed = datetime.strptime(at_time, "%H:%M").time()
        now = datetime.combine(datetime.now(UTC).date(), parsed)
    items = dispatch_due_medication_reminders(db, now=now)
    return {"items": items, "count": len(items)}


@router.get("/lab-panels")
def get_lab_panels():
    return LAB_PANEL_TEMPLATES


@router.get("/patients/{patient_id}/lab-tests")
def get_lab_tests(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_patient_for_user(patient_id, user, db)
    return {"items": list_patient_lab_test_names(db, patient)}


@router.get("/patients/{patient_id}/charts/pdf")
def export_chart_pdf(
    patient_id: int,
    chart_type: str = Query(default="blood_pressure"),
    lab_test_name: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    if chart_type == "lab_result" and not lab_test_name:
        lab_tests = list_patient_lab_test_names(db, patient)
        if lab_tests:
            lab_test_name = lab_tests[0]
    observations = list_patient_history(db, patient, chart_type, date_from, date_to)
    pdf_bytes = build_chart_pdf(
        patient_name=patient.name,
        chart_type=chart_type,
        observations=observations,
        date_from=date_from.date().isoformat() if date_from else None,
        date_to=date_to.date().isoformat() if date_to else None,
        lab_test_name=lab_test_name,
    )
    headers = {"Content-Disposition": f'attachment; filename="patient-{patient.id}-{chart_type}-chart.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.delete("/lab-results/{lab_result_id}", status_code=204)
def delete_lab_result(lab_result_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lab_result = db.scalar(
        select(LabResult).join(Patient).where(LabResult.id == lab_result_id, Patient.family_id == user.family_id)
    )
    if not lab_result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Результат анализа не найден")
    get_writable_patient_for_user(lab_result.patient_id, user, db)
    db.delete(lab_result)
    db.commit()
