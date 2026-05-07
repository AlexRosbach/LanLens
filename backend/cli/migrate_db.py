"""
Database migration — applies incremental schema changes to existing databases.
Called from entrypoint.sh after init_db.py on every container start.
All migrations are idempotent (safe to run multiple times).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("SECRET_KEY", "init-placeholder-32chars-do-not-use")

from sqlalchemy import text, inspect as sa_inspect
from backend.database import engine, IS_SQLITE


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if column exists — works for SQLite and MariaDB/MySQL."""
    try:
        inspector = sa_inspect(engine)
        cols = [c["name"] for c in inspector.get_columns(table)]
        return column in cols
    except Exception:
        # Fallback to SQLite PRAGMA
        try:
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            return any(row[1] == column for row in result)
        except Exception:
            return False


def _table_exists(conn, table: str) -> bool:
    """Check if table exists — works for SQLite and MariaDB/MySQL."""
    try:
        inspector = sa_inspect(engine)
        return inspector.has_table(table)
    except Exception:
        # Fallback to SQLite sqlite_master
        try:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table"), {"table": table})
            return result.first() is not None
        except Exception:
            return False


def _index_exists(conn, index: str) -> bool:
    """Check if index exists — SQLite only (skipped for other DBs)."""
    if not IS_SQLITE:
        return True  # Skip index creation for non-SQLite (handled by SQLAlchemy)
    try:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name=:index"), {"index": index})
        return result.first() is not None
    except Exception:
        return False


