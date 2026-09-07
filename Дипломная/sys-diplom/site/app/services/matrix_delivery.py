from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MatrixProfile, Observation, Patient, PatientCheckin, User, UserPatient
from app.services.matrix_link import link_matrix_profile
from app.services.notification_queue import queue_dir, record_incident


logger = logging.getLogger(__name__)
_MATRIX_DIRECT_ROOM_CACHE: dict[str, str] = {}
_CODE_RE = re.compile(r"^[A-Z0-9]{4,12}$")
_PRESSURE_RE = re.compile(r"^(?:(?:давление|ад|pressure)\s+)?(\d{2,3})\s*(?:/|\s)\s*(\d{2,3})(?:\s+(?:(?:пульс|pulse)\s*)?(\d{2,3}))?$", re.IGNORECASE)
_SUGAR_RE = re.compile(r"^(?:сахар|sugar|glucose)\s+(\d{1,2}(?:[.,]\d)?)$", re.IGNORECASE)
_TEMPERATURE_RE = re.compile(r"^(?:температура|темп|temperature)\s+(\d{2}(?:[.,]\d)?)$", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"^(?:вес|weight)\s+(\d{1,3}(?:[.,]\d)?)$", re.IGNORECASE)


def matrix_state_path() -> Path:
    path = queue_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "matrix-bot-state.json"


def load_matrix_state() -> dict:
    path = matrix_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_matrix_state(state: dict) -> None:
    matrix_state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_matrix_room(matrix_user_id: str, room_id: str) -> None:
    normalized_matrix_user_id = (matrix_user_id or "").strip()
    normalized_room_id = (room_id or "").strip()
    if not normalized_matrix_user_id or not normalized_room_id:
        return
    _MATRIX_DIRECT_ROOM_CACHE[normalized_matrix_user_id] = normalized_room_id
    state = load_matrix_state()
    direct_rooms = dict(state.get("direct_rooms") or {})
    direct_rooms[normalized_matrix_user_id] = normalized_room_id
    state["direct_rooms"] = direct_rooms
    save_matrix_state(state)


def _matrix_dialog_state(matrix_user_id: str) -> dict:
    dialogs = dict(load_matrix_state().get("dialogs") or {})
    return dict(dialogs.get(matrix_user_id) or {})


def _set_matrix_dialog_state(matrix_user_id: str, payload: dict | None) -> None:
    state = load_matrix_state()
    dialogs = dict(state.get("dialogs") or {})
    if payload:
        dialogs[matrix_user_id] = payload
    else:
        dialogs.pop(matrix_user_id, None)
    state["dialogs"] = dialogs
    save_matrix_state(state)


def matrix_base_url() -> str | None:
    if not settings.matrix_homeserver_url or not settings.matrix_access_token:
        return None
    return settings.matrix_homeserver_url.rstrip("/")


def matrix_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.matrix_access_token}",
        "Content-Type": "application/json",
    }


def _retry_delay(attempt: int, exc: Exception) -> float:
    if isinstance(exc, HTTPError):
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except ValueError:
                pass
    return float(2**attempt)


def _should_retry_matrix_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 429 or 500 <= exc.code < 600
    if isinstance(exc, URLError):
        return True
    return "timed out" in str(exc).lower()


