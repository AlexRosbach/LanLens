import os
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-inventory-change-tests-12345")

from backend.database import Base
from backend.models import Device, DeviceChangeEvent, User
from backend.routers.inventory import list_network_changes


class InventoryChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_lists_recent_changes_with_device_metadata(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="nas-01",
                label="NAS",
                device_class="NAS",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            older = DeviceChangeEvent(
                device_id=device.id,
                event_type="device_discovered",
                source="scan",
                message="Discovered at 192.0.2.10",
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
            newer = DeviceChangeEvent(
                device_id=device.id,
                event_type="ip_changed",
                field_name="ip_address",
                old_value="192.0.2.9",
                new_value="192.0.2.10",
                source="scan",
                created_at=datetime.utcnow(),
            )
            db.add_all([older, newer])
            db.commit()

            rows = list_network_changes(
                event_type=None,
                device_id=None,
                source=None,
                since_hours=None,
                search=None,
                limit=100,
                db=db,
                _=User(username="admin", password_hash="x"),
            )

            self.assertEqual([row.event_type for row in rows], ["ip_changed", "device_discovered"])
            self.assertEqual(rows[0].device_label, "NAS")
            self.assertEqual(rows[0].device_ip, "192.0.2.10")
            self.assertEqual(rows[0].device_mac, "00:11:22:33:44:55")
            self.assertEqual(rows[0].device_class, "NAS")
        finally:
            db.close()

    def test_filters_by_event_type_source_time_and_search(self):
        db = self.Session()
        try:
            router = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.1", hostname="router-01", device_class="Router")
            printer = Device(mac_address="00:11:22:33:44:66", ip_address="192.0.2.20", hostname="printer-01", device_class="Printer")
            db.add_all([router, printer])
            db.commit()
            db.refresh(router)
            db.refresh(printer)

            db.add_all([
                DeviceChangeEvent(
                    device_id=router.id,
                    event_type="online_state_changed",
                    field_name="is_online",
                    old_value="False",
                    new_value="True",
                    source="scan",
                    created_at=datetime.utcnow() - timedelta(minutes=20),
                ),
                DeviceChangeEvent(
                    device_id=printer.id,
                    event_type="device_updated",
                    field_name="label",
                    old_value=None,
                    new_value="Office Printer",
                    source="user",
                    created_at=datetime.utcnow() - timedelta(days=10),
                ),
            ])
            db.commit()

            rows = list_network_changes(
                event_type="online_state_changed",
                source="scan",
                since_hours=24,
                search="router",
                device_id=None,
                limit=100,
                db=db,
                _=User(username="admin", password_hash="x"),
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].device_label, "router-01")
            self.assertEqual(rows[0].event_type, "online_state_changed")
        finally:
            db.close()

    def test_ignores_whitespace_only_search(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="nas-01",
                device_class="NAS",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            db.add(DeviceChangeEvent(
                device_id=device.id,
                event_type="device_discovered",
                source="scan",
                message="Discovered at 192.0.2.10",
                created_at=datetime.utcnow(),
            ))
            db.commit()

            rows = list_network_changes(
                event_type=None,
                device_id=None,
                source=None,
                since_hours=None,
                search="   ",
                limit=100,
                db=db,
                _=User(username="admin", password_hash="x"),
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].device_label, "nas-01")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
