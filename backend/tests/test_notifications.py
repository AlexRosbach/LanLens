import os
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-notification-tests-12345")

from backend.database import Base
from backend.models import Device, Notification, Setting
from backend.routers.notifications import delete_all_notifications
from backend.services.notification import (
    notification_device_path,
    notification_device_url,
    send_smtp_for_notification,
    send_telegram_for_notification,
    send_webhook_for_notification,
)
from backend.services.scanner import _send_notification_deliveries


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

    async def test_network_change_smtp_uses_change_payload(self):
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
                message="Network change: hostname changed (desk-01 -> desk-02)",
            )
            db.add_all([
                notification,
                Setting(key="smtp_enabled", value="true"),
                Setting(key="smtp_host", value="smtp.example"),
                Setting(key="smtp_from_email", value="lanlens@example.com"),
                Setting(key="smtp_to_email", value="admin@example.com"),
                Setting(key="server_url", value="https://lanlens.example"),
            ])
            db.commit()
            db.refresh(notification)

            with patch("backend.services.notification._send_smtp") as send:
                self.assertTrue(await send_smtp_for_notification(db, notification))

            msg = send.call_args.args[6]
            self.assertEqual(msg["Subject"], "LanLens — Network Change")
            self.assertIn("desk-02", msg.get_payload(decode=True).decode("utf-8"))
            self.assertIn(f"https://lanlens.example/devices/{device.id}", msg.get_payload(decode=True).decode("utf-8"))
        finally:
            db.close()

    async def test_delivery_rules_route_events_per_channel(self):
        db = self.Session()
        try:
            new_device = Notification(event_type="new_device", message="New device detected")
            network_change = Notification(event_type="network_change", message="Network change: IP changed")
            db.add_all([
                new_device,
                network_change,
                Setting(key="notify_on_new_device", value="true"),
                Setting(key="notify_on_network_changes", value="true"),
                Setting(key="telegram_enabled", value="true"),
                Setting(key="telegram_bot_token", value="test-token"),
                Setting(key="telegram_chat_id", value="test-chat"),
                Setting(key="telegram_notify_new_device", value="true"),
                Setting(key="telegram_notify_network_changes", value="false"),
                Setting(key="webhook_enabled", value="true"),
                Setting(key="webhook_url", value="https://notify.example/message?token=test"),
                Setting(key="webhook_notify_new_device", value="false"),
                Setting(key="webhook_notify_network_changes", value="true"),
                Setting(key="smtp_enabled", value="true"),
                Setting(key="smtp_host", value="smtp.example"),
                Setting(key="smtp_from_email", value="lanlens@example.com"),
                Setting(key="smtp_to_email", value="admin@example.com"),
                Setting(key="smtp_notify_new_device", value="true"),
                Setting(key="smtp_notify_network_changes", value="true"),
            ])
            db.commit()

            with patch("backend.services.scanner.send_telegram_for_notification", new_callable=AsyncMock) as telegram, \
                 patch("backend.services.scanner.send_webhook_for_notification", new_callable=AsyncMock) as webhook, \
                 patch("backend.services.scanner.send_smtp_for_notification", new_callable=AsyncMock) as smtp:
                telegram.return_value = True
                webhook.return_value = True
                smtp.return_value = True
                await _send_notification_deliveries(db)

            db.refresh(new_device)
            db.refresh(network_change)

            self.assertEqual([call.args[1].event_type for call in telegram.await_args_list], ["new_device"])
            self.assertEqual([call.args[1].event_type for call in webhook.await_args_list], ["network_change"])
            self.assertEqual([call.args[1].event_type for call in smtp.await_args_list], ["new_device", "network_change"])
            self.assertTrue(new_device.telegram_sent)
            self.assertFalse(new_device.webhook_sent)
            self.assertTrue(new_device.smtp_sent)
            self.assertFalse(network_change.telegram_sent)
            self.assertTrue(network_change.webhook_sent)
            self.assertTrue(network_change.smtp_sent)
        finally:
            db.close()

    async def test_global_notification_rules_suppress_channel_delivery(self):
        db = self.Session()
        try:
            new_device = Notification(event_type="new_device", message="New device detected")
            network_change = Notification(event_type="network_change", message="Network change: IP changed")
            db.add_all([
                new_device,
                network_change,
                Setting(key="notify_on_new_device", value="false"),
                Setting(key="notify_on_network_changes", value="false"),
                Setting(key="telegram_enabled", value="true"),
                Setting(key="telegram_bot_token", value="test-token"),
                Setting(key="telegram_chat_id", value="test-chat"),
                Setting(key="telegram_notify_new_device", value="true"),
                Setting(key="telegram_notify_network_changes", value="true"),
                Setting(key="webhook_enabled", value="true"),
                Setting(key="webhook_url", value="https://notify.example/message?token=test"),
                Setting(key="webhook_notify_new_device", value="true"),
                Setting(key="webhook_notify_network_changes", value="true"),
                Setting(key="smtp_enabled", value="true"),
                Setting(key="smtp_host", value="smtp.example"),
                Setting(key="smtp_from_email", value="lanlens@example.com"),
                Setting(key="smtp_to_email", value="admin@example.com"),
                Setting(key="smtp_notify_new_device", value="true"),
                Setting(key="smtp_notify_network_changes", value="true"),
            ])
            db.commit()

            with patch("backend.services.scanner.send_telegram_for_notification", new_callable=AsyncMock) as telegram, \
                 patch("backend.services.scanner.send_webhook_for_notification", new_callable=AsyncMock) as webhook, \
                 patch("backend.services.scanner.send_smtp_for_notification", new_callable=AsyncMock) as smtp:
                await _send_notification_deliveries(db)

            telegram.assert_not_awaited()
            webhook.assert_not_awaited()
            smtp.assert_not_awaited()
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

    def test_delete_all_notifications_removes_every_notification(self):
        db = self.Session()
        try:
            db.add_all([
                Notification(event_type="new_device", message="first", is_read=False),
                Notification(event_type="network_change", message="second", is_read=True),
            ])
            db.commit()

            response = delete_all_notifications(db, None)

            self.assertEqual(response.message, "Deleted 2 notifications")
            self.assertEqual(db.query(Notification).count(), 0)
        finally:
            db.close()