def matrix_request(method: str, path: str, payload: dict | None = None) -> dict:
    base_url = matrix_base_url()
    if not base_url:
        raise RuntimeError("matrix is not configured")
    last_error: Exception | None = None
    for attempt in range(3):
        request = Request(
            f"{base_url}{path}",
            data=json.dumps(payload or {}).encode("utf-8") if payload is not None else None,
            headers=matrix_headers(),
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except Exception as exc:
            last_error = exc
            if attempt >= 2 or not _should_retry_matrix_error(exc):
                raise
            time.sleep(_retry_delay(attempt, exc))
    if last_error:
        raise last_error
    return {}


def user_matrix_id(user: User) -> str | None:
    if getattr(user, "matrix_profile", None) and user.matrix_profile and user.matrix_profile.is_linked:
        return (user.matrix_profile.matrix_user_id or "").strip() or None
    return user.canonical_matrix_user_id


def ensure_matrix_direct_room(matrix_user_id: str, label: str | None = None) -> str:
    if settings.matrix_room_id:
        return settings.matrix_room_id
    if not matrix_user_id:
        raise RuntimeError("matrix_user_id is not configured")
    cached_room_id = _MATRIX_DIRECT_ROOM_CACHE.get(matrix_user_id)
    if not cached_room_id:
        cached_room_id = (load_matrix_state().get("direct_rooms") or {}).get(matrix_user_id)
    if cached_room_id:
        return cached_room_id
    payload = {
        "invite": [matrix_user_id],
        "is_direct": True,
        "preset": "trusted_private_chat",
        "name": f"Family PHR: {label or matrix_user_id}",
    }
    response = matrix_request("POST", "/_matrix/client/v3/createRoom", payload)
    room_id = response.get("room_id")
    if not room_id:
        raise RuntimeError("matrix createRoom did not return room_id")
    remember_matrix_room(matrix_user_id, room_id)
    return room_id


def linked_matrix_user(db: Session, sender: str) -> User | None:
    return db.scalar(
        select(User)
        .join(MatrixProfile, MatrixProfile.user_id == User.id)
        .where(MatrixProfile.matrix_user_id == sender, MatrixProfile.is_linked.is_(True))
    ) or db.scalar(select(User).where(or_(User.matrix_user_id == sender, User.matrix_id == sender)))


def matrix_accessible_patients(db: Session, user: User) -> list[Patient]:
    if user.role == "owner":
        return db.scalars(select(Patient).where(Patient.family_id == user.family_id).order_by(Patient.created_at.asc())).all()
    return db.scalars(
        select(Patient)
        .join(UserPatient, UserPatient.patient_id == Patient.id)
        .where(UserPatient.user_id == user.id)
        .order_by(Patient.created_at.asc())
    ).all()


def _remember_linked_room(db: Session, user: User, room_id: str) -> None:
    if not room_id:
        return
    profile = user.matrix_profile
    if not profile:
        profile = db.scalar(select(MatrixProfile).where(MatrixProfile.user_id == user.id).limit(1))
    if not profile or not profile.is_linked or not profile.matrix_user_id:
        return
    if profile.matrix_room_id != room_id:
        profile.matrix_room_id = room_id
        db.add(profile)
        db.commit()
    remember_matrix_room(profile.matrix_user_id, room_id)


def _extract_link_code(body: str) -> str | None:
    text = body.strip()
    if not text:
        return None
    if text.lower().startswith("/start "):
        candidate = text.split(maxsplit=1)[1].strip().upper()
        return candidate or None
    if _CODE_RE.fullmatch(text.upper()):
        return text.upper()
    return None


def _parse_measurement(body: str) -> dict | None:
    text = body.strip()
    match = _PRESSURE_RE.fullmatch(text)
    if match:
        return {
            "kind": "blood_pressure",
            "sys": int(match.group(1)),
            "dia": int(match.group(2)),
            "pulse": int(match.group(3)) if match.group(3) else None,
        }
    match = _SUGAR_RE.fullmatch(text)
    if match:
        return {"kind": "blood_sugar", "value": float(match.group(1).replace(",", ".")), "unit": "ммоль/л"}
    match = _TEMPERATURE_RE.fullmatch(text)
    if match:
        return {"kind": "temperature", "value": float(match.group(1).replace(",", ".")), "unit": "°C"}
    match = _WEIGHT_RE.fullmatch(text)
    if match:
        return {"kind": "weight", "value": float(match.group(1).replace(",", ".")), "unit": "кг"}
    return None


def _get_linked_matrix_profile(db: Session, user: User) -> MatrixProfile | None:
    profile = user.matrix_profile
    if profile:
        return profile
    return db.scalar(select(MatrixProfile).where(MatrixProfile.user_id == user.id).limit(1))


def _patients_by_id(db: Session, user: User) -> dict[int, Patient]:
    return {patient.id: patient for patient in matrix_accessible_patients(db, user)}


def _matrix_patient_prompt(user: User, patients: list[Patient]) -> str:
    lines = ["У вас несколько пациентов. Выберите активного:"]
    for patient in patients[:8]:
        lines.append(f"/use {patient.id} — {patient.name}")
    lines.append("Проверка текущего выбора: /current")
    return "\n".join(lines)


def _build_matrix_patient_picker(sender: str, patients: list[Patient], next_action: str | None = None) -> str:
    _set_matrix_dialog_state(
        sender,
        {
            "mode": "choose_patient",
            "patient_ids": [patient.id for patient in patients[:9]],
            "next_action": next_action or "",
        },
    )
    lines = ["Кого выбираем? Отправьте только цифру:"]
    for index, patient in enumerate(patients[:9], start=1):
        lines.append(f"{index}. {patient.name}")
    lines.append("0. Назад в меню")
    return "\n".join(lines)


def _set_active_matrix_patient(db: Session, user: User, patient: Patient) -> None:
    profile = _get_linked_matrix_profile(db, user)
    if not profile:
        return
    if profile.active_patient_id != patient.id:
        profile.active_patient_id = patient.id
        db.add(profile)
        db.commit()


def _resolve_matrix_patient(db: Session, user: User) -> tuple[Patient | None, str | None]:
    patients = matrix_accessible_patients(db, user)
    if not patients:
        return None, "У вас пока нет доступных пациентов."
    profile = _get_linked_matrix_profile(db, user)
    if len(patients) == 1:
        if profile and profile.active_patient_id != patients[0].id:
            profile.active_patient_id = patients[0].id
            db.add(profile)
            db.commit()
        return patients[0], None
    if profile and profile.active_patient_id:
        patient_map = {patient.id: patient for patient in patients}
        selected_patient = patient_map.get(profile.active_patient_id)
        if selected_patient:
            return selected_patient, None
    return None, _matrix_patient_prompt(user, patients)


def _matrix_account_summary(user: User, sender: str) -> str:
    return f"Matrix {sender} привязан к аккаунту Family PHR: {user.account_name}"


def _build_matrix_menu_message(db: Session, user: User, sender: str) -> str:
    patients = matrix_accessible_patients(db, user)
    profile = _get_linked_matrix_profile(db, user)
    active_patient = None
    if profile and profile.active_patient_id:
        active_patient = next((patient for patient in patients if patient.id == profile.active_patient_id), None)
    if not active_patient and len(patients) == 1:
        active_patient = patients[0]

    _set_matrix_dialog_state(sender, {"mode": "main_menu"})
    lines = ["Что хотите сделать?"]
    if active_patient:
        lines.append(f"Сейчас выбран: {active_patient.name}")
    elif patients:
        lines.append("Пациент пока не выбран.")
    else:
        lines.append("У вас пока нет доступных пациентов.")
    lines.extend(
        [
            "",
            "1. Давление",
            "2. Сахар",
            "3. Температура",
            "4. Вес",
            "5. Мне плохо",
            "6. Выбрать пациента",
            "7. Кто сейчас выбран",
            "8. Помощь",
            "",
            "Можно также писать сразу:",
            "120 80 63",
            "сахар 5.6",
            "температура 36.6",
        ]
    )
    return "\n".join(lines)


def _build_matrix_guest_menu_message() -> str:
    return "\n".join(
        [
            "Меню Matrix-бота Family PHR",
            "1. Откройте сайт и получите код привязки.",
            "2. Отправьте боту код вида U9OK91 или /start U9OK91.",
            "",
            "После привязки можно писать:",
            "120 80 63",
            "сахар 5.6",
            "температура 36.6",
            "вес 72.4",
            "мне плохо",
            "",
            "Команды после привязки:",
            "/menu",
            "/patients",
            "/use ID",
            "/current",
            "/status",
            "/inbox",
            "/ack ID",
        ]
    )


def _build_matrix_linked_message(db: Session, user: User, sender: str) -> str:
    lines = [
        "Устройство подключено.",
        "Аккаунт успешно привязан.",
        _matrix_account_summary(user, sender),
    ]
    patients = matrix_accessible_patients(db, user)
    if len(patients) == 1:
        lines.append(f"Текущий пациент: {patients[0].name}")
    elif len(patients) > 1:
        lines.append(f"Доступно пациентов: {len(patients)}.")
        lines.append("Вы кто? Сейчас помогу выбрать пациента.")
        lines.append("")
        lines.append(_build_matrix_patient_picker(sender, patients))
        return "\n".join(lines)
    lines.append("Для подсказки отправьте /menu или просто 1")
    return "\n".join(lines)


def _parse_decimal_text(text: str) -> float | None:
    candidate = text.strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,3}(?:\.\d)?", candidate):
        return None
    return float(candidate)


