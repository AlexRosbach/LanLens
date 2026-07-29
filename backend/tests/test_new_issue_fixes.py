import os
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-new-issue-fixes-12345")

from backend.auth.dependencies import get_current_user
from backend.config import settings
from backend.database import Base
from backend.models import Device, Notification, ScanRun, User
from backend.routers.scan import get_scan_status
from backend.services.scanner import _detect_local_host_result


class NewIssueFixTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_persistent_api_token_allows_reads_and_blocks_writes_by_default(self):
        db = self.Session()
        original_token = settings.api_token
        original_read_only = settings.api_token_read_only
        try:
            db.add(User(username="admin", password_hash="x", force_password_change=False))
            db.commit()
            settings.api_token = "persistent-test-token-that-is-long-enough"
            settings.api_token_read_only = True
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=settings.api_token,
            )

            user = get_current_user(
                Request({"type": "http", "method": "GET", "headers": []}),
                credentials,
                db,
            )
            self.assertEqual(user.username, "admin")

            with self.assertRaises(HTTPException) as ctx:
                get_current_user(
                    Request({"type": "http", "method": "POST", "headers": []}),
                    credentials,
                    db,
                )
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            settings.api_token = original_token
            settings.api_token_read_only = original_read_only
            db.close()

    def test_scan_status_includes_live_inventory_and_notification_counts(self):
        db = self.Session()
        try:
            db.add_all([
                User(username="admin", password_hash="x", force_password_change=False),
                Device(mac_address="00:11:22:33:44:01", is_online=True, is_archived=False),
                Device(mac_address="00:11:22:33:44:02", is_online=False, is_archived=False),
                Device(mac_address="00:11:22:33:44:03", is_online=False, is_archived=True),
                Notification(event_type="test", message="Unread", is_read=False),
                Notification(event_type="test", message="Read", is_read=True),
                ScanRun(scan_type="manual", devices_found=1, status="done"),
            ])
            db.commit()

            status = get_scan_status(db=db, _=None)

            self.assertEqual(status.last_scan.devices_found, 1)
            self.assertEqual(status.current_stats.total, 2)
            self.assertEqual(status.current_stats.online, 1)
            self.assertEqual(status.current_stats.offline, 1)
            self.assertEqual(status.current_stats.unread_notifications, 1)
        finally:
            db.close()

    def test_local_host_identity_is_added_from_primary_interface(self):
        fake_netifaces = types.SimpleNamespace(
            AF_INET=2,
            AF_LINK=17,
            gateways=lambda: {"default": {2: ("192.168.50.1", "eth0")}},
            interfaces=lambda: ["lo", "eth0"],
            ifaddresses=lambda iface: {
                2: [{"addr": "192.168.50.20", "netmask": "255.255.255.0"}],
                17: [{"addr": "00:11:22:33:44:55"}],
            } if iface == "eth0" else {},
        )
        with patch.dict(sys.modules, {"netifaces": fake_netifaces}):
            result = _detect_local_host_result("192.168.50.1", "192.168.50.254")

        self.assertIsNotNone(result)
        self.assertEqual(result.ip, "192.168.50.20")
        self.assertEqual(result.mac, "00:11:22:33:44:55")

    def test_local_host_identity_is_skipped_outside_configured_range(self):
        fake_netifaces = types.SimpleNamespace(
            AF_INET=2,
            AF_LINK=17,
            gateways=lambda: {"default": {2: ("192.168.50.1", "eth0")}},
            interfaces=lambda: ["eth0"],
            ifaddresses=lambda _iface: {
                2: [{"addr": "192.168.50.20", "netmask": "255.255.255.0"}],
                17: [{"addr": "00:11:22:33:44:55"}],
            },
        )
        with patch.dict(sys.modules, {"netifaces": fake_netifaces}):
            result = _detect_local_host_result("10.0.0.1", "10.0.0.254")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
