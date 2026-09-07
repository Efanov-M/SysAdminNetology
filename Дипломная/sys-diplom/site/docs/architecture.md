# Architecture

`Family PHR MVP` остаётся монолитом `FastAPI + Jinja2 + PostgreSQL`, но внутри уже разбит на понятные домены.

## Контейнеры

- `web` — основной FastAPI/Jinja2 backend
- `notification-worker` — фоновая обработка retry-очереди, reminder-циклы и Matrix sync
- `matrix-bot` — отдельный listener для Matrix / Element
- `db` — PostgreSQL

## Backend слои

### Entry points

- `app/main.py` — bootstrap, middleware, health/readiness
- `app/workers/` — worker entry points
- `matrix-bot/` — отдельный Matrix listener

### Core

- `app/core/config.py` — runtime settings
- `app/core/security.py` — password hashing and JWT helpers
- `app/core/csrf.py` — CSRF token generation and validation
- `app/core/middleware.py` — security headers and request middleware

Старые импорты `app.config`, `app.security`, `app.csrf` и `app.middleware` оставлены как совместимые адаптеры.

### Database

- `app/database/session.py` — SQLAlchemy `Base`, engine, session factory and `get_db`
- `app/db.py` — compatibility facade for older imports and alembic/tests

### Routers

- `app/routers/auth.py` — login/register/session
- `app/routers/api.py` — JSON API
- `app/routers/family.py` — семья, инвайты, printable family flows
- `app/routers/account.py` — account settings, Matrix link, worker monitor
- `app/routers/documents.py` — документы и import/review flows
- `app/routers/inbox.py` — inbox события
- `app/routers/patients.py` — dashboard, patient pages, simple mode
- `app/routers/planner.py` — reminder/event pages
- `app/routers/admin.py` — operational/admin pages

### Schemas

- `app/schemas/` — Pydantic request/response contracts for API boundaries

The package keeps `from app.schemas import PatientRead` style imports working.

### Models

- `app/models/` — SQLAlchemy ORM entities and database model helpers

The package keeps `from app.models import Patient` style imports working.

### Repositories

- `app/repositories/base.py` — shared repository base
- `app/repositories/users.py` — user lookup queries
- `app/repositories/patients.py` — patient access queries

Repositories own reusable database queries. Services and dependencies should prefer them over duplicating raw `select(...)` blocks.

### Services

- `app/services/records.py` — read-model helpers for screens
- `app/services/alerts_service.py` — threshold alerts
- `app/services/emergency_service.py` — emergency signal flow
- `app/services/inbox_service.py` — inbox helpers
- `app/services/reminders_service.py` — reminder logic
- `app/services/today_service.py` — dashboard/today context
- `app/services/notification_delivery.py` — senders for email/telegram/matrix
- `app/services/notification_queue.py` — file-backed retry queue, incidents, diagnostics
- `app/services/notification_worker_flow.py` — worker retry loop
- `app/services/matrix_link.py` — link code flow
- `app/services/matrix_delivery.py` — Matrix delivery, bot menu, patient context
- `app/services/pdf_import.py` — OCR/import pipeline

## Модель данных

Ключевые сущности:

- `User`
- `Family`
- `Invite`
- `Patient`
- `UserPatient`
- `Observation`
- `Medication`
- `Document`
- `MatrixProfile`
- `Reminder`
- `InboxEvent`
- `EmergencyEvent`

Canonical поля после cleanup:

- account identity: `login`
- Matrix identity: `matrix_user_id`
- Matrix link status: `is_linked`

## Очередь уведомлений

Очередь остаётся file-backed и хранится в `backups/notification_queue/`, но теперь использует:

- атомарную запись `temp file + rename`
- `*.processing` marker для claim worker'ом
- lock при записи incident history
- отдельный мониторинг в `/account/worker-monitor`

## Matrix

Matrix разделён на два контура:

- `matrix-bot` принимает входящие сообщения и проксирует их в backend
- backend хранит привязку пользователя, room id, активного пациента и решает медицинскую логику

Подробности: `docs/matrix.md`

## Почему проект не разбит на microservices

Это deliberate tradeoff:

- проще self-hosted развёртывание;
- проще миграции и авторизация;
- меньше operational cost для семейного сценария;
- можно быстрее поддерживать UX для реального домашнего использования.