def _parse_measurement_for_mode(mode: str, body: str) -> dict | None:
    text = body.strip()
    if mode == "pressure":
        match = re.fullmatch(r"(\d{2,3})\s*(?:/|\s)\s*(\d{2,3})(?:\s+(\d{2,3}))?", text)
        if match:
            return {
                "kind": "blood_pressure",
                "sys": int(match.group(1)),
                "dia": int(match.group(2)),
                "pulse": int(match.group(3)) if match.group(3) else None,
            }
        return None
    value = _parse_decimal_text(text)
    if value is None:
        return None
    if mode == "sugar":
        return {"kind": "blood_sugar", "value": value, "unit": "ммоль/л"}
    if mode == "temperature":
        return {"kind": "temperature", "value": value, "unit": "°C"}
    if mode == "weight":
        return {"kind": "weight", "value": value, "unit": "кг"}
    return None


def _resolve_patient_or_prompt(db: Session, user: User, sender: str, next_action: str | None = None) -> tuple[Patient | None, str | None]:
    patients = matrix_accessible_patients(db, user)
    if not patients:
        return None, "У вас пока нет доступных пациентов."
    profile = _get_linked_matrix_profile(db, user)
    if len(patients) == 1:
        if profile and profile.active_patient_id != patients[0].id:
            profile.active_patient_id = patients[0].id
            db.add(profile)
            db.commit()
        return patients[0], None
    if profile and profile.active_patient_id:
        selected = next((patient for patient in patients if patient.id == profile.active_patient_id), None)
        if selected:
            return selected, None
    if next_action in {"pressure", "sugar", "temperature", "weight", "alert"}:
        prompts = {
            "pressure": "Сначала выберите пациента.",
            "sugar": "Сначала выберите пациента.",
            "temperature": "Сначала выберите пациента.",
            "weight": "Сначала выберите пациента.",
            "alert": "Для тревоги сначала выберите пациента.",
        }
        return None, prompts[next_action] + "\n\n" + _build_matrix_patient_picker(sender, patients, next_action=next_action)
    return None, _build_matrix_patient_picker(sender, patients, next_action=next_action)


