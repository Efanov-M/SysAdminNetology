import json
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, get_writable_patient_for_user
from app.models import Invite, Patient, PatientShare, User
from app.routers.pages import (
    build_dashboard_context,
    build_template_response,
    is_htmx_request,
    redirect_with_message,
    require_family_owner,
    templates,
)
from app.services.audit import log_audit_event
from app.services.records import collect_family_record, list_family_invites, list_family_users, list_user_patients


router = APIRouter(tags=["family-pages"])


@router.get("/family/users", response_class=HTMLResponse)
def family_users_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_family_owner(user)
    return templates.TemplateResponse(
        request,
        "family_users.html",
        {
            "request": request,
            "user": user,
            "family_users": list_family_users(db, user),
            "family_invites": list_family_invites(db, user),
            "patients": list_user_patients(db, user),
            "message": request.query_params.get("message"),
            "is_error": request.query_params.get("error") == "1",
        },
    )


@router.get("/invite")
def invite_get_fallback(user: User = Depends(get_current_user)):
    require_family_owner(user)
    return redirect_with_message("/family/users", "Форма приглашения открыта на экране семьи", is_error=True)


@router.post("/invite")
def create_invite_page(
    login: str | None = Form(default=None),
    email: str | None = Form(default=None),
    patient_id: int | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_family_owner(user)
    normalized_login = (login or email or "").strip().lower()
    if not normalized_login:
        return redirect_with_message("/family/users", "Логин обязателен", is_error=True)
    existing_user = db.scalar(select(User).where(User.login == normalized_login))
    if not existing_user:
        existing_user = db.scalar(select(User).where(User.email == normalized_login))
    if existing_user:
        return redirect_with_message("/family/users", "Пользователь с таким логином уже существует", is_error=True)
    if patient_id is not None:
        patient = db.scalar(select(Patient).where(Patient.id == patient_id, Patient.family_id == user.family_id))
        if not patient:
            return redirect_with_message("/family/users", "Пациент для приглашения не найден", is_error=True)
    invite = Invite(
        login=normalized_login,
        email=normalized_login,
        family_id=user.family_id,
        role="member",
        patient_id=patient_id,
        token=token_urlsafe(24),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        used=False,
    )
    db.add(invite)
    db.commit()
    return redirect_with_message("/family/users", "Приглашение отправлено")


@router.get("/family/export")
def export_family_record_page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = collect_family_record(db, user)
    log_audit_event(db, "family_export", user, {"patients": len(payload["patients"])})
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    headers = {"Content-Disposition": 'attachment; filename="family-export.json"'}
    return Response(content=content, media_type="application/json; charset=utf-8", headers=headers)


@router.get("/family/print", response_class=HTMLResponse)
def print_family_record_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = collect_family_record(db, user)
    return templates.TemplateResponse(request, "family_print.html", {"request": request, "payload": payload})


@router.get("/family/packet/print", response_class=HTMLResponse)
def print_family_packet_page(
    request: Request,
    packet: str = "emergency",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = collect_family_record(db, user)
    packet_map = {
        "emergency": {"title": "Экстренная папка", "subtitle": "Короткий набор данных для вызова скорой или экстренной поездки."},
        "hospital": {"title": "Госпитализация", "subtitle": "Набор для приёма в стационар и передачи родственникам или врачу."},
        "rehab": {"title": "Санаторий / реабилитация", "subtitle": "Спокойная бумажная версия для длительного наблюдения и планового ухода."},
        "homecare": {"title": "Долгий уход дома", "subtitle": "Удобный комплект для ежедневного ухода и передачи сменяющимся родственникам."},
        "discharge": {"title": "После выписки", "subtitle": "Краткая бумажная версия на первые недели после стационара."},
        "kid_trip": {"title": "Поездка с ребёнком", "subtitle": "Сводка для детской поездки, отпуска или дороги с семейной аптечкой."},
        "monthly": {"title": "Контроль терапии на месяц", "subtitle": "Пакет для контроля хронической терапии и регулярных лекарств на ближайший месяц."},
        "caregiver": {"title": "Уход сиделки", "subtitle": "Краткий пакет для сменяющегося ухода и передачи бытовых инструкций."},
        "postop_month": {"title": "Месяц после операции", "subtitle": "Пакет для дома на первый месяц восстановления после операции."},
        "elder_meds": {"title": "Контроль лекарств у пожилого родственника", "subtitle": "Сводка лекарств и наблюдений, чтобы не потеряться в длительной терапии."},
        "kid_home": {"title": "Домашняя папка ребёнка", "subtitle": "Быстрая бумажная карточка ребёнка для дома, школы и поездок."},
        "night_shift": {"title": "Ночная смена", "subtitle": "Компактная бумажная сводка для ночного ухода, лекарств и тревожных признаков."},
        "weekly_control": {"title": "Недельный контроль давления и сахара", "subtitle": "Пакет для регулярной домашней записи давления, сахара и быстрых сверок за неделю."},
        "social_worker": {"title": "Набор для соцработника", "subtitle": "Короткая версия для соцработника: кто пациент, какие лекарства и что важно проверить дома."},
        "guardian_full": {"title": "Подробная папка для опекуна", "subtitle": "Развёрнутый семейный пакет для опекуна с лекарствами, документами и регулярными наблюдениями."},
        "weekend_duty": {"title": "Дежурство выходного дня", "subtitle": "Короткий комплект для родственника, который берёт уход на выходные."},
        "clinic_doctor": {"title": "Короткая сводка для врача поликлиники", "subtitle": "Сжатая печатная версия для визита к врачу и быстрого рассказа о семье."},
        "homecare_2weeks": {"title": "Контроль домашнего ухода на 2 недели", "subtitle": "Пакет для наблюдений, лекарств и бытового контроля на ближайшие 14 дней."},
        "morning_duty": {"title": "Утреннее дежурство семьи", "subtitle": "Короткая бумажная сводка для утренней смены ухода: лекарства, давление, сахар и что проверить сразу."},
        "evening_duty": {"title": "Вечернее дежурство семьи", "subtitle": "Пакет для вечернего контроля лекарств, самочувствия и ночной подготовки."},
        "helper_card": {"title": "Краткая карточка для соседей и помощников", "subtitle": "Очень короткая версия: кого позвать, что проверить и где лежат важные документы."},
        "weekly_board": {"title": "Недельная бумажная доска контроля", "subtitle": "Printable-формат для холодильника или папки: лекарства, давление, сахар и домашние отметки на неделю."},
        "weekday_shift": {"title": "Семейная смена: будни", "subtitle": "Короткая бумажная версия для будних дежурств с фокусом на ежедневных задачах."},
        "weekend_shift": {"title": "Семейная смена: выходные", "subtitle": "Пакет для выходных с акцентом на контроль лекарств и бытовых задач."},
        "social_route": {"title": "Маршрут для соцслужб", "subtitle": "Сводка для соцслужбы: кто пациент, что важно проверить и какие документы под рукой."},
        "child_school_trip": {"title": "Детский пакет для школы или поездки", "subtitle": "Короткая версия для школы, секции или поездки: лекарства, аллергии, контакты."},
        "shift_handover": {"title": "Передача смены между родственниками", "subtitle": "Узкий printable-пакет, чтобы быстро передать: что сделано, что осталось и где тревожные точки."},
        "respiratory_route": {"title": "Комбинированный дыхательный маршрут", "subtitle": "Сводка для длительного домашнего ухода с кислородом, вентиляцией, расходниками и бытовыми заметками."},
        "palliative_daily": {"title": "Паллиативный уход дома", "subtitle": "Печатная версия для длительного бытового ухода: боль, питание, симптомы, лекарства и передача смены."},
        "sedation_watch": {"title": "Наблюдение при длительной седации", "subtitle": "Узкий printable-пакет для смены семьи: дыхание, питание, лекарства и что нужно сверить перед передачей."},
        "airway_handover": {"title": "Смена при трахеостоме и дыхательной поддержке", "subtitle": "Пакет для домашних смен: расходники, тревожные признаки, документы и короткие бытовые инструкции."},
    }
    packet_info = packet_map.get(packet, packet_map["emergency"])
    return templates.TemplateResponse(
        request,
        "family_packet_print.html",
        {"request": request, "payload": payload, "packet": packet, "packet_info": packet_info},
    )


@router.post("/patients/{patient_id}/share")
def share_patient_page(
    request: Request,
    patient_id: int,
    viewer_email: str = Form(...),
    role: str = Form(default="read_only"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del request, patient_id, viewer_email, role, user, db
    return redirect_with_message("/family/users", "Прямой share отключён. Используйте семейные приглашения.", is_error=True)


@router.post("/patients/{patient_id}/share/{share_id}/delete")
def delete_patient_share_page(
    request: Request,
    patient_id: int,
    share_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    share = db.scalar(
        select(PatientShare).where(PatientShare.id == share_id, PatientShare.patient_id == patient.id)
    )
    if share:
        db.delete(share)
        db.commit()
    if is_htmx_request(request):
        context = build_dashboard_context(
            request=request,
            user=user,
            db=db,
            selected_patient_id=patient.id,
            message="Доступ удалён",
            is_error=False,
        )
        return build_template_response(request, "partials/shares.html", context)
    return redirect_with_message(f"/?selected_patient_id={patient.id}", "Доступ удалён")


@router.post("/patients/{patient_id}/share/{share_id}/reminders")
def update_patient_share_reminders_page(
    request: Request,
    patient_id: int,
    share_id: int,
    receive_reminders: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_writable_patient_for_user(patient_id, user, db)
    share = db.scalar(select(PatientShare).where(PatientShare.id == share_id, PatientShare.patient_id == patient.id))
    if not share:
        if is_htmx_request(request):
            context = build_dashboard_context(request, user, db, selected_patient_id=patient.id, message="Правило доступа не найдено", is_error=True)
            return build_template_response(request, "partials/shares.html", context)
        return redirect_with_message(f"/?selected_patient_id={patient.id}", "Правило доступа не найдено", is_error=True)

    share.receive_reminders = receive_reminders == "on"
    db.add(share)
    db.commit()
    message = "Напоминания для родственника обновлены"
    if is_htmx_request(request):
        context = build_dashboard_context(request, user, db, selected_patient_id=patient.id, message=message, is_error=False)
        return build_template_response(request, "partials/shares.html", context)
    return redirect_with_message(f"/?selected_patient_id={patient.id}", message)
