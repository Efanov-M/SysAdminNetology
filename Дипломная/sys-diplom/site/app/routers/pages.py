import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from datetime import UTC
from secrets import token_urlsafe
from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.dependencies import (
    can_comment_patient,
    can_write_patient,
    get_current_user,
    get_patient_access_role,
    get_patient_for_user,
    get_writable_patient_for_user,
)
from app.db import get_db
from app.models import AlertRule, CareEvent, ChildMedication, Document, EmergencyEvent, GrowthRecord, HealthEvent, InboxEvent, Invite, LabResult, MatrixProfile, Medication, Observation, Patient, PatientCheckin, PatientComment, PatientShare, Reminder, ReminderEvent, User, UserPatient, VaccineRecord
from app.exporters import build_backup_archive
from app.services.charts import build_chart_pdf, build_comments_pdf
from app.services.care import (
    acknowledge_inbox_item,
    build_today_items,
    build_care_event_ics,
    create_emergency_signal,
    build_simple_insights,
    check_threshold_alerts,
    get_or_create_alert_rule,
    get_recent_emergency_event,
    list_patient_alert_rules,
    list_relative_inbox_items,
    list_patient_events,
    list_patient_reminders,
    list_recent_checkins,
    summarize_inbox_by_patient,
)
from app.csrf import get_or_create_request_csrf_token
from app.services.document_processing import (
    build_uploaded_document,
    cleanup_document_files,
    get_document_active_path,
    queue_document_processing,
)
from app.services.audit import describe_audit_event, format_duration, log_audit_event
from app.services.records import (
    collect_family_record,
    get_owned_patient_record,
    list_audit_logs,
    list_comment_journal,
    list_family_invites,
    list_family_users,
    list_patient_child_medications,
    list_patient_documents,
    list_patient_growth_records,
    list_patient_health_events,
    get_patient_emergency_info,
    list_patient_history,
    list_patient_lab_test_names,
    list_patient_medications,
    list_patient_comments,
    list_patient_vaccine_records,
    list_user_patients,
)
from app.services.backup import restore_backup_archive
from app.services.health import get_worker_health, get_worker_pool_health
from app.services.lab_panels import LAB_PANEL_TEMPLATES
from app.services.medications import clear_drug_cache, fetch_medication_info, get_drug_cache_maintenance_report, get_drug_cache_summary, lookup_drug_cache, moderate_drug_cache, resolve_medication_query
from app.services.notifications import (
    get_active_matrix_link_token,
    get_matrix_profile,
    build_blood_pressure_message,
    build_lab_result_message,
    build_medication_created_message,
    build_medication_reminder_matrix_message,
    build_medication_reminder_message,
    process_notification_queue,
    send_matrix_message,
    send_matrix_target_message,
    send_notification,
    link_matrix_profile,
    start_matrix_link,
    unlink_matrix_profile,
)
from app.services.notification_queue import (
    build_admin_runbook,
    build_channel_degradation_warnings,
    build_diagnostics_bundle,
    build_incident_retention_summary,
    build_notification_incidents,
    build_operational_alerts,
    build_notification_queue_stats,
    build_sla_alerts,
    cleanup_incident_history,
    list_incident_history,
    list_notification_queue_items,
)
from app.services.pdf_import import import_medical_pdf
from app.services.restore_preview import apply_restore_wizard_preview, create_restore_wizard_preview, get_restore_wizard_preview
from app.security import hash_password, verify_password
from app.utils import (
    DOCTOR_TYPE_LABELS,
    DOCTOR_TYPE_OPTIONS,
    build_medication_reminder_ics,
    delete_upload_file,
    save_import_source_bytes,
    save_pdf_bytes,
    save_upload_file,
)


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["csrf_token"] = get_or_create_request_csrf_token
router = APIRouter(tags=["pages"])


def validate_pressure_values(sys: int, dia: int, pulse: int | None) -> str | None:
    if not 40 <= sys <= 300:
        return "SYS должен быть от 40 до 300"
    if not 30 <= dia <= 200:
        return "DIA должен быть от 30 до 200"
    if pulse is not None and not 20 <= pulse <= 250:
        return "Пульс должен быть от 20 до 250"
    return None


def parse_optional_time(value: str | None) -> time | None:
    if not value:
        return None
    return time.fromisoformat(value)


def parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def normalize_notification_channels(values: list[str] | None) -> list[str]:
    channels: list[str] = []
    for item in values or []:
        channel = (item or "").strip().lower()
        if channel and channel not in channels:
            channels.append(channel)
    return channels or ["log"]


def find_existing_client_entity(db: Session, model, client_id: str | None):
    if not client_id:
        return None
    return db.scalar(select(model).where(model.client_id == client_id))


def _pdf_review_dir() -> Path:
    path = settings.backup_path / "pdf_import_review"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pdf_review_meta_path(review_id: str) -> Path:
    return _pdf_review_dir() / f"{review_id}.json"


def _pdf_review_file_path(review_id: str) -> Path:
    return _pdf_review_dir() / f"{review_id}.pdf"


def redirect_with_message(url: str, message: str, is_error: bool = False) -> RedirectResponse:
    parts = urlsplit(url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params.update({"message": message, "error": str(int(is_error))})
    target_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_params), parts.fragment))
    return RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def require_family_owner(user: User) -> None:
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только владельцу семьи")


def get_valid_invite(db: Session, token: str | None) -> Invite | None:
    if not token:
        return None
    invite = db.scalar(select(Invite).where(Invite.token == token))
    if not invite:
        return None
    if invite.used or invite.expires_at < datetime.now(UTC).replace(tzinfo=None):
        return None
    return invite


def build_template_response(
    request: Request,
    template_name: str,
    context: dict,
    htmx_trigger: dict | None = None,
) -> HTMLResponse:
    response = templates.TemplateResponse(request, template_name, context)
    if htmx_trigger:
        response.headers["HX-Trigger"] = json.dumps(htmx_trigger)
    return response


def calculate_patient_age(date_of_birth: date | None) -> int | None:
    if not date_of_birth:
        return None
    today = date.today()
    years = today.year - date_of_birth.year
    if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return max(years, 0)


def patient_has_matrix_recipients(db: Session, patient: Patient) -> bool:
    return db.scalar(
        select(MatrixProfile.id)
        .join(User, User.id == MatrixProfile.user_id)
        .where(
            User.family_id == patient.family_id,
            MatrixProfile.matrix_user_id.is_not(None),
            MatrixProfile.is_linked.is_(True),
        )
        .limit(1)
    ) is not None


def parse_history_datetime_range(
    history_date_from: str | None,
    history_date_to: str | None,
) -> tuple[datetime | None, datetime | None]:
    date_from = None
    date_to = None
    if history_date_from:
        try:
            date_from = datetime.fromisoformat(f"{history_date_from}T00:00:00")
        except ValueError:
            pass
    if history_date_to:
        try:
            date_to = datetime.fromisoformat(f"{history_date_to}T23:59:59")
        except ValueError:
            pass
    return date_from, date_to


def apply_date_range_preset(
    history_date_from: str | None,
    history_date_to: str | None,
    date_preset: str | None,
) -> tuple[str | None, str | None, str]:
    preset = (date_preset or "").strip().lower()
    if preset not in {"today", "7d", "30d", "90d"}:
        return history_date_from, history_date_to, ""

    today = date.today()
    days = {"today": 1, "7d": 7, "30d": 30, "90d": 90}[preset]
    start_date = today - timedelta(days=days - 1)
    return start_date.isoformat(), today.isoformat(), preset


