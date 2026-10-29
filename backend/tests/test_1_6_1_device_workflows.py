import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-1-6-1-workflows")

from backend.database import Base
from backend.models import Device, ManualConnectEntry, User
from backend.routers import devices as devices_router
from backend.routers import scan as scan_router
from backend.schemas import (
    DeviceBulkUpdateRequest,
    ManualConnectEntryCreate,
    ManualConnectEntryUpdate,
)


class DeviceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_bulk_update_changes_only_selected_fields(self):
        db = self.Session()
        devices = [
            Device(
                mac_address=f"02:00:00:00:00:0{index}",
                device_class="Unknown",
                responsible="Existing owner",
                location="Rack A",
            )
            for index in range(1, 3)
        ]
        db.add_all(devices)
        db.commit()

        result = devices_router.bulk_update_devices(
            DeviceBulkUpdateRequest(
                device_ids=[device.id for device in devices],
                device_class="Server",
                responsible="Operations",
            ),
            db=db,
            _=User(id=1, username="tester", password_hash="unused"),
        )

        self.assertEqual(result.updated, 2)
        db.expire_all()
        for device in db.query(Device).all():
            self.assertEqual(device.device_class, "Server")
            self.assertEqual(device.responsible, "Operations")
            self.assertEqual(device.location, "Rack A")
        db.close()

    def test_vendor_override_is_effective_without_destroying_detected_vendor(self):
        device = Device(
            mac_address="02:00:00:00:00:11",
            vendor="Detected Vendor",
            vendor_override="Corrected Vendor",
        )
        self.assertEqual(device.effective_vendor, "Corrected Vendor")
        device.vendor_override = None
        self.assertEqual(device.effective_vendor, "Detected Vendor")

    def test_device_response_exposes_effective_vendor_and_manual_links(self):
        db = self.Session()
        user = User(username="tester", password_hash="unused", force_password_change=False)
        device = Device(
            mac_address="02:00:00:00:00:12",
            ip_address="192.0.2.12",
            vendor="Detected Vendor",
            vendor_override="Corrected Vendor",
        )
        device.manual_connect_entries.append(ManualConnectEntry(
            label="Portal",
            url="https://portal.example.test",
            protocol="https",
        ))
        db.add_all([user, device])
        db.commit()

        response = devices_router.list_devices(db=db, current_user=user)

        self.assertEqual(response.items[0].vendor, "Corrected Vendor")
        self.assertEqual(response.items[0].vendor_detected, "Detected Vendor")
        self.assertEqual(response.items[0].vendor_override, "Corrected Vendor")
        self.assertEqual(response.items[0].manual_connect_entries[0].label, "Portal")
        db.close()

    def test_manual_connect_entries_can_be_created_updated_and_deleted(self):
        db = self.Session()
        device = Device(mac_address="02:00:00:00:00:21", ip_address="192.0.2.21")
        db.add(device)
        db.commit()
        user = User(id=1, username="tester", password_hash="unused")

        created = devices_router.create_manual_connect_entry(
            device.id,
            ManualConnectEntryCreate(label="DSM", url="https://nas.example.com", protocol="https"),
            db=db,
            _=user,
        )
        self.assertEqual(created.label, "DSM")

        updated = devices_router.update_manual_connect_entry(
            device.id,
            created.id,
            ManualConnectEntryUpdate(label="NAS", url="https://nas.example.com/admin", protocol="https"),
            db=db,
            _=user,
        )
        self.assertEqual(updated.label, "NAS")

        devices_router.delete_manual_connect_entry(device.id, created.id, db=db, _=user)
        self.assertEqual(db.query(ManualConnectEntry).count(), 0)
        db.close()

    def test_manual_connect_url_rejects_unsafe_scheme(self):
        with self.assertRaises(ValueError):
            ManualConnectEntryCreate(label="Unsafe", url="javascript:alert(1)", protocol="https")


class BulkPortScanRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_tracks_success_failure_and_skipped_devices(self):
        devices_router._bulk_port_scan_job = devices_router.BulkPortScanJob(
            job_id="test-job",
            status="running",
            total=3,
            completed=1,
            skipped=1,
        )
        scan_result = {
            "open_ports": [],
            "ssh_available": False,
            "rdp_available": False,
            "http_available": False,
            "https_available": False,
        }
        scanner = AsyncMock(side_effect=[scan_result, None])

        with patch.object(devices_router, "scan_ports_async", scanner), patch.object(devices_router, "_store_port_scan_result") as store:
            await devices_router._run_bulk_port_scan([(1, "192.0.2.1"), (2, "192.0.2.2")], "top:1000")

        status = devices_router._bulk_port_scan_status()
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.completed, 3)
        self.assertEqual(status.succeeded, 1)
        self.assertEqual(status.failed, 1)
        self.assertEqual(status.skipped, 1)
        store.assert_called_once_with(1, scan_result)

    async def test_automatic_scan_targets_only_online_non_ignored_devices(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        devices = [
            Device(mac_address="02:00:00:00:01:01", ip_address="192.0.2.1", is_online=True),
            Device(mac_address="02:00:00:00:01:02", ip_address="192.0.2.2", is_online=False),
            Device(mac_address="02:00:00:00:01:03", ip_address="192.0.2.3", is_online=True, ignored=True),
        ]
        db.add_all(devices)
        db.commit()

        try:
            with patch.object(devices_router, "_run_bulk_port_scan", new_callable=AsyncMock) as runner:
                status = devices_router._launch_bulk_port_scan(db, online_only=True)
                await asyncio.sleep(0)

            self.assertEqual(status.total, 1)
            runner.assert_awaited_once_with([(devices[0].id, "192.0.2.1")], "top:1000")
        finally:
            devices_router._bulk_port_scan_job = devices_router.BulkPortScanJob()
            devices_router._bulk_port_scan_task = None
            db.close()
            Base.metadata.drop_all(engine)


class ManualScanPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_scan_waits_for_follow_up_port_scan(self):
        completed = False

        async def port_scan():
            nonlocal completed
            await asyncio.sleep(0)
            completed = True

        task = asyncio.create_task(port_scan())
        scan_router._manual_scan_pipeline_running = True
        with (
            patch.object(scan_router, "run_scan", new=AsyncMock(return_value=SimpleNamespace(status="done"))) as discovery,
            patch.object(devices_router, "start_automatic_bulk_port_scan", return_value=task) as start_ports,
        ):
            await scan_router._run_manual_scan_pipeline()

        discovery.assert_awaited_once_with("manual")
        start_ports.assert_called_once_with()
        self.assertTrue(completed)
        self.assertFalse(scan_router._manual_scan_pipeline_running)


if __name__ == "__main__":
    unittest.main()
