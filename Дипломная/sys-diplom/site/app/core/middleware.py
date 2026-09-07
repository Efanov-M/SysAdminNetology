from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.csrf import CSRF_COOKIE_NAME, get_or_create_request_csrf_token, validate_csrf_request


def _build_csp_header() -> str:
    script_sources = [
        "'self'",
        "'unsafe-eval'",
        "'unsafe-inline'",
    ]
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {' '.join(script_sources)}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
    )


SECURITY_HEADERS = {
    "Content-Security-Policy": _build_csp_header(),
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def install_security_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        get_or_create_request_csrf_token(request)
        try:
            await validate_csrf_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        response = await call_next(request)

        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers.setdefault("Cache-Control", "no-store, max-age=0")

        if request.cookies.get(CSRF_COOKIE_NAME) != request.state.csrf_token:
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=request.state.csrf_token,
                httponly=False,
                samesite="lax",
                secure=settings.session_cookie_secure,
                max_age=60 * 60 * 24,
            )
        return response
