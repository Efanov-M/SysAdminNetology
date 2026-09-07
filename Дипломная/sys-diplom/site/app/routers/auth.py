from datetime import UTC, datetime
from secrets import token_urlsafe
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Family, Invite, User, UserPatient
from app.security import create_access_token, hash_password, verify_password
from app.services.rate_limit import is_rate_limited


router = APIRouter(tags=["auth"])


def _build_family_name(login: str) -> str:
    local_part = login.replace(".", " ").replace("_", " ").strip()
    return f"Семья {local_part.title() or 'PHR'}"


def _find_valid_invite(db: Session, token: str) -> Invite | None:
    invite = db.scalar(select(Invite).where(Invite.token == token))
    if not invite:
        return None
    if invite.used or invite.expires_at < datetime.now(UTC).replace(tzinfo=None):
        return None
    return invite


def _rate_limit_key(request: Request, action: str, login: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{action}:{client_host}:{login.strip().lower()}"


def _normalize_login(login: str | None, email: str | None = None) -> str:
    value = (login or email or "").strip().lower()
    return value


def _find_user_by_login(db: Session, normalized_login: str) -> User | None:
    user = db.scalar(select(User).where(User.login == normalized_login))
    if not user:
        user = db.scalar(select(User).where(User.email == normalized_login))
    return user


@router.post("/register")
def register(
    request: Request,
    login: str | None = Form(default=None),
    email: str | None = Form(default=None),
    password: str = Form(...),
    token: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    normalized_login = _normalize_login(login, email)
    invite_token = (token or "").strip()
    if is_rate_limited(_rate_limit_key(request, "register", normalized_login)):
        return RedirectResponse(
            url=f"/register?error={quote_plus('Слишком много попыток. Подождите минуту и попробуйте снова')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    existing_user = _find_user_by_login(db, normalized_login)
    if existing_user:
        return RedirectResponse(
            url=f"/register?error={quote_plus('Пользователь с таким логином уже существует')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if len(password) < 6:
        redirect_url = "/register"
        if invite_token:
            redirect_url += f"?token={quote_plus(invite_token)}&error={quote_plus('Пароль должен быть не короче 6 символов')}"
        else:
            redirect_url += f"?error={quote_plus('Пароль должен быть не короче 6 символов')}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    users_count = db.scalar(select(func.count()).select_from(User)) or 0
    is_initial_registration = users_count == 0

    if invite_token:
        invite = _find_valid_invite(db, invite_token)
        if not invite:
            return RedirectResponse(
                url=f"/register?error={quote_plus('Приглашение недействительно или уже использовано')}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        if normalized_login != invite.account_name.strip().lower():
            return RedirectResponse(
                url=f"/register?token={quote_plus(invite_token)}&error={quote_plus('Логин должен совпадать с приглашением')}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        user = User(
            login=normalized_login,
            email=normalized_login,
            password_hash=hash_password(password),
            family_id=invite.family_id,
            role="member",
        )
        db.add(user)
        db.flush()
        if invite.patient_id:
            db.add(UserPatient(user_id=user.id, patient_id=invite.patient_id))
        invite.used = True
        invite.used_by_user_id = user.id
        db.add(invite)
        db.commit()
    else:
        if not settings.allow_registration and not is_initial_registration:
            return RedirectResponse(
                url=f"/register?error={quote_plus('Свободная регистрация отключена. Используйте приглашение от владельца семьи')}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        family = Family(name=_build_family_name(normalized_login))
        db.add(family)
        db.flush()
        user = User(
            login=normalized_login,
            email=normalized_login,
            password_hash=hash_password(password),
            family_id=family.id,
            role="owner",
        )
        db.add(user)
        db.flush()
        family.owner_id = user.id
        db.add(family)
        db.commit()

    response = RedirectResponse(url="/login?registered=1", status_code=status.HTTP_303_SEE_OTHER)
    return response


@router.post("/login")
def login(
    request: Request,
    login: str | None = Form(default=None),
    email: str | None = Form(default=None),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    normalized_login = _normalize_login(login, email)
    if is_rate_limited(_rate_limit_key(request, "login", normalized_login)):
        return RedirectResponse(
            url=f"/login?error={quote_plus('Слишком много попыток входа. Подождите минуту и попробуйте снова')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    user = _find_user_by_login(db, normalized_login)
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(
            url=f"/login?error={quote_plus('Неверный логин или пароль')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    token = create_access_token(user.account_name)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        max_age=60 * 60 * 24,
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
