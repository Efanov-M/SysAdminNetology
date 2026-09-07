import json
from datetime import UTC, datetime
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import User
from app.routers.pages import build_audit_entry_view, redirect_with_message, templates
from app.services.audit import log_audit_event
from app.services.backup import restore_backup_archive
from app.services.notification_queue import list_notification_queue_items
from app.services.records import collect_family_record, list_audit_logs, list_comment_journal, list_user_patients
from app.services.restore_preview import apply_restore_wizard_preview, create_restore_wizard_preview, get_restore_wizard_preview
from app.services.charts import build_comments_pdf
from app.services.medications import fetch_medication_info, resolve_medication_query
from app.exporters import build_backup_archive


router = APIRouter(tags=["admin-pages"])


@router.get("/audit", response_class=HTMLResponse)
def audit_log_page(request: Request, action: str | None = None, q: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = [build_audit_entry_view(item) for item in list_audit_logs(db, user, limit=200, action=action)]
    if q:
        query = q.strip().lower()
        entries = [item for item in entries if query in item["action"].lower() or query in item["action_label"].lower() or query in json.dumps(item["details"], ensure_ascii=False).lower()]
    return templates.TemplateResponse(request, "audit.html", {"request": request, "entries": entries, "user": user, "selected_action": action or "", "query": q or ""})


@router.get("/comments", response_class=HTMLResponse)
def comment_journal_page(request: Request, q: str | None = None, category: str | None = None, author_email: str | None = None, patient_id: int | None = None, pinned_only: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = list_comment_journal(db, user, search=q, category=category, author_email=author_email, patient_id=patient_id, pinned_only=bool(pinned_only), limit=300)
    return templates.TemplateResponse(request, "comments_journal.html", {"request": request, "entries": entries, "query": q or "", "selected_category": category or "", "selected_author_email": author_email or "", "selected_patient_id": patient_id or 0, "pinned_only": bool(pinned_only), "patients": list_user_patients(db, user)})


@router.get("/comments/export")
def export_comment_journal_page(q: str | None = None, category: str | None = None, author_email: str | None = None, patient_id: int | None = None, pinned_only: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = list_comment_journal(db, user, search=q, category=category, author_email=author_email, patient_id=patient_id, pinned_only=bool(pinned_only), limit=1000)
    payload = {"exported_at": datetime.now(UTC).isoformat(), "entries": [{**item, "created_at": item["created_at"].isoformat() if item.get("created_at") else None} for item in entries]}
    log_audit_event(db, "comment_journal_export", user, {"entries": len(entries), "category": category, "pinned_only": bool(pinned_only), "author_email": author_email, "patient_id": patient_id})
    headers = {"Content-Disposition": 'attachment; filename="family-comments.json"'}
    return Response(content=json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8", headers=headers)


@router.get("/comments/print", response_class=HTMLResponse)
def print_comment_journal_page(request: Request, q: str | None = None, category: str | None = None, author_email: str | None = None, patient_id: int | None = None, layout: str = "compact", pinned_only: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = list_comment_journal(db, user, search=q, category=category, author_email=author_email, patient_id=patient_id, pinned_only=bool(pinned_only), limit=1000)
    return templates.TemplateResponse(request, "comments_print.html", {"request": request, "entries": entries, "layout": layout})


@router.get("/comments/pdf")
def export_comment_journal_pdf_page(q: str | None = None, category: str | None = None, author_email: str | None = None, patient_id: int | None = None, pinned_only: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = list_comment_journal(db, user, search=q, category=category, author_email=author_email, patient_id=patient_id, pinned_only=bool(pinned_only), limit=1000)
    pdf_bytes = build_comments_pdf(entries)
    log_audit_event(db, "comment_journal_export_pdf", user, {"entries": len(entries), "category": category, "author_email": author_email, "patient_id": patient_id})
    headers = {"Content-Disposition": 'attachment; filename="family-comments.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/notifications/print", response_class=HTMLResponse)
def print_notification_history_page(request: Request, layout: str = "compact", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = [build_audit_entry_view(item) for item in list_audit_logs(db, user, limit=200) if item.action in {"notification_test", "patient_notification_send", "medication_reminder_auto", "notification_retry_processed", "notification_retry_scheduled"}]
    return templates.TemplateResponse(request, "notifications_print.html", {"request": request, "entries": entries, "layout": layout})


@router.get("/medications/search", response_class=HTMLResponse)
def medication_info_page(request: Request, query: str | None = None, refresh: int = 0, selected_patient_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del user
    items = []
    error = None
    error_kind = ""
    canonical_query = ""
    if query:
        canonical_query = resolve_medication_query(query)
        try:
            items = fetch_medication_info(query, db, force_refresh=bool(refresh))
        except RuntimeError as exc:
            items = []
            if "unavailable" in str(exc).lower():
                error = "Не удалось связаться с источником данных. Похоже на таймаут или временную недоступность."
                error_kind = "timeout"
            else:
                error = "Источник данных по препаратам ответил с ошибкой. Попробуйте повторить запрос позже."
                error_kind = "api"
        except Exception:
            items = []
            error = "Не удалось обработать запрос по препарату."
            error_kind = "api"
        if query and not items and not error:
            error_kind = "not_found"
    return templates.TemplateResponse(request, "medication_info.html", {"request": request, "query": query or "", "canonical_query": canonical_query, "items": items, "error": error, "error_kind": error_kind, "refresh": bool(refresh), "selected_patient_id": selected_patient_id})


@router.post("/backup/restore/wizard", response_class=HTMLResponse)
def restore_backup_wizard_preview_page(request: Request, file: UploadFile = File(...), restore_mode: str = Form(default="merge"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        preview = create_restore_wizard_preview(db, user, file)
    except HTTPException as exc:
        return redirect_with_message("/", str(exc.detail), is_error=True)
    return templates.TemplateResponse(request, "restore_wizard.html", {"request": request, "preview": preview, "preview_id": preview["preview_id"], "restore_mode": restore_mode})


@router.get("/backup/restore/wizard/{preview_id}", response_class=HTMLResponse)
def restore_backup_wizard_page(request: Request, preview_id: str, restore_mode: str = "merge", user: User = Depends(get_current_user)):
    del user
    preview = get_restore_wizard_preview(preview_id)
    return templates.TemplateResponse(request, "restore_wizard.html", {"request": request, "preview": preview, "preview_id": preview_id, "restore_mode": restore_mode})


@router.post("/backup/restore/wizard/{preview_id}/apply")
async def restore_backup_wizard_apply_page(request: Request, preview_id: str, restore_mode: str = Form(default="merge"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    started_at = perf_counter()
    form = await request.form()
    decisions = {"patient_actions": {}, "medication_actions": {}, "document_actions": {}}
    for key, action in zip(form.getlist("patient_key"), form.getlist("patient_action")):
        decisions["patient_actions"][str(key)] = str(action)
    for key, action in zip(form.getlist("medication_key"), form.getlist("medication_action")):
        decisions["medication_actions"][str(key)] = str(action)
    for key, action in zip(form.getlist("document_key"), form.getlist("document_action")):
        decisions["document_actions"][str(key)] = str(action)
    try:
        result = apply_restore_wizard_preview(db, user, preview_id, mode=restore_mode, decisions=decisions)
    except HTTPException as exc:
        log_audit_event(db, "backup_restore", user, {"status": "failed", "mode": restore_mode, "error": str(exc.detail), "duration_ms": int((perf_counter() - started_at) * 1000)})
        return redirect_with_message("/", str(exc.detail), is_error=True)
    result["status"] = "success"
    result["mode"] = restore_mode
    result["duration_ms"] = int((perf_counter() - started_at) * 1000)
    log_audit_event(db, "backup_restore", user, result)
    return redirect_with_message("/", f"Restore завершён: пациентов {result['patients']}, показателей {result['observations']}, анализов {result['lab_results']}, лекарств {result['medications']}, документов {result['documents']}")


@router.get("/backup/download")
def download_backup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    started_at = perf_counter()
    payload = collect_family_record(db, user)
    archive = build_backup_archive(payload)
    duration_ms = int((perf_counter() - started_at) * 1000)
    log_audit_event(db, "backup_download", user, {"status": "success", "patients": len(payload["patients"]), "archive_size_bytes": len(archive), "duration_ms": duration_ms})
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    headers = {"Content-Disposition": f'attachment; filename=\"family-backup-{timestamp}.zip\"'}
    return Response(content=archive, media_type="application/zip", headers=headers)


@router.post("/backup/restore")
def restore_backup(file: UploadFile = File(...), restore_mode: str = Form(default="merge"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    started_at = perf_counter()
    try:
        result = restore_backup_archive(db, user, file, mode=restore_mode)
    except HTTPException as exc:
        log_audit_event(db, "backup_restore", user, {"status": "failed", "mode": restore_mode, "error": str(exc.detail), "duration_ms": int((perf_counter() - started_at) * 1000)})
        return redirect_with_message("/", str(exc.detail), is_error=True)
    result["status"] = "success"
    result["mode"] = restore_mode
    result["duration_ms"] = int((perf_counter() - started_at) * 1000)
    log_audit_event(db, "backup_restore", user, result)
    return redirect_with_message("/", f"Восстановлено: пациентов {result['patients']}, показателей {result['observations']}, анализов {result['lab_results']}, лекарств {result['medications']}, документов {result['documents']}")
