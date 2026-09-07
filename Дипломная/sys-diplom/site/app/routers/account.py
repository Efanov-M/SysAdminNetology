import json
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, Form, Header, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, get_patient_for_user
from app.models import User
from app.routers import pages as pages_module
from app.routers.pages import (
    build_audit_entry_view,
    normalize_notification_channels,
    parse_optional_time,
    redirect_with_message,
    require_family_owner,
    templates,
)
from app.security import hash_password, verify_password
from app.services.audit import log_audit_event
from app.services.care import get_or_create_alert_rule, list_patient_alert_rules
from app.services.health import get_worker_health, get_worker_pool_health
from app.services.medications import (
    clear_drug_cache,
    get_drug_cache_maintenance_report,
    get_drug_cache_summary,
    moderate_drug_cache,
)
from app.services.notification_queue import (
    build_admin_runbook,
    build_channel_degradation_warnings,
    build_diagnostics_bundle,
    build_incident_retention_summary,
    build_notification_incidents,
    build_notification_queue_stats,
    build_operational_alerts,
    build_sla_alerts,
    cleanup_incident_history,
    list_incident_history,
    list_notification_queue_items,
)
from app.services.notifications import (
    get_active_matrix_link_token,
    get_matrix_profile,
    handle_matrix_message,
    link_matrix_profile,
    process_notification_queue,
    send_notification,
    start_matrix_link,
    unlink_matrix_profile,
)
from app.services.records import list_audit_logs, list_user_patients


router = APIRouter(tags=["account-pages"])


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit_entries = [build_audit_entry_view(item) for item in list_audit_logs(db, user, limit=20)]
    backup_entries = [item for item in audit_entries if item["is_backup_event"]]
    notification_entries = [item for item in audit_entries if item["action"] in {"notification_test", "patient_notification_send", "medication_reminder_auto"}]
    failed_notification_entries = [
        item
        for item in notification_entries
        if item["status"] == "failed"
        or any(channel.get("status") == "failed" for channel in (item["details"].get("channels") or []))
    ]
    queued_notification_entries = list_notification_queue_items(limit=20)
    queue_stats = build_notification_queue_stats(queued_notification_entries)
    worker_health = get_worker_health()
    matrix_profile = get_matrix_profile(db, user)
    matrix_status = "connected" if matrix_profile and matrix_profile.is_linked else "not_connected"
    matrix_link_token = get_active_matrix_link_token(db, user)
    patients = list_user_patients(db, user)
    alert_rules_map = {
        patient.id: {
            item.type: item for item in list_patient_alert_rules(db, patient)
        }
        for patient in patients
    }
    drug_cache_summary = get_drug_cache_summary(db)
    drug_cache_report = get_drug_cache_maintenance_report(db)
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "request": request,
            "user": user,
            "audit_entries": audit_entries[:10],
            "backup_entries": backup_entries[:10],
            "notification_entries": notification_entries[:10],
            "failed_notification_entries": failed_notification_entries[:10],
            "queued_notification_entries": queued_notification_entries,
            "queue_stats": queue_stats,
            "worker_health": worker_health,
            "session_cookie_secure": settings.session_cookie_secure,
            "session_ttl_hours": round(settings.access_token_expire_minutes / 60, 1),
            "notification_channel": settings.notification_channel,
            "available_notification_channels": ["log", "email", "telegram", "matrix"],
            "matrix_bot_id": settings.matrix_bot_id or settings.matrix_user_id,
            "matrix_status": matrix_status,
            "matrix_profile": matrix_profile,
            "matrix_link_token": matrix_link_token,
            "patients": patients,
            "alert_rules_map": alert_rules_map,
            "drug_cache_summary": drug_cache_summary,
            "drug_cache_report": drug_cache_report,
            "message": request.query_params.get("message"),
            "is_error": request.query_params.get("error") == "1",
        },
    )


