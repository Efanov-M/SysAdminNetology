from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Patient, User, UserPatient
from app.repositories.patients import patients_repository
from app.repositories.users import users_repository
from app.security import decode_token


def get_current_user(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = access_token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Нужен вход в систему")

    subject = decode_token(token)
    user = users_repository(db).get_by_login_or_email(subject)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


def get_patient_for_user(patient_id: int, user: User, db: Session) -> Patient:
    patient = patients_repository(db).get_visible_to_user(patient_id, user)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пациент не найден")
    return patient


def can_write_patient(patient: Patient, user: User) -> bool:
    return patient.family_id == user.family_id and (user.role == "owner" or any(link.user_id == user.id for link in patient.user_links))


def get_patient_access_role(patient: Patient, user: User) -> str:
    if patient.family_id != user.family_id:
        return "none"
    return user.role if can_write_patient(patient, user) else "none"


def can_comment_patient(patient: Patient, user: User) -> bool:
    return can_write_patient(patient, user)


def get_writable_patient_for_user(patient_id: int, user: User, db: Session) -> Patient:
    patient = get_patient_for_user(patient_id, user, db)
    if not can_write_patient(patient, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас только доступ на просмотр для этого пациента",
        )
    return patient
