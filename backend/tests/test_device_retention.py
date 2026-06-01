import os
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-retention-tests-12345")

from backend.database import Base
from backend.models import Device, DeviceChangeEvent, Setting
from backend.services.device_retention import apply_device_retention, get_device_retention_settings


class DeviceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_retention_defaults_are_disabled(self):
        db = self.Session()
        try:
            self.assertEqual(get_device_retention_settings(db), {
                "device_archive_after_days": 0,
                "device_delete_archived_after_days": 0,
            })
        finally:
            db.close()

    def test_archives_inactive_devices_without_deleting_them(self):
        db = self.Session()
        try:
            now = datetime(2026, 6, 1, 12, 0, 0)
            stale = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                device_class="Unknown",
                is_online=True,
                first_seen=now - timedelta(days=10),
                last_seen=now - timedelta(days=8),
            )
            recent = Device(
                mac_address="00:11:22:33:44:66",
                ip_address="192.0.2.11",
                device_class="Unknown",
                is_online=True,
                first_seen=now - timedelta(days=2),
                last_seen=now - timedelta(days=2),
            )
            registered = Device(
                mac_address="00:11:22:33:44:77",
                ip_address="192.0.2.12",
                device_class="Server",
                is_registered=True,
                is_online=True,
                first_seen=now - timedelta(days=20),
                last_seen=now - timedelta(days=15),
            )
            db.add_all([
                stale,
                recent,
                registered,
                Setting(key="device_archive_after_days", value="7"),
                Setting(key="device_delete_archived_after_days", value="0"),
            ])
            db.commit()

            result = apply_device_retention(db, now)
            db.commit()

            self.assertEqual(result, {"archived": 1, "deleted": 0})
            self.assertTrue(stale.is_archived)
            self.assertEqual(stale.archived_at, now)
            self.assertFalse(stale.is_online)
            self.assertFalse(recent.is_archived)
            self.assertFalse(registered.is_archived)
            self.assertTrue(registered.is_online)
            self.assertEqual(db.query(DeviceChangeEvent).filter(DeviceChangeEvent.device_id == stale.id).count(), 1)
        finally:
            db.close()

    def test_deletes_devices_after_archive_retention(self):
        db = self.Session()
        try:
            now = datetime(2026, 6, 1, 12, 0, 0)
            archived = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                device_class="Unknown",
                is_archived=True,
                archived_at=now - timedelta(days=31),
                first_seen=now - timedelta(days=60),
                last_seen=now - timedelta(days=40),
            )
            retained = Device(
                mac_address="00:11:22:33:44:66",
                ip_address="192.0.2.11",
                device_class="Unknown",
                is_archived=True,
                archived_at=now - timedelta(days=3),
                first_seen=now - timedelta(days=30),
                last_seen=now - timedelta(days=10),
            )
            registered = Device(
                mac_address="00:11:22:33:44:77",
                ip_address="192.0.2.12",
                device_class="Server",
                is_registered=True,
                is_archived=True,
                archived_at=now - timedelta(days=90),
                first_seen=now - timedelta(days=120),
                last_seen=now - timedelta(days=100),
            )
            db.add_all([
                archived,
                retained,
                registered,
                Setting(key="device_archive_after_days", value="7"),
                Setting(key="device_delete_archived_after_days", value="30"),
            ])
            db.commit()

            result = apply_device_retention(db, now)
            db.commit()

            self.assertEqual(result, {"archived": 0, "deleted": 1})
            self.assertIsNone(db.query(Device).filter(Device.mac_address == "00:11:22:33:44:55").first())
            self.assertIsNotNone(db.query(Device).filter(Device.mac_address == "00:11:22:33:44:66").first())
            self.assertIsNotNone(db.query(Device).filter(Device.mac_address == "00:11:22:33:44:77").first())
        finally:
            db.close()
