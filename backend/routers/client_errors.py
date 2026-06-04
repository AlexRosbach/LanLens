"""Client-side error logging endpoint for browser-visible UI failures."""
import logging
import re
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/client-errors", tags=["client-errors"])
logger = logging.getLogger("lanlens.client_errors")
CLIENT_ERROR_RATE_LIMIT = 30
CLIENT_ERROR_RATE_WINDOW_SECONDS = 60
_client_error_hits: dict[str, list[float]] = {}

SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(password|passwort|token|secret|apikey|api_key|authorization)\b\s*[:=]\s*[^,\s;]+"
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
    return text[:limit]


def _rate_limited(client_ip: str, now: float | None = None) -> bool:
    current = now if now is not None else time.monotonic()
    window_start = current - CLIENT_ERROR_RATE_WINDOW_SECONDS
    hits = [hit for hit in _client_error_hits.get(client_ip, []) if hit >= window_start]
    if len(hits) >= CLIENT_ERROR_RATE_LIMIT:
        _client_error_hits[client_ip] = hits
        return True
    hits.append(current)
    _client_error_hits[client_ip] = hits
    return False


@router.post("")
def log_client_error(payload: ClientErrorLogRequest, request: Request) -> dict[str, bool]:
    """Write browser-visible errors to the backend log stream.

    The endpoint is intentionally lightweight so client logging still works for
    UI failures that happen before a normal authenticated API call succeeds.
    """
    client_ip = request.client.host if request.client else "unknown"
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