@router.get("/account/worker-monitor", response_class=HTMLResponse)
def notification_worker_monitor_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    removed_history = cleanup_incident_history()
    queued_notification_entries = list_notification_queue_items(limit=200)
    queue_stats = build_notification_queue_stats(queued_notification_entries)
    incidents = build_notification_incidents(queued_notification_entries)
    incident_history = list_incident_history(limit=200, period_days=14)
    retention_summary = build_incident_retention_summary(incident_history)
    retry_entries = [
        build_audit_entry_view(item)
        for item in list_audit_logs(db, user, limit=100)
        if item.action in {"notification_retry_processed", "notification_retry_scheduled"}
    ]
    worker_health = get_worker_health()
    worker_pool = get_worker_pool_health()
    operational_alerts = build_operational_alerts(queue_stats, incidents, worker_pool["status"])
    degradation_warnings = build_channel_degradation_warnings(incident_history, period_days=14)
    sla_alerts = build_sla_alerts(queue_stats, worker_health, worker_pool, incident_history)
    return templates.TemplateResponse(
        request,
        "worker_monitor.html",
        {
            "request": request,
            "worker_health": worker_health,
            "worker_pool": worker_pool,
            "queue_stats": queue_stats,
            "incidents": incidents,
            "incident_history": incident_history[:20],
            "retention_summary": retention_summary,
            "operational_alerts": operational_alerts,
            "degradation_warnings": degradation_warnings,
            "sla_alerts": sla_alerts,
            "admin_runbook": build_admin_runbook(queue_stats, worker_health, worker_pool, incident_history),
            "removed_history": removed_history,
            "queued_notification_entries": queued_notification_entries,
            "retry_entries": retry_entries[:30],
        },
    )