def _save_matrix_measurement(db: Session, user: User, patient: Patient, payload: dict) -> str:
    kind = payload["kind"]
    if kind == "blood_pressure":
        observation = Observation(
            patient_id=patient.id,
            type="blood_pressure",
            value={"sys": payload["sys"], "dia": payload["dia"], "pulse": payload.get("pulse")},
        )
        db.add(observation)
        db.commit()
        from app.services.alerts_service import check_threshold_alerts

        check_threshold_alerts(db, patient, "blood_pressure", observation.value, observation.created_at)
        pulse_suffix = f" пульс {payload['pulse']}." if payload.get("pulse") else "."
        return f"Сохранено: {patient.name} — давление {payload['sys']}/{payload['dia']}{pulse_suffix}"
    observation = Observation(
        patient_id=patient.id,
        type=kind,
        value={"value": payload["value"], "unit": payload.get("unit"), "label": None},
    )
    db.add(observation)
    if kind == "weight":
        patient.weight = payload["value"]
        db.add(patient)
    db.commit()
    if kind == "blood_sugar":
        from app.services.alerts_service import check_threshold_alerts

        check_threshold_alerts(db, patient, "blood_sugar", observation.value, observation.created_at)
        return f"Сохранено: {patient.name} — сахар {payload['value']} {payload.get('unit') or 'ммоль/л'}."
    if kind == "weight":
        return f"Сохранено: {patient.name} — вес {payload['value']} {payload.get('unit') or 'кг'}."
    return f"Сохранено: {patient.name} — температура {payload['value']} {payload.get('unit') or '°C'}."


def _menu_prompt_for_choice(choice: int, patient_name: str | None = None) -> str:
    if choice == 1:
        suffix = f" для {patient_name}" if patient_name else ""
        return f"Введите давление{suffix} через пробел:\n120 80 63\n\nГде 63 — пульс. Если пульса нет:\n120 80"
    if choice == 2:
        suffix = f" для {patient_name}" if patient_name else ""
        return f"Введите сахар{suffix}:\n5.6"
    if choice == 3:
        suffix = f" для {patient_name}" if patient_name else ""
        return f"Введите температуру{suffix}:\n36.6"
    if choice == 4:
        suffix = f" для {patient_name}" if patient_name else ""
        return f"Введите вес{suffix}:\n72.4"
    return ""


