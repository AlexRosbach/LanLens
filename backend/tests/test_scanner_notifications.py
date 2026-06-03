import os
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-scanner-tests-12345")

from backend.database import Base
from backend.models import Device, Notification, Setting
from backend.services.scanner import _record_change


class ScannerNetworkChangeNotificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_network_change_notification_setting_is_cached_per_session(self):
        db = self.Session()
        setting_selects = 0

        def count_setting_selects(_conn, _cursor, statement, parameters, _context, _executemany):
            nonlocal setting_selects
            if "FROM settings" in statement and "notify_on_network_changes" in parameters:
                setting_selects += 1

        event.listen(self.engine, "before_cursor_execute", count_setting_selects)
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                device_class="computer",
                hostname="desk-01",
            )
            db.add_all([
                device,
                Setting(key="notify_on_network_changes", value="true"),
            ])
            db.commit()
            db.refresh(device)

            _record_change(db, device.id, "ip_changed", "ip_address", "192.0.2.10", "192.0.2.11", "test")
            _record_change(db, device.id, "hostname_changed", "hostname", "desk-01", "desk-02", "test")

            self.assertEqual(setting_selects, 1)
            self.assertEqual(db.query(Notification).filter(Notification.event_type == "network_change").count(), 2)
        finally:
            event.remove(self.engine, "before_cursor_execute", count_setting_selects)
            db.close()
