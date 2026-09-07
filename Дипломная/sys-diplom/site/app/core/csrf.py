from hmac import compare_digest
from secrets import token_urlsafe
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status


CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {
    "/health",
    "/ready",
    "/health/worker",
    "/ready/worker",
    "/health/workers",
    "/ready/workers",
    "/matrix/link/confirm",
}


def generate_csrf_token() -> str:
    return token_urlsafe(32)


def get_or_create_request_csrf_token(request: Request) -> str:
    token = getattr(request.state, "csrf_token", None) or request.cookies.get(CSRF_COOKIE_NAME)
    if not token:
        token = generate_csrf_token()
    request.state.csrf_token = token
    return token


def _origin_matches_request(request: Request, candidate: str | None) -> bool:
    if not candidate:
        return False
    parsed = urlparse(candidate)
    target = urlparse(str(request.base_url))
    return (
        parsed.scheme == target.scheme
        and parsed.hostname == target.hostname
        and (parsed.port or _default_port(parsed.scheme)) == (target.port or _default_port(target.scheme))
    )


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


async def validate_csrf_request(request: Request) -> None:
    if request.method not in UNSAFE_METHODS:
        return
    if request.url.path in CSRF_EXEMPT_PATHS:
        return
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return
    if not request.cookies.get("access_token"):
        return

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME) or ""
    header_token = request.headers.get(CSRF_HEADER_NAME, "")
    if cookie_token and header_token and compare_digest(cookie_token, header_token):
        return

    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if sec_fetch_site in {"same-origin", "same-site", "none"}:
        return

    if _origin_matches_request(request, request.headers.get("origin")):
        return
    if _origin_matches_request(request, request.headers.get("referer")):
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