def handle_matrix_message(db: Session, sender: str, room_id: str, body: str) -> str | None:
    from app.services.care import acknowledge_inbox_item, describe_inbox_item, list_relative_inbox_items, summarize_inbox_by_patient
    from app.services.emergency_service import create_emergency_signal

    text = body.strip()
    if not text:
        return None
    dialog_state = _matrix_dialog_state(sender)

    code = _extract_link_code(text)
    if code:
        success, message = link_matrix_profile(db, sender, room_id, code)
        if success:
            remember_matrix_room(sender, room_id)
            linked_user = linked_matrix_user(db, sender)
            if linked_user:
                return _build_matrix_linked_message(db, linked_user, sender)
            if text.lower().startswith("/start "):
                return message or "Устройство подключено"
            return "Аккаунт успешно привязан"
        return message or "Неверный или просроченный код"

    parts = text.split()
    command = parts[0].lower()
    user = linked_matrix_user(db, sender)
    if not user:
        if command in {"/help", "/menu"} or text.lower() in {"меню", "menu", "помощь", "help"}:
            return _build_matrix_guest_menu_message()
        return "Matrix-аккаунт ещё не привязан.\n\n" + _build_matrix_guest_menu_message()

    _remember_linked_room(db, user, room_id)

    if text == "0":
        return _build_matrix_menu_message(db, user, sender)

    if dialog_state.get("mode") == "choose_patient" and text.isdigit():
        choice = int(text)
        if choice == 0:
            return _build_matrix_menu_message(db, user, sender)
        patient_ids = list(dialog_state.get("patient_ids") or [])
        if 1 <= choice <= len(patient_ids):
            patient_map = _patients_by_id(db, user)
            patient = patient_map.get(patient_ids[choice - 1])
            if patient:
                _set_active_matrix_patient(db, user, patient)
                next_action = str(dialog_state.get("next_action") or "")
                if next_action == "pressure":
                    _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "pressure"})
                    return f"Текущий пациент: {patient.name}\n\n" + _menu_prompt_for_choice(1, patient.name)
                if next_action == "sugar":
                    _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "sugar"})
                    return f"Текущий пациент: {patient.name}\n\n" + _menu_prompt_for_choice(2, patient.name)
                if next_action == "temperature":
                    _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "temperature"})
                    return f"Текущий пациент: {patient.name}\n\n" + _menu_prompt_for_choice(3, patient.name)
                if next_action == "weight":
                    _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "weight"})
                    return f"Текущий пациент: {patient.name}\n\n" + _menu_prompt_for_choice(4, patient.name)
                if next_action == "alert":
                    event, results = create_emergency_signal(db, patient, "Мне плохо")
                    sent_count = sum(1 for item in results if item.get("status") == "sent")
                    record_incident(
                        "matrix_bot_emergency_signal",
                        {
                            "channel": "matrix",
                            "sender": sender,
                            "room_id": room_id,
                            "patient_id": patient.id,
                            "emergency_event_id": event.id,
                            "sent_count": sent_count,
                        },
                    )
                    if sent_count:
                        return f"Текущий пациент: {patient.name}\n\nСигнал отправлен. Уведомления доставлены {sent_count} получателям.\n\n" + _build_matrix_menu_message(db, user, sender)
                    return f"Текущий пациент: {patient.name}\n\nСигнал создан, но уведомление пока не доставлено.\n\n" + _build_matrix_menu_message(db, user, sender)
                return f"Текущий пациент: {patient.name}\n\n" + _build_matrix_menu_message(db, user, sender)
        return "Не понял выбор. Отправьте только цифру из списка."

    if dialog_state.get("mode") == "await_measurement":
        measurement = _parse_measurement_for_mode(str(dialog_state.get("measurement_kind") or ""), text)
        if not measurement:
            kind = str(dialog_state.get("measurement_kind") or "")
            prompts = {
                "pressure": "Введите давление через пробел: 120 80 63",
                "sugar": "Введите сахар: 5.6",
                "temperature": "Введите температуру: 36.6",
                "weight": "Введите вес: 72.4",
            }
            return prompts.get(kind, "Введите значение ещё раз.")
        patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action=str(dialog_state.get("measurement_kind") or ""))
        if error_message:
            return error_message
        _set_matrix_dialog_state(sender, {"mode": "main_menu"})
        message = _save_matrix_measurement(db, user, patient, measurement)
        return message + "\n\n" + _build_matrix_menu_message(db, user, sender)

    if command == "/ping":
        return "Бот на связи."
    if command in {"/help", "/menu"} or text.lower() in {"меню", "menu", "помощь", "help"}:
        return _build_matrix_menu_message(db, user, sender)
    if text.isdigit() and dialog_state.get("mode") == "main_menu":
        choice = int(text)
        if choice == 1:
            patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action="pressure")
            if error_message:
                return error_message
            _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "pressure"})
            return _menu_prompt_for_choice(choice, patient.name if patient else None)
        if choice == 2:
            patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action="sugar")
            if error_message:
                return error_message
            _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "sugar"})
            return _menu_prompt_for_choice(choice, patient.name if patient else None)
        if choice == 3:
            patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action="temperature")
            if error_message:
                return error_message
            _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "temperature"})
            return _menu_prompt_for_choice(choice, patient.name if patient else None)
        if choice == 4:
            patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action="weight")
            if error_message:
                return error_message
            _set_matrix_dialog_state(sender, {"mode": "await_measurement", "measurement_kind": "weight"})
            return _menu_prompt_for_choice(choice, patient.name if patient else None)
        if choice == 5:
            patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action="alert")
            if error_message:
                return error_message
            event, results = create_emergency_signal(db, patient, "Мне плохо")
            sent_count = sum(1 for item in results if item.get("status") == "sent")
            record_incident(
                "matrix_bot_emergency_signal",
                {
                    "channel": "matrix",
                    "sender": sender,
                    "room_id": room_id,
                    "patient_id": patient.id,
                    "emergency_event_id": event.id,
                    "sent_count": sent_count,
                },
            )
            if sent_count:
                return f"Сигнал отправлен: {patient.name}. Уведомления доставлены {sent_count} получателям.\n\n" + _build_matrix_menu_message(db, user, sender)
            return f"Сигнал создан для {patient.name}, но уведомление пока не доставлено.\n\n" + _build_matrix_menu_message(db, user, sender)
        if choice == 6:
            patients = matrix_accessible_patients(db, user)
            if not patients:
                return "У вас пока нет доступных пациентов."
            return _build_matrix_patient_picker(sender, patients)
        if choice == 7:
            patient, error_message = _resolve_matrix_patient(db, user)
            if error_message:
                return error_message
            return f"Сейчас выбран пациент: {patient.name}\n\n" + _build_matrix_menu_message(db, user, sender)
        if choice == 8:
            return _build_matrix_menu_message(db, user, sender)
        return "Не понял выбор. Отправьте цифру от 1 до 8."
    if command == "/patients":
        patients = matrix_accessible_patients(db, user)
        if not patients:
            return "У вас пока нет доступных пациентов."
        active_patient, _ = _resolve_matrix_patient(db, user)
        picker = _build_matrix_patient_picker(sender, patients)
        if active_patient:
            return f"Сейчас выбран: {active_patient.name}\n\n{picker}"
        return picker
    if command == "/use":
        if len(parts) < 2 or not parts[1].isdigit():
            return "Укажите ID пациента: /use 123"
        patient_map = _patients_by_id(db, user)
        patient = patient_map.get(int(parts[1]))
        if not patient:
            return "Пациент не найден."
        _set_active_matrix_patient(db, user, patient)
        return f"Текущий пациент: {patient.name}"
    if text.isdigit() and not dialog_state.get("mode"):
        return _build_matrix_menu_message(db, user, sender)
    if command == "/current":
        patient, error_message = _resolve_matrix_patient(db, user)
        if error_message:
            return error_message
        return f"Текущий пациент: {patient.name}"
    if command == "/status":
        return build_matrix_status_message(db, sender)
    if command == "/inbox":
        items = list_relative_inbox_items(db, user, limit=5)
        if not items:
            return "Новых тревог и пропусков нет."
        grouped = summarize_inbox_by_patient(items)
        total = sum(len(group["items"]) for group in grouped)
        lines = [f"Inbox Family PHR: {total} новых событий"]
        for group in grouped:
            lines.append(f"{group['patient'].name}: {len(group['items'])} новых")
            for item in group["items"][:3]:
                lines.append(f"#{item.id} • {describe_inbox_item(item)}")
        lines.append("Подтверждение: /ack ID")
        return "\n".join(lines)
    if command == "/ack" and len(parts) >= 2 and parts[1].isdigit():
        from app.models import InboxEvent

        item = db.scalar(select(InboxEvent).where(InboxEvent.id == int(parts[1])))
        accessible_patient_ids = {patient.id for patient in user.family.patients} if user.role == "owner" else {link.patient_id for link in user.patient_links}
        if not item or item.patient_id not in accessible_patient_ids:
            return "Событие не найдено."
        acknowledge_inbox_item(db, user, item, "Подтверждено из Matrix")
        remaining = db.scalar(select(func.count(InboxEvent.id)).where(InboxEvent.patient_id == item.patient_id, InboxEvent.status == "new")) or 0
        if remaining:
            return f"Подтверждено: {item.patient.name} • {describe_inbox_item(item)}.\nОсталось новых событий: {remaining}."
        return f"Подтверждено: {item.patient.name} • {describe_inbox_item(item)}.\nПо этому пациенту новых событий больше нет."
    if command == "/alert" or text.lower() in {"мне плохо", "тревога"}:
        patient, error_message = _resolve_matrix_patient(db, user)
        if error_message:
            return error_message
        event, results = create_emergency_signal(db, patient, "Мне плохо")
        sent_count = sum(1 for item in results if item.get("status") == "sent")
        record_incident(
            "matrix_bot_emergency_signal",
            {
                "channel": "matrix",
                "sender": sender,
                "room_id": room_id,
                "patient_id": patient.id,
                "emergency_event_id": event.id,
                "sent_count": sent_count,
            },
        )
        if sent_count:
            return f"Сигнал отправлен: {patient.name}. Уведомления доставлены {sent_count} получателям."
        return f"Сигнал создан для {patient.name}, но уведомление пока не доставлено. Проверьте Matrix-настройки."

    measurement = _parse_measurement(text)
    if measurement:
        patient, error_message = _resolve_patient_or_prompt(db, user, sender, next_action="pressure" if measurement["kind"] == "blood_pressure" else measurement["kind"].replace("blood_sugar", "sugar"))
        if error_message:
            return error_message
        message = _save_matrix_measurement(db, user, patient, measurement)
        record_incident(
            "matrix_bot_measurement_saved",
            {
                "channel": "matrix",
                "sender": sender,
                "room_id": room_id,
                "patient_id": patient.id,
                "measurement_type": measurement["kind"],
            },
        )
        return message

    if command.startswith("/"):
        return "Команда не распознана.\n\n" + _build_matrix_menu_message(db, user, sender)
    return None