def build_dashboard_context(
    request: Request,
    user: User,
    db: Session,
    current_screen: str = "main",
    selected_patient_id: int | None = None,
    chart_type: str | None = None,
    chart_lab_test: str | None = None,
    medication_query: str | None = None,
    history_type: str | None = None,
    history_date_from: str | None = None,
    history_date_to: str | None = None,
    history_sort: str | None = None,
    date_preset: str | None = None,
    child_tab: str | None = None,
    edit_patient: bool = False,
    message: str | None = None,
    is_error: bool | None = None,
    form_errors: dict | None = None,
) -> dict:
    history_date_from, history_date_to, effective_date_preset = apply_date_range_preset(
        history_date_from,
        history_date_to,
        date_preset,
    )
    patients = list_user_patients(db, user)
    selected_patient = None
    selected_patient_can_edit = False
    selected_patient_can_comment = False
    selected_patient_access_role = "none"
    observations: list[dict] = []
    medications: list[Medication] = []
    documents: list[Document] = []
    medication_info_items: list[dict] = []
    lab_test_names: list[str] = []
    patient_comments: list[PatientComment] = []
    patient_reminders: list[Reminder] = []
    patient_events: list[CareEvent] = []
    patient_checkins: list[PatientCheckin] = []
    today_items: list[dict] = []
    simple_insights: list[str] = []
    latest_weight: dict | None = None
    latest_sugar: dict | None = None
    previous_weight: dict | None = None
    weight_delta: float | None = None
    weight_delta_label: str | None = None
    emergency_info: dict | None = None
    growth_records: list[GrowthRecord] = []
    vaccine_records: list[VaccineRecord] = []
    health_events: list[HealthEvent] = []
    child_medications: list[ChildMedication] = []
    child_history: list[dict] = []
    child_recent_vaccines: list[VaccineRecord] = []
    child_next_vaccine: VaccineRecord | None = None
    child_active_medications: list[ChildMedication] = []
    child_next_medication_reminder: Reminder | None = None
    inbox_items: list[PatientCheckin] = list_relative_inbox_items(db, user, limit=8)
    matrix_profile = get_matrix_profile(db, user)
    matrix_connected = bool(matrix_profile and matrix_profile.is_linked)
    selected_patient_alert_setting = None
    signal_actions_enabled = matrix_connected
    patient_age: int | None = None

    if patients:
        if selected_patient_id is None:
            selected_patient = patients[0]
        else:
            selected_patient = next((item for item in patients if item.id == selected_patient_id), patients[0])

    if selected_patient:
        selected_patient_can_edit = can_write_patient(selected_patient, user)
        selected_patient_can_comment = can_comment_patient(selected_patient, user)
        selected_patient_access_role = get_patient_access_role(selected_patient, user)
        patient_age = calculate_patient_age(selected_patient.date_of_birth)
        date_from, date_to = parse_history_datetime_range(history_date_from, history_date_to)

        documents = list_patient_documents(db, selected_patient)
        patient_comments = list_patient_comments(db, selected_patient, limit=20)
        patient_reminders = list_patient_reminders(db, selected_patient)
        patient_events = list_patient_events(db, selected_patient)
        patient_checkins = list_recent_checkins(db, selected_patient, limit=20)
        today_items = build_today_items(db, selected_patient, patient_reminders, patient_events)
        emergency_info = get_patient_emergency_info(db, selected_patient)
        selected_patient_alert_setting = next(
            (item for item in list_patient_alert_rules(db, selected_patient) if item.type == "blood_pressure"),
            None,
        )
        signal_actions_enabled = patient_has_matrix_recipients(db, selected_patient)
        if selected_patient.patient_type == "child":
            growth_records = list_patient_growth_records(db, selected_patient)
            vaccine_records = list_patient_vaccine_records(db, selected_patient)
            health_events = list_patient_health_events(db, selected_patient)
            child_medications = list_patient_child_medications(db, selected_patient)
            child_recent_vaccines = sorted(
                vaccine_records,
                key=lambda item: item.date or date.min,
                reverse=True,
            )[:2]
            planned_vaccines = sorted(
                [item for item in vaccine_records if item.status == "planned"],
                key=lambda item: item.date or date.max,
            )
            child_next_vaccine = planned_vaccines[0] if planned_vaccines else None
            child_active_medications = sorted(
                child_medications,
                key=lambda item: item.date,
                reverse=True,
            )[:3]
            medication_reminders = sorted(
                [
                    reminder
                    for reminder in patient_reminders
                    if reminder.reminder_type in {"child_medication", "medication"}
                ],
                key=lambda reminder: reminder.time_of_day,
            )
            child_next_medication_reminder = medication_reminders[0] if medication_reminders else None
            child_history = []
            for item in growth_records:
                child_history.append({"entry_type": "growth", "date": item.date, "title": "Рост и вес", "subtitle": f"Рост: {item.height or '—'} см • Вес: {item.weight or '—'} кг", "id": item.id})
            for item in health_events:
                subtitle_parts = []
                if item.temperature is not None:
                    subtitle_parts.append(f"Температура: {item.temperature} °C")
                if item.symptoms:
                    subtitle_parts.append(item.symptoms)
                if item.comment:
                    subtitle_parts.append(item.comment)
                child_history.append({"entry_type": "health_event", "date": item.date, "title": "Событие здоровья", "subtitle": " • ".join(subtitle_parts) or "Без деталей", "id": item.id})
            for item in child_medications:
                child_history.append({"entry_type": "child_medication", "date": item.date, "title": item.name, "subtitle": " • ".join(part for part in [item.dosage, item.comment] if part) or "Лекарство", "id": item.id})
            for item in vaccine_records:
                child_history.append({"entry_type": "vaccine", "date": item.date or date.today(), "title": item.name, "subtitle": f"{'Сделана' if item.status == 'done' else 'Планируется'}{f' • {item.comment}' if item.comment else ''}", "id": item.id})
            child_history.sort(key=lambda item: item["date"], reverse=(history_sort or "desc") != "asc")
        else:
            observations = list_patient_history(
                db,
                selected_patient,
                history_type,
                date_from,
                date_to,
                sort_order=history_sort or "desc",
                limit=50,
            )
            medications = list_patient_medications(db, selected_patient)
            lab_test_names = list_patient_lab_test_names(db, selected_patient)
            weight_observations = [item for item in observations if item.get("type") == "weight"]
            sugar_observations = [item for item in observations if item.get("type") == "blood_sugar"]
            latest_weight = weight_observations[0] if weight_observations else None
            latest_sugar = sugar_observations[0] if sugar_observations else None
            previous_weight = weight_observations[1] if len(weight_observations) > 1 else None
            if latest_weight and previous_weight:
                latest_weight_value = float(latest_weight.get("value", {}).get("value", 0) or 0)
                previous_weight_value = float(previous_weight.get("value", {}).get("value", 0) or 0)
                weight_delta = round(latest_weight_value - previous_weight_value, 1)
                day_diff = abs((latest_weight["created_at"].date() - previous_weight["created_at"].date()).days)
                weight_delta_label = "за неделю" if day_diff <= 8 else "с прошлой записи"
            if (chart_type or "blood_pressure") == "lab_result" and not chart_lab_test and lab_test_names:
                chart_lab_test = lab_test_names[0]
            simple_insights = build_simple_insights(selected_patient, observations, medications, patient_checkins)

    return {
        "request": request,
        "now": datetime.now(),
        "user": user,
        "current_screen": current_screen,
        "screen_path": {
            "main": "/",
            "graph": "/graph",
            "history": "/history",
            "extra": "/extra",
            "planner": "/planner",
            "control": "/planner",
            "emergency": "/emergency",
        }.get(current_screen, "/"),
        "patients": patients,
        "selected_patient": selected_patient,
        "selected_patient_can_edit": selected_patient_can_edit,
        "selected_patient_can_comment": selected_patient_can_comment,
        "selected_patient_access_role": selected_patient_access_role,
        "patient_age": patient_age,
        "observations": observations,
        "medications": medications,
        "documents": documents,
        "patient_comments": patient_comments,
        "patient_reminders": patient_reminders,
        "patient_events": patient_events,
        "patient_checkins": patient_checkins,
        "today_items": today_items,
        "simple_insights": simple_insights,
        "latest_weight": latest_weight,
        "latest_sugar": latest_sugar,
        "previous_weight": previous_weight,
        "weight_delta": weight_delta,
        "weight_delta_label": weight_delta_label,
        "emergency_info": emergency_info,
        "growth_records": growth_records,
        "vaccine_records": vaccine_records,
        "health_events": health_events,
        "child_medications": child_medications,
        "child_history": child_history,
        "child_recent_vaccines": child_recent_vaccines,
        "child_next_vaccine": child_next_vaccine,
        "child_active_medications": child_active_medications,
        "child_next_medication_reminder": child_next_medication_reminder,
        "inbox_items": inbox_items,
        "matrix_profile": matrix_profile,
        "matrix_connected": matrix_connected,
        "selected_patient_alert_setting": selected_patient_alert_setting,
        "signal_actions_enabled": signal_actions_enabled,
        "child_tab": child_tab or "vaccines",
        "patient_edit_mode": edit_patient,
        "lab_panels": LAB_PANEL_TEMPLATES,
        "chart_type": chart_type or "blood_pressure",
        "chart_lab_test": chart_lab_test or "",
        "lab_test_names": lab_test_names,
        "history_type": history_type or "",
        "history_date_from": history_date_from or "",
        "history_date_to": history_date_to or "",
        "history_sort": history_sort or "desc",
        "date_preset": effective_date_preset,
        "medication_query": medication_query or "",
        "medication_info_items": medication_info_items,
        "message": request.query_params.get("message") if message is None else message,
        "is_error": request.query_params.get("error") == "1" if is_error is None else is_error,
        "form_errors": form_errors or {},
        "doctor_type_options": DOCTOR_TYPE_OPTIONS,
        "doctor_type_labels": DOCTOR_TYPE_LABELS,
    }


