from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import User


def build_system_backup_payload(db: Session) -> dict:
    from app.services.records import collect_family_record

    users = db.scalars(select(User).order_by(User.login)).all()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "users": [collect_family_record(db, user) for user in users],
    }


def write_scheduled_backup(db: Session) -> Path:
    payload = build_system_backup_payload(db)
    settings.backup_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = settings.backup_path / f"system-backup-{timestamp}.zip"

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("system-backup.json", json.dumps(payload, ensure_ascii=False, indent=2))

    cleanup_old_backups()
    return archive_path


def cleanup_old_backups() -> None:
    if settings.backup_retention_days <= 0:
        return
    cutoff = datetime.now(UTC) - timedelta(days=settings.backup_retention_days)
    for file_path in settings.backup_path.glob("system-backup-*.zip"):
        modified_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
        if modified_at < cutoff:
            file_path.unlink(missing_ok=True)


async def scheduled_backup_loop(session_factory: sessionmaker) -> None:
    interval_seconds = max(settings.auto_backup_interval_hours, 1) * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        db = session_factory()
        try:
            write_scheduled_backup(db)
        finally:
            db.close()
