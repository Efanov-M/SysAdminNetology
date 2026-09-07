import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler as fastapi_http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.db import SessionLocal, get_db
from app.middleware import install_security_middleware
from app.routers import account, admin, api, auth, documents, family, inbox, pages, patients, planner
from app.services.health import check_database_connection, get_worker_health, get_worker_pool_health
from app.services.notifications import scheduled_reminder_loop
from app.services.system_backups import scheduled_backup_loop


settings.upload_path.mkdir(parents=True, exist_ok=True)
settings.backup_path.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    backup_task = None
    reminder_task = None
    if settings.auto_backup_enabled:
        backup_task = asyncio.create_task(scheduled_backup_loop(SessionLocal))
    if settings.reminder_scheduler_enabled:
        reminder_task = asyncio.create_task(scheduled_reminder_loop(SessionLocal))
    try:
        yield
    finally:
        if backup_task:
            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await backup_task
        if reminder_task:
            reminder_task.cancel()
            with suppress(asyncio.CancelledError):
                await reminder_task


app = FastAPI(title=settings.app_name, lifespan=lifespan)

if settings.force_https_redirect:
    app.add_middleware(HTTPSRedirectMiddleware)
install_security_middleware(app)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/sw.js")
def service_worker():
    return FileResponse(BASE_DIR / "static" / "sw.js", media_type="application/javascript")


@app.get("/health")
def healthcheck():
    return {"status": "ok", "service": "family-phr-mvp"}


@app.get("/ready")
def readiness(db: Session = Depends(get_db)):
    try:
        check_database_connection(db)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="База данных недоступна",
        ) from exc
    return {"status": "ready", "database": "ok"}


@app.get("/health/worker")
def worker_healthcheck():
    worker = get_worker_health()
    return {"status": "ok", "worker": worker}


@app.get("/ready/worker")
def worker_readiness():
    worker = get_worker_health()
    if worker["status"] != "ok":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker недоступен")
    return {"status": "ready", "worker": worker}


@app.get("/health/workers")
def worker_pool_healthcheck():
    pool = get_worker_pool_health()
    return {"status": "ok", "pool": pool}


@app.get("/ready/workers")
def worker_pool_readiness():
    pool = get_worker_pool_health()
    if pool["status"] != "ok":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker pool недоступен")
    return {"status": "ready", "pool": pool}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    wants_html = "text/html" in request.headers.get("accept", "")
    is_browser_page = not request.url.path.startswith("/api")
    if wants_html and is_browser_page and exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)
    return await fastapi_http_exception_handler(request, exc)

app.include_router(auth.router)
app.include_router(api.router)
app.include_router(account.router)
app.include_router(inbox.router)
app.include_router(documents.router)
app.include_router(family.router)
app.include_router(patients.router)
app.include_router(planner.router)
app.include_router(admin.router)
app.include_router(pages.router)