def build_audit_entry_view(item) -> dict:
    details = item.details or {}
    return {
        "id": item.id,
        "action": item.action,
        "action_label": describe_audit_event(item.action, details),
        "details": details,
        "created_at": item.created_at,
        "duration_label": format_duration(details.get("duration_ms")),
        "is_backup_event": item.action in {"backup_download", "backup_restore"},
        "status": details.get("status", "success"),
    }


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": request.query_params.get("error")},
    )


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, token: str | None = None, db: Session = Depends(get_db)):
    invite = get_valid_invite(db, token)
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "request": request,
            "error": request.query_params.get("error"),
            "invite": invite,
            "token": token or "",
            "allow_registration": settings.allow_registration,
            "bootstrap_allowed": (db.scalar(select(User.id).limit(1)) is None),
        },
    )


@router.get("/partials/medications", response_class=HTMLResponse)
def dashboard_medications_partial(
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
    return templates.TemplateResponse(request, "partials/medications.html", context)


@router.get("/partials/comments", response_class=HTMLResponse)
def dashboard_comments_partial(
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
    return templates.TemplateResponse(request, "partials/comments.html", context)


@router.get("/partials/shares", response_class=HTMLResponse)
def dashboard_shares_partial(
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
    return templates.TemplateResponse(request, "partials/shares.html", context)




@router.post("/patients/{patient_id}/comments")
def add_patient_comment_page(
    request: Request,
    patient_id: int,
    category: str = Form(default="note"),
    pinned: str | None = Form(default=None),
    text: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    if not can_comment_patient(patient, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Комментарии для вас недоступны")
    if not text.strip():
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Комментарий не может быть пустым",
                is_error=True,
                form_errors={"text": "Напишите короткий комментарий"},
            )
            return build_template_response(request, "partials/comments.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Комментарий не может быть пустым", is_error=True)
    should_pin = pinned == "on" and can_write_patient(patient, user)
    comment = PatientComment(patient_id=patient.id, user_id=user.id, category=category.strip() or "note", pinned=should_pin, text=text.strip())
    db.add(comment)
    db.commit()
    if should_pin:
        log_audit_event(
            db,
            "patient_comment_pin",
            user,
            {"patient_id": patient.id, "comment_id": comment.id, "category": comment.category, "source": "create"},
        )
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient.id,
            message="Комментарий сохранён",
            is_error=False,
        )
        return build_template_response(request, "partials/comments.html", context)
    return redirect_with_message(f"/?selected_patient_id={patient.id}", "Комментарий сохранён")


@router.post("/patients/{patient_id}/comments/{comment_id}/pin")
def pin_patient_comment_page(
    request: Request,
    patient_id: int,
    comment_id: int,
    pinned: str = Form(default="on"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    if not can_write_patient(patient, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только владелец может закреплять заметки")
    comment = db.scalar(select(PatientComment).where(PatientComment.id == comment_id, PatientComment.patient_id == patient.id))
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден")
    comment.pinned = pinned == "on"
    db.add(comment)
    db.commit()
    log_audit_event(
        db,
        "patient_comment_pin" if comment.pinned else "patient_comment_unpin",
        user,
        {"patient_id": patient.id, "comment_id": comment.id, "category": comment.category},
    )
    message = "Заметка закреплена" if comment.pinned else "Закрепление снято"
    if is_htmx_request(request):
        context = build_dashboard_context(request, user, db, selected_patient_id=patient.id, message=message, is_error=False)
        return build_template_response(request, "partials/comments.html", context)
    return redirect_with_message(f"/?selected_patient_id={patient.id}", message)


@router.post("/patients/{patient_id}/comments/{comment_id}/delete")
def delete_patient_comment_page(
    request: Request,
    patient_id: int,
    comment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_patient_for_user(patient_id, user, db)
    comment = db.scalar(
        select(PatientComment).where(PatientComment.id == comment_id, PatientComment.patient_id == patient.id)
    )
    if comment and (comment.user_id == user.id or can_write_patient(patient, user)):
        db.delete(comment)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient.id,
            message="Комментарий удалён",
            is_error=False,
        )
        return build_template_response(request, "partials/comments.html", context)
    return redirect_with_message(f"/?selected_patient_id={patient.id}", "Комментарий удалён")


@router.post("/blood-pressure")
def create_blood_pressure_page(
    request: Request,
    patient_id: int = Form(...),
    client_id: str | None = Form(default=None),
    sys: int = Form(...),
    dia: int = Form(...),
    pulse: int | None = Form(default=None),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    history_sort: str | None = Form(default=None),
    date_preset: str | None = Form(default=None),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    existing_observation = find_existing_client_entity(db, Observation, client_id)
    if existing_observation:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                selected_patient_id=patient.id,
                history_type=history_type,
                history_date_from=history_date_from,
                history_date_to=history_date_to,
                history_sort=history_sort,
                date_preset=date_preset,
                chart_type=chart_type,
                chart_lab_test=chart_lab_test,
                message="Давление уже синхронизировано",
                is_error=False,
            )
            return build_template_response(
                request,
                "partials/pressure_form.html",
                context,
                htmx_trigger={"historyChanged": True, "chartChanged": True},
            )
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Давление уже синхронизировано")
    validation_error = validate_pressure_values(sys, dia, pulse)
    if validation_error:
        if is_htmx_request(request):
            form_errors = {}
            if "SYS" in validation_error:
                form_errors["sys"] = validation_error
            elif "DIA" in validation_error:
                form_errors["dia"] = validation_error
            else:
                form_errors["pulse"] = validation_error
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                selected_patient_id=patient.id,
                history_type=history_type,
                history_date_from=history_date_from,
                history_date_to=history_date_to,
                history_sort=history_sort,
                date_preset=date_preset,
                chart_type=chart_type,
                chart_lab_test=chart_lab_test,
                message=validation_error,
                is_error=True,
                form_errors=form_errors,
            )
            return build_template_response(request, "partials/pressure_form.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", validation_error, is_error=True)
    observation = Observation(
        patient_id=patient.id,
        client_id=(client_id or "").strip() or None,
        type="blood_pressure",
        value={"sys": sys, "dia": dia, "pulse": pulse},
    )
    db.add(observation)
    db.commit()
    send_matrix_message(user, build_blood_pressure_message(patient.name, sys, dia, pulse, observation.created_at))
    check_threshold_alerts(db, patient, "blood_pressure", observation.value, observation.created_at)
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient.id,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            history_sort=history_sort,
            date_preset=date_preset,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            message="Давление сохранено",
            is_error=False,
        )
        return build_template_response(
            request,
            "partials/pressure_form.html",
            context,
            htmx_trigger={"historyChanged": True, "chartChanged": True},
        )
    return redirect_with_message(f"/?selected_patient_id={patient.id}", "Давление сохранено")


@router.post("/measurements/save")
def save_main_measurements_page(
    request: Request,
    patient_id: int = Form(...),
    sys: int | None = Form(default=None),
    dia: int | None = Form(default=None),
    pulse: int | None = Form(default=None),
    blood_sugar_value: float | None = Form(default=None),
    temperature_value: float | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)

    has_pressure = sys is not None or dia is not None or pulse is not None
    has_sugar = blood_sugar_value is not None
    has_temperature = temperature_value is not None
    if not any([has_pressure, has_sugar, has_temperature]):
        message = "Введите хотя бы один показатель"
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                current_screen="main",
                selected_patient_id=patient.id,
                message=message,
                is_error=True,
            )
            return build_template_response(request, "partials/pressure_form.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", message, is_error=True)

    if has_pressure:
        if sys is None or dia is None:
            message = "Для давления заполните SYS и DIA"
            if is_htmx_request(request):
                context = build_dashboard_context(
                    request=request,
                    user=user,
                    db=db,
                    current_screen="main",
                    selected_patient_id=patient.id,
                    message=message,
                    is_error=True,
                )
                return build_template_response(request, "partials/pressure_form.html", context)
            return redirect_with_message(f"/?selected_patient_id={patient.id}", message, is_error=True)
        validation_error = validate_pressure_values(sys, dia, pulse)
        if validation_error:
            if is_htmx_request(request):
                context = build_dashboard_context(
                    request=request,
                    user=user,
                    db=db,
                    current_screen="main",
                    selected_patient_id=patient.id,
                    message=validation_error,
                    is_error=True,
                )
                return build_template_response(request, "partials/pressure_form.html", context)
            return redirect_with_message(f"/?selected_patient_id={patient.id}", validation_error, is_error=True)
        observation = Observation(
            patient_id=patient.id,
            type="blood_pressure",
            value={"sys": sys, "dia": dia, "pulse": pulse},
        )
        db.add(observation)
        db.flush()
        send_matrix_message(user, build_blood_pressure_message(patient.name, sys, dia, pulse, observation.created_at))
        check_threshold_alerts(db, patient, "blood_pressure", observation.value, observation.created_at)

    if has_sugar:
        sugar_observation = Observation(
            patient_id=patient.id,
            type="blood_sugar",
            value={"value": blood_sugar_value, "unit": "ммоль/л", "label": None},
        )
        db.add(sugar_observation)
        db.flush()
        check_threshold_alerts(db, patient, "blood_sugar", sugar_observation.value, sugar_observation.created_at)

    if has_temperature:
        db.add(
            Observation(
                patient_id=patient.id,
                type="temperature",
                value={"value": temperature_value, "unit": "°C", "label": None},
            )
        )

    db.commit()
    success_message = "Показатели сохранены"
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            current_screen="main",
            selected_patient_id=patient.id,
            message=success_message,
            is_error=False,
        )
        return build_template_response(
            request,
            "partials/pressure_form.html",
            context,
            htmx_trigger={"historyChanged": True, "chartChanged": True},
        )
    return redirect_with_message(f"/?selected_patient_id={patient.id}", success_message)


@router.post("/observations/quick")
def create_quick_observation_page(
    request: Request,
    patient_id: int = Form(...),
    client_id: str | None = Form(default=None),
    observation_kind: str = Form(...),
    value: float | None = Form(default=None),
    unit: str | None = Form(default=None),
    label: str | None = Form(default=None),
    test_name: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    existing_observation = find_existing_client_entity(db, Observation, client_id)
    if existing_observation:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                current_screen="main",
                selected_patient_id=patient.id,
                message="Запись уже синхронизирована",
                is_error=False,
            )
            return build_template_response(
                request,
                "partials/pressure_form.html",
                context,
                htmx_trigger={"historyChanged": True, "chartChanged": True},
            )
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Запись уже синхронизирована")

    if observation_kind not in {"blood_sugar", "temperature", "weight", "lab_result"}:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                current_screen="main",
                selected_patient_id=patient.id,
                message="Неизвестный тип показателя",
                is_error=True,
            )
            return build_template_response(request, "partials/pressure_form.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Неизвестный тип показателя", is_error=True)

    if observation_kind == "lab_result":
        if not test_name or value is None:
            if is_htmx_request(request):
                context = build_dashboard_context(
                    request=request,
                    user=user,
                    db=db,
                    current_screen="main",
                    selected_patient_id=patient.id,
                    message="Для анализа крови нужны название и значение",
                    is_error=True,
                )
                return build_template_response(request, "partials/pressure_form.html", context)
            return redirect_with_message(
                f"/?selected_patient_id={patient.id}",
                "Для анализа крови нужны название и значение",
                is_error=True,
            )
        lab_result = LabResult(
            patient_id=patient.id,
            test_name=test_name.strip(),
            value=value,
            unit=unit or None,
        )
        db.add(lab_result)
        db.commit()
        send_matrix_message(
            user,
            build_lab_result_message(
                patient.name,
                lab_result.test_name,
                lab_result.value,
                lab_result.unit,
                lab_result.created_at,
            ),
        )
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                current_screen="main",
                selected_patient_id=patient.id,
                message="Показатель сохранён",
                is_error=False,
            )
            return build_template_response(
                request,
                "partials/pressure_form.html",
                context,
                htmx_trigger={"historyChanged": True, "chartChanged": True},
            )
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Показатель сохранён")
    else:
        if value is None:
            if is_htmx_request(request):
                context = build_dashboard_context(
                    request=request,
                    user=user,
                    db=db,
                    current_screen="main",
                    selected_patient_id=patient.id,
                    message="Укажите значение",
                    is_error=True,
                )
                return build_template_response(request, "partials/pressure_form.html", context)
            return redirect_with_message(f"/?selected_patient_id={patient.id}", "Укажите значение", is_error=True)
        observation = Observation(
            patient_id=patient.id,
            client_id=(client_id or "").strip() or None,
            type=observation_kind,
            value={"value": value, "unit": unit or None, "label": label or None},
        )
        if observation_kind == "weight":
            patient.weight = value
            db.add(patient)

    db.add(observation)
    db.commit()
    if observation_kind == "blood_sugar":
        check_threshold_alerts(db, patient, "blood_sugar", observation.value, observation.created_at)
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            current_screen="main",
            selected_patient_id=patient.id,
            message="Показатель сохранён",
            is_error=False,
        )
        return build_template_response(
            request,
            "partials/pressure_form.html",
            context,
            htmx_trigger={"historyChanged": True, "chartChanged": True},
        )
    return redirect_with_message(f"/?selected_patient_id={patient.id}", "Показатель сохранён")


