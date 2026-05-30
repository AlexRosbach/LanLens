import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-service-tls-tests-12345")

from backend.database import Base
from backend.models import Device, DevicePingSample, Service, Setting
from backend.routers.devices import _auto_check_https_certificate
from backend.routers.services import _normalize_tls_expiry, _resolve_safe_tls_addresses, _service_tls_target
from backend.services.scanner import PING_SAMPLE_RETENTION_PER_DEVICE, record_ping_sample
from backend.services.settings_helpers import is_advanced_feature_enabled


class ServiceTlsAndPingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_tls_resolver_blocks_loopback_targets(self):
        with patch("backend.routers.services.socket.getaddrinfo", return_value=[
            (None, None, None, None, ("127.0.0.1", 443)),
        ]):
            with self.assertRaises(HTTPException) as ctx:
                _resolve_safe_tls_addresses("example.test", 443)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("loopback", ctx.exception.detail)

    def test_tls_resolver_returns_prevalidated_addresses_for_pinned_connect(self):
        with patch("backend.routers.services.socket.getaddrinfo", return_value=[
            (None, None, None, None, ("192.168.10.20", 443)),
            (None, None, None, None, ("192.168.10.20", 443)),
        ]):
            self.assertEqual(_resolve_safe_tls_addresses("service.local", 443), ["192.168.10.20"])

    def test_tls_expiry_is_normalized_to_naive_utc(self):
        expiry = datetime(2026, 5, 27, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(_normalize_tls_expiry(expiry), datetime(2026, 5, 27, 12, 30))

    def test_tls_target_rejects_invalid_https_port_cleanly(self):
        device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.10")
        service = Service(device=device, name="Bad HTTPS", url="https://example.test:99999")

        with self.assertRaises(HTTPException) as ctx:
            _service_tls_target(device, service)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("port", ctx.exception.detail)

    def test_tls_target_rejects_https_url_without_host(self):
        device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.10")
        service = Service(device=device, name="Bad HTTPS", url="https:///status")

        with self.assertRaises(HTTPException) as ctx:
            _service_tls_target(device, service)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("host", ctx.exception.detail)

    def test_advanced_feature_requires_global_and_specific_switch(self):
        db = self.Session()
        try:
            db.add_all([
                Setting(key="advanced_view_enabled", value="true"),
                Setting(key="show_tls_checks", value="false"),
            ])
            db.commit()

            self.assertFalse(is_advanced_feature_enabled(db, "show_tls_checks"))

            db.query(Setting).filter(Setting.key == "show_tls_checks").one().value = "true"
            db.commit()
            self.assertTrue(is_advanced_feature_enabled(db, "show_tls_checks"))

            db.query(Setting).filter(Setting.key == "advanced_view_enabled").one().value = "false"
            db.commit()
            self.assertFalse(is_advanced_feature_enabled(db, "show_tls_checks"))
        finally:
            db.close()

    def test_ping_sample_retention_keeps_latest_samples_per_device(self):
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.10")
            db.add(device)
            db.commit()
            db.refresh(device)

            base_time = datetime.utcnow() - timedelta(days=1)
            for index in range(PING_SAMPLE_RETENTION_PER_DEVICE + 5):
                record_ping_sample(
                    db,
                    device.id,
                    True,
                    1.0,
                    "test",
                    base_time + timedelta(seconds=index),
                )
            db.commit()

            rows = (
                db.query(DevicePingSample)
                .filter(DevicePingSample.device_id == device.id)
                .order_by(DevicePingSample.checked_at)
                .all()
            )

            self.assertEqual(len(rows), PING_SAMPLE_RETENTION_PER_DEVICE)
            self.assertEqual(rows[0].checked_at, base_time + timedelta(seconds=5))
        finally:
            db.close()

    def test_https_port_scan_creates_service_and_records_tls_status(self):
        db = self.Session()
        try:
            db.add_all([
                Setting(key="advanced_view_enabled", value="true"),
                Setting(key="show_tls_checks", value="true"),
            ])
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.10", hostname="server.local")
            db.add(device)
            db.commit()
            db.refresh(device)

            with patch("backend.routers.devices._inspect_tls_certificate", return_value={
                "status": "valid",
                "expires_at": datetime.utcnow() + timedelta(days=90),
                "issuer": "CN=Test CA",
                "subject": "CN=server.local",
                "sans": "server.local",
                "self_signed": False,
                "error": None,
                "checked_at": datetime.utcnow(),
            }) as inspect:
                _auto_check_https_certificate(db, device.id, [{"port": 443, "protocol": "tcp", "service": "https"}])
                db.commit()

            service = db.query(Service).filter(Service.device_id == device.id, Service.port == 443).one()
            self.assertEqual(service.name, "HTTPS")
            self.assertEqual(service.protocol, "https")
            self.assertEqual(service.tls_status, "valid")
            inspect.assert_called_once_with("192.0.2.10", 443, "server.local")
        finally:
            db.close()

    def test_https_port_scan_does_not_check_tls_when_feature_disabled(self):
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.10")
            db.add(device)
            db.commit()
            db.refresh(device)

            with patch("backend.routers.devices._inspect_tls_certificate") as inspect:
                _auto_check_https_certificate(db, device.id, [{"port": 443, "protocol": "tcp", "service": "https"}])

            self.assertEqual(db.query(Service).count(), 0)
            inspect.assert_not_called()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
