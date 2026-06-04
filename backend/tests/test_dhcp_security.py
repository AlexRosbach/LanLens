import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-dhcp-security-12345")

from backend.database import Base
from backend.models import DhcpAuthorizedServer, DhcpObservation, Notification, Setting
from backend.routers.dhcp_monitor import create_authorized_server, update_authorized_server
from backend.schemas import DhcpAuthorizedServerCreate, DhcpAuthorizedServerUpdate
from backend.services.dhcp_monitor import (
    _passive_capture_dhcp_replies,
    authorization_for_observation,
    notify_unknown_dhcp_servers,
    observation_to_response,
)


class DhcpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_authorized_server_matches_by_ip_or_mac(self):
        allowed_by_ip = DhcpAuthorizedServer(name="router", server_ip="192.0.2.1", enabled=True)
        allowed_by_mac = DhcpAuthorizedServer(name="backup", server_mac="AA:BB:CC:DD:EE:FF", enabled=True)
        ip_observation = DhcpObservation(server_ip="192.0.2.1", server_mac="00:11:22:33:44:55", options_json="{}")
        mac_observation = DhcpObservation(server_ip="192.0.2.2", server_mac="aa:bb:cc:dd:ee:ff", options_json="{}")

        self.assertEqual(authorization_for_observation(ip_observation, [allowed_by_ip])[1], allowed_by_ip)
        self.assertEqual(authorization_for_observation(mac_observation, [allowed_by_mac])[1], allowed_by_mac)

    def test_observation_response_marks_unknown_server(self):
        row = DhcpObservation(server_ip="192.0.2.99", server_mac="00:11:22:33:44:55", options_json='{"router": "192.0.2.1"}')

        response = observation_to_response(row, [])

        self.assertFalse(response["is_authorized"])
        self.assertIsNone(response["authorized_server_id"])
        self.assertEqual(response["options"]["router"], "192.0.2.1")

    def test_unknown_dhcp_server_creates_single_network_notification(self):
        db = self.Session()
        try:
            row = DhcpObservation(server_ip="192.0.2.99", server_mac="00:11:22:33:44:55", options_json="{}")
            db.add_all([row, Setting(key="notify_on_network_changes", value="true")])
            db.commit()

            self.assertEqual(notify_unknown_dhcp_servers(db, [row]), 1)
            self.assertEqual(notify_unknown_dhcp_servers(db, [row]), 0)

            notifications = db.query(Notification).all()
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].event_type, "network_change")
            self.assertIn("unknown DHCP server", notifications[0].message)
        finally:
            db.close()

    def test_unknown_dhcp_server_dedupes_pending_notifications_without_autoflush(self):
        SessionNoAutoflush = sessionmaker(bind=self.engine, autoflush=False)
        db = SessionNoAutoflush()
        try:
            row = DhcpObservation(server_ip="192.0.2.99", server_mac="00:11:22:33:44:55", options_json="{}")
            db.add_all([row, Setting(key="notify_on_network_changes", value="true")])
            db.commit()

            self.assertEqual(notify_unknown_dhcp_servers(db, [row, row]), 1)

            db.commit()
            notifications = db.query(Notification).all()
            self.assertEqual(len(notifications), 1)
            self.assertIn("unknown DHCP server", notifications[0].message)
        finally:
            db.close()

    def test_unknown_dhcp_server_respects_network_change_notification_setting(self):
        db = self.Session()
        try:
            row = DhcpObservation(server_ip="192.0.2.99", server_mac="00:11:22:33:44:55", options_json="{}")
            db.add(row)
            db.commit()

            self.assertEqual(notify_unknown_dhcp_servers(db, [row]), 0)
            self.assertEqual(db.query(Notification).count(), 0)
        finally:
            db.close()

    def test_passive_dhcp_capture_dedupes_repeated_server_replies(self):
        db = self.Session()
        try:
            row = DhcpObservation(
                server_ip="192.0.2.99",
                server_mac="00:11:22:33:44:55",
                message_type="offer",
                options_json="{}",
            )

            def fake_sniff(prn, **_kwargs):
                prn(object())
                prn(object())

            with patch("scapy.sendrecv.sniff", side_effect=fake_sniff), \
                 patch("backend.services.dhcp_monitor._packet_to_observation", return_value=row):
                stored = _passive_capture_dhcp_replies(db, timeout_seconds=5, packet_limit=10)

            self.assertEqual(stored, 1)
            self.assertEqual(db.query(DhcpObservation).count(), 1)
        finally:
            db.close()

    def test_authorized_server_create_rejects_whitespace_only_mac(self):
        db = self.Session()
        try:
            db.add_all([
                Setting(key="advanced_view_enabled", value="true"),
                Setting(key="show_dhcp_monitor_nav", value="true"),
            ])
            db.commit()

            with self.assertRaises(Exception) as raised:
                create_authorized_server(
                    DhcpAuthorizedServerCreate(name="empty", server_mac="   "),
                    db,
                    None,
                )

            self.assertEqual(getattr(raised.exception, "status_code", None), 422)
            self.assertEqual(db.query(DhcpAuthorizedServer).count(), 0)
        finally:
            db.close()

    def test_authorized_server_create_rejects_invalid_ip_or_mac(self):
        db = self.Session()
        try:
            db.add_all([
                Setting(key="advanced_view_enabled", value="true"),
                Setting(key="show_dhcp_monitor_nav", value="true"),
            ])
            db.commit()

            with self.assertRaises(Exception) as bad_ip:
                create_authorized_server(
                    DhcpAuthorizedServerCreate(name="bad-ip", server_ip="192.0.2.999"),
                    db,
                    None,
                )
            with self.assertRaises(Exception) as bad_mac:
                create_authorized_server(
                    DhcpAuthorizedServerCreate(name="bad-mac", server_mac="not-a-mac"),
                    db,
                    None,
                )

            self.assertEqual(getattr(bad_ip.exception, "status_code", None), 422)
            self.assertEqual(getattr(bad_mac.exception, "status_code", None), 422)
            self.assertEqual(db.query(DhcpAuthorizedServer).count(), 0)
        finally:
            db.close()

    def test_authorized_server_update_rejects_invalid_mac(self):
        db = self.Session()
        try:
            db.add_all([
                Setting(key="advanced_view_enabled", value="true"),
                Setting(key="show_dhcp_monitor_nav", value="true"),
                DhcpAuthorizedServer(name="router", server_ip="192.0.2.1"),
            ])
            db.commit()
            row = db.query(DhcpAuthorizedServer).first()

            with self.assertRaises(Exception) as raised:
                update_authorized_server(
                    row.id,
                    DhcpAuthorizedServerUpdate(server_mac="00:11:22:33:44:GG"),
                    db,
                    None,
                )

            self.assertEqual(getattr(raised.exception, "status_code", None), 422)
            db.refresh(row)
            self.assertIsNone(row.server_mac)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
