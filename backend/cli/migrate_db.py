"""
Database migration — applies incremental schema changes to existing databases.
Called from entrypoint.sh after init_db.py on every container start.
All migrations are idempotent (safe to run multiple times).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("SECRET_KEY", "init-placeholder-32chars-do-not-use")

from sqlalchemy import text
from backend.database import engine


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table"), {"table": table})
    return result.first() is not None


def _index_exists(conn, index: str) -> bool:
    result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name=:index"), {"index": index})
    return result.first() is not None


def migrate():
    with engine.connect() as conn:
        # ── v1.1.0 ── Add segment_id to devices ──────────────────────────────
        if not _column_exists(conn, "devices", "segment_id"):
            conn.execute(
                text(
                    "ALTER TABLE devices ADD COLUMN segment_id INTEGER "
                    "REFERENCES segments(id) ON DELETE SET NULL"
                )
            )
            conn.commit()
            print("Migration: added devices.segment_id")
        else:
            print("Migration: devices.segment_id already exists — skipped")

        # ── v1.2.4 ── Add server-side device view tracking ───────────────────
        created_device_views = False
        if not _table_exists(conn, "device_views"):
            conn.execute(text(
                "CREATE TABLE device_views ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
                "viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            created_device_views = True
            print("Migration: created device_views")
        else:
            print("Migration: device_views already exists — skipped")

        if not _index_exists(conn, "ix_device_views_user_device"):
            conn.execute(text(
                "CREATE UNIQUE INDEX ix_device_views_user_device ON device_views(user_id, device_id)"
            ))
            print("Migration: created ix_device_views_user_device")
            conn.commit()
        elif created_device_views:
            conn.commit()
            print("Migration: ix_device_views_user_device already exists — skipped")
        else:
            print("Migration: ix_device_views_user_device already exists — skipped")


if __name__ == "__main__":
    migrate()
