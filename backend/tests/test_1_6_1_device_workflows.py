import asyncio
import inspect
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-1-6-1-workflows")

from backend.database import Base
from backend.models import Credential, DeepScanFinding, DeepScanRun, Device, ManualConnectEntry, PortScan, Setting, User
from backend.routers import devices as devices_router
from backend.routers import scan as scan_router
from backend.routers import settings as settings_router
from backend.services import deep_scanner
from backend.schemas import (
    BulkPortScanRequest,
    DeviceBulkUpdateRequest,
    ManualConnectEntryCreate,
    ManualConnectEntryUpdate,
    UiSettings,
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
        db.bulk_save_objects(devices, return_defaults=True)
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

    def test_bulk_update_rejects_explicit_null_device_class(self):
        db = self.Session()
        device = Device(mac_address="02:00:00:00:00:09", device_class="Server")
        db.add(device)
        db.commit()

        with self.assertRaises(HTTPException) as raised:
            devices_router.bulk_update_devices(
                DeviceBulkUpdateRequest(device_ids=[device.id], device_class=None),
                db=db,
                _=User(id=1, username="tester", password_hash="unused"),
            )

        self.assertEqual(raised.exception.status_code, 400)
        db.refresh(device)
        self.assertEqual(device.device_class, "Server")
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

    def test_device_response_exposes_kernel_version(self):
        db = self.Session()
        user = User(username="tester", password_hash="unused", force_password_change=False)
        device = Device(
            mac_address="02:00:00:00:00:13",
            ip_address="192.0.2.13",
            kernel_version="6.8.12-4-pve",
        )
        db.add_all([user, device])
        db.commit()

        response = devices_router.list_devices(db=db, current_user=user)

        self.assertEqual(response.items[0].kernel_version, "6.8.12-4-pve")
        db.close()

    def test_optional_os_inference_explains_windows_evidence_without_overwriting_os_fields(self):
        db = self.Session()
        user = User(username="tester", password_hash="unused", force_password_change=False)
        device = Device(
            mac_address="02:00:00:00:00:14",
            ip_address="192.0.2.14",
            hostname="win-accounting",
            device_class="Workstation",
            os_info="Operator maintained value",
        )
        device.port_scans.append(PortScan(
            open_ports=json.dumps([
                {"port": 445, "protocol": "tcp", "service": "microsoft-ds", "state": "open"},
                {"port": 3389, "protocol": "tcp", "service": "rdp", "state": "open"},
            ]),
            ssh_available=False,
            rdp_available=True,
            http_available=False,
            https_available=False,
        ))
        db.add_all([user, device, Setting(key="show_os_inference", value="true")])
        db.commit()

        response = devices_router.list_devices(db=db, current_user=user).items[0]

        self.assertEqual(response.inferred_os_family, "Windows")
        self.assertEqual(response.os_inference_confidence, "high")
        self.assertIn("RDP port 3389 is open", response.os_inference_reasons)
        self.assertEqual(response.os_info, "Operator maintained value")
        db.close()

    def test_os_inference_is_hidden_when_feature_is_disabled(self):
        db = self.Session()
        user = User(username="tester", password_hash="unused", force_password_change=False)
        device = Device(
            mac_address="02:00:00:00:00:15",
            hostname="ubuntu-app",
            device_class="Linux Server",
        )
        db.add_all([user, device])
        db.commit()

        response = devices_router.list_devices(db=db, current_user=user).items[0]

        self.assertIsNone(response.inferred_os_family)
        self.assertEqual(response.os_inference_reasons, [])
        db.close()

    def test_os_inference_toggle_is_persisted(self):
        db = self.Session()
        with (
            patch.object(settings_router, "update_passive_discovery_schedule"),
            patch.object(settings_router, "update_ping_monitor_schedule"),
            patch.object(settings_router, "update_port_scan_schedule"),
            patch.object(settings_router, "update_snmp_poll_schedule"),
        ):
            settings_router.update_ui_settings(
                UiSettings(show_os_inference=True),
                db=db,
                _=User(id=1, username="tester", password_hash="unused"),
            )

        stored = db.query(Setting).filter(Setting.key == "show_os_inference").one()
        self.assertEqual(stored.value, "true")
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

    async def test_runner_offloads_result_storage_from_event_loop(self):
        devices_router._bulk_port_scan_job = devices_router.BulkPortScanJob(
            job_id="test-job",
            status="running",
            total=1,
        )
        scan_result = {
            "open_ports": [],
            "ssh_available": False,
            "rdp_available": False,
            "http_available": False,
            "https_available": False,
        }

        with (
            patch.object(devices_router, "scan_ports_async", new=AsyncMock(return_value=scan_result)),
            patch.object(asyncio, "to_thread", new=AsyncMock()) as to_thread,
        ):
            await devices_router._run_bulk_port_scan([(1, "192.0.2.1")], "top:1000")

        to_thread.assert_awaited_once_with(devices_router._store_port_scan_result, 1, scan_result)

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

    async def test_selected_scan_accepts_more_than_one_thousand_devices(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        devices = [
            Device(
                mac_address=f"02:00:{index // 65536:02X}:{(index // 256) % 256:02X}:{index % 256:02X}:01",
                ip_address=f"10.0.{index // 250}.{index % 250 + 1}",
            )
            for index in range(1001)
        ]
        db.add_all(devices)
        db.commit()

        try:
            request = BulkPortScanRequest(device_ids=[device.id for device in devices])
            with patch.object(devices_router, "_run_bulk_port_scan", new_callable=AsyncMock) as runner:
                status = devices_router._launch_bulk_port_scan(db, request.device_ids)
                await asyncio.sleep(0)

            self.assertEqual(status.total, 1001)
            targets = runner.await_args.args[0]
            self.assertEqual(len(targets), 1001)
        finally:
            devices_router._bulk_port_scan_job = devices_router.BulkPortScanJob()
            devices_router._bulk_port_scan_task = None
            db.close()
            Base.metadata.drop_all(engine)

    async def test_manual_discovery_blocks_an_independent_bulk_scan(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        scan_router._manual_scan_pipeline_running = True
        try:
            with self.assertRaises(HTTPException) as raised:
                await devices_router.start_bulk_port_scan(
                    BulkPortScanRequest(device_ids=[1]),
                    db=db,
                    _=User(id=1, username="tester", password_hash="unused"),
                )
            self.assertEqual(raised.exception.status_code, 409)
        finally:
            scan_router._manual_scan_pipeline_running = False
            db.close()
            Base.metadata.drop_all(engine)

    async def test_cancel_endpoint_runs_on_the_event_loop(self):
        self.assertTrue(inspect.iscoroutinefunction(devices_router.cancel_bulk_port_scan))
        devices_router._bulk_port_scan_job = devices_router.BulkPortScanJob(
            job_id="test-job",
            status="running",
            total=1,
        )
        status = await devices_router.cancel_bulk_port_scan(
            _=User(id=1, username="tester", password_hash="unused"),
        )
        self.assertTrue(status.cancel_requested)
        self.assertEqual(status.status, "cancelling")


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


class LinuxKernelDeepScanTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_linux_deep_scan_updates_dedicated_kernel_field(self):
        db = self.Session()
        device = Device(mac_address="02:00:00:00:02:01", ip_address="192.0.2.21")
        credential = Credential(
            name="Linux test",
            credential_type="linux_ssh",
            auth_method="password",
            username="scanner",
            encrypted_secret="unused",
        )
        db.add_all([device, credential])
        db.commit()
        run = DeepScanRun(
            device_id=device.id,
            credential_id=credential.id,
            profile="os_services",
            status="running",
        )
        db.add(run)
        db.commit()

        class Stream:
            def __init__(self, value: str):
                self.value = value

            def read(self):
                return self.value.encode()

        class Client:
            def connect(self, **_kwargs):
                return None

            def exec_command(self, command, timeout=20):
                output = "6.8.12-4-pve\n" if command.startswith("uname -r") else ""
                return None, Stream(output), Stream("")

            def close(self):
                return None

        with (
            patch.dict(sys.modules, {"paramiko": SimpleNamespace()}),
            patch.object(deep_scanner, "create_verified_ssh_client", return_value=Client()),
        ):
            deep_scanner._run_linux_scan(db, device, run, credential, "secret")

        db.refresh(device)
        self.assertEqual(device.kernel_version, "6.8.12-4-pve")
        finding = db.query(DeepScanFinding).filter_by(device_id=device.id, key="kernel").one()
        self.assertIn("6.8.12-4-pve", finding.value_json)
        db.close()


if __name__ == "__main__":
    unittest.main()
