import os
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-device-list-12345")

from backend.database import Base
from backend.models import Device, PortScan, Service, User
from backend.routers.devices import bulk_delete_devices, list_devices
from backend.schemas import DeviceBulkDeleteRequest


class DeviceBulkAndListPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_device_list_uses_bounded_queries_for_related_rows(self):
        db = self.Session()
        user = User(username="tester", password_hash="unused", force_password_change=False)
        db.add(user)
        for index in range(100):
            device = Device(
                mac_address=f"02:00:00:00:{index // 256:02X}:{index % 256:02X}",
                ip_address=f"192.0.2.{index + 1}",
                is_online=True,
            )
            device.services.append(Service(name=f"Service {index}"))
            device.port_scans.append(PortScan(open_ports="[]"))
            db.add(device)
        db.commit()

        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            response = list_devices(db=db, current_user=user)
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)
            db.close()

        self.assertEqual(len(response.items), 100)
        # The endpoint reads several independent settings, but relationship
        # loading must remain constant instead of adding two queries per row.
        self.assertLessEqual(len(statements), 40)

    def test_bulk_delete_removes_only_requested_devices(self):
        db = self.Session()
        devices = [
            Device(mac_address=f"02:00:00:00:00:{index:02X}", ip_address=f"198.51.100.{index}")
            for index in range(1, 4)
        ]
        db.add_all(devices)
        db.commit()
        ids = [device.id for device in devices]

        response = bulk_delete_devices(
            DeviceBulkDeleteRequest(device_ids=[ids[0], ids[1], ids[1]]),
            db=db,
            _=User(id=1, username="tester", password_hash="unused"),
        )

        self.assertEqual(response.message, "Deleted 2 devices")
        self.assertEqual([row.id for row in db.query(Device).all()], [ids[2]])
        db.close()


if __name__ == "__main__":
    unittest.main()