class MatrixBotService:
    def __init__(self) -> None:
        self.bot_user_id = (settings.matrix_bot_id or settings.matrix_user_id or "").strip() or None

    def is_configured(self) -> bool:
        return bool(matrix_base_url() and settings.matrix_access_token)

    def send_message(self, target: str, message: str) -> dict:
        if not self.is_configured():
            return {"channel": "matrix", "status": "failed", "error": "matrix is not configured"}
        try:
            room_id = target if target.startswith("!") else ensure_matrix_direct_room(target, label=target)
            response = matrix_request(
                "PUT",
                f"/_matrix/client/v3/rooms/{quote(room_id, safe='')}/send/m.room.message/{uuid4().hex}",
                {"msgtype": "m.text", "body": message},
            )
            return {
                "channel": "matrix",
                "status": "sent",
                "target": target,
                "room_id": room_id,
                "event_id": response.get("event_id"),
            }
        except Exception as exc:
            logger.warning("Matrix bot send failed for %s: %s", target, exc)
            return {"channel": "matrix", "status": "failed", "error": "matrix_unavailable", "target": target}

    def process_incoming_commands(self, db: Session) -> list[dict]:
        if not self.is_configured():
            return []
        state = load_matrix_state()
        params = {"timeout": 1000}
        if state.get("next_batch"):
            params["since"] = state["next_batch"]
        try:
            payload = matrix_request("GET", f"/_matrix/client/r0/sync?{urlencode(params)}")
        except Exception as exc:
            logger.warning("Matrix bot sync failed: %s", exc)
            record_incident("matrix_bot_sync_failed", {"channel": "matrix", "error": str(exc)})
            return []

        processed: list[dict] = []
        joined_rooms = (((payload.get("rooms") or {}).get("join")) or {})
        for room_id, room_data in joined_rooms.items():
            events = ((((room_data or {}).get("timeline") or {}).get("events")) or [])
            for event in events:
                if event.get("type") != "m.room.message":
                    continue
                sender = (event.get("sender") or "").strip()
                body = ((event.get("content") or {}).get("body") or "").strip()
                if self.bot_user_id and sender == self.bot_user_id:
                    continue
                reply = handle_matrix_message(db, sender, room_id, body)
                if not reply:
                    continue
                result = self.send_message(room_id, reply)
                processed.append({"room_id": room_id, "sender": sender, "command": body, "result": result})
                record_incident(
                    "matrix_bot_command_processed",
                    {
                        "channel": "matrix",
                        "room_id": room_id,
                        "sender": sender,
                        "command": body,
                        "status": result.get("status"),
                    },
                )

        if payload.get("next_batch"):
            state = load_matrix_state()
            state["next_batch"] = payload["next_batch"]
            state["updated_at"] = datetime.now(UTC).isoformat()
            save_matrix_state(state)
        return processed

    def _handle_command(self, db: Session, sender: str, room_id: str, body: str) -> str | None:
        return handle_matrix_message(db, sender, room_id, body)

