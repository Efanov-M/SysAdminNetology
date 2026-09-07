from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import LabResult, Patient


def get_lab_status(value: float, reference_low: float | None, reference_high: float | None) -> str:
    if reference_low is not None and value < reference_low:
        return "low"
    if reference_high is not None and value > reference_high:
        return "high"
    return "normal"


def serialize_lab_result(lab_result: LabResult) -> dict:
    return {
        "id": lab_result.id,
        "patient_id": lab_result.patient_id,
        "type": "lab_result",
        "entry_kind": "lab_result",
        "value": {
            "panel_name": lab_result.panel_name,
            "test_name": lab_result.test_name,
            "value": lab_result.value,
            "unit": lab_result.unit,
            "reference_low": lab_result.reference_low,
            "reference_high": lab_result.reference_high,
            "reference_text": lab_result.reference_text,
            "status": get_lab_status(lab_result.value, lab_result.reference_low, lab_result.reference_high),
        },
        "created_at": lab_result.created_at,
    }


def list_patient_lab_results(
    db: Session,
    patient: Patient,
    test_name: str | None = None,
    date_from=None,
    date_to=None,
) -> list[LabResult]:
    query = select(LabResult).where(LabResult.patient_id == patient.id)
    if test_name:
        query = query.where(LabResult.test_name == test_name)
    if date_from:
        query = query.where(LabResult.created_at >= date_from)
    if date_to:
        query = query.where(LabResult.created_at <= date_to)
    query = query.order_by(desc(LabResult.created_at))
    return db.scalars(query).all()


def list_distinct_lab_tests(db: Session, patient: Patient) -> list[str]:
    rows = db.execute(
        select(LabResult.test_name).where(LabResult.patient_id == patient.id).distinct().order_by(LabResult.test_name)
    )
    return [row[0] for row in rows]
