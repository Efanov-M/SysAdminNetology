# Family PHR MVP

Self-hosted семейная медицинская карта на `FastAPI + Jinja2 + PostgreSQL`.

## Что это

`Family PHR MVP` помогает семье вести домашнюю карту пациента без отдельного frontend-приложения:

- семейные аккаунты и приглашения;
- взрослый и детский режимы;
- быстрый ввод давления, сахара, температуры, веса и детских событий;
- напоминания, тревоги и уведомления;
- Matrix / Element бот для привязки, ввода показателей и alert-сигналов;
- документы, printable-форматы, backup/restore.

Проект остаётся монолитом, но уже разделён на домены в `routers/` и `services/`.

Подробности:
- архитектура: [docs/architecture.md](/Users/mihailefanov/Documents/VSCODE/Python3/projects/family-phr-mvp/docs/architecture.md)
- деплой: [docs/deploy.md](/Users/mihailefanov/Documents/VSCODE/Python3/projects/family-phr-mvp/docs/deploy.md)
- боевой запуск Docker: [docs/production-docker.md](docs/production-docker.md)
- Matrix-бот: [docs/matrix.md](/Users/mihailefanov/Documents/VSCODE/Python3/projects/family-phr-mvp/docs/matrix.md)
- backup/restore: [docs/restore.md](/Users/mihailefanov/Documents/VSCODE/Python3/projects/family-phr-mvp/docs/restore.md)

## Быстрый запуск

```bash
docker compose up --build
```

После старта приложение доступно на `http://localhost:8000`.

Контейнер `web` при запуске автоматически делает:

```bash
alembic upgrade head
```

## Основные сценарии

- создать аккаунт и семью;
- добавить взрослого или ребёнка;
- вносить измерения и лекарства;
- подключить Matrix-бота через одноразовый код;
- получать напоминания и тревоги;
- скачать backup ZIP или экспорт пациента.

## Локальная разработка

Миграции:

```bash
alembic upgrade head
```

Тесты:

```bash
pytest -q
```

Frontend assets:

```bash
npm run build:assets
```

## Диагностика

Основные endpoints:

- `GET /health`
- `GET /ready`
- `GET /health/worker`
- `GET /ready/worker`
- `GET /health/workers`
- `GET /ready/workers`

Для очереди уведомлений есть отдельный мониторинг из интерфейса аккаунта:

- `/account/worker-monitor`

## Безопасность и ограничения

- регистрация может быть свободной или только по invite token;
- загрузки и документы отдаются через backend с проверкой доступа;
- проект не является medical device и не заменяет врача;
- Matrix, email и Telegram остаются дополнительными каналами, а не источником истины.

## Workflow

- меняйте проект небольшими логическими шагами;
- перед коммитом прогоняйте тесты изменённого контура;
- не смешивайте крупный frontend-рефакторинг и backend-изменения в одном коммите.
