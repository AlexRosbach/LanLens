import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-service-tls-tests-12345")

from backend.database import Base
from backend.models import Device, DevicePingSample
from backend.routers.services import _normalize_tls_expiry, _resolve_safe_tls_addresses
from backend.services.scanner import PING_SAMPLE_RETENTION_PER_DEVICE, record_ping_sample


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


if __name__ == "__main__":
    unittest.main()