@router.post("/observations/panel")
async def create_panel_observations_page(
    request: Request,
    patient_id: int = Form(...),
    panel_type: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    panel = LAB_PANEL_TEMPLATES.get(panel_type)
    if not panel:
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Неизвестная панель анализа", is_error=True)

    form = await request.form()
    saved = 0
    for test in panel["tests"]:
        field_name = f"panel_{panel_type}_{test['name']}"
        raw_value = form.get(field_name)
        if raw_value in (None, ""):
            continue
        lab_result = LabResult(
            patient_id=patient.id,
            panel_name=panel["title"],
            test_name=test["name"],
            value=float(raw_value),
            unit=test["unit"],
            reference_low=test.get("reference_low"),
            reference_high=test.get("reference_high"),
            reference_text=test.get("reference_text"),
        )
        db.add(lab_result)
        saved += 1

    if saved == 0:
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Заполните хотя бы одно поле панели", is_error=True)

    db.commit()
    send_matrix_message(
        user,
        "\n".join(
            [
                f"Пациент: {patient.name}",
                f"Панель анализов: {panel['title']}",
                f"Сохранено показателей: {saved}",
                f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            ]
        ),
    )
    return redirect_with_message(f"/?selected_patient_id={patient.id}", f"Сохранено показателей: {saved}")


@router.post("/patients/{patient_id}/checkins/medication")
def mark_medication_taken_page(
    patient_id: int,
    request: Request,
    medication_id: int | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    details: dict = {}
    if medication_id is not None:
        medication = db.scalar(select(Medication).where(Medication.id == medication_id, Medication.patient_id == patient.id))
        if medication:
            details = {"medication_id": medication.id, "medication_name": medication.name}
    checkin = PatientCheckin(patient_id=patient.id, user_id=user.id, checkin_type="medication_taken", details=details)
    db.add(checkin)
    db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(request=request, user=user, db=db, selected_patient_id=patient.id, message="Приём лекарств отмечен", is_error=False)
        return templates.TemplateResponse(request, "simple_mode.html", context)
    return redirect_with_message(f"/simple?selected_patient_id={patient.id}", "Приём лекарств отмечен")


@router.post("/patients/{patient_id}/medications/{medication_id}/taken")
def mark_medication_taken_from_card_page(
    patient_id: int,
    medication_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    medication = db.scalar(select(Medication).where(Medication.id == medication_id, Medication.patient_id == patient.id))
    if not medication:
        return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Лекарство не найдено", is_error=True)
    checkin = PatientCheckin(
        patient_id=patient.id,
        user_id=user.id,
        checkin_type="medication_taken",
        details={"medication_id": medication.id, "medication_name": medication.name},
    )
    db.add(checkin)
    db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(request=request, user=user, db=db, selected_patient_id=patient.id, current_screen="extra", message=f"Приём {medication.name} отмечен", is_error=False)
        return build_template_response(request, "partials/medications.html", context)
    return redirect_with_message(f"/extra?selected_patient_id={patient.id}", f"Приём {medication.name} отмечен")


@router.post("/patients/{patient_id}/emergency")
@router.post("/patients/{patient_id}/status")
def patient_status_signal_page(
    patient_id: int,
    request: Request,
    status_kind: str = Form(default="bad"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    if status_kind not in {"ok", "bad"}:
        return redirect_with_message(f"/simple?selected_patient_id={patient.id}", "Неизвестный сигнал состояния", is_error=True)

    if not build_dashboard_context(request=request, user=user, db=db, selected_patient_id=patient.id).get("signal_actions_enabled"):
        message = "Чтобы отправлять сигнал, подключите Matrix"
        if is_htmx_request(request):
            context = build_dashboard_context(request=request, user=user, db=db, selected_patient_id=patient.id, message=message, is_error=True)
            return templates.TemplateResponse(request, "simple_mode.html", context)
        return redirect_with_message(f"/simple?selected_patient_id={patient.id}", message, is_error=True)

    if status_kind == "bad":
        recent_bad_signal = get_recent_emergency_event(db, patient, minutes=5)
        if recent_bad_signal:
            message = "Сигнал уже отправлен. Следующий можно отправить через 5 минут."
            if is_htmx_request(request):
                context = build_dashboard_context(request=request, user=user, db=db, selected_patient_id=patient.id, message=message, is_error=True)
                return templates.TemplateResponse(request, "simple_mode.html", context)
            return redirect_with_message(f"/simple?selected_patient_id={patient.id}", message, is_error=True)

    label = "Я в порядке" if status_kind == "ok" else "Мне плохо"
    response_message = label
    is_error_response = False
    if status_kind == "bad":
        emergency_event, results = create_emergency_signal(db, patient, "Мне плохо")
        matrix_not_ready = not any(item.get("status") == "sent" for item in results)
        if matrix_not_ready:
            response_message = "Чтобы отправлять сигнал, подключите Matrix"
            is_error_response = True
        log_audit_event(
            db,
            "patient_emergency_signal",
            user,
            {
                "patient_id": patient.id,
                "emergency_event_id": emergency_event.id,
                "channels": results,
                "status": "sent" if any(item.get("status") == "sent" for item in results) else "failed",
            },
        )
    else:
        checkin = PatientCheckin(
            patient_id=patient.id,
            user_id=user.id,
            checkin_type="feeling_ok",
            details={"label": label, "signal_type": status_kind},
        )
        db.add(checkin)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(request=request, user=user, db=db, selected_patient_id=patient.id, message=response_message, is_error=is_error_response)
        return templates.TemplateResponse(request, "simple_mode.html", context)
    return redirect_with_message(f"/simple?selected_patient_id={patient.id}", response_message, is_error=is_error_response)


@router.post("/patients/{patient_id}/reminders")
def create_patient_reminder_page(
    patient_id: int,
    title: str = Form(...),
    reminder_type: str = Form(...),
    time_of_day: str = Form(...),
    repeat_mode: str = Form(default="daily"),
    one_time_date: str | None = Form(default=None),
    weekdays: list[str] | None = Form(default=None),
    recipient_mode: str = Form(default="family"),
    recipient_user_id: int | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    reminder = Reminder(
        patient_id=patient.id,
        title=title.strip(),
        type="visit" if reminder_type == "doctor_visit" else reminder_type,
        time=parse_optional_time(time_of_day) or time(9, 0),
        repeat_type=repeat_mode if repeat_mode in {"daily", "weekly", "once"} else "daily",
        enabled=True,
    )
    db.add(reminder)
    db.commit()
    return redirect_with_message(f"/planner?selected_patient_id={patient.id}", "Напоминание сохранено")


@router.post("/patients/{patient_id}/events")
def create_care_event_page(
    patient_id: int,
    client_id: str | None = Form(default=None),
    title: str = Form(default="Визит к врачу"),
    scheduled_at: str = Form(...),
    doctor: str | None = Form(default=None),
    place: str | None = Form(default=None),
    comment: str | None = Form(default=None),
    remind_day_before: str | None = Form(default=None),
    remind_hours_before: int | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    existing_event = find_existing_client_entity(db, CareEvent, client_id)
    if existing_event:
        return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Событие уже синхронизировано")
    event = CareEvent(
        patient_id=patient.id,
        client_id=(client_id or "").strip() or None,
        title=(title or "Визит к врачу").strip(),
        scheduled_at=datetime.fromisoformat(scheduled_at),
        doctor=(doctor or "").strip() or None,
        place=(place or "").strip() or None,
        comment=(comment or "").strip() or None,
        remind_day_before=remind_day_before == "on",
        remind_hours_before=remind_hours_before,
    )
    db.add(event)
    db.commit()
    return redirect_with_message(f"/planner?selected_patient_id={patient.id}", "Событие сохранено")


@router.post("/patients/{patient_id}/reminders/{reminder_id}/done")
def complete_patient_reminder_page(
    patient_id: int,
    reminder_id: int,
    return_to: str | None = Form(default="main"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    reminder = db.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.patient_id == patient.id))
    reminder_event = None
    if reminder:
        reminder_event = db.scalar(
            select(ReminderEvent)
            .where(
                ReminderEvent.reminder_id == reminder.id,
                ReminderEvent.patient_id == patient.id,
                ReminderEvent.status == "pending",
            )
            .order_by(ReminderEvent.id.desc())
            .limit(1)
        )
    else:
        reminder_event = db.scalar(
            select(ReminderEvent).where(ReminderEvent.id == reminder_id, ReminderEvent.patient_id == patient.id)
        )
        reminder = reminder_event.reminder if reminder_event else None
    if reminder_event:
        reminder_event.status = "done"
        reminder_event.done_at = datetime.now()
        if reminder and reminder.repeat_type == "once":
            reminder.enabled = False
        db.commit()
    else:
        if reminder:
            event = ReminderEvent(
                reminder_id=reminder.id,
                patient_id=patient.id,
                status="done",
                scheduled_at=datetime.combine(date.today(), reminder.time),
                done_at=datetime.now(),
            )
            if reminder.repeat_type == "once":
                reminder.enabled = False
            db.add(event)
            db.commit()
    target = "/planner" if return_to in {"control", "planner"} else "/"
    return redirect_with_message(f"{target}?selected_patient_id={patient.id}", "Действие отмечено как выполненное")


@router.post("/patients/{patient_id}/reminders/{reminder_id}/snooze")
def snooze_patient_reminder_page(
    patient_id: int,
    reminder_id: int,
    return_to: str | None = Form(default="main"),
    hours: int = Form(default=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    reminder = db.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.patient_id == patient.id))
    reminder_event = None
    if reminder:
        reminder_event = db.scalar(
            select(ReminderEvent)
            .where(
                ReminderEvent.reminder_id == reminder.id,
                ReminderEvent.patient_id == patient.id,
                ReminderEvent.status == "pending",
            )
            .order_by(ReminderEvent.id.desc())
            .limit(1)
        )
    else:
        reminder_event = db.scalar(
            select(ReminderEvent).where(ReminderEvent.id == reminder_id, ReminderEvent.patient_id == patient.id)
        )
    if reminder_event:
        reminder_event.scheduled_at = reminder_event.scheduled_at + timedelta(hours=max(1, min(hours, 24)))
        db.commit()
    else:
        if reminder:
            event = ReminderEvent(
                reminder_id=reminder.id,
                patient_id=patient.id,
                status="pending",
                scheduled_at=datetime.now() + timedelta(hours=max(1, min(hours, 24))),
            )
            db.add(event)
            db.commit()
    target = "/planner" if return_to in {"control", "planner"} else "/"
    return redirect_with_message(f"{target}?selected_patient_id={patient.id}", "Напоминание отложено")


@router.post("/patients/{patient_id}/events/{event_id}/done")
def complete_care_event_page(
    patient_id: int,
    event_id: int,
    return_to: str | None = Form(default="main"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    event = db.scalar(select(CareEvent).where(CareEvent.id == event_id, CareEvent.patient_id == patient.id))
    if event:
        event.completed_at = datetime.now()
        event.status = "completed"
        event.snoozed_until = None
        db.commit()
    target = "/planner" if return_to in {"control", "planner"} else "/"
    return redirect_with_message(f"{target}?selected_patient_id={patient.id}", "Визит отмечен как выполненный")


@router.post("/patients/{patient_id}/events/{event_id}/snooze")
def snooze_care_event_page(
    patient_id: int,
    event_id: int,
    return_to: str | None = Form(default="main"),
    hours: int = Form(default=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    event = db.scalar(select(CareEvent).where(CareEvent.id == event_id, CareEvent.patient_id == patient.id))
    if event:
        event.snoozed_until = (event.snoozed_until or event.scheduled_at) + timedelta(hours=max(1, min(hours, 24)))
        event.status = "scheduled"
        db.commit()
    target = "/planner" if return_to in {"control", "planner"} else "/"
    return redirect_with_message(f"{target}?selected_patient_id={patient.id}", "Визит отложен")


@router.post("/patients/{patient_id}/growth")
def create_growth_record_page(
    patient_id: int,
    height: float | None = Form(default=None),
    weight: float | None = Form(default=None),
    record_date: str | None = Form(default=None),
    next_url: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    target_url = next_url or f"/?selected_patient_id={patient.id}"
    if patient.patient_type != "child":
        return redirect_with_message(target_url, "Этот экран доступен только для ребёнка", is_error=True)
    if height is None and weight is None:
        return redirect_with_message(target_url, "Укажите рост, вес или оба показателя", is_error=True)
    try:
        parsed_date = date.fromisoformat(record_date) if record_date else date.today()
    except ValueError:
        return redirect_with_message(target_url, "Неверный формат даты", is_error=True)
    db.add(GrowthRecord(patient_id=patient.id, height=height, weight=weight, date=parsed_date))
    db.commit()
    return redirect_with_message(target_url, "Рост и вес сохранены")


@router.post("/patients/{patient_id}/child-health-events")
def create_health_event_page(
    patient_id: int,
    temperature: float | None = Form(default=None),
    symptoms: str | None = Form(default=None),
    comment: str | None = Form(default=None),
    event_date: str | None = Form(default=None),
    next_url: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    target_url = next_url or f"/?selected_patient_id={patient.id}"
    if patient.patient_type != "child":
        return redirect_with_message(target_url, "Этот экран доступен только для ребёнка", is_error=True)
    try:
        parsed_date = date.fromisoformat(event_date) if event_date else date.today()
    except ValueError:
        return redirect_with_message(target_url, "Неверный формат даты", is_error=True)
    db.add(
        HealthEvent(
            patient_id=patient.id,
            temperature=temperature,
            symptoms=(symptoms or "").strip() or None,
            comment=(comment or "").strip() or None,
            date=parsed_date,
        )
    )
    db.commit()
    if temperature is not None:
        send_matrix_message(user, f"Ребёнок: {patient.name}\nТемпература: {temperature} °C\nДата: {parsed_date.strftime('%d.%m.%Y')}")
        return redirect_with_message(target_url, "Температура сохранена")
    return redirect_with_message(target_url, "Событие сохранено")


@router.post("/patients/{patient_id}/child-medications")
def create_child_medication_page(
    patient_id: int,
    name: str = Form(...),
    dosage: str | None = Form(default=None),
    comment: str | None = Form(default=None),
    medication_date: str | None = Form(default=None),
    next_url: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    target_url = next_url or f"/extra?selected_patient_id={patient.id}"
    if patient.patient_type != "child":
        return redirect_with_message(target_url, "Этот экран доступен только для ребёнка", is_error=True)
    if not name.strip():
        return redirect_with_message(target_url, "Название лекарства обязательно", is_error=True)
    try:
        parsed_date = date.fromisoformat(medication_date) if medication_date else date.today()
    except ValueError:
        return redirect_with_message(target_url, "Неверный формат даты", is_error=True)
    db.add(
        ChildMedication(
            patient_id=patient.id,
            name=name.strip(),
            dosage=(dosage or "").strip() or None,
            comment=(comment or "").strip() or None,
            date=parsed_date,
        )
    )
    db.commit()
    return redirect_with_message(target_url, "Детское лекарство сохранено")


@router.post("/patients/{patient_id}/vaccines")
def create_vaccine_record_page(
    patient_id: int,
    name: str = Form(...),
    vaccine_date: str | None = Form(default=None),
    status_value: str = Form(default="planned"),
    comment: str | None = Form(default=None),
    next_url: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    target_url = next_url or f"/extra?selected_patient_id={patient.id}"
    if patient.patient_type != "child":
        return redirect_with_message(target_url, "Этот экран доступен только для ребёнка", is_error=True)
    if not name.strip():
        return redirect_with_message(target_url, "Название прививки обязательно", is_error=True)
    if status_value not in {"planned", "done"}:
        return redirect_with_message(target_url, "Неверный статус прививки", is_error=True)
    try:
        parsed_date = date.fromisoformat(vaccine_date) if vaccine_date else None
    except ValueError:
        return redirect_with_message(target_url, "Неверный формат даты", is_error=True)
    db.add(
        VaccineRecord(
            patient_id=patient.id,
            name=name.strip(),
            date=parsed_date,
            status=status_value,
            comment=(comment or "").strip() or None,
        )
    )
    db.commit()
    return redirect_with_message(target_url, "Прививка сохранена")


@router.get("/patients/{patient_id}/events.ics")
def export_patient_events_ics_page(patient_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = get_patient_for_user(patient_id, user, db)
    content = build_care_event_ics(patient.name, list_patient_events(db, patient))
    headers = {"Content-Disposition": f'attachment; filename="patient-{patient.id}-events.ics"'}
    return Response(content=content, media_type="text/calendar; charset=utf-8", headers=headers)


@router.post("/medications")
def create_medication_page(
    request: Request,
    patient_id: int = Form(...),
    client_id: str | None = Form(default=None),
    name: str = Form(...),
    dosage: str | None = Form(default=None),
    schedule: str | None = Form(default=None),
    instructions: str | None = Form(default=None),
    start_date: str | None = Form(default=None),
    end_date: str | None = Form(default=None),
    is_active: str | None = Form(default="on"),
    reminder_enabled: str | None = Form(default=None),
    reminder_time: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    existing_medication = find_existing_client_entity(db, Medication, client_id)
    if existing_medication:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Назначение уже синхронизировано",
                is_error=False,
            )
            return build_template_response(request, "partials/medications.html", context)
        return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Назначение уже синхронизировано")
    if not name.strip():
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Название лекарства обязательно",
                is_error=True,
                form_errors={"name": "Введите название лекарства"},
            )
            return build_template_response(request, "partials/medications.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Название лекарства обязательно", is_error=True)
    try:
        parsed_reminder_time = parse_optional_time(reminder_time)
    except ValueError:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Время напоминания должно быть в формате ЧЧ:ММ",
                is_error=True,
                form_errors={"reminder_time": "Используйте формат ЧЧ:ММ"},
            )
            return build_template_response(request, "partials/medications.html", context)
        return redirect_with_message(
            f"/?selected_patient_id={patient.id}",
            "Время напоминания должно быть в формате ЧЧ:ММ",
            is_error=True,
        )
    try:
        parsed_start_date = parse_optional_date(start_date)
        parsed_end_date = parse_optional_date(end_date)
    except ValueError:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Дата должна быть в формате ГГГГ-ММ-ДД",
                is_error=True,
            )
            return build_template_response(request, "partials/medications.html", context)
        return redirect_with_message(
            f"/extra?selected_patient_id={patient.id}",
            "Дата должна быть в формате ГГГГ-ММ-ДД",
            is_error=True,
        )
    if parsed_start_date and parsed_end_date and parsed_end_date < parsed_start_date:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Дата окончания не может быть раньше даты начала",
                is_error=True,
            )
            return build_template_response(request, "partials/medications.html", context)
        return redirect_with_message(
            f"/extra?selected_patient_id={patient.id}",
            "Дата окончания не может быть раньше даты начала",
            is_error=True,
        )

    cached_drug = next(iter(lookup_drug_cache(db, name.strip(), limit=1)), None)
    normalized_name = (cached_drug or {}).get("brand_name") or name.strip()
    resolved_instructions = (instructions or "").strip() or (cached_drug or {}).get("instructions")
    resolved_notes = (notes or "").strip() or (cached_drug or {}).get("purpose") or (cached_drug or {}).get("indications")

    is_profile_active = is_active == "on"
    is_reminder_enabled = reminder_enabled == "on" and is_profile_active
    if is_reminder_enabled and not parsed_reminder_time:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request,
                user,
                db,
                selected_patient_id=patient.id,
                message="Укажите время напоминания",
                is_error=True,
                form_errors={"reminder_time": "Нужно указать время, если напоминание включено"},
            )
            return build_template_response(request, "partials/medications.html", context)
        return redirect_with_message(
            f"/?selected_patient_id={patient.id}",
            "Укажите время напоминания",
            is_error=True,
        )
    medication = Medication(
        patient_id=patient.id,
        client_id=(client_id or "").strip() or None,
        name=normalized_name,
        dosage=dosage or None,
        schedule=schedule or None,
        instructions=resolved_instructions or None,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        is_active=is_profile_active,
        reminder_enabled=is_reminder_enabled,
        reminder_time=parsed_reminder_time,
        notes=resolved_notes or None,
    )
    db.add(medication)
    db.commit()
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
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient.id,
            message="Назначение сохранено",
            is_error=False,
        )
        return build_template_response(request, "partials/medications.html", context)
    return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Назначение сохранено")


@router.post("/observations/{observation_id}/delete")
def delete_observation_page(
    request: Request,
    observation_id: int,
    patient_id: int = Form(...),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    history_sort: str | None = Form(default=None),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    observation = db.scalar(select(Observation).where(Observation.id == observation_id, Observation.patient_id == patient.id))
    if observation:
        db.delete(observation)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            history_sort=history_sort,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            message="Запись удалена",
            is_error=False,
        )
        return build_template_response(
            request,
            "partials/history.html",
            context,
            htmx_trigger={"chartChanged": True},
        )
    return redirect_with_message(f"/?selected_patient_id={patient_id}", "Запись удалена")


@router.post("/lab-results/{lab_result_id}/delete")
def delete_lab_result_page(
    request: Request,
    lab_result_id: int,
    patient_id: int = Form(...),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    history_sort: str | None = Form(default=None),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    lab_result = db.scalar(select(LabResult).where(LabResult.id == lab_result_id, LabResult.patient_id == patient.id))
    if lab_result:
        db.delete(lab_result)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            history_sort=history_sort,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            message="Результат анализа удалён",
            is_error=False,
        )
        return build_template_response(
            request,
            "partials/history.html",
            context,
            htmx_trigger={"chartChanged": True},
        )
    return redirect_with_message(f"/?selected_patient_id={patient_id}", "Результат анализа удалён")


@router.post("/observations/{observation_id}/update")
def update_observation_page(
    request: Request,
    observation_id: int,
    patient_id: int = Form(...),
    observation_type: str = Form(...),
    sys: int | None = Form(default=None),
    dia: int | None = Form(default=None),
    pulse: int | None = Form(default=None),
    value: float | None = Form(default=None),
    unit: str | None = Form(default=None),
    label: str | None = Form(default=None),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    history_sort: str | None = Form(default=None),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    observation = db.scalar(select(Observation).where(Observation.id == observation_id, Observation.patient_id == patient.id))
    if not observation:
        return redirect_with_message(f"/?selected_patient_id={patient_id}", "Запись не найдена", is_error=True)
    if observation_type == "blood_pressure":
        if sys is None or dia is None:
            return redirect_with_message(f"/?selected_patient_id={patient_id}", "Укажите SYS и DIA", is_error=True)
        validation_error = validate_pressure_values(sys, dia, pulse)
        if validation_error:
            return redirect_with_message(f"/?selected_patient_id={patient_id}", validation_error, is_error=True)
        observation.value = {"sys": sys, "dia": dia, "pulse": pulse}
    else:
        if value is None:
            return redirect_with_message(f"/?selected_patient_id={patient_id}", "Укажите значение", is_error=True)
        observation.value = {"value": value, "unit": unit or None, "label": label or None}
    db.add(observation)
    db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            history_sort=history_sort,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            message="Запись обновлена",
            is_error=False,
        )
        return build_template_response(request, "partials/history.html", context, htmx_trigger={"chartChanged": True})
    return redirect_with_message(f"/?selected_patient_id={patient_id}", "Запись обновлена")


@router.post("/lab-results/{lab_result_id}/update")
def update_lab_result_page(
    request: Request,
    lab_result_id: int,
    patient_id: int = Form(...),
    test_name: str = Form(...),
    value: float = Form(...),
    unit: str | None = Form(default=None),
    panel_name: str | None = Form(default=None),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    history_sort: str | None = Form(default=None),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    lab_result = db.scalar(select(LabResult).where(LabResult.id == lab_result_id, LabResult.patient_id == patient.id))
    if not lab_result:
        return redirect_with_message(f"/?selected_patient_id={patient_id}", "Результат анализа не найден", is_error=True)
    lab_result.test_name = test_name.strip() or lab_result.test_name
    lab_result.value = value
    lab_result.unit = unit or None
    lab_result.panel_name = panel_name or None
    db.add(lab_result)
    db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            history_sort=history_sort,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            message="Результат анализа обновлён",
            is_error=False,
        )
        return build_template_response(request, "partials/history.html", context, htmx_trigger={"chartChanged": True})
    return redirect_with_message(f"/?selected_patient_id={patient_id}", "Результат анализа обновлён")


@router.post("/medications/{medication_id}/delete")
def delete_medication_page(
    request: Request,
    medication_id: int,
    patient_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    medication = db.scalar(select(Medication).where(Medication.id == medication_id, Medication.patient_id == patient.id))
    if medication:
        db.delete(medication)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            message="Назначение удалено",
            is_error=False,
        )
        return build_template_response(request, "partials/medications.html", context)
    return redirect_with_message(f"/extra?selected_patient_id={patient_id}", "Назначение удалено")


@router.post("/medications/{medication_id}/toggle-active")
def toggle_medication_active_page(
    request: Request,
    medication_id: int,
    patient_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    medication = db.scalar(select(Medication).where(Medication.id == medication_id, Medication.patient_id == patient.id))
    if medication is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Назначение не найдено")
    medication.is_active = not medication.is_active
    if not medication.is_active:
        medication.reminder_enabled = False
    db.commit()
    status_label = "активно" if medication.is_active else "отключено"
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            message=f"Лекарство теперь {status_label}",
            is_error=False,
        )
        return build_template_response(request, "partials/medications.html", context)
    return redirect_with_message(f"/extra?selected_patient_id={patient_id}", f"Лекарство теперь {status_label}")


@router.post("/patients/{patient_id}/notifications/send")
def send_patient_reminder_notification_page(
    patient_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    medications = list_patient_medications(db, patient)
    title, message = build_medication_reminder_message(patient.name, medications)
    result = send_notification(title, message, channels=user.notification_channels, recipient_email=user.email)
    matrix_result = send_matrix_message(user, build_medication_reminder_matrix_message(patient.name, medications))
    result["channels"] = [*result.get("channels", []), matrix_result]
    if result.get("status") != "sent" and matrix_result.get("status") == "sent":
        result["status"] = "sent"
    log_audit_event(db, "patient_notification_send", user, {"patient_id": patient.id, **result})
    channels = ", ".join(item.get("channel", "log") for item in result.get("channels", [])) or "log"
    return redirect_with_message(f"/?selected_patient_id={patient.id}", f"Напоминание отправлено через {channels}")


@router.post("/patients/{patient_id}/import/pdf/review", response_class=HTMLResponse)
def review_medical_pdf_page(
    request: Request,
    patient_id: int,
    file: UploadFile = File(...),
    confidence_threshold: float = Form(default=0.8),
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
        save_results=False,
        store_document=False,
    )
    review_id = uuid4().hex
    payload = {
        "patient_id": patient.id,
        "patient_name": patient.name,
        "original_filename": file.filename or "medical.pdf",
        "confidence_threshold": confidence_threshold,
        "result": result,
    }
    _pdf_review_file_path(review_id).write_bytes(pdf_bytes)
    _pdf_review_meta_path(review_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return templates.TemplateResponse(
        request,
        "pdf_import_review.html",
        {
            "request": request,
            "review_id": review_id,
            "patient": patient,
            "payload": payload,
        },
    )


@router.get("/patients/{patient_id}/import/pdf/review/{review_id}", response_class=HTMLResponse)
def medical_pdf_review_page(
    request: Request,
    patient_id: int,
    review_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    payload = json.loads(_pdf_review_meta_path(review_id).read_text(encoding="utf-8"))
    return templates.TemplateResponse(
        request,
        "pdf_import_review.html",
        {
            "request": request,
            "review_id": review_id,
            "patient": patient,
            "payload": payload,
        },
    )


@router.post("/patients/{patient_id}/import/pdf/review/{review_id}/apply")
async def apply_medical_pdf_review_page(
    request: Request,
    patient_id: int,
    review_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    payload = json.loads(_pdf_review_meta_path(review_id).read_text(encoding="utf-8"))
    candidates = payload.get("result", {}).get("candidates", [])
    form = await request.form()
    selected_indexes = {int(item) for item in form.getlist("candidate_index")}
    store_document = form.get("store_document") == "on"
    created = {"observations": 0, "lab_results": 0, "document": False}
    for index, item in enumerate(candidates):
        if index not in selected_indexes:
            continue
        if item.get("kind") == "blood_pressure":
            value = {
                "sys": int(form.get(f"candidate_{index}_sys") or item.get("value", {}).get("sys", 0)),
                "dia": int(form.get(f"candidate_{index}_dia") or item.get("value", {}).get("dia", 0)),
                "pulse": int(form.get(f"candidate_{index}_pulse")) if form.get(f"candidate_{index}_pulse") else item.get("value", {}).get("pulse"),
            }
            db.add(Observation(patient_id=patient.id, type="blood_pressure", value=value))
            created["observations"] += 1
        elif item.get("kind") == "lab_result":
            source_value = item.get("value", {})
            value = {
                "test_name": form.get(f"candidate_{index}_test_name") or source_value.get("test_name", "Анализ"),
                "value": float(form.get(f"candidate_{index}_value") or source_value.get("value", 0)),
                "unit": form.get(f"candidate_{index}_unit") or source_value.get("unit"),
                "panel_name": form.get(f"candidate_{index}_panel_name") or source_value.get("panel_name"),
            }
            db.add(
                LabResult(
                    patient_id=patient.id,
                    test_name=value.get("test_name", "Анализ"),
                    value=float(value.get("value", 0)),
                    unit=value.get("unit"),
                    panel_name=value.get("panel_name"),
                )
            )
            created["lab_results"] += 1
    if store_document:
        original_name = payload.get("original_filename", "medical.pdf")
        stored_path = save_import_source_bytes(original_name, _pdf_review_file_path(review_id).read_bytes(), patient.id)
        document = build_uploaded_document(
            patient_id=patient.id,
            stored_path=stored_path,
            original_filename=original_name,
            description="Импортированный медицинский документ",
        )
        db.add(document)
        created["document"] = True
    db.commit()
    if store_document:
        db.refresh(document)
        queue_document_processing(document)
    log_audit_event(db, "pdf_import_review_apply", user, {"patient_id": patient.id, **created, "selected": len(selected_indexes)})
    return redirect_with_message(
        f"/?selected_patient_id={patient.id}",
        f"Импортировано: показателей {created['observations']}, анализов {created['lab_results']}",
    )


@router.get("/patients/{patient_id}/charts/pdf")
def export_chart_pdf_page(
    patient_id: int,
    chart_type: str = "blood_pressure",
    lab_test_name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)

    parsed_date_from = datetime.fromisoformat(f"{date_from}T00:00:00") if date_from else None
    parsed_date_to = datetime.fromisoformat(f"{date_to}T23:59:59") if date_to else None
    if chart_type == "lab_result" and not lab_test_name:
        lab_tests = list_patient_lab_test_names(db, patient)
        if lab_tests:
            lab_test_name = lab_tests[0]
    observations = list_patient_history(db, patient, chart_type, parsed_date_from, parsed_date_to)

    pdf_bytes = build_chart_pdf(patient.name, chart_type, observations, date_from, date_to, lab_test_name)
    log_audit_event(db, "chart_pdf_export", user, {"patient_id": patient.id, "chart_type": chart_type, "lab_test_name": lab_test_name})
    headers = {"Content-Disposition": f'attachment; filename="patient-{patient.id}-{chart_type}-chart.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/patients/{patient_id}/charts/print", response_class=HTMLResponse)
def print_chart_page(
    request: Request,
    patient_id: int,
    chart_type: str = "blood_pressure",
    chart_lab_test: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    if chart_type == "lab_result" and not chart_lab_test:
        lab_tests = list_patient_lab_test_names(db, patient)
        if lab_tests:
            chart_lab_test = lab_tests[0]
    return templates.TemplateResponse(
        request,
        "chart_print.html",
        {
            "request": request,
            "patient": patient,
            "chart_type": chart_type,
            "chart_lab_test": chart_lab_test or "",
        },
    )