@router.get("/account/worker-monitor/incidents")
def notification_worker_incidents_export_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user, db
    items = list_notification_queue_items(limit=500)
    history = list_incident_history(limit=500, period_days=30)
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "stats": build_notification_queue_stats(items),
        "incidents": build_notification_incidents(items),
        "retention_summary": build_incident_retention_summary(history),
        "incident_history": history,
    }
    headers = {"Content-Disposition": 'attachment; filename="notification-incidents.json"'}
    return Response(content=json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8", headers=headers)


@router.get("/account/worker-monitor/incidents-page", response_class=HTMLResponse)
def notification_worker_incidents_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user, db
    items = list_notification_queue_items(limit=500)
    incidents = build_notification_incidents(items)
    history = list_incident_history(limit=500, period_days=30)
    channels: dict[str, list[dict]] = {}
    for item in incidents:
        channels.setdefault(item.get("channel") or "unknown", []).append(item)
    return templates.TemplateResponse(
        request,
        "worker_incidents.html",
        {
            "request": request,
            "incidents_by_channel": channels,
            "incidents": incidents,
            "retention_summary": build_incident_retention_summary(history),
            "degradation_warnings": build_channel_degradation_warnings(history, period_days=30),
        },
    )


@router.get("/account/worker-monitor/diagnostics")
def notification_worker_diagnostics_bundle_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user, db
    queue_items = list_notification_queue_items(limit=500)
    incidents = build_notification_incidents(queue_items)
    history = list_incident_history(limit=1000, period_days=30)
    queue_stats = build_notification_queue_stats(queue_items)
    diagnostics = build_diagnostics_bundle(
        queue_items=queue_items,
        incident_history=history,
        queue_stats=queue_stats,
        incidents=incidents,
        worker_health=get_worker_health(),
        worker_pool=get_worker_pool_health(),
    )
    headers = {"Content-Disposition": 'attachment; filename="notification-diagnostics.zip"'}
    return Response(content=diagnostics, media_type="application/zip", headers=headers)


@router.get("/account/worker-monitor/print", response_class=HTMLResponse)
def notification_worker_print_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user, db
    queue_items = list_notification_queue_items(limit=200)
    incident_history = list_incident_history(limit=200, period_days=14)
    queue_stats = build_notification_queue_stats(queue_items)
    worker_health = get_worker_health()
    worker_pool = get_worker_pool_health()
    incidents = build_notification_incidents(queue_items)
    return templates.TemplateResponse(
        request,
        "worker_monitor_print.html",
        {
            "request": request,
            "queue_stats": queue_stats,
            "incidents": incidents,
            "retention_summary": build_incident_retention_summary(incident_history),
            "degradation_warnings": build_channel_degradation_warnings(incident_history, period_days=14),
            "sla_alerts": build_sla_alerts(queue_stats, worker_health, worker_pool, incident_history),
            "admin_runbook": build_admin_runbook(queue_stats, worker_health, worker_pool, incident_history),
            "operational_alerts": build_operational_alerts(queue_stats, incidents, worker_pool["status"]),
            "worker_health": worker_health,
            "worker_pool": worker_pool,
        },
    )


@router.post("/account/notifications/process-queue")
def process_notification_queue_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user
    results = process_notification_queue(db)
    return redirect_with_message("/account", f"Очередь уведомлений обработана: {len(results)} элементов")


@router.post("/account/drug-cache/clear")
def clear_drug_cache_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user
    removed = clear_drug_cache(db)
    return redirect_with_message("/account", f"Локальный кэш лекарств очищен: {removed} записей")


@router.post("/account/drug-cache/moderate")
def moderate_drug_cache_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user
    result = moderate_drug_cache(db)
    return redirect_with_message("/account", f"Локальный кэш лекарств проверен: обновлено {result['updated']} записей, объединено {result['merged']}")


@router.post("/matrix/link/start")
@router.post("/matrix/link-token")
def create_matrix_link_token_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link_token = start_matrix_link(db, user)
    log_audit_event(
        db,
        "matrix_link_token_create",
        user,
        {
            "code": link_token.token,
            "bot_id": settings.matrix_bot_id or settings.matrix_user_id,
        },
    )
    return redirect_with_message("/account", f"Код для Matrix готов: {link_token.token}. Теперь укажите свой Matrix ID.")


@router.post("/matrix/link/manual")
def complete_matrix_link_manually_page(
    code: str = Form(...),
    matrix_user_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del user
    success, message = link_matrix_profile(db, matrix_user_id, "", code)
    return redirect_with_message("/account", message, is_error=not success)


@router.post("/matrix/link/confirm")
def confirm_matrix_link_page(payload: dict = Body(...), db: Session = Depends(get_db)):
    code = str(payload.get("code") or "").strip()
    matrix_user_id = str(payload.get("matrix_user_id") or "").strip()
    room_id = str(payload.get("room_id") or "").strip()
    if not code or not matrix_user_id:
        return Response(
            content=json.dumps({"ok": False, "message": "Неверный или просроченный код"}, ensure_ascii=False),
            media_type="application/json; charset=utf-8",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    success, message = link_matrix_profile(db, matrix_user_id, room_id, code)
    return Response(
        content=json.dumps({"ok": success, "message": message}, ensure_ascii=False),
        media_type="application/json; charset=utf-8",
        status_code=status.HTTP_200_OK if success else status.HTTP_400_BAD_REQUEST,
    )


@router.post("/matrix/bot/message")
def process_matrix_bot_message_page(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    expected_token = (settings.matrix_access_token or "").strip()
    provided_token = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization.split(" ", 1)[1].strip()
    if not expected_token or provided_token != expected_token:
        return Response(
            content=json.dumps({"ok": False, "message": "forbidden"}, ensure_ascii=False),
            media_type="application/json; charset=utf-8",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    sender = str(payload.get("sender") or "").strip()
    room_id = str(payload.get("room_id") or "").strip()
    body = str(payload.get("body") or "")
    if not sender or not room_id or not body.strip():
        return Response(
            content=json.dumps({"ok": False, "message": "invalid payload"}, ensure_ascii=False),
            media_type="application/json; charset=utf-8",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    reply = handle_matrix_message(db, sender, room_id, body)
    return Response(
        content=json.dumps({"ok": True, "reply": reply, "action_type": "message"}, ensure_ascii=False),
        media_type="application/json; charset=utf-8",
    )


@router.post("/matrix/test")
def send_matrix_test_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_matrix_profile(db, user)
    if not profile or not profile.is_linked:
        return redirect_with_message("/account", "Matrix ещё не подключен", is_error=True)
    matrix_target = (profile.matrix_room_id or profile.matrix_user_id or "").strip()
    matrix_result = pages_module.send_matrix_target_message(matrix_target or "", "Тестовое уведомление")
    status_value = matrix_result.get("status")
    if status_value != "sent":
        return redirect_with_message("/account", "Не удалось отправить тестовое сообщение", is_error=True)
    log_audit_event(db, "notification_test", user, {"channels": [matrix_result], "matrix_profile_id": profile.id})
    return redirect_with_message("/account", "Тестовое сообщение отправлено в Matrix")


@router.get("/matrix/test")
def send_matrix_test_get_page():
    return redirect_with_message("/account", "Тестовое сообщение запускается только кнопкой из аккаунта", is_error=True)


@router.post("/matrix/unlink")
def unlink_matrix_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = unlink_matrix_profile(db, user)
    log_audit_event(db, "matrix_unlink", user, {"matrix_profile_id": profile.id})
    return redirect_with_message("/account", "Matrix отключён")


@router.post("/account/preferences")
def update_account_preferences_page(
    timezone_value: str = Form(default="Europe/Moscow"),
    quiet_hours_start: str | None = Form(default=None),
    quiet_hours_end: str | None = Form(default=None),
    notification_channels: list[str] | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.timezone = timezone_value.strip() or "Europe/Moscow"
    user.quiet_hours_start = parse_optional_time(quiet_hours_start)
    user.quiet_hours_end = parse_optional_time(quiet_hours_end)
    user.notification_channels = normalize_notification_channels(notification_channels)
    db.add(user)
    db.commit()
    log_audit_event(
        db,
        "account_preferences_update",
        user,
        {
            "timezone": user.timezone,
            "quiet_hours_start": user.quiet_hours_start.isoformat() if user.quiet_hours_start else None,
            "quiet_hours_end": user.quiet_hours_end.isoformat() if user.quiet_hours_end else None,
            "notification_channels": user.notification_channels,
        },
    )
    return redirect_with_message("/account", "Настройки уведомлений обновлены")


@router.post("/account/alert-settings")
def update_alert_settings_page(
    patient_id: int = Form(...),
    enabled: str | None = Form(default=None),
    blood_pressure_sys_threshold: int | None = Form(default=None),
    blood_pressure_dia_threshold: int | None = Form(default=None),
    blood_sugar_threshold: float | None = Form(default=None),
    bp_quiet_hours_start: str | None = Form(default=None),
    bp_quiet_hours_end: str | None = Form(default=None),
    bp_escalation_targets: str | None = Form(default=None),
    glucose_quiet_hours_start: str | None = Form(default=None),
    glucose_quiet_hours_end: str | None = Form(default=None),
    glucose_escalation_targets: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    def parse_targets(raw: str | None) -> list[str]:
        if not raw:
            return []
        items: list[str] = []
        for chunk in raw.replace(",", "\n").splitlines():
            candidate = chunk.strip()
            if candidate and candidate not in items:
                items.append(candidate)
        return items

    patient = get_patient_for_user(patient_id, user, db)
    bp_rule = get_or_create_alert_rule(db, patient, "blood_pressure")
    glucose_rule = get_or_create_alert_rule(db, patient, "glucose")
    rule_enabled = enabled == "on"
    bp_rule.enabled = rule_enabled and any(value is not None for value in [blood_pressure_sys_threshold, blood_pressure_dia_threshold])
    bp_rule.systolic_max = blood_pressure_sys_threshold or None
    bp_rule.diastolic_max = blood_pressure_dia_threshold or None
    bp_rule.quiet_hours_start = parse_optional_time(bp_quiet_hours_start)
    bp_rule.quiet_hours_end = parse_optional_time(bp_quiet_hours_end)
    bp_rule.escalation_targets = parse_targets(bp_escalation_targets)
    glucose_rule.enabled = rule_enabled and blood_sugar_threshold is not None
    glucose_rule.glucose_max = blood_sugar_threshold or None
    glucose_rule.quiet_hours_start = parse_optional_time(glucose_quiet_hours_start)
    glucose_rule.quiet_hours_end = parse_optional_time(glucose_quiet_hours_end)
    glucose_rule.escalation_targets = parse_targets(glucose_escalation_targets)
    db.add(bp_rule)
    db.add(glucose_rule)
    db.commit()
    log_audit_event(
        db,
        "alert_rules_update",
        user,
        {
            "patient_id": patient.id,
            "enabled": rule_enabled,
            "blood_pressure_sys_threshold": bp_rule.systolic_max,
            "blood_pressure_dia_threshold": bp_rule.diastolic_max,
            "blood_sugar_threshold": glucose_rule.glucose_max,
            "bp_quiet_hours_start": bp_rule.quiet_hours_start.isoformat() if bp_rule.quiet_hours_start else None,
            "bp_quiet_hours_end": bp_rule.quiet_hours_end.isoformat() if bp_rule.quiet_hours_end else None,
            "bp_escalation_targets": bp_rule.escalation_targets,
            "glucose_quiet_hours_start": glucose_rule.quiet_hours_start.isoformat() if glucose_rule.quiet_hours_start else None,
            "glucose_quiet_hours_end": glucose_rule.quiet_hours_end.isoformat() if glucose_rule.quiet_hours_end else None,
            "glucose_escalation_targets": glucose_rule.escalation_targets,
        },
    )
    return redirect_with_message("/account", f"Контроль показателей сохранён для пациента {patient.name}")


@router.post("/account/password")
def change_password_page(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(current_password, user.password_hash):
        return redirect_with_message("/account", "Текущий пароль введён неверно", is_error=True)
    if len(new_password) < 6:
        return redirect_with_message("/account", "Новый пароль должен быть не короче 6 символов", is_error=True)
    if new_password != confirm_password:
        return redirect_with_message("/account", "Подтверждение пароля не совпадает", is_error=True)

    user.password_hash = hash_password(new_password)
    db.add(user)
    db.commit()
    log_audit_event(db, "password_change", user, {"status": "success"})
    return redirect_with_message("/account", "Пароль обновлён")


@router.post("/account/notifications/test")
def send_test_notification_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    non_matrix_channels = [channel for channel in user.notification_channels if channel != "matrix"]
    result = send_notification(
        "Тест Family PHR",
        f"Тестовое уведомление для {user.account_name}. Каналы: {', '.join(user.notification_channels)}.",
        channels=non_matrix_channels,
        recipient_email=user.email,
    )
    matrix_result = pages_module.send_matrix_message(
        user,
        f"Тест Family PHR\n\nПользователь: {user.account_name}\nMatrix ID: {(user.matrix_profile.matrix_user_id if user.matrix_profile else user.canonical_matrix_user_id) or 'не задан'}",
    )
    result["channels"] = [*result.get("channels", []), matrix_result]
    if result.get("status") != "sent" and matrix_result.get("status") == "sent":
        result["status"] = "sent"
    log_audit_event(db, "notification_test", user, result)
    channels = ", ".join(item.get("channel", "log") for item in result.get("channels", [])) or "log"
    return redirect_with_message("/account", f"Тестовое уведомление подготовлено через {channels}")