def build_matrix_status_message(db: Session, sender: str) -> str:
    user = linked_matrix_user(db, sender)
    if not user:
        return "Matrix-аккаунт не привязан к пользователю Family PHR."

    patients = matrix_accessible_patients(db, user)
    if not patients:
        return "У вас пока нет доступных пациентов."

    profile = _get_linked_matrix_profile(db, user)
    patient_map = {item.id: item for item in patients}
    patient = patient_map.get(profile.active_patient_id) if profile and profile.active_patient_id else None
    if not patient:
        patient = patients[0]
    lines = ["Краткий статус", _matrix_account_summary(user, sender), f"Пациент: {patient.name}"]
    if len(patients) > 1:
        lines.append(f"Всего пациентов: {len(patients)}")

    latest_observation = db.scalar(
        select(Observation).where(Observation.patient_id == patient.id).order_by(Observation.created_at.desc()).limit(1)
    )
    latest_checkin = db.scalar(
        select(PatientCheckin).where(PatientCheckin.patient_id == patient.id).order_by(PatientCheckin.created_at.desc()).limit(1)
    )
    if latest_observation:
        lines.append(f"Последняя запись: {latest_observation.created_at.strftime('%d.%m.%Y %H:%M')}")
        if latest_observation.type == "blood_pressure":
            lines.append(f"Давление: {latest_observation.value.get('sys', '?')}/{latest_observation.value.get('dia', '?')}")
        elif latest_observation.type == "blood_sugar":
            lines.append(f"Сахар: {latest_observation.value.get('value', '?')} {latest_observation.value.get('unit', '')}".strip())
        elif latest_observation.type == "temperature":
            lines.append(f"Температура: {latest_observation.value.get('value', '?')} {latest_observation.value.get('unit', '°C')}".strip())
        else:
            lines.append(f"Тип записи: {latest_observation.type}")
    else:
        lines.append("Свежих записей пока нет.")
    if latest_checkin:
        status_label = {
            "feeling_ok": "Я в порядке",
            "feeling_bad": "Мне плохо",
            "medication_taken": "Лекарства приняты",
            "missed_data": "Нет показателей",
            "missed_medication": "Пропущен приём лекарств",
        }.get(latest_checkin.checkin_type, latest_checkin.checkin_type)
        lines.append(f"Самочувствие: {status_label}")
        lines.append(f"Отмечено: {latest_checkin.created_at.strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(lines)


def send_matrix_message(user: User, text: str) -> dict:
    if "matrix" not in (user.notification_channels or []):
        return {"channel": "matrix", "status": "skipped", "reason": "disabled"}
    profile = getattr(user, "matrix_profile", None)
    target = None
    if profile and profile.is_linked:
        if profile.matrix_room_id:
            target = profile.matrix_room_id.strip()
            remember_matrix_room(profile.matrix_user_id or "", target)
        else:
            target = (profile.matrix_user_id or "").strip() or None
    if not target:
        target = settings.matrix_room_id or user_matrix_id(user)
    if not target:
        return {"channel": "matrix", "status": "skipped", "reason": "matrix_not_connected"}
    return MatrixBotService().send_message(target, text)


def send_matrix_target_message(target: str, text: str) -> dict:
    if not target.strip():
        return {"channel": "matrix", "status": "failed", "error": "matrix_target_missing"}
    return MatrixBotService().send_message(target.strip(), text)


def process_matrix_bot_updates(db: Session) -> list[dict]:
    return MatrixBotService().process_incoming_commands(db)
