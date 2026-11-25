"""Regression coverage for upgrading a persisted pre-1.7.0 SQLite database."""
import unittest

from sqlalchemy import create_engine, inspect, text

from backend.database import Base
import backend.models  # noqa: F401 - registers current metadata
from backend.cli import migrate_db


class LegacyDatabaseUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=self.engine)
        with self.engine.begin() as connection:
            # Recreate the 1.6.1 agent schema exactly as it existed before the
            # platform field. init_db() intentionally creates new tables first;
            # migrate_db() must then upgrade existing tables without data loss.
            connection.execute(text("DROP TABLE windows_agents"))
            connection.execute(text(
                "CREATE TABLE windows_agents ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "agent_id VARCHAR(64) NOT NULL UNIQUE, "
                "device_id INTEGER NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE, "
                "enrollment_token_id INTEGER REFERENCES agent_enrollment_tokens(id) ON DELETE SET NULL, "
                "secret_hash VARCHAR(64) NOT NULL, "
                "last_sequence INTEGER NOT NULL DEFAULT 0, "
                "last_seen_at DATETIME, revoked_at DATETIME, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            ))

    def tearDown(self):
        self.engine.dispose()

    def test_legacy_database_receives_agent_platform_and_vsphere_schema(self):
        original_engine, original_sqlite = migrate_db.engine, migrate_db.IS_SQLITE
        migrate_db.engine, migrate_db.IS_SQLITE = self.engine, True
        try:
            migrate_db.migrate()
        finally:
            migrate_db.engine, migrate_db.IS_SQLITE = original_engine, original_sqlite

        inspector = inspect(self.engine)
        self.assertIn("platform", {column["name"] for column in inspector.get_columns("windows_agents")})
        self.assertTrue(inspector.has_table("vsphere_connections"))
        self.assertTrue(inspector.has_table("vsphere_inventory_objects"))
        self.assertTrue(inspector.has_table("vsphere_debug_logs"))


if __name__ == "__main__":
    unittest.main()
