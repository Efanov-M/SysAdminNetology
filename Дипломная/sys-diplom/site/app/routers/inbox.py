from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import InboxEvent, User
from app.routers.pages import redirect_with_message, templates
from app.services.audit import log_audit_event
from app.services.care import acknowledge_inbox_item, list_relative_inbox_items, summarize_inbox_by_patient
from app.services.records import list_user_patients


router = APIRouter(tags=["inbox-pages"])


@router.get("/inbox", response_class=HTMLResponse)
def relative_inbox_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = list_relative_inbox_items(db, user, limit=50)
    grouped_items = summarize_inbox_by_patient(items)
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "request": request,
            "items": items,
            "grouped_items": grouped_items,
            "message": request.query_params.get("message"),
            "is_error": request.query_params.get("error") == "1",
        },
    )


@router.post("/inbox/{checkin_id}/ack")
def acknowledge_inbox_item_page(
    checkin_id: int,
    note: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(InboxEvent).where(InboxEvent.id == checkin_id))
    if not item or item.patient not in list_user_patients(db, user):
        return redirect_with_message("/inbox", "Событие не найдено", is_error=True)
    acknowledge_inbox_item(db, user, item, note)
    log_audit_event(db, "inbox_item_acknowledged", user, {"inbox_event_id": item.id, "patient_id": item.patient_id})
    return redirect_with_message("/inbox", f"Подтверждено: {item.patient.name} — {note or 'без комментария'}")
