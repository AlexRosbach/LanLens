import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import CmdbSyncLog, Device, IdoitSyncLog, Setting, User
from backend.routers.debug import list_debug_logs


class DebugLogsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def _user(self) -> User:
        return User(username="tester", password_hash="x")

    def _enable_debug(self, db):
        db.add_all([
            Setting(key="advanced_view_enabled", value="true"),
            Setting(key="show_debug_tools", value="true"),
            Setting(key="debug_log_level", value="warning"),
        ])
        db.commit()

    def test_debug_logs_require_feature_flag(self):
        db = self.Session()
        try:
            with self.assertRaises(HTTPException) as raised:
                list_debug_logs(db=db, _=self._user())
            self.assertEqual(raised.exception.status_code, 403)
        finally:
            db.close()

    def test_debug_logs_filter_cmdb_and_idoit_entries(self):
        db = self.Session()
        try:
            self._enable_debug(db)
            device = Device(mac_address="00:11:22:33:44:55", hostname="app-01", cmdb_id="CMDB-42")
            db.add(device)
            db.commit()
            db.refresh(device)
            db.add_all([
                IdoitSyncLog(
                    device_id=device.id,
                    mode="manual",
                    result="failure",
                    message="No confident existing i-doit match found",
                    details_json='{"payload": {"identity": {"cmdb_id": "CMDB-42"}}}',
                ),
                CmdbSyncLog(
                    device_id=device.id,
                    mode="push",
                    result="success",
                    message="CMDB REST push completed",
                    details_json='{"status_code": 200}',
                ),
            ])
            db.commit()

            cmdb = list_debug_logs(topic="cmdb", level="info", q="", limit=100, db=db, _=self._user())
            self.assertEqual(len(cmdb["entries"]), 1)
            self.assertEqual(cmdb["entries"][0]["topic"], "cmdb")

            idoit = list_debug_logs(topic="idoit", level="error", q="CMDB-42", limit=100, db=db, _=self._user())
            self.assertEqual(len(idoit["entries"]), 1)
            self.assertEqual(idoit["entries"][0]["level"], "error")
            self.assertEqual(idoit["entries"][0]["device_name"], "app-01")
        finally:
            db.close()
