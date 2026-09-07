from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, get_writable_patient_for_user
from app.models import User, Patient
from app.routers.pages import build_dashboard_context, build_template_response, get_patient_emergency_info, redirect_with_message, require_family_owner, templates
from app.services.audit import log_audit_event
from app.services.records import (
    get_owned_patient_record,
    list_patient_growth_records,
    list_patient_health_events,
    list_patient_history,
    list_patient_medications,
    list_patient_vaccine_records,
)
from app.utils import build_medication_reminder_ics


router = APIRouter(tags=["patient-pages"])


@router.get("/manage", response_class=HTMLResponse)
def manage_data_page(
    request: Request,
    selected_patient_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_dashboard_context(
        request=request,
        user=user,
        db=db,
        selected_patient_id=selected_patient_id,
    )
    return templates.TemplateResponse(request, "manage.html", context)


@router.get("/partials/patient-block", response_class=HTMLResponse)
def dashboard_patient_block_partial(
    request: Request,
    selected_patient_id: int | None = None,
    current_screen: str = "main",
    chart_type: str | None = None,
    chart_lab_test: str | None = None,
    history_type: str | None = None,
    history_date_from: str | None = None,
    history_date_to: str | None = None,
    history_sort: str | None = None,
    date_preset: str | None = None,
    child_tab: str | None = None,
    edit_patient: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_dashboard_context(
        request=request,
        user=user,
        db=db,
        current_screen=current_screen,
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
        child_tab=child_tab,
        edit_patient=edit_patient,
    )
    return templates.TemplateResponse(request, "partials/patient_block.html", context)


@router.post("/patients")
def create_patient_page(
    name: str = Form(...),
    patient_type: str = Form(default="elderly"),
    date_of_birth: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    weight: float = Form(default=0.0),
    emergency_contact_name: str | None = Form(default=None),
    emergency_contact_phone: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_family_owner(user)
    if not name.strip():
        return redirect_with_message("/", "Имя пациента не может быть пустым", is_error=True)
    try:
        parsed_date = date.fromisoformat(date_of_birth) if date_of_birth else None
    except ValueError:
        return redirect_with_message("/", "Неверный формат даты", is_error=True)
    if patient_type not in {"elderly", "child"}:
        return redirect_with_message("/", "Неверный тип пациента", is_error=True)
    patient = Patient(
        user_id=user.id,
        family_id=user.family_id,
        created_by_user_id=user.id,
        name=name.strip(),
        patient_type=patient_type,
        date_of_birth=parsed_date,
        notes=notes or None,
        weight=weight or 0.0,
        emergency_contact_name=(emergency_contact_name or "").strip() or None,
        emergency_contact_phone=(emergency_contact_phone or "").strip() or None,
    )
    db.add(patient)
    db.commit()
    return redirect_with_message(f"/?selected_patient_id={patient.id}", "Пациент добавлен")


@router.post("/patients/{patient_id}/update", response_class=HTMLResponse)
def update_patient_page(
    request: Request,
    patient_id: int,
    name: str = Form(...),
    date_of_birth: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    weight: float | None = Form(default=None),
    emergency_contact_name: str | None = Form(default=None),
    emergency_contact_phone: str | None = Form(default=None),
    current_screen: str = Form(default="main"),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    history_sort: str | None = Form(default=None),
    date_preset: str | None = Form(default=None),
    child_tab: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    clean_name = name.strip()
    if not clean_name:
        message = "Имя пациента не может быть пустым"
        if request.headers.get("hx-request") == "true":
            context = build_dashboard_context(request=request, user=user, db=db, current_screen=current_screen, selected_patient_id=patient_id, chart_type=chart_type, chart_lab_test=chart_lab_test, history_type=history_type, history_date_from=history_date_from, history_date_to=history_date_to, history_sort=history_sort, date_preset=date_preset, child_tab=child_tab, edit_patient=True, message=message, is_error=True)
            return templates.TemplateResponse(request, "partials/patient_block.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient_id}", message, is_error=True)
    try:
        parsed_date = date.fromisoformat(date_of_birth) if date_of_birth else None
    except ValueError:
        message = "Неверный формат даты"
        if request.headers.get("hx-request") == "true":
            context = build_dashboard_context(request=request, user=user, db=db, current_screen=current_screen, selected_patient_id=patient_id, chart_type=chart_type, chart_lab_test=chart_lab_test, history_type=history_type, history_date_from=history_date_from, history_date_to=history_date_to, history_sort=history_sort, date_preset=date_preset, child_tab=child_tab, edit_patient=True, message=message, is_error=True)
            return templates.TemplateResponse(request, "partials/patient_block.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient_id}", message, is_error=True)
    patient.name = clean_name
    patient.date_of_birth = parsed_date
    patient.notes = notes.strip() if notes and notes.strip() else None
    if weight is not None:
        patient.weight = weight
    patient.emergency_contact_name = (emergency_contact_name or "").strip() or None
    patient.emergency_contact_phone = (emergency_contact_phone or "").strip() or None
    db.add(patient)
    db.commit()
    db.refresh(patient)
    if request.headers.get("hx-request") == "true":
        context = build_dashboard_context(request=request, user=user, db=db, current_screen=current_screen, selected_patient_id=patient_id, chart_type=chart_type, chart_lab_test=chart_lab_test, history_type=history_type, history_date_from=history_date_from, history_date_to=history_date_to, history_sort=history_sort, date_preset=date_preset, child_tab=child_tab, message="Данные пациента сохранены", is_error=False)
        return templates.TemplateResponse(request, "partials/patient_block.html", context)
    screen_path = {"graph": "/graph", "history": "/history", "extra": "/extra", "emergency": "/emergency"}.get(current_screen, "/")
    return redirect_with_message(f"{screen_path}?selected_patient_id={patient_id}", "Данные пациента сохранены")


@router.post("/patients/{patient_id}/emergency-info")
def save_emergency_info_page(
    patient_id: int,
    blood_type: str | None = Form(default=None),
    allergies: str | None = Form(default=None),
    diagnoses: str | None = Form(default=None),
    permanent_medications: str | None = Form(default=None),
    emergency_contacts: str | None = Form(default=None),
    emergency_contact_name: str | None = Form(default=None),
    emergency_contact_phone: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    patient.blood_type = (blood_type or "").strip() or None
    patient.allergies = (allergies or "").strip() or None
    patient.chronic_diseases = (diagnoses or "").strip() or None
    patient.permanent_medications = (permanent_medications or "").strip() or None
    patient.emergency_contacts = (emergency_contacts or "").strip() or None
    patient.emergency_contact_name = (emergency_contact_name or "").strip() or None
    patient.emergency_contact_phone = (emergency_contact_phone or "").strip() or None
    db.commit()
    return redirect_with_message(f"/patient/emergency?selected_patient_id={patient.id}", "Экстренная информация сохранена")


@router.get("/patients/{patient_id}/export")
def export_patient_record_page(
    patient_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, payload = get_owned_patient_record(db, patient_id, user)
    log_audit_event(db, "patient_export", user, {"patient_id": patient.id})
    content = __import__("json").dumps(payload, ensure_ascii=False, indent=2)
    filename = f"patient-{patient.id}-export.json"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return Response(content=content, media_type="application/json; charset=utf-8", headers=headers)


@router.get("/patients/{patient_id}/print", response_class=HTMLResponse)
def print_patient_record_page(request: Request, patient_id: int, layout: str = "default", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_writable_patient_for_user(patient_id, user, db)
    return templates.TemplateResponse(request, "patient_print.html", {"request": request, "patient": patient, "observations": list_patient_history(db, patient, limit=20), "medications": list_patient_medications(db, patient), "emergency_info": get_patient_emergency_info(db, patient), "layout": layout})


@router.get("/patients/{patient_id}/print/medications", response_class=HTMLResponse)
def print_medications_page(request: Request, patient_id: int, layout: str = "default", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_writable_patient_for_user(patient_id, user, db)
    medications = list_patient_medications(db, patient)
    return templates.TemplateResponse(request, "medications_print.html", {"request": request, "patient": patient, "medications": medications, "layout": layout})


@router.get("/patients/{patient_id}/print/child", response_class=HTMLResponse)
def print_child_packet_page(request: Request, patient_id: int, layout: str = "school_trip", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_writable_patient_for_user(patient_id, user, db)
    return templates.TemplateResponse(request, "child_packet_print.html", {"request": request, "patient": patient, "layout": layout, "vaccines": list_patient_vaccine_records(db, patient), "health_events": list_patient_health_events(db, patient), "growth_records": list_patient_growth_records(db, patient)})


@router.get("/patients/{patient_id}/print/blood-pressure", response_class=HTMLResponse)
def print_blood_pressure_page(request: Request, patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_writable_patient_for_user(patient_id, user, db)
    observations = list_patient_history(db, patient, observation_type="blood_pressure", limit=30)
    return templates.TemplateResponse(request, "blood_pressure_print.html", {"request": request, "patient": patient, "observations": observations})


@router.get("/patients/{patient_id}/reminders.ics")
def export_reminders_ics(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_writable_patient_for_user(patient_id, user, db)
    medications = list_patient_medications(db, patient)
    log_audit_event(db, "reminders_export", user, {"patient_id": patient.id})
    calendar = build_medication_reminder_ics(patient.name, medications)
    filename = f"patient-{patient.id}-reminders.ics"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return Response(content=calendar, media_type="text/calendar; charset=utf-8", headers=headers)
