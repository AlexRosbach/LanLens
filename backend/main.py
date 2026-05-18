from contextlib import asynccontextmanager
from datetime import datetime
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings  # validates SECRET_KEY on import — must be first
from .database import SessionLocal
from .models import TokenBlacklist
from .routers import admin, auth, auto_scan_rules, cmdb, connect, credentials, deep_scan, devices, dhcp_monitor, idoit, inventory, notifications, scan, scan_nodes, segments, services
from .routers import settings as settings_router
from .services import deep_scan_scheduler, idoit_scheduler, scheduler
from .services.settings_helpers import get_scan_interval_minutes
from .version import APP_VERSION

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
        interval = get_scan_interval_minutes(db)
        from .services.idoit import get_config as get_idoit_config
        idoit_interval = get_idoit_config(db).sync_interval_minutes
        _cleanup_expired_tokens(db)
    finally:
        db.close()

    scheduler.start_scheduler(interval)
    deep_scan_scheduler.start_deep_scan_scheduler()
    idoit_scheduler.start_idoit_scheduler(idoit_interval)
    logger.info(f"LanLens started — scan interval: {interval} min")
    yield
    scheduler.stop_scheduler()
    deep_scan_scheduler.stop_deep_scan_scheduler()
    idoit_scheduler.stop_idoit_scheduler()
    logger.info("LanLens stopped")


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

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(scan.router)
app.include_router(scan_nodes.router)
app.include_router(settings_router.router)
app.include_router(notifications.router)
app.include_router(services.router)
app.include_router(services.global_router)
app.include_router(connect.router)
app.include_router(segments.router)
app.include_router(credentials.router)
app.include_router(deep_scan.router)
app.include_router(auto_scan_rules.router)
app.include_router(idoit.router)
app.include_router(cmdb.router)
app.include_router(dhcp_monitor.router)
app.include_router(inventory.router)
app.include_router(inventory.ignore_router)
app.include_router(inventory.backup_router)


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
