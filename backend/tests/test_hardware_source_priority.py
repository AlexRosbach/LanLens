import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-hardware-priority-secret-key-123456789")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import DeepScanFinding, DeepScanRun, Device, Setting, User, VsphereConnection, VsphereInventoryObject
from backend.routers.devices import get_device, list_devices
from backend.services.hardware_inventory import latest_hardware_by_device
from backend.services.idoit import IdoitClient, device_payload, get_config
from backend.services.vsphere import vmware_dashboard_inventory, vmware_hardware_inventory


class HardwareSourcePriorityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.device = Device(mac_address="00:50:56:00:00:01", hostname="test-vm", os_info="Example OS")
        self.user = User(username="tester", password_hash="unused", force_password_change=False)
        self.connection = VsphereConnection(id=1, enabled=True)
        self.db.add_all([self.device, self.user, self.connection, Setting(key="advanced_view_enabled", value="true")])
        self.db.flush()
        self.now = datetime(2026, 1, 1, 12)
        self.vm = VsphereInventoryObject(connection_id=1, device_id=self.device.id, kind="vm", external_id="vm-1",
                                        name="test-vm", match_status="existing", observed_at=self.now,
                                        metadata_json=json.dumps({"cpu_count": 4, "memory_size_mib": 8192,
                                                                  "disks": [{"disk_id": "2000", "label": "Disk 1", "capacity_bytes": 40 * 1024 ** 3}]}))
        self.db.add(self.vm)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def guest_report(self, observed_at, source="lanlens_windows_agent", status="done"):
        run = DeepScanRun(device_id=self.device.id, profile="windows_agent", status=status)
        self.db.add(run)
        self.db.flush()
        values = {
            "processor": {"Name": "Guest CPU model", "NumberOfCores": 2, "MaxClockSpeed": 2400},
            "physical_memory": [{"Capacity": 16 * 1024 ** 3, "DeviceLocator": "DIMM 1"}],
            "disk_drives": [{"Model": "Guest disk", "Size": 20 * 1024 ** 3, "DeviceID": "Disk 0", "SerialNumber": "GUEST-1"}],
            "computer_system": {"Manufacturer": "Guest vendor", "Model": "Guest model"},
            "bios": {"SerialNumber": "Guest serial"},
        }
        self.db.add_all([DeepScanFinding(device_id=self.device.id, run_id=run.id, finding_type="hardware",
                                        key=key, value_json=json.dumps(value), source=source, observed_at=observed_at)
                         for key, value in values.items()])
        self.db.commit()

    def assert_api_summary(self, expected):
        self.assertEqual(get_device(self.device.id, db=self.db, current_user=self.user).hardware_summary, expected)
        response = list_devices(db=self.db, current_user=self.user)
        self.assertEqual(response.items[0].hardware_summary, expected)

    def test_vmware_wins_before_and_after_guest_reports_without_rewriting_findings(self):
        for observed_at, source in ((self.now - timedelta(hours=1), "lanlens_windows_agent"),
                                    (self.now + timedelta(hours=1), "winrm/ps")):
            with self.subTest(guest_observed_at=observed_at, source=source):
                self.guest_report(observed_at, source=source)
                self.assert_api_summary("VMware: 4 vCPU · 8 GiB RAM")
                payload = device_payload(self.device, get_config(self.db), self.db)
                fields = payload["fields"]
                self.assertEqual(fields["C__CATG__CPU.cores"], 4)
                self.assertEqual(fields["C__CATG__CPU.title"], "Guest CPU model")
                self.assertEqual(fields["C__CATG__CPU.frequency"], 2.4)
                self.assertEqual(fields["C__CATG__MEMORY.title"], [{"quantity": 1, "title": "System memory", "capacity": 8, "unit": 3}])
                self.assertEqual(fields["C__CATG__DRIVE.title"], [{"title": "Disk 1 [LanLens disk: VMware disk 2000]", "capacity": 40, "unit": 3}])
                self.assertEqual(fields["C__CATG__MODEL.title"], "Guest model")
                self.assertEqual(fields["C__CATG__MODEL.serial"], "Guest serial")
                self.assertEqual(payload["operatingSystem"]["title"], "Example OS")
        self.assertEqual(self.db.query(DeepScanFinding).count(), 10)
        self.assertTrue(all(json.loads(row.value_json)["NumberOfCores"] == 2 for row in
                            self.db.query(DeepScanFinding).filter_by(key="processor")))

    def test_partial_vmware_values_keep_guest_fallback_for_each_missing_field(self):
        self.guest_report(self.now)
        self.vm.metadata_json = json.dumps({"cpu_count": 8, "memory_size_mib": None, "disks": []})
        self.db.commit()
        self.assert_api_summary("VMware: 8 vCPU · Deep Scan: 16 GiB RAM")
        fields = device_payload(self.device, get_config(self.db), self.db)["fields"]
        self.assertEqual(fields["C__CATG__CPU.cores"], 8)
        self.assertEqual(fields["C__CATG__MEMORY.title"][0]["capacity"], 16)
        self.assertEqual(fields["C__CATG__DRIVE.title"][0]["capacity"], 20)
        self.vm.metadata_json = json.dumps({"cpu_count": 0, "memory_size_mib": 4096})
        self.db.commit()
        self.assert_api_summary("VMware: 4 GiB RAM · Deep Scan: Guest CPU model")
        self.assertEqual(device_payload(self.device, get_config(self.db), self.db)["fields"]["C__CATG__CPU.cores"], 2)

    def test_stale_disabled_ambiguous_or_hidden_vmware_never_overrides(self):
        self.guest_report(self.now)
        for state in ("stale", "disabled", "ambiguous", "hidden"):
            with self.subTest(state=state):
                self.vm.match_status = "stale" if state == "stale" else "existing"
                self.connection.enabled = state != "disabled"
                self.connection.visible_fields_json = "[]" if state == "hidden" else None
                other = None
                if state == "ambiguous":
                    other = VsphereInventoryObject(connection_id=1, device_id=self.device.id, kind="vm",
                                                   external_id="vm-2", name="conflict", match_status="existing",
                                                   metadata_json=self.vm.metadata_json)
                    self.db.add(other)
                self.db.commit()
                self.assert_api_summary("Guest CPU model · 16 GiB RAM")
                fields = device_payload(self.device, get_config(self.db), self.db)["fields"]
                self.assertEqual(fields["C__CATG__CPU.cores"], 2)
                self.assertEqual(fields["C__CATG__MEMORY.title"][0]["capacity"], 16)
                if other:
                    self.db.delete(other)
                    self.db.commit()

    def test_malformed_or_partial_disk_snapshot_cannot_replace_guest_disks(self):
        self.guest_report(self.now)
        for data in ({"cpu_count": True, "memory_size_mib": -1},
                     {"disks": [{"disk_id": "2000", "capacity_bytes": 40 * 1024 ** 3}, {"disk_id": "2001"}]},
                     {"disks": [{"disk_id": "2000", "capacity_bytes": 40}, {"disk_id": "2000", "capacity_bytes": 80}]},
                     []):
            with self.subTest(data=data):
                self.vm.metadata_json = json.dumps(data)
                self.db.commit()
                self.assertEqual(vmware_hardware_inventory(self.db, [self.device.id])[1], {})
                self.assert_api_summary("Guest CPU model · 16 GiB RAM")
                fields = device_payload(self.device, get_config(self.db), self.db)["fields"]
                self.assertEqual(fields["C__CATG__DRIVE.title"][0]["capacity"], 20)

    def test_failed_guest_run_does_not_supply_effective_hardware(self):
        self.guest_report(self.now, status="error")
        self.assertEqual(latest_hardware_by_device(self.db, [self.device.id]), {})
        self.assertEqual(vmware_dashboard_inventory(self.db, [self.device.id])[1], {self.device.id: "VMware: 4 vCPU · 8 GiB RAM"})

    def test_linux_memory_can_fill_missing_vmware_field_without_overriding_cpu(self):
        run = DeepScanRun(device_id=self.device.id, profile="linux_full", status="done")
        self.db.add(run)
        self.db.flush()
        for key, value in (("cpu", "CPU(s): 2\nModel name: Guest processor\n"), ("memory", "Mem: 16Gi 2Gi 14Gi")):
            self.db.add(DeepScanFinding(device_id=self.device.id, run_id=run.id, finding_type="hardware",
                                        key=key, value_json=json.dumps(value), source="lscpu" if key == "cpu" else "free"))
        self.vm.metadata_json = json.dumps({"cpu_count": 6})
        self.db.commit()
        self.assert_api_summary("VMware: 6 vCPU · Deep Scan: 16 GB RAM")

    def test_device_api_keeps_advanced_view_gating(self):
        self.guest_report(self.now)
        self.db.query(Setting).filter_by(key="advanced_view_enabled").one().value = "false"
        self.db.commit()
        self.assert_api_summary("Guest CPU model · 16 GiB RAM")
        self.assertEqual(get_device(self.device.id, db=self.db, current_user=self.user).vsphere_inventory, [])

    def test_identical_vmware_exports_reuse_rows_and_preserve_legacy_guest_entries(self):
        self.guest_report(self.now)

        class Client(IdoitClient):
            def __init__(self, config):
                super().__init__(config)
                self.rows = {
                    "C__CATG__MEMORY": [{"id": "1", "status": "2", "title": "DIMM 1 [LanLens memory: DIMM 1]",
                                        "capacity": 16, "unit": 3, "quantity": 1}],
                    "C__CATG__DRIVE": [{"id": "1", "status": "2", "title": "Guest disk [LanLens disk: Disk 0]",
                                       "capacity": 20, "unit": 3, "serial": "GUEST-1"}],
                }
                self.writes = []

            async def read_category(self, object_id, category):
                return [dict(row) for row in self.rows.setdefault(category, [])]

            async def save_category(self, object_id, category, data, entry_id=None):
                self.writes.append((category, entry_id, dict(data)))
                rows = self.rows[category]
                if entry_id:
                    row = next(row for row in rows if row["id"] == str(entry_id))
                    row.update(data)
                else:
                    row = {"id": str(len(rows) + 1), "status": "2", **data}
                    rows.append(row)
                return {"success": True, "entry": int(row["id"])}

        config = get_config(self.db)
        client = Client(config)
        original_rows = {category: dict(rows[0]) for category, rows in client.rows.items()}

        async def reconcile_twice():
            for expected in ("created", "unchanged"):
                # Regenerate the payload from the persisted source observations,
                # rather than reusing a prebuilt category fixture.
                fields = device_payload(self.device, config, self.db)["fields"]
                cpu = {key.removeprefix("C__CATG__CPU."): value for key, value in fields.items()
                       if key.startswith("C__CATG__CPU.")}
                desired = {"C__CATG__CPU": [cpu], "C__CATG__MEMORY": fields["C__CATG__MEMORY.title"],
                           "C__CATG__DRIVE": fields["C__CATG__DRIVE.title"]}
                client.writes.clear()
                client.category_snapshot = {}
                for category, entries in desired.items():
                    results = await client.reconcile_category("42", category, entries)
                    self.assertEqual([result["status"] for result in results], [expected] * len(entries))
                self.assertEqual(len(client.writes), 3 if expected == "created" else 0)
                self.assertEqual(len(client.rows["C__CATG__CPU"]), 1)
                for category, original in original_rows.items():
                    self.assertEqual(len(client.rows[category]), 2)
                    self.assertEqual(client.rows[category][0], original)

        asyncio.run(reconcile_twice())
