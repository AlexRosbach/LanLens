import os
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-notification-tests-12345")

from backend.database import Base
from backend.models import Device, Notification, Setting
from backend.services.notification import (
    notification_device_path,
    notification_device_url,
    send_telegram_for_notification,
    send_webhook_for_notification,
)


class NotificationLinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    async def test_webhook_payload_includes_clickable_device_link(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                vendor="Example",
                device_class="computer",
                hostname="desk-01",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            notification = Notification(
                device_id=device.id,
                event_type="new_device",
                message="New device detected",
            )
            db.add_all([
                notification,
                Setting(key="webhook_enabled", value="true"),
                Setting(key="webhook_url", value="https://notify.example/message?token=test"),
                Setting(key="server_url", value="https://lanlens.example"),
            ])
            db.commit()
            db.refresh(notification)

            with patch("backend.services.notification._send_webhook", new_callable=AsyncMock) as send:
                send.return_value = True
                self.assertTrue(await send_webhook_for_notification(db, notification))

            payload = send.await_args.args[1]
            self.assertEqual(payload["device_path"], f"/devices/{device.id}")
            self.assertEqual(payload["device_url"], f"https://lanlens.example/devices/{device.id}")
            self.assertEqual(payload["url"], payload["device_url"])
            self.assertIn(payload["device_url"], payload["message"])
            self.assertEqual(
                payload["extras"]["client::notification"]["click"]["url"],
                payload["device_url"],
            )
        finally:
            db.close()

    async def test_network_change_webhook_uses_change_payload(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                vendor="Example",
                device_class="computer",
                hostname="desk-01",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            notification = Notification(
                device_id=device.id,
                event_type="network_change",
                message="Network change: ip changed (ip_address: 192.0.2.10 -> 192.0.2.20)",
            )
            db.add_all([
                notification,
                Setting(key="webhook_enabled", value="true"),
                Setting(key="webhook_url", value="https://notify.example/message?token=test"),
                Setting(key="server_url", value="https://lanlens.example"),
            ])
            db.commit()
            db.refresh(notification)

            with patch("backend.services.notification._send_webhook", new_callable=AsyncMock) as send:
                send.return_value = True
                self.assertTrue(await send_webhook_for_notification(db, notification))

            payload = send.await_args.args[1]
            self.assertEqual(payload["title"], "LanLens — Network Change")
            self.assertEqual(payload["event_type"], "network_change")
            self.assertIn("192.0.2.20", payload["message"])
            self.assertEqual(payload["device_path"], f"/devices/{device.id}")
            self.assertEqual(payload["url"], f"https://lanlens.example/devices/{device.id}")
        finally:
            db.close()

    async def test_network_change_telegram_escapes_html_payload(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                vendor="Example",
                device_class="computer",
                hostname='desk<01>&"',
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            notification = Notification(
                device_id=device.id,
                event_type="network_change",
                message='Network change: hostname changed (<old>&" -> <new>&")',
            )
            db.add_all([
                notification,
                Setting(key="telegram_enabled", value="true"),
                Setting(key="telegram_bot_token", value="test-token"),
                Setting(key="telegram_chat_id", value="test-chat"),
                Setting(key="server_url", value='https://lanlens.example/?device="<bad>&'),
            ])
            db.commit()
            db.refresh(notification)

            with patch("backend.services.notification._send_message", new_callable=AsyncMock) as send:
                send.return_value = True
                self.assertTrue(await send_telegram_for_notification(db, notification))

            text = send.await_args.args[2]
            self.assertIn("&lt;old&gt;&amp;&quot;", text)
            self.assertIn("desk&lt;01&gt;&amp;&quot;", text)
            self.assertIn('href="https://lanlens.example/?device=&quot;&lt;bad&gt;&amp;/devices/', text)
            self.assertNotIn("<old>", text)
            self.assertNotIn("desk<01>", text)
        finally:
            db.close()

    def test_notification_device_path_and_url_use_app_route(self):
        db = self.Session()
        try:
            notification = Notification(device_id=42, event_type="new_device", message="New device detected")
            db.add_all([
                notification,
                Setting(key="server_url", value="https://lanlens.example/"),
            ])
            db.commit()

            self.assertEqual(notification_device_path(notification), "/devices/42")
            self.assertEqual(notification_device_url(db, notification), "https://lanlens.example/devices/42")
        finally:
            db.close()
