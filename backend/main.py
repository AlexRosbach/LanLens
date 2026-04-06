from contextlib import asynccontextmanager
from datetime import datetime
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings  # validates SECRET_KEY on import — must be first
from .database import SessionLocal
from .models import Setting, TokenBlacklist
from .routers import auth, connect, devices, notifications, scan, segments, services
from .routers import settings as settings_router
from .services import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage active WebSocket connections for live scan updates."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws) if hasattr(self.active, "discard") else (
            self.active.remove(ws) if ws in self.active else None
        )

    async def broadcast(self, data: dict) -> None:
        for ws in list(self.active):
            try:
                await ws.send_json(data)
            except Exception:
                if ws in self.active:
                    self.active.remove(ws)


manager = ConnectionManager()


def _cleanup_expired_tokens(db_session) -> None:
    """Remove expired tokens from the blacklist (housekeeping)."""
    try:
        db_session.query(TokenBlacklist).filter(
            TokenBlacklist.expires_at < datetime.utcnow()
        ).delete()
        db_session.commit()
    except Exception as e:
        logger.warning(f"Token blacklist cleanup failed: {e}")
        db_session.rollback()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == "scan_interval_minutes").first()
        try:
            interval = int(row.value) if row and row.value else 5
        except (ValueError, TypeError):
            interval = 5
        _cleanup_expired_tokens(db)
    finally:
        db.close()

    scheduler.start_scheduler(interval)
    logger.info(f"LanLens started — scan interval: {interval} min")
    yield
    scheduler.stop_scheduler()
    logger.info("LanLens stopped")


APP_VERSION = "1.2.5"

app = FastAPI(
    title="LanLens",
    version=APP_VERSION,
    lifespan=lifespan,
    # Disable auto-generated docs in production (security hardening)
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(scan.router)
app.include_router(settings_router.router)
app.include_router(notifications.router)
app.include_router(services.router)
app.include_router(connect.router)
app.include_router(segments.router)


@app.websocket("/ws/scan-updates")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in manager.active:
            manager.active.remove(websocket)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "LanLens", "version": APP_VERSION}