def _has_unique_device_views_constraint(conn) -> bool:
    """Returns True if the unique index on device_views(user_id, device_id) exists.
    Non-SQLite: always returns True — SQLAlchemy create_all() handles this via metadata."""
    if not IS_SQLITE:
        return True
    indexes = conn.execute(text("PRAGMA index_list(device_views)"))
    for row in indexes:
        if not row[2]:
            continue
        idx_name = row[1]
        columns = conn.execute(text(f"PRAGMA index_info({idx_name})")).fetchall()
        if [col[2] for col in columns] == ["user_id", "device_id"]:
            return True
    return False


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
        # CREATE TABLE uses SQLite-specific AUTOINCREMENT syntax.
        # On MariaDB/PostgreSQL the table is already created by Base.metadata.create_all()
        # in init_db.py using dialect-aware DDL — only run this block on SQLite.
        created_device_views = False
        if IS_SQLITE and not _table_exists(conn, "device_views"):
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
        elif not IS_SQLITE:
            print("Migration: device_views — skipped (non-SQLite, handled by create_all)")
        else:
            print("Migration: device_views already exists — skipped")

        if not _has_unique_device_views_constraint(conn):
            conn.execute(text(
                "CREATE UNIQUE INDEX ix_device_views_user_device ON device_views(user_id, device_id)"
            ))
            print("Migration: created ix_device_views_user_device")
            conn.commit()
        elif created_device_views:
            conn.commit()
        else:
            print("Migration: device_views uniqueness already exists — skipped")

        # ── v1.4.0 ── Deep Scan feature tables ───────────────────────────────
        # All CREATE TABLE blocks below are SQLite-only for the same reason.
        if IS_SQLITE and not _table_exists(conn, "credentials"):
            conn.execute(text(
                "CREATE TABLE credentials ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name VARCHAR(128) NOT NULL, "
                "credential_type VARCHAR(32) NOT NULL, "
                "username VARCHAR(128) NOT NULL, "
                "encrypted_secret TEXT NOT NULL, "
                "description TEXT, "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            print("Migration: created credentials")
        elif not IS_SQLITE:
            print("Migration: credentials — skipped (non-SQLite)")
        else:
            print("Migration: credentials already exists — skipped")

        if IS_SQLITE and not _table_exists(conn, "device_deep_scan_config"):
            conn.execute(text(
                "CREATE TABLE device_deep_scan_config ("
                "device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE, "
                "enabled BOOLEAN NOT NULL DEFAULT 0, "
                "credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL, "
                "scan_profile VARCHAR(64) NOT NULL DEFAULT 'os_services', "
                "auto_scan_enabled BOOLEAN NOT NULL DEFAULT 0, "
                "interval_minutes INTEGER NOT NULL DEFAULT 60, "
                "last_scan_at DATETIME"
                ")"
            ))
            print("Migration: created device_deep_scan_config")
        elif not IS_SQLITE:
            print("Migration: device_deep_scan_config — skipped (non-SQLite)")
        else:
            print("Migration: device_deep_scan_config already exists — skipped")

        if IS_SQLITE and not _table_exists(conn, "deep_scan_runs"):
            conn.execute(text(
                "CREATE TABLE deep_scan_runs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
                "credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL, "
                "profile VARCHAR(64) NOT NULL, "
                "status VARCHAR(16) NOT NULL DEFAULT 'running', "
                "started_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "finished_at DATETIME, "
                "summary_json TEXT, "
                "error_message TEXT, "
                "triggered_by VARCHAR(16) NOT NULL DEFAULT 'manual'"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX ix_deep_scan_runs_device_id ON deep_scan_runs(device_id)"
            ))
            print("Migration: created deep_scan_runs")
        elif not IS_SQLITE:
            print("Migration: deep_scan_runs — skipped (non-SQLite)")
        else:
            print("Migration: deep_scan_runs already exists — skipped")

        if IS_SQLITE and not _table_exists(conn, "deep_scan_findings"):
            conn.execute(text(
                "CREATE TABLE deep_scan_findings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
                "run_id INTEGER NOT NULL REFERENCES deep_scan_runs(id) ON DELETE CASCADE, "
                "finding_type VARCHAR(32) NOT NULL, "
                "key VARCHAR(256) NOT NULL, "
                "value_json TEXT, "
                "source VARCHAR(64), "
                "observed_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX ix_deep_scan_findings_device_run "
                "ON deep_scan_findings(device_id, run_id)"
            ))
            print("Migration: created deep_scan_findings")
        elif not IS_SQLITE:
            print("Migration: deep_scan_findings — skipped (non-SQLite)")
        else:
            print("Migration: deep_scan_findings already exists — skipped")

        if IS_SQLITE and not _table_exists(conn, "device_host_relationships"):
            conn.execute(text(
                "CREATE TABLE device_host_relationships ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "child_device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
                "host_device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
                "relationship_type VARCHAR(32) NOT NULL DEFAULT 'vm_on_host', "
                "match_source VARCHAR(16), "
                "vm_identifier VARCHAR(256), "
                "observed_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "last_confirmed_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            conn.execute(text(
                "CREATE UNIQUE INDEX ix_host_rel_child_host "
                "ON device_host_relationships(child_device_id, host_device_id)"
            ))
            print("Migration: created device_host_relationships")
        elif not IS_SQLITE:
            print("Migration: device_host_relationships — skipped (non-SQLite)")
        else:
            print("Migration: device_host_relationships already exists — skipped")

        # ── v1.4.1 ── Auto-scan rules ─────────────────────────────────────────
        if IS_SQLITE and not _table_exists(conn, "auto_scan_rules"):
            conn.execute(text(
                "CREATE TABLE auto_scan_rules ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name VARCHAR(128) NOT NULL, "
                "device_class VARCHAR(64), "
                "credential_id INTEGER NOT NULL REFERENCES credentials(id) ON DELETE CASCADE, "
                "scan_profile VARCHAR(64) NOT NULL DEFAULT 'os_services', "
                "interval_minutes INTEGER NOT NULL DEFAULT 720, "
                "enabled INTEGER NOT NULL DEFAULT 1, "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            print("Migration: created auto_scan_rules")
        elif not IS_SQLITE:
            print("Migration: auto_scan_rules — skipped (non-SQLite)")
        else:
            print("Migration: auto_scan_rules already exists — skipped")

        # ── v1.4.1 ── SSH key auth support for credentials ───────────────────
        if not _column_exists(conn, "credentials", "auth_method"):
            conn.execute(text(
                "ALTER TABLE credentials ADD COLUMN auth_method VARCHAR(16) NOT NULL DEFAULT 'password'"
            ))
            conn.commit()
            print("Migration: added credentials.auth_method")
        else:
            print("Migration: credentials.auth_method already exists — skipped")

        # ── v1.4.1 ── CMDB ID per device ─────────────────────────────────────
        if not _column_exists(conn, "devices", "cmdb_id"):
            conn.execute(text("ALTER TABLE devices ADD COLUMN cmdb_id VARCHAR(64)"))
            conn.commit()
            print("Migration: added devices.cmdb_id")
            # Add unique index (SQLite only — other DBs handle via SQLAlchemy)
            try:
                conn.execute(text("CREATE UNIQUE INDEX ix_devices_cmdb_id ON devices(cmdb_id)"))
                conn.commit()
            except Exception:
                pass  # Index may already exist or not supported
        else:
            print("Migration: devices.cmdb_id already exists — skipped")


        # ── v1.4.4 ── IP history per device ──────────────────────────────────
        if IS_SQLITE and not _table_exists(conn, "device_ip_history"):
            conn.execute(text(
                "CREATE TABLE device_ip_history ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE, "
                "ip_address VARCHAR(45) NOT NULL, "
                "first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "seen_count INTEGER NOT NULL DEFAULT 1"
                ")"
            ))
            conn.execute(text(
                "CREATE UNIQUE INDEX ix_device_ip_history_device_ip "
                "ON device_ip_history(device_id, ip_address)"
            ))
            conn.commit()
            print("Migration: created device_ip_history")
        elif not IS_SQLITE:
            print("Migration: device_ip_history table — handled by create_all")
        else:
            print("Migration: device_ip_history already exists — skipped")

        if IS_SQLITE:
            conn.execute(text(
                "INSERT OR IGNORE INTO device_ip_history "
                "(device_id, ip_address, first_seen, last_seen, seen_count) "
                "SELECT id, ip_address, COALESCE(first_seen, CURRENT_TIMESTAMP), "
                "COALESCE(last_seen, CURRENT_TIMESTAMP), 1 "
                "FROM devices WHERE ip_address IS NOT NULL"
            ))
        elif _table_exists(conn, "device_ip_history"):
            conn.execute(text(
                "INSERT INTO device_ip_history "
                "(device_id, ip_address, first_seen, last_seen, seen_count) "
                "SELECT d.id, d.ip_address, COALESCE(d.first_seen, CURRENT_TIMESTAMP), "
                "COALESCE(d.last_seen, CURRENT_TIMESTAMP), 1 "
                "FROM devices d "
                "WHERE d.ip_address IS NOT NULL "
                "AND NOT EXISTS ("
                "SELECT 1 FROM device_ip_history h "
                "WHERE h.device_id = d.id AND h.ip_address = d.ip_address"
                ")"
            ))
        conn.commit()
        print("Migration: backfilled device_ip_history from existing device IPs")


        # ── v1.4.4 ── Service groups and custom service icons ───────────────
        if IS_SQLITE and not _table_exists(conn, "service_groups"):
            conn.execute(text(
                "CREATE TABLE service_groups ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name VARCHAR(128) NOT NULL UNIQUE, "
                "color VARCHAR(16) DEFAULT '#6366f1', "
                "sort_order INTEGER DEFAULT 0, "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            conn.commit()
            print("Migration: created service_groups")
        elif not IS_SQLITE:
            print("Migration: service_groups — skipped (non-SQLite, handled by create_all)")
        else:
            print("Migration: service_groups already exists — skipped")

        if not _column_exists(conn, "services", "icon_url"):
            conn.execute(text("ALTER TABLE services ADD COLUMN icon_url VARCHAR(2048)"))
            conn.commit()
            print("Migration: added services.icon_url")
        else:
            print("Migration: services.icon_url already exists — skipped")

        if not _column_exists(conn, "services", "service_group_id"):
            conn.execute(text("ALTER TABLE services ADD COLUMN service_group_id INTEGER REFERENCES service_groups(id) ON DELETE SET NULL"))
            conn.commit()
            print("Migration: added services.service_group_id")
        else:
            print("Migration: services.service_group_id already exists — skipped")

        # ── v1.5.0 ── i-doit one-way sync state/logs ───────────────────────
        # SQLite installations need explicit table/index creation here. Other
        # database engines rely on SQLAlchemy create_all from the app startup,
        # which keeps this migration runner safe for existing non-SQLite setups.
        if IS_SQLITE and not _table_exists(conn, "idoit_device_sync"):
            conn.execute(text(
                "CREATE TABLE idoit_device_sync ("
                "device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE, "
                "status VARCHAR(32) NOT NULL DEFAULT 'never_synced', "
                "idoit_object_id VARCHAR(64), "
                "last_sync_at DATETIME, "
                "last_success_at DATETIME, "
                "last_validation_at DATETIME, "
                "last_error TEXT, "
                "last_mode VARCHAR(16), "
                "payload_hash VARCHAR(64), "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            conn.commit()
            print("Migration: created idoit_device_sync")
        elif not IS_SQLITE:
            print("Migration: idoit_device_sync — skipped (non-SQLite, handled by create_all)")
        else:
            print("Migration: idoit_device_sync already exists — skipped")

        if _table_exists(conn, "idoit_device_sync") and not _column_exists(conn, "idoit_device_sync", "last_validation_at"):
            conn.execute(text("ALTER TABLE idoit_device_sync ADD COLUMN last_validation_at DATETIME"))
            conn.execute(text("UPDATE idoit_device_sync SET last_validation_at = last_sync_at WHERE last_validation_at IS NULL AND last_success_at IS NULL AND last_sync_at IS NOT NULL"))
            conn.commit()
            print("Migration: added idoit_device_sync.last_validation_at")

        if IS_SQLITE and not _table_exists(conn, "idoit_sync_logs"):
            conn.execute(text(
                "CREATE TABLE idoit_sync_logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL, "
                "mode VARCHAR(16) NOT NULL, "
                "result VARCHAR(16) NOT NULL, "
                "idoit_object_id VARCHAR(64), "
                "message TEXT, "
                "details_json TEXT, "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            conn.execute(text("CREATE INDEX ix_idoit_sync_logs_device_id ON idoit_sync_logs(device_id)"))
            conn.commit()
            print("Migration: created idoit_sync_logs")
        elif not IS_SQLITE:
            print("Migration: idoit_sync_logs — skipped (non-SQLite, handled by create_all)")
        else:
            print("Migration: idoit_sync_logs already exists — skipped")

        # Track webhook delivery separately from Telegram so disabled/unconfigured
        # channels do not make old notification rows look permanently pending.
        if not _column_exists(conn, "notifications", "webhook_sent"):
            conn.execute(text("ALTER TABLE notifications ADD COLUMN webhook_sent BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
            print("Migration: added notifications.webhook_sent")
        else:
            print("Migration: notifications.webhook_sent already exists — skipped")
        conn.execute(text("UPDATE notifications SET webhook_sent = 0 WHERE webhook_sent IS NULL"))
        conn.commit()

        conn.commit()


if __name__ == "__main__":
    migrate()
