from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app.dependencies import get_patient_for_user
from app.exporters import serialize_family_record, serialize_patient_record
from app.models import AuditLog, ChildMedication, Document, GrowthRecord, HealthEvent, Invite, Medication, Observation, Patient, PatientComment, PatientShare, User, UserPatient, VaccineRecord
from app.services.labs import list_patient_lab_results, list_distinct_lab_tests, serialize_lab_result


def list_user_patients(db: Session, user: User) -> list[Patient]:
    query = select(Patient).where(Patient.family_id == user.family_id)
    if user.role != "owner":
        query = query.join(UserPatient, UserPatient.patient_id == Patient.id).where(UserPatient.user_id == user.id)
    return db.scalars(query.order_by(Patient.name)).all()


def list_owned_patients(db: Session, user: User) -> list[Patient]:
    return db.scalars(select(Patient).where(Patient.family_id == user.family_id).order_by(Patient.name)).all()


def build_history_conditions(
    patient_id: int,
    observation_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    conditions = [Observation.patient_id == patient_id]
    if observation_type:
        conditions.append(Observation.type == observation_type)
    if date_from:
        conditions.append(Observation.created_at >= date_from)
    if date_to:
        conditions.append(Observation.created_at <= date_to)
    return conditions


def list_patient_observations(
    db: Session,
    patient: Patient,
    observation_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int | None = None,
) -> list[Observation]:
    query = (
        select(Observation)
        .where(and_(*build_history_conditions(patient.id, observation_type, date_from, date_to)))
        .order_by(desc(Observation.created_at))
    )
    if limit is not None:
        query = query.limit(limit)
    return db.scalars(query).all()


def list_patient_history(
    db: Session,
    patient: Patient,
    observation_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_order: str = "desc",
    limit: int | None = None,
) -> list[dict]:
    entries: list[dict] = []
    lab_test = None
    if observation_type and observation_type.startswith("lab:"):
        lab_test = observation_type.split("lab:", 1)[1]

    if observation_type in (None, "", "lab_result") or lab_test:
        lab_results = list_patient_lab_results(db, patient, lab_test, date_from, date_to)
        entries.extend(serialize_lab_result(item) for item in lab_results)

    non_lab_type = observation_type
    if observation_type == "lab_result" or (observation_type and observation_type.startswith("lab:")):
        non_lab_type = None
    if observation_type not in ("lab_result",) and not (observation_type and observation_type.startswith("lab:")):
        observations = list_patient_observations(db, patient, non_lab_type, date_from, date_to)
        entries.extend(
            {
                "id": item.id,
                "patient_id": item.patient_id,
                "type": item.type,
                "entry_kind": "observation",
                "value": item.value,
                "created_at": item.created_at,
            }
            for item in observations
        )

    reverse = sort_order != "asc"
    entries.sort(key=lambda item: item["created_at"], reverse=reverse)
    if limit is not None:
        entries = entries[:limit]
    return entries


def list_patient_medications(db: Session, patient: Patient) -> list[Medication]:
    return db.scalars(
        select(Medication).where(Medication.patient_id == patient.id).order_by(desc(Medication.is_active), desc(Medication.created_at))
    ).all()


def list_active_patient_medications(db: Session, patient: Patient) -> list[Medication]:
    return db.scalars(
        select(Medication)
        .where(Medication.patient_id == patient.id, Medication.is_active.is_(True))
        .order_by(desc(Medication.created_at))
    ).all()


def list_patient_documents(
    db: Session,
    patient: Patient,
    document_type: str | None = None,
    doctor_type: str | None = None,
) -> list[Document]:
    query = select(Document).where(Document.patient_id == patient.id)
    if document_type in {"lab", "report"}:
        query = query.where(Document.document_type == document_type)
    if doctor_type:
        query = query.where(Document.doctor_type == doctor_type)
    return db.scalars(query.order_by(desc(Document.created_at))).all()


def get_patient_emergency_info(db: Session, patient: Patient) -> dict:
    return {
        "patient_id": patient.id,
        "blood_type": patient.blood_type,
        "allergies": patient.allergies,
        "diagnoses": patient.chronic_diseases,
        "chronic_diseases": patient.chronic_diseases,
        "permanent_medications": patient.permanent_medications,
        "emergency_contacts": patient.emergency_contacts,
        "emergency_contact_name": patient.emergency_contact_name,
        "emergency_contact_phone": patient.emergency_contact_phone,
    }


def list_patient_growth_records(db: Session, patient: Patient) -> list[GrowthRecord]:
    return db.scalars(select(GrowthRecord).where(GrowthRecord.patient_id == patient.id).order_by(desc(GrowthRecord.date), desc(GrowthRecord.id))).all()


def list_patient_vaccine_records(db: Session, patient: Patient) -> list[VaccineRecord]:
    return db.scalars(select(VaccineRecord).where(VaccineRecord.patient_id == patient.id).order_by(desc(VaccineRecord.date), desc(VaccineRecord.id))).all()


def list_patient_health_events(db: Session, patient: Patient) -> list[HealthEvent]:
    return db.scalars(select(HealthEvent).where(HealthEvent.patient_id == patient.id).order_by(desc(HealthEvent.date), desc(HealthEvent.id))).all()


def list_patient_child_medications(db: Session, patient: Patient) -> list[ChildMedication]:
    return db.scalars(select(ChildMedication).where(ChildMedication.patient_id == patient.id).order_by(desc(ChildMedication.date), desc(ChildMedication.id))).all()


def collect_patient_record(db: Session, patient: Patient) -> dict:
    return serialize_patient_record(
        patient=patient,
        observations=list_patient_observations(db, patient),
        lab_results=list_patient_lab_results(db, patient),
        medications=list_patient_medications(db, patient),
        documents=list_patient_documents(db, patient),
        emergency_info=get_patient_emergency_info(db, patient),
    )


def collect_family_record(db: Session, user: User) -> dict:
    patient_records = [collect_patient_record(db, patient) for patient in list_owned_patients(db, user)]
    return serialize_family_record(patient_records, user)


def get_owned_patient_record(db: Session, patient_id: int, user: User) -> tuple[Patient, dict]:
    patient_query = select(Patient).where(Patient.id == patient_id, Patient.family_id == user.family_id)
    if user.role != "owner":
        patient_query = patient_query.join(UserPatient, UserPatient.patient_id == Patient.id).where(UserPatient.user_id == user.id)
    patient = db.scalar(patient_query)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пациент не найден")
    return patient, collect_patient_record(db, patient)


def list_audit_logs(
    db: Session,
    user: User,
    limit: int = 100,
    action: str | None = None,
    search: str | None = None,
) -> list[AuditLog]:
    query = select(AuditLog).where(AuditLog.user_id == user.id)
    if action:
        query = query.where(AuditLog.action == action)
    if search:
        query = query.where(AuditLog.action.ilike(f"%{search.strip().lower()}%"))
    query = query.order_by(desc(AuditLog.created_at)).limit(limit)
    return db.scalars(query).all()


def list_patient_lab_test_names(db: Session, patient: Patient) -> list[str]:
    return list_distinct_lab_tests(db, patient)


def list_patient_shares(db: Session, patient: Patient) -> list[PatientShare]:
    return db.scalars(
        select(PatientShare).where(PatientShare.patient_id == patient.id).order_by(desc(PatientShare.created_at))
    ).all()


def list_family_users(db: Session, user: User) -> list[User]:
    return db.scalars(select(User).where(User.family_id == user.family_id).order_by(User.role.desc(), User.login)).all()


def list_family_invites(db: Session, user: User) -> list[Invite]:
    return db.scalars(select(Invite).where(Invite.family_id == user.family_id).order_by(desc(Invite.created_at))).all()


def list_patient_comments(db: Session, patient: Patient, limit: int = 100) -> list[PatientComment]:
    return db.scalars(
        select(PatientComment)
        .where(PatientComment.patient_id == patient.id)
        .order_by(desc(PatientComment.pinned), desc(PatientComment.created_at))
        .limit(limit)
    ).all()


def list_patient_comments_filtered(
    db: Session,
    patient: Patient,
    limit: int = 100,
    pinned_only: bool = False,
    search: str | None = None,
) -> list[PatientComment]:
    query = select(PatientComment).where(PatientComment.patient_id == patient.id)
    if pinned_only:
        query = query.where(PatientComment.pinned.is_(True))
    if search:
        query = query.where(PatientComment.text.ilike(f"%{search.strip()}%"))
    query = query.order_by(desc(PatientComment.pinned), desc(PatientComment.created_at)).limit(limit)
    return db.scalars(query).all()


def list_comment_journal(
    db: Session,
    user: User,
    search: str | None = None,
    category: str | None = None,
    author_email: str | None = None,
    patient_id: int | None = None,
    pinned_only: bool = False,
    limit: int = 200,
) -> list[dict]:
    accessible_patients = list_user_patients(db, user)
    patient_ids = [item.id for item in accessible_patients]
    if not patient_ids:
        return []
    query = select(PatientComment).where(PatientComment.patient_id.in_(patient_ids))
    if patient_id:
        query = query.where(PatientComment.patient_id == patient_id)
    if pinned_only:
        query = query.where(PatientComment.pinned.is_(True))
    if category:
        query = query.where(PatientComment.category == category)
    if search:
        query = query.where(PatientComment.text.ilike(f"%{search.strip()}%"))
    if author_email:
        query = query.join(User, User.id == PatientComment.user_id).where(User.login.ilike(f"%{author_email.strip()}%"))
    query = query.order_by(desc(PatientComment.pinned), desc(PatientComment.created_at)).limit(limit)
    comments = db.scalars(query).all()
    patient_map = {patient.id: patient.name for patient in accessible_patients}
    return [
        {
            "id": item.id,
            "patient_id": item.patient_id,
            "patient_name": patient_map.get(item.patient_id, "Пациент"),
            "user_id": item.user_id,
            "author_email": item.author.account_name,
            "category": item.category,
            "text": item.text,
            "pinned": item.pinned,
            "created_at": item.created_at,
        }
        for item in comments
    ]
