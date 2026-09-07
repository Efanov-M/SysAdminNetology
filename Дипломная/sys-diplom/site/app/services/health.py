from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings


def check_database_connection(db: Session) -> bool:
    db.execute(text("SELECT 1"))
    return True


def worker_heartbeat_path() -> Path:
    path = settings.backup_path / "worker-heartbeats"
    path.mkdir(parents=True, exist_ok=True)
    return path / "notification-worker.txt"


def worker_heartbeat_dir() -> Path:
    path = settings.backup_path / "worker-heartbeats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def update_worker_heartbeat() -> str:
    heartbeat = datetime.now(UTC).isoformat()
    worker_heartbeat_path().write_text(heartbeat, encoding="utf-8")
    return heartbeat


def worker_restart_log_path() -> Path:
    return worker_heartbeat_dir() / "worker-restarts.jsonl"


def record_worker_restart(worker_name: str = "notification-worker") -> dict:
    event = {"worker_name": worker_name, "started_at": datetime.now(UTC).isoformat()}
    with worker_restart_log_path().open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def list_worker_restarts(limit: int = 50) -> list[dict]:
    path = worker_restart_log_path()
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events[-limit:][::-1]


def get_worker_health(max_age_seconds: int = 180) -> dict:
    path = worker_heartbeat_path()
    if not path.exists():
        return {"status": "missing", "age_seconds": None}
    heartbeat = path.read_text(encoding="utf-8").strip()
    try:
        last_seen = datetime.fromisoformat(heartbeat)
    except ValueError:
        return {"status": "invalid", "age_seconds": None}
    age = datetime.now(UTC) - last_seen
    status = "ok" if age <= timedelta(seconds=max_age_seconds) else "stale"
    return {"status": status, "age_seconds": int(age.total_seconds()), "last_seen": heartbeat}


def get_worker_pool_health(max_age_seconds: int = 180) -> dict:
    workers = []
    for path in sorted(worker_heartbeat_dir().glob("*.txt")):
        worker = get_worker_health_for_path(path, max_age_seconds=max_age_seconds)
        worker["worker_name"] = path.stem
        workers.append(worker)
    overall_status = "ok"
    if not workers:
        overall_status = "missing"
    elif any(worker["status"] != "ok" for worker in workers):
        overall_status = "degraded"
    return {"status": overall_status, "workers": workers, "count": len(workers), "restarts": list_worker_restarts(limit=20)}


def get_worker_health_for_path(path: Path, max_age_seconds: int = 180) -> dict:
    if not path.exists():
        return {"status": "missing", "age_seconds": None}
    heartbeat = path.read_text(encoding="utf-8").strip()
    try:
        last_seen = datetime.fromisoformat(heartbeat)
    except ValueError:
        return {"status": "invalid", "age_seconds": None}
    age = datetime.now(UTC) - last_seen
    status = "ok" if age <= timedelta(seconds=max_age_seconds) else "stale"
    return {"status": status, "age_seconds": int(age.total_seconds()), "last_seen": heartbeat}
