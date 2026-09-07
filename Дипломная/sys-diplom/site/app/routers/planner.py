from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import User
from app.routers.pages import build_dashboard_context, templates


router = APIRouter(tags=["planner-pages"])


@router.get("/", response_class=HTMLResponse)
def dashboard_main(
    request: Request,
    selected_patient_id: int | None = None,
    chart_type: str | None = None,
    chart_lab_test: str | None = None,
    medication_query: str | None = None,
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
        current_screen="main",
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        medication_query=medication_query,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/simple", response_class=HTMLResponse)
def simple_mode_page(
    request: Request,
    selected_patient_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_dashboard_context(
        request=request,
        user=user,
        db=db,
        current_screen="main",
        selected_patient_id=selected_patient_id,
    )
    return templates.TemplateResponse(request, "simple_mode.html", context)


@router.get("/graph", response_class=HTMLResponse)
def dashboard_graph(
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
        current_screen="graph",
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/history", response_class=HTMLResponse)
def dashboard_history(
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
        current_screen="history",
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/extra", response_class=HTMLResponse)
def dashboard_extra(
    request: Request,
    selected_patient_id: int | None = None,
    child_tab: str | None = None,
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
        current_screen="extra",
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
        child_tab=child_tab,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/planner", response_class=HTMLResponse)
@router.get("/control", response_class=HTMLResponse)
def dashboard_control(
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
        current_screen="planner",
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/emergency", response_class=HTMLResponse)
@router.get("/patient/emergency", response_class=HTMLResponse)
def dashboard_emergency(
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
        current_screen="emergency",
        selected_patient_id=selected_patient_id,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/partials/dashboard-shell", response_class=HTMLResponse)
def dashboard_shell_partial(
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
    return templates.TemplateResponse(request, "partials/dashboard_shell.html", context)


@router.get("/partials/history", response_class=HTMLResponse)
def dashboard_history_partial(
    request: Request,
    selected_patient_id: int | None = None,
    history_type: str | None = None,
    history_date_from: str | None = None,
    history_date_to: str | None = None,
    history_sort: str | None = None,
    date_preset: str | None = None,
    chart_type: str | None = None,
    chart_lab_test: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_dashboard_context(
        request=request,
        user=user,
        db=db,
        selected_patient_id=selected_patient_id,
        history_type=history_type,
        history_date_from=history_date_from,
        history_date_to=history_date_to,
        history_sort=history_sort,
        date_preset=date_preset,
        chart_type=chart_type,
        chart_lab_test=chart_lab_test,
    )
    return templates.TemplateResponse(request, "partials/history.html", context)


@router.get("/partials/chart", response_class=HTMLResponse)
def dashboard_chart_partial(
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
    return templates.TemplateResponse(request, "partials/chart.html", context)
