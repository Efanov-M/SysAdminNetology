# Deploy

Короткая памятка. Подробная пошаговая инструкция для боевого запуска через Docker: `docs/production-docker.md`.

## Базовый production путь

1. Подготовьте `.env.production` из `.env.production.example`.
2. Настройте домен в `Caddyfile` или через `CADDY_SITE_ADDRESS`.
3. Поднимите контейнеры:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

## Что должно быть настроено

- `SECRET_KEY`
- `SESSION_COOKIE_SECURE=true`
- `FORCE_HTTPS_REDIRECT=false` при запуске за Caddy
- `DATABASE_URL`
- `BACKUP_DIR`

Опционально:

- SMTP
- Telegram
- Matrix

## Проверка после запуска

- `GET /health`
- `GET /ready`
- `GET /health/worker`
- `GET /ready/workers`

## Обновление

```bash
git pull
docker compose -f docker-compose.prod.yml up --build -d
```

Контейнер `web` сам применяет `alembic upgrade head` при старте.

## Что проверять при проблемах

- логи `web`
- логи `notification-worker`
- `/account/worker-monitor`
- наличие свободного места в volume `backups_data` / директории `BACKUP_DIR`
- доступность SMTP / Matrix / Telegram с сервера
