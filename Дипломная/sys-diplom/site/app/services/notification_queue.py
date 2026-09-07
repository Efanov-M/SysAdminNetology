from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings


def queue_dir() -> Path:
    path = settings.backup_path / "notification_queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def queue_item_path(item_id: str) -> Path:
    return queue_dir() / f"{item_id}.json"


def queue_processing_marker_path(item_id: str) -> Path:
    return queue_dir() / f"{item_id}.processing"


def incident_history_path() -> Path:
    path = queue_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "incident-history.jsonl"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _append_jsonl_locked(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with path.open("a+", encoding="utf-8") as file:
        try:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        file.write(line)
        file.flush()
        os.fsync(file.fileno())
        try:
            import fcntl

            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass


def save_queue_item(item: dict) -> Path:
    item_id = str(item.get("id") or "").strip()
    if not item_id:
        raise ValueError("queue item id is required")
    path = queue_item_path(item_id)
    _write_text_atomic(path, json.dumps(item, ensure_ascii=False, indent=2))
    return path


def remove_queue_item(item_id: str) -> None:
    path = queue_item_path(item_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def release_queue_processing_marker(item_id: str) -> None:
    marker_path = queue_processing_marker_path(item_id)
    try:
        marker_path.unlink()
    except FileNotFoundError:
        pass


def claim_queue_item(item_id: str, worker_name: str = "notification-worker", stale_after_seconds: int = 900) -> dict | None:
    item_path = queue_item_path(item_id)
    if not item_path.exists():
        return None
    marker_path = queue_processing_marker_path(item_id)
    marker_payload = {
        "item_id": item_id,
        "worker_name": worker_name,
        "claimed_at": datetime.now(UTC).isoformat(),
    }
    try:
        descriptor = os.open(marker_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as marker_file:
            marker_file.write(json.dumps(marker_payload, ensure_ascii=False, indent=2))
    except FileExistsError:
        try:
            existing = json.loads(marker_path.read_text(encoding="utf-8"))
            claimed_at = datetime.fromisoformat(str(existing.get("claimed_at")))
            if claimed_at >= datetime.now(UTC) - timedelta(seconds=stale_after_seconds):
                return None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        release_queue_processing_marker(item_id)
        return claim_queue_item(item_id, worker_name=worker_name, stale_after_seconds=stale_after_seconds)
    try:
        return json.loads(item_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        release_queue_processing_marker(item_id)
        return None


def record_incident(event_type: str, payload: dict) -> dict:
    event = {
        "event_type": event_type,
        "created_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    _append_jsonl_locked(incident_history_path(), event)
    return event


def cleanup_incident_history(retention_days: int | None = None) -> int:
    path = incident_history_path()
    if not path.exists():
        return 0
    keep_days = retention_days if retention_days is not None else settings.backup_retention_days
    if keep_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            created_at = datetime.fromisoformat(event.get("created_at"))
        except (json.JSONDecodeError, TypeError, ValueError):
            kept.append(line)
            continue
        if created_at >= cutoff:
            kept.append(line)
        else:
            removed += 1
    _write_text_atomic(path, "\n".join(kept) + ("\n" if kept else ""))
    return removed


def list_incident_history(limit: int = 500, period_days: int | None = None) -> list[dict]:
    path = incident_history_path()
    if not path.exists():
        return []
    cutoff = None
    if period_days is not None and period_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=period_days)
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff:
            try:
                created_at = datetime.fromisoformat(event.get("created_at"))
                if created_at < cutoff:
                    continue
            except Exception:
                pass
        events.append(event)
    return events[-limit:][::-1]


def list_notification_queue_items(limit: int = 100) -> list[dict]:
    items = []
    for path in sorted(queue_dir().glob("*.json"))[:limit]:
        if path.name == incident_history_path().name:
            continue
        item_id = path.stem
        marker_path = queue_processing_marker_path(item_id)
        if marker_path.exists():
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                claimed_at = datetime.fromisoformat(str(marker.get("claimed_at")))
                if claimed_at >= datetime.now(UTC) - timedelta(minutes=15):
                    continue
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return items


def build_notification_queue_stats(items: list[dict], now: datetime | None = None) -> dict:
    now_utc = now or datetime.now(UTC)
    queued = len(items)
    stale = 0
    max_attempts = 0
    channels: dict[str, int] = {}
    for item in items:
        channel = item.get("channel", "unknown")
        channels[channel] = channels.get(channel, 0) + 1
        attempts = int(item.get("attempts", 0))
        max_attempts = max(max_attempts, attempts)
        next_retry_at = item.get("next_retry_at")
        if next_retry_at:
            try:
                retry_time = datetime.fromisoformat(next_retry_at)
                if retry_time < now_utc - timedelta(minutes=15):
                    stale += 1
            except ValueError:
                stale += 1
    alerts = []
    if stale:
        alerts.append(f"Есть застрявшие повторы: {stale}")
    if max_attempts >= 3:
        alerts.append(f"Есть уведомления с числом попыток {max_attempts}")
    return {
        "queued": queued,
        "stale": stale,
        "max_attempts": max_attempts,
        "channels": channels,
        "alerts": alerts,
    }


def build_notification_incidents(items: list[dict], now: datetime | None = None) -> list[dict]:
    now_utc = now or datetime.now(UTC)
    incidents = []
    for item in items:
        attempts = int(item.get("attempts", 0))
        next_retry_at = item.get("next_retry_at")
        is_stale = False
        if next_retry_at:
            try:
                retry_time = datetime.fromisoformat(next_retry_at)
                is_stale = retry_time < now_utc - timedelta(minutes=15)
            except ValueError:
                is_stale = True
        if not is_stale and attempts < 3:
            continue
        incidents.append(
            {
                "id": item.get("id"),
                "channel": item.get("channel"),
                "recipient_email": item.get("recipient_email"),
                "attempts": attempts,
                "error": item.get("error"),
                "next_retry_at": next_retry_at,
                "incident_type": "stale" if is_stale else "high_attempts",
            }
        )
    return incidents


def build_incident_retention_summary(history: list[dict]) -> dict:
    by_channel: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for item in history:
        channel = item.get("channel") or "unknown"
        by_channel[channel] = by_channel.get(channel, 0) + 1
        event_type = item.get("event_type") or item.get("incident_type") or "unknown"
        by_type[event_type] = by_type.get(event_type, 0) + 1
    return {
        "total": len(history),
        "by_channel": by_channel,
        "by_type": by_type,
        "latest": history[0] if history else None,
    }


def build_channel_degradation_warnings(history: list[dict], period_days: int = 7) -> list[str]:
    warnings: list[str] = []
    by_channel: dict[str, dict[str, int]] = {}
    for item in history:
        channel = item.get("channel") or "unknown"
        channel_stats = by_channel.setdefault(channel, {"failed": 0, "recovered": 0, "stale": 0})
        event_type = item.get("event_type") or item.get("incident_type") or ""
        if "failed" in event_type:
            channel_stats["failed"] += 1
        if "processed" in event_type or "recovered" in event_type:
            channel_stats["recovered"] += 1
        if "stale" in event_type:
            channel_stats["stale"] += 1
    for channel, stats in sorted(by_channel.items()):
        if stats["failed"] >= 3:
            warnings.append(f"Канал {channel} деградирует за {period_days} дн.: сбоев {stats['failed']}")
        if stats["stale"] >= 2:
            warnings.append(f"Канал {channel}: есть повторяющиеся застрявшие задачи ({stats['stale']})")
    return warnings


def build_sla_alerts(queue_stats: dict, worker_health: dict, worker_pool: dict, history: list[dict]) -> list[str]:
    alerts: list[str] = []
    if queue_stats.get("queued", 0) >= 10:
        alerts.append("SLA: очередь выросла до 10+ задач, доставку стоит проверить вручную")
    if queue_stats.get("stale", 0) >= 2:
        alerts.append("SLA: есть 2+ застрявших повтора, канал доставки деградирует")
    if worker_health.get("status") != "ok":
        alerts.append(f"SLA: основной worker в состоянии {worker_health.get('status')}")
    if worker_pool.get("status") != "ok":
        alerts.append(f"SLA: worker pool в состоянии {worker_pool.get('status')}")
    failed_recent = len([item for item in history if "failed" in (item.get("event_type") or "")])
    if failed_recent >= 5:
        alerts.append("SLA: за период накопилось 5+ неуспешных доставок")
    return alerts


def build_admin_runbook(queue_stats: dict, worker_health: dict, worker_pool: dict, history: list[dict]) -> list[str]:
    steps: list[str] = []
    if worker_health.get("status") != "ok":
        steps.append("[Self-hosted] Проверьте, запущен ли notification worker, и обновляется ли heartbeat в worker-heartbeats.")
    if worker_pool.get("status") != "ok":
        steps.append("[Self-hosted] Сверьте число worker-процессов с ожидаемым и проверьте docker/systemd логи.")
    if queue_stats.get("queued", 0) > 0:
        steps.append("[Self-hosted] Если очередь не пуста, проверьте SMTP/Telegram/Matrix конфиг и выполните ручную обработку очереди.")
    by_channel = {}
    for item in history:
        channel = item.get("channel") or "unknown"
        by_channel[channel] = by_channel.get(channel, 0) + 1
    for channel, count in sorted(by_channel.items()):
        if count >= 3:
            steps.append(f"[Канал: {channel}] Накопилось {count} инцидентов, проверьте токены, адреса и доступность внешнего сервиса.")
        if channel == "email":
            steps.append("[SMTP] Проверьте SMTP_HOST/SMTP_PORT, логин, пароль приложения и доступность исходящего порта с хоста.")
        if channel == "telegram":
            steps.append("[Telegram] Проверьте TELEGRAM_BOT_TOKEN, chat id и может ли бот писать в этот чат без ограничений.")
        if channel == "matrix":
            steps.append("[Matrix] Проверьте MATRIX_HOMESERVER, access token, связку комнаты и отвечает ли bot /sync без ошибок.")
    if queue_stats.get("stale", 0) >= 1:
        steps.append("[Инцидент: застрявшие retry] Проверьте время next_retry_at, доступность сети и не накопились ли ошибки одного канала.")
    if queue_stats.get("queued", 0) >= 5:
        steps.append("[Инцидент: рост очереди] Снимите diagnostics bundle и проверьте, не завис ли один из внешних каналов доставки.")
    if any((item.get("channel") or "") == "email" and "auth" in (item.get("error") or "").lower() for item in history):
        steps.append("[SMTP инцидент] Есть признаки ошибки авторизации: проверьте пароль приложения, TLS и доступ со стороны провайдера почты.")
    if any((item.get("channel") or "") == "telegram" and "429" in str(item.get("error") or "") for item in history):
        steps.append("[Telegram инцидент] Похоже на rate limit: временно снизьте частоту тестовых отправок и проверьте очередь повторов.")
    if any((item.get("channel") or "") == "matrix" and "sync" in (item.get("error") or "").lower() for item in history):
        steps.append("[Matrix инцидент] Ошибки /sync обычно означают битый token, проблемы homeserver или неверную комнату привязки.")
    if not steps:
        steps.append("[Self-hosted] Система выглядит стабильно: периодически проверяйте retention и делайте diagnostics bundle перед изменениями.")
    return steps


def build_diagnostics_bundle(
    queue_items: list[dict],
    incident_history: list[dict],
    queue_stats: dict,
    incidents: list[dict],
    worker_health: dict,
    worker_pool: dict,
) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("queue/queued-items.json", json.dumps(queue_items, ensure_ascii=False, indent=2))
        archive.writestr("queue/active-incidents.json", json.dumps(incidents, ensure_ascii=False, indent=2))
        archive.writestr("queue/incident-history.json", json.dumps(incident_history, ensure_ascii=False, indent=2))
        archive.writestr(
            "queue/summary.json",
            json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "queue_stats": queue_stats,
                    "worker_health": worker_health,
                    "worker_pool": worker_pool,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return buffer.getvalue()


def build_operational_alerts(queue_stats: dict, incidents: list[dict], worker_pool_status: str) -> list[str]:
    alerts = list(queue_stats.get("alerts", []))
    if worker_pool_status != "ok":
        alerts.append(f"Worker pool в состоянии {worker_pool_status}")
    by_channel: dict[str, int] = {}
    for item in incidents:
        channel = item.get("channel") or "unknown"
        by_channel[channel] = by_channel.get(channel, 0) + 1
    for channel, count in sorted(by_channel.items()):
        if count >= 2:
            alerts.append(f"Повторяющиеся инциденты по каналу {channel}: {count}")
    return alerts


def enqueue_notification_retry(
    title: str,
    message: str,
    channel: str,
    recipient_email: str | None,
    error: str,
    attempts: int,
    recipient_target: str | None = None,
) -> dict:
    item = {
        "id": uuid4().hex,
        "title": title,
        "message": message,
        "channel": channel,
        "recipient_email": recipient_email,
        "recipient_target": recipient_target,
        "error": error,
        "attempts": attempts,
        "created_at": datetime.now(UTC).isoformat(),
        "next_retry_at": datetime.now(UTC).isoformat(),
        "status": "queued",
    }
    save_queue_item(item)
    record_incident(
        "retry_enqueued_failed_delivery",
        {
            "queue_id": item["id"],
            "channel": channel,
            "recipient_email": recipient_email,
            "recipient_target": recipient_target,
            "attempts": attempts,
            "error": error,
        },
    )
    return item
