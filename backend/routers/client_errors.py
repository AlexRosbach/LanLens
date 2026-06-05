"""Client-side error logging endpoint for browser-visible UI failures."""
import logging
import re
import threading
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/client-errors", tags=["client-errors"])
logger = logging.getLogger("lanlens.client_errors")
CLIENT_ERROR_RATE_LIMIT = 30
CLIENT_ERROR_RATE_WINDOW_SECONDS = 60
CLIENT_ERROR_RATE_MAX_CLIENTS = 512
_client_error_hits: dict[str, list[float]] = {}
_client_error_hits_lock = threading.Lock()

SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(password|passwort|token|secret|apikey|api_key)\b\s*[:=]\s*[^,\s;]+"
)
AUTHORIZATION_VALUE_RE = re.compile(
    r"(?i)\bauthorization\b\s*[:=]\s*(?:(?:bearer|basic)\s+)?[^,\s;]+"
)


class ClientErrorLogRequest(BaseModel):
    kind: str = Field(default="ui", max_length=40)
    message: str = Field(default="", max_length=600)
    path: str = Field(default="", max_length=300)
    source: str | None = Field(default=None, max_length=120)
    status: int | None = Field(default=None, ge=100, le=599)
    endpoint: str | None = Field(default=None, max_length=300)


def _clean(value: str | None, limit: int) -> str:
    if not value:
        return ""
    text = "".join(ch if ch.isprintable() else " " for ch in str(value))
    text = SENSITIVE_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = AUTHORIZATION_VALUE_RE.sub("authorization=[redacted]", text)
    return text[:limit]


def _rate_limited(client_ip: str, now: float | None = None) -> bool:
    current = now if now is not None else time.monotonic()
    window_start = current - CLIENT_ERROR_RATE_WINDOW_SECONDS
    with _client_error_hits_lock:
        hits = [hit for hit in _client_error_hits.get(client_ip, []) if hit >= window_start]
        if len(hits) >= CLIENT_ERROR_RATE_LIMIT:
            _client_error_hits[client_ip] = hits
            _prune_client_error_hits(window_start)
            return True
        hits.append(current)
        _client_error_hits[client_ip] = hits
        _prune_client_error_hits(window_start)
        return False


def _prune_client_error_hits(window_start: float) -> None:
    if len(_client_error_hits) <= CLIENT_ERROR_RATE_MAX_CLIENTS:
        return
    expired = [
        client_ip
        for client_ip, hits in _client_error_hits.items()
        if not any(hit >= window_start for hit in hits)
    ]
    for client_ip in expired:
        _client_error_hits.pop(client_ip, None)
    while len(_client_error_hits) > CLIENT_ERROR_RATE_MAX_CLIENTS:
        oldest_client = min(
            _client_error_hits,
            key=lambda key: max(_client_error_hits[key]) if _client_error_hits[key] else 0,
        )
        _client_error_hits.pop(oldest_client, None)


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return _clean(real_ip, 80)
    forwarded_for = request.headers.get("x-forwarded-for", "")
    forwarded_ip = forwarded_for.rsplit(",", 1)[-1].strip()
    if forwarded_ip:
        return _clean(forwarded_ip, 80)
    return request.client.host if request.client else "unknown"


@router.post("")
def log_client_error(payload: ClientErrorLogRequest, request: Request) -> dict[str, bool]:
    """Write browser-visible errors to the backend log stream.

    The endpoint is intentionally lightweight so client logging still works for
    UI failures that happen before a normal authenticated API call succeeds.
    """
    client_ip = _client_ip(request)
    if _rate_limited(client_ip):
        return {"success": True, "throttled": True}

    user_agent = _clean(request.headers.get("user-agent"), 180)
    logger.warning(
        "Client UI error: kind=%s path=%s status=%s endpoint=%s source=%s message=%s client_ip=%s user_agent=%s",
        _clean(payload.kind, 40),
        _clean(payload.path, 300),
        payload.status,
        _clean(payload.endpoint, 300),
        _clean(payload.source, 120),
        _clean(payload.message, 600),
        client_ip,
        user_agent,
    )
    return {"success": True}
