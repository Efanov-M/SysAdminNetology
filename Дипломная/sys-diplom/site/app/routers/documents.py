from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, get_patient_for_user, get_writable_patient_for_user
from app.models import Document, Patient, User
from app.routers.pages import build_dashboard_context, build_template_response, is_htmx_request, redirect_with_message, templates
from app.services.document_processing import build_uploaded_document, cleanup_document_files, get_document_active_path, queue_document_processing
from app.utils import DOCTOR_TYPE_OPTIONS, delete_upload_file, save_upload_file


router = APIRouter(tags=["document-pages"])


@router.get("/partials/documents", response_class=HTMLResponse)
def dashboard_documents_partial(
    request: Request,
    selected_patient_id: int | None = None,
    chart_type: str | None = None,
    chart_lab_test: str | None = None,
    history_type: str | None = None,
    history_date_from: str | None = None,
    history_date_to: str | None = None,
    history_sort: str | None = None,
    date_preset: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_dashboard_context(
        request=request,
        user=user,
        db=db,
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
    )
    return templates.TemplateResponse(request, "partials/documents.html", context)


@router.post("/documents")
def upload_document_page(
    request: Request,
    patient_id: int = Form(...),
    document_type: str = Form(...),
    doctor_type: str | None = Form(default=None),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    normalized_doctor_type = (doctor_type or "").strip().lower() or None
    if document_type not in {"lab", "report"}:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                selected_patient_id=patient.id,
                chart_type=chart_type,
                chart_lab_test=chart_lab_test,
                history_type=history_type,
                history_date_from=history_date_from,
                history_date_to=history_date_to,
                message="Выберите тип документа",
                is_error=True,
            )
            return build_template_response(request, "partials/documents.html", context)
        return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Выберите тип документа", is_error=True)
    if document_type == "report" and normalized_doctor_type not in DOCTOR_TYPE_OPTIONS:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                selected_patient_id=patient.id,
                chart_type=chart_type,
                chart_lab_test=chart_lab_test,
                history_type=history_type,
                history_date_from=history_date_from,
                history_date_to=history_date_to,
                message="Выберите тип врача для выписки",
                is_error=True,
            )
            return build_template_response(request, "partials/documents.html", context)
        return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Выберите тип врача для выписки", is_error=True)
    try:
        stored_path, original_name = save_upload_file(file, patient.id)
    except HTTPException as exc:
        if is_htmx_request(request):
            context = build_dashboard_context(
                request=request,
                user=user,
                db=db,
                selected_patient_id=patient.id,
                chart_type=chart_type,
                chart_lab_test=chart_lab_test,
                history_type=history_type,
                history_date_from=history_date_from,
                history_date_to=history_date_to,
                message=str(exc.detail),
                is_error=True,
            )
            return build_template_response(request, "partials/documents.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", str(exc.detail), is_error=True)
    document = build_uploaded_document(
        patient_id=patient.id,
        stored_path=stored_path,
        original_filename=original_name,
        document_type=document_type,
        doctor_type=normalized_doctor_type if document_type == "report" else None,
        description=description or None,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    queue_document_processing(document)
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient.id,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            message="Документ загружен",
            is_error=False,
        )
        return build_template_response(request, "partials/documents.html", context)
    return redirect_with_message(f"/extra?selected_patient_id={patient.id}", "Документ загружен")


@router.post("/documents/{document_id}/delete")
def delete_document_page(
    request: Request,
    document_id: int,
    patient_id: int = Form(...),
    chart_type: str | None = Form(default=None),
    chart_lab_test: str | None = Form(default=None),
    history_type: str | None = Form(default=None),
    history_date_from: str | None = Form(default=None),
    history_date_to: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    document = db.scalar(select(Document).where(Document.id == document_id, Document.patient_id == patient.id))
    if document:
        for path in cleanup_document_files(document):
            delete_upload_file(path)
        db.delete(document)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient_id,
            chart_type=chart_type,
            chart_lab_test=chart_lab_test,
            history_type=history_type,
            history_date_from=history_date_from,
            history_date_to=history_date_to,
            message="Документ удалён",
            is_error=False,
        )
        return build_template_response(request, "partials/documents.html", context)
    return redirect_with_message(f"/?selected_patient_id={patient_id}", "Документ удалён")


@router.get("/documents/{document_id}/file")
def download_document_file_page(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.scalar(select(Document).join(Patient).where(Document.id == document_id, Patient.family_id == user.family_id))
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    get_patient_for_user(document.patient_id, user, db)
    file_path = settings.upload_path.parent / get_document_active_path(document)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл документа не найден")
    filename = document.original_filename or file_path.name
    return FileResponse(file_path, filename=filename, media_type="application/octet-stream")
