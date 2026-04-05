"""
Database migration — applies incremental schema changes to existing databases.
Called from entrypoint.sh after init_db.py on every container start.
All migrations are idempotent (safe to run multiple times).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("SECRET_KEY", "init-placeholder-32chars-do-not-use")

from backend.database import engine


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in result)


def migrate():
    with engine.connect() as conn:
        # ── v1.1.0 ── Add segment_id to devices ──────────────────────────────
        if not _column_exists(conn, "devices", "segment_id"):
            conn.execute(
                "ALTER TABLE devices ADD COLUMN segment_id INTEGER "
                "REFERENCES segments(id) ON DELETE SET NULL"
            )
            conn.commit()
            print("Migration: added devices.segment_id")
        else:
            print("Migration: devices.segment_id already exists — skipped")


if __name__ == "__main__":
    migrate()
