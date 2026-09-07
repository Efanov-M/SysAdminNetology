import asyncio

from app.config import settings
from app.db import SessionLocal
from app.services.health import record_worker_restart, update_worker_heartbeat
from app.services.notifications import process_notification_queue


async def run_worker() -> None:
    interval_seconds = max(settings.reminder_scheduler_poll_seconds, 30)
    record_worker_restart()
    while True:
        db = SessionLocal()
        try:
            update_worker_heartbeat()
            process_notification_queue(db)
        finally:
            db.close()
        await asyncio.sleep(interval_seconds)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
