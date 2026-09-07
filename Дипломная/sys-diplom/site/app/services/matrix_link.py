from __future__ import annotations

import string
from datetime import UTC, datetime, timedelta
from secrets import choice

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MatrixLinkToken, MatrixProfile, User


def generate_matrix_link_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(choice(alphabet) for _ in range(length))


def get_or_create_matrix_profile(db: Session, user: User) -> MatrixProfile:
    profile = db.scalar(select(MatrixProfile).where(MatrixProfile.user_id == user.id).limit(1))
    if profile:
        return profile
    profile = MatrixProfile(user_id=user.id, connected=False, is_linked=False)
    db.add(profile)
    db.flush()
    return profile


def start_matrix_link(db: Session, user: User, ttl_minutes: int = 10) -> MatrixLinkToken:
    now = datetime.now(UTC).replace(tzinfo=None)
    active_token = db.scalar(
        select(MatrixLinkToken)
        .where(
            MatrixLinkToken.user_id == user.id,
            MatrixLinkToken.used.is_(False),
            MatrixLinkToken.expires_at >= now,
        )
        .order_by(MatrixLinkToken.id.desc())
        .limit(1)
    )
    if active_token:
        return active_token

    code = generate_matrix_link_code()
    while db.scalar(select(MatrixLinkToken).where(MatrixLinkToken.token == code)):
        code = generate_matrix_link_code()

    profile = get_or_create_matrix_profile(db, user)
    profile.link_code = code
    profile.is_linked = False
    profile.connected = False
    profile.matrix_user_id = None
    profile.matrix_room_id = None
    profile.active_patient_id = None
    profile.created_at = now
    token = MatrixLinkToken(
        user_id=user.id,
        token=code,
        expires_at=now + timedelta(minutes=ttl_minutes),
        used=False,
    )
    db.add(profile)
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def get_matrix_profile(db: Session, user: User) -> MatrixProfile | None:
    return db.scalar(select(MatrixProfile).where(MatrixProfile.user_id == user.id).limit(1))


def get_active_matrix_link(db: Session, user: User, ttl_minutes: int = 10) -> MatrixLinkToken | None:
    now = datetime.now(UTC).replace(tzinfo=None)
    return db.scalar(
        select(MatrixLinkToken)
        .where(
            MatrixLinkToken.user_id == user.id,
            MatrixLinkToken.used.is_(False),
            MatrixLinkToken.expires_at >= now - timedelta(minutes=ttl_minutes),
        )
        .order_by(MatrixLinkToken.id.desc())
        .limit(1)
    )


def link_matrix_profile(db: Session, matrix_user_id: str, room_id: str, code_value: str, ttl_minutes: int = 10) -> tuple[bool, str]:
    code = code_value.strip().upper()
    now = datetime.now(UTC).replace(tzinfo=None)
    token = db.scalar(select(MatrixLinkToken).where(MatrixLinkToken.token == code).limit(1))
    if not token or token.used or token.expires_at < now - timedelta(minutes=ttl_minutes):
        return False, "Неверный или устаревший код"

    user = db.get(User, token.user_id)
    if not user:
        token.used = True
        db.add(token)
        db.commit()
        return False, "Неверный или устаревший код"

    profile = get_or_create_matrix_profile(db, user)
    normalized_matrix_id = matrix_user_id.strip()
    if profile.is_linked and profile.matrix_user_id == normalized_matrix_id:
        token.used = True
        db.add(token)
        db.commit()
        return True, "Устройство уже подключено"

    profile.matrix_user_id = normalized_matrix_id
    profile.matrix_room_id = room_id.strip() or None
    profile.is_linked = True
    profile.connected = True
    profile.link_code = None
    token.used = True
    user.matrix_user_id = normalized_matrix_id
    user.matrix_id = normalized_matrix_id
    if "matrix" not in (user.notification_channels or []):
        user.notification_channels = [*(user.notification_channels or ["log"]), "matrix"]
    db.add(profile)
    db.add(token)
    db.add(user)
    db.commit()
    return True, "Устройство подключено"


def unlink_matrix_profile(db: Session, user: User) -> MatrixProfile:
    profile = get_or_create_matrix_profile(db, user)
    profile.is_linked = False
    profile.connected = False
    profile.matrix_user_id = None
    profile.matrix_room_id = None
    profile.active_patient_id = None
    profile.link_code = None
    user.matrix_user_id = None
    user.matrix_id = None
    db.add(profile)
    db.add(user)
    db.commit()
    db.refresh(profile)
    return profile


def create_matrix_link_token(db: Session, user: User, ttl_minutes: int = 10) -> MatrixLinkToken:
    return start_matrix_link(db, user, ttl_minutes=ttl_minutes)


def get_active_matrix_link_token(db: Session, user: User) -> MatrixLinkToken | None:
    return get_active_matrix_link(db, user)


def consume_matrix_link_token(db: Session, matrix_user_id: str, token_value: str) -> tuple[bool, str]:
    return link_matrix_profile(db, matrix_user_id, "", token_value)
