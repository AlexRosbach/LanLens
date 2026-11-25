import csv
import io
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import DeepScanFinding, DeepScanRun, Device, IdoitDeviceSync, PassiveDiscoveryObservation, PortScan, Service, Setting, SnmpInterface, SnmpMacTableEntry, SnmpSwitch
from backend.services.idoit import DEFAULT_MAPPING, IdoitClient, IdoitConnectionError, _drive_entries, device_payload, get_config, build_export_rows, rows_to_export_csv, sync_device_to_idoit, update_config, _safe_log_details


class IdoitExportCsvTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_v13_default_named_mapping_preserves_operator_customizations(self):
        db = self.Session()
        try:
            mapping = {
                "name": "Default i-doit mapping",
                "version": 13,
                "objectType": "C__OBJTYPE__SERVER",
                "fields": {
                    "hostname": "C__CATG__GLOBAL.custom_hostname",
                    "os_info": "C__CATG__OPERATING_SYSTEM.description",
                },
            }
            db.add(Setting(key="idoit_mapping_json", value=json.dumps(mapping)))
            db.commit()

            config = get_config(db)

            self.assertEqual(config.mapping["version"], 14)
            self.assertEqual(config.mapping["objectType"], "C__OBJTYPE__SERVER")
            self.assertEqual(config.mapping["fields"]["hostname"], "C__CATG__GLOBAL.custom_hostname")
            self.assertEqual(config.mapping["fields"]["os_info"], "")
        finally:
            db.close()

    def test_rows_to_export_csv_skips_unchecked_rows(self):
        csv_body = rows_to_export_csv([
            {
                "include": True,
                "object_type": "C__OBJTYPE__CLIENT",
                "title": "included",
                "ip_address": "192.0.2.10",
                "mac_address": "00:11:22:33:44:55",
            },
            {
                "include": False,
                "object_type": "C__OBJTYPE__CLIENT",
                "title": "excluded",
                "ip_address": "192.0.2.20",
            },
        ])

        rows = list(csv.DictReader(io.StringIO(csv_body.lstrip("\ufeff")), delimiter=";"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Bezeichnung"], "included")
        self.assertEqual(rows[0]["IP-Adresse"], "192.0.2.10")
        self.assertIn("SNMP-Switch", rows[0])
        self.assertIn("TLS-Zertifikate", rows[0])
        self.assertIn("mDNS", rows[0])
        self.assertIn("UPnP/SSDP", rows[0])
        self.assertIn("Passive Discovery", rows[0])
        self.assertNotIn("SNMP-VLAN", rows[0])
        self.assertIn("Identity Confidence", rows[0])

    def test_cpu_description_is_readable_and_retains_structured_fields(self):
        from backend.services.idoit import _cpu_details
        details = _cpu_details(json.dumps({
            "Name": "Intel(R) Example CPU", "NumberOfCores": 4,
            "MaxClockSpeed": 3200, "NumberOfLogicalProcessors": 8,
        }))
        self.assertEqual(details["title"], "Intel(R) Example CPU")
        self.assertEqual(details["cores"], 4)
        self.assertEqual(details["frequency"], 3.2)
        self.assertEqual(details["frequency_unit"], 4)
        self.assertEqual(details["description"],
                         "Processor: Intel Example CPU\nCores: 4\nClock speed: 3.2 GHz\nLogical processors: 8")

    def test_cpu_linux_description_does_not_dump_lscpu_output(self):
        from backend.services.idoit import _cpu_details
        details = _cpu_details("Model name: AMD Example CPU\nCPU(s): 8\nCore(s) per socket: 4\nCPU max MHz: 3200\nFlags: avx")
        self.assertEqual(details["cores"], 4)
        self.assertEqual(details["frequency"], 3.2)
        self.assertEqual(details["description"], "Processor: AMD Example CPU\nCores: 4\nClock speed: 3.2 GHz")

    def test_drive_capacity_is_normalized_to_idoit_gigabytes(self):
        entries = _drive_entries([
            {"Model": "NVMe", "Size": "476.94 GB"},
            {"Model": "SATA", "Size": "102400 MB"},
            {"Model": "Archive", "Size": "2 TB"},
        ])

        self.assertEqual(entries, [
            {"title": "NVMe [LanLens disk: Observed 476.94 GB #1]", "capacity": 476.94, "unit": 3},
            {"title": "SATA [LanLens disk: Observed 100 GB #1]", "capacity": 100.0, "unit": 3},
            {"title": "Archive [LanLens disk: Observed 2048 GB #1]", "capacity": 2048.0, "unit": 3},
        ])

    def test_identical_disks_have_distinct_locators(self):
        entries = _drive_entries([
            {"Model": "Example Virtual Disk", "Size": "100 GB", "Index": 0, "SerialNumber": "0000"},
            {"Model": "Example Virtual Disk", "Size": "100 GB", "Index": 1, "SerialNumber": "0000"},
        ])
        self.assertEqual([row["title"] for row in entries], [
            "Example Virtual Disk [LanLens disk: Disk 0]",
            "Example Virtual Disk [LanLens disk: Disk 1]",
        ])
        self.assertTrue(all("serial" not in row for row in entries))
        legacy = _drive_entries([{"Model": "Example", "Size": "100 GB"}] * 2)
        self.assertNotEqual(legacy[0]["title"], legacy[1]["title"])
        linux = _drive_entries("NAME SIZE TYPE MODEL\nsda 100G disk Example\nsdb 100G disk Example\nsr0 1G rom CD")
        self.assertEqual(len(linux), 2)
        self.assertNotEqual(linux[0]["title"], linux[1]["title"])

    def test_build_export_rows_uses_bulk_snmp_identity(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
            )
            switch_device = Device(
                mac_address="00:aa:bb:cc:dd:ee",
                ip_address="192.0.2.1",
                hostname="switch-01",
            )
            db.add_all([device, switch_device])
            db.commit()
            db.refresh(device)
            db.refresh(switch_device)

            switch = SnmpSwitch(name="core-switch", host="192.0.2.1", device_id=switch_device.id)
            db.add(switch)
            db.commit()
            db.refresh(switch)

            db.add(SnmpInterface(
                switch_id=switch.id,
                if_index=12,
                name="Gi1/0/12",
            ))
            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address="00:11:22:33:44:55",
                if_index=12,
                vlan="20",
            ))
            db.commit()

            rows = build_export_rows(db, [device], get_config(db))

            self.assertEqual(rows[0]["snmp_switch"], "core-switch")
            self.assertEqual(rows[0]["snmp_port"], "Gi1/0/12")
            self.assertNotIn("snmp_vlan", rows[0])
        finally:
            db.close()

    def test_build_export_rows_normalizes_snmp_port_to_string(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
            )
            switch_device = Device(
                mac_address="00:aa:bb:cc:dd:ee",
                ip_address="192.0.2.1",
                hostname="switch-01",
            )
            db.add_all([device, switch_device])
            db.commit()
            db.refresh(device)
            db.refresh(switch_device)

            switch = SnmpSwitch(name="core-switch", host="192.0.2.1", device_id=switch_device.id)
            db.add(switch)
            db.commit()
            db.refresh(switch)

            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address="00:11:22:33:44:55",
                if_index=12,
                vlan=None,
            ))
            db.commit()

            rows = build_export_rows(db, [device], get_config(db))

            self.assertEqual(rows[0]["snmp_port"], "12")
            self.assertIsInstance(rows[0]["snmp_port"], str)
        finally:
            db.close()

    def test_build_export_rows_includes_tls_certificate_summary(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            db.add(Service(
                device_id=device.id,
                name="Admin UI",
                service_type="web",
                protocol="https",
                url="https://client-01.example.test",
                tls_checked_at=datetime.utcnow(),
                tls_status="expiring_soon",
                tls_expires_at=datetime(2026, 6, 15, 12, 0),
                tls_issuer="CN=Example CA",
                tls_subject="CN=client-01.example.test",
                tls_sans="client-01.example.test",
                tls_self_signed=False,
            ))
            db.commit()

            rows = build_export_rows(db, [device], get_config(db))

            self.assertIn("Admin UI", rows[0]["tls_certificates"])
            self.assertIn("expiring_soon", rows[0]["tls_certificates"])
            self.assertIn("CN=Example CA", rows[0]["tls_certificates"])
        finally:
            db.close()

    def test_build_export_rows_includes_passive_discovery_summaries(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            db.add_all([
                PassiveDiscoveryObservation(
                    protocol="mdns",
                    source_ip="192.0.2.10",
                    source_mac="00:11:22:33:44:55",
                    destination_ip="224.0.0.251",
                    service_name="client-01._workstation._tcp.local.",
                    service_type="_workstation._tcp.local.",
                    summary="mDNS _workstation._tcp.local.",
                    metadata_json='{"answer_count": 2}',
                ),
                PassiveDiscoveryObservation(
                    protocol="ssdp",
                    source_ip="192.0.2.10",
                    source_mac="00:11:22:33:44:55",
                    destination_ip="239.255.255.250",
                    service_name="uuid:device-1::upnp:rootdevice",
                    service_type="upnp:rootdevice",
                    summary="HTTP/1.1 200 OK upnp:rootdevice",
                    metadata_json='{"location": "http://192.0.2.10/device.xml"}',
                ),
            ])
            db.commit()

            rows = build_export_rows(db, [device], get_config(db))

            self.assertIn("_workstation._tcp.local.", rows[0]["mdns_discovery"])
            self.assertIn("upnp:rootdevice", rows[0]["upnp_discovery"])
            self.assertIn("mDNS", rows[0]["passive_discovery"])
            self.assertIn("SSDP", rows[0]["passive_discovery"])
        finally:
            db.close()

    def test_idoit_payload_allows_mapping_passive_discovery_fields(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            db.add(PassiveDiscoveryObservation(
                protocol="ssdp",
                source_ip="192.0.2.10",
                source_mac="00:11:22:33:44:55",
                destination_ip="239.255.255.250",
                service_name="uuid:device-1::upnp:rootdevice",
                service_type="upnp:rootdevice",
                summary="HTTP/1.1 200 OK upnp:rootdevice",
                metadata_json="{}",
            ))
            db.commit()

            config = get_config(db)
            config.mapping = {
                **DEFAULT_MAPPING,
                "fields": {
                    **DEFAULT_MAPPING["fields"],
                    "upnp_discovery": "C__CATG__GLOBAL.description",
                },
            }

            payload = device_payload(device, config, db)

            self.assertIn("upnp:rootdevice", payload["fields"]["C__CATG__GLOBAL.description"])
        finally:
            db.close()

    def test_default_idoit_payload_keeps_os_out_of_description_fields(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
                description="Runs the workshop dashboard",
                notes="Rack shelf 2, patch planned",
                os_info="Ubuntu 24.04 LTS",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            payload = device_payload(device, get_config(db), db)
            fields = payload["fields"]

            self.assertNotIn("C__CATG__OPERATING_SYSTEM.description", fields)
            self.assertEqual(payload["operatingSystem"]["title"], "Ubuntu 24.04 LTS")
            self.assertEqual(payload["operatingSystem"]["assigned_version"], "24.04")
            self.assertIn("Runs the workshop dashboard", fields["C__CATG__GLOBAL.description"])
            self.assertIn("Rack shelf 2, patch planned", fields["C__CATG__GLOBAL.description"])
            self.assertNotIn("Ubuntu 24.04 LTS", fields["C__CATG__GLOBAL.description"])
            self.assertEqual(DEFAULT_MAPPING["fields"]["notes"], "C__CATG__GLOBAL.description")
        finally:
            db.close()

    def test_operating_system_assignment_uses_documented_os_not_kernel_fallback(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:66",
                ip_address="192.0.2.66",
                kernel_version="6.8.12-4-pve",
            )
            db.add(device)
            db.commit()
            db.refresh(device)
            run = DeepScanRun(device_id=device.id, profile="os_services", status="done")
            db.add(run)
            db.commit()
            db.refresh(run)
            db.add(DeepScanFinding(
                device_id=device.id,
                run_id=run.id,
                finding_type="os",
                key="kernel",
                value_json=json.dumps("6.8.12-4-pve"),
            ))
            db.commit()

            self.assertNotIn("operatingSystem", device_payload(device, get_config(db), db))

            db.add(DeepScanFinding(
                device_id=device.id,
                run_id=run.id,
                finding_type="os",
                key="operating_system",
                value_json=json.dumps({"Caption": "Windows 11 Pro", "Version": "24H2"}),
            ))
            db.commit()

            assignment = device_payload(device, get_config(db), db)["operatingSystem"]
            self.assertEqual(assignment["title"], "Windows 11 Pro 24H2")
            self.assertEqual(assignment["description"], "Kernel: 6.8.12-4-pve")
        finally:
            db.close()

    def test_payload_extracts_installed_software_for_application_assignments(self):
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:77", hostname="software-host")
            db.add(device)
            db.commit()
            run = DeepScanRun(device_id=device.id, profile="windows_agent", status="done")
            db.add(run)
            db.commit()
            db.add(DeepScanFinding(
                device_id=device.id, run_id=run.id, finding_type="software", key="installed_software",
                value_json=json.dumps([
                    {"name": "Mozilla Firefox", "version": "132.0", "publisher": "Mozilla"},
                    {"name": "Mozilla Firefox", "version": "132.0", "publisher": "Mozilla"},
                    {"name": "7-Zip", "version": "24.09", "publisher": "Igor Pavlov"},
                ]),
            ))
            db.commit()

            self.assertEqual(device_payload(device, get_config(db), db)["applications"], [
                {"title": "Mozilla Firefox", "assigned_version": "132.0", "description": "Publisher: Mozilla"},
                {"title": "7-Zip", "assigned_version": "24.09", "description": "Publisher: Igor Pavlov"},
            ])
        finally:
            db.close()

    def test_payload_accepts_single_software_object_and_linux_package_rows(self):
        from backend.services.idoit import _software_assignments
        def extract(value):
            return _software_assignments({"software": {"installed_software": {"value": value}}})
        self.assertEqual(extract({"Name": "Example App", "Version": "1.2"}), [
            {"title": "Example App", "assigned_version": "1.2"},
        ])
        self.assertEqual(extract("example-package\t1.2\tamd64\nother-package\t2.0\tamd64"), [
            {"title": "example-package", "assigned_version": "1.2"},
            {"title": "other-package", "assigned_version": "2.0"},
        ])

    def test_default_idoit_payload_maps_new_inventory_to_standard_categories(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            db.add(PortScan(
                device_id=device.id,
                open_ports='[{"port": 443, "protocol": "tcp", "service": "https"}]',
                scanned_at=datetime.utcnow(),
            ))
            db.add(Service(
                device_id=device.id,
                name="Admin UI",
                service_type="web",
                protocol="https",
                port=443,
                url="https://client-01.example.test",
                tls_checked_at=datetime.utcnow(),
                tls_status="valid",
                tls_expires_at=datetime(2026, 7, 1, 12, 0),
                tls_issuer="CN=Example CA",
                tls_subject="CN=client-01.example.test",
            ))
            db.commit()

            payload = device_payload(device, get_config(db), db)
            fields = payload["fields"]

            connection_entries = fields["C__CATG__NET_CONNECTIONS_FOLDER"]
            certificate_entries = fields["C__CATG__CERTIFICATE"]
            self.assertTrue(any(
                entry["port_from"] == 443
                and entry["port_to"] == 443
                and entry["protocol"] == "TCP"
                and entry["protocol_layer_5"] == "HTTPS"
                for entry in connection_entries
            ))
            self.assertTrue(any(
                entry["port_from"] == 443
                and "Service: Admin UI" in entry["description"]
                for entry in connection_entries
            ))
            self.assertEqual(certificate_entries[0]["common_name"], "client-01.example.test")
            self.assertEqual(certificate_entries[0]["expire_date"], "2026-07-01")
            self.assertEqual(certificate_entries[0]["type"], "SSL/TLS")
            self.assertIn("Issuer: CN=Example CA", certificate_entries[0]["description"])
            self.assertNotIn("subject", certificate_entries[0])
            self.assertNotIn("valid_to", certificate_entries[0])
            self.assertNotIn("C__CATG__NET_CONNECTIONS_FOLDER.description", fields)
            self.assertNotIn("C__CATG__CERTIFICATE.description", fields)
            self.assertEqual(DEFAULT_MAPPING["fields"]["open_ports"], "C__CATG__NET_CONNECTIONS_FOLDER")
            self.assertEqual(DEFAULT_MAPPING["fields"]["services"], "C__CATG__NET_CONNECTIONS_FOLDER")
            self.assertEqual(DEFAULT_MAPPING["fields"]["tls_certificates"], "C__CATG__CERTIFICATE")
            self.assertEqual(DEFAULT_MAPPING["fields"]["containers"], "C__CATG__APPLICATION")
        finally:
            db.close()


class IdoitSyncMatchingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    async def test_match_only_links_existing_object_from_identity_match(self):
        db = self.Session()

        class FakeClient:
            def __init__(self, config):
                self.config = config

            async def login(self):
                return {"session-id": "test"}

            async def find_existing_object(self, payload):
                return {"object_id": "42", "confidence": 100, "matched_by": "mac_address"}

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client", "sysid": "SYS-42"}

            async def object_type_title(self, object_id):
                return "Client"

            async def update_object_title(self, object_id, title):
                return {"id": object_id, "title": title}

            async def save_category_best_effort(self, object_id, category, data):
                return {"status": "saved", "result": True}

            async def cleanup_lanlens_global_description(self, object_id):
                return None

            async def object_sysid(self, object_id):
                return "SYS-42"

        try:
            update_config(db, {
                "idoit_enabled": True,
                "idoit_base_url": "https://idoit.example.test",
                "idoit_api_key": "secret",
                "idoit_create_policy": "match_only",
            })
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
                is_registered=True,
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            with patch("backend.services.idoit.IdoitClient", FakeClient):
                result = await sync_device_to_idoit(db, device, mode="manual")

            self.assertEqual(result["status"], "synced")
            self.assertEqual(result["action"], "link_existing")
            self.assertEqual(result["idoit_object_id"], "42")
            self.assertEqual(device.idoit_sync.idoit_object_id, "42")
            self.assertEqual(device.idoit_sync.idoit_sysid, "SYS-42")
        finally:
            db.close()

    async def test_sync_links_real_operating_system_object(self):
        db = self.Session()
        saved_categories = []

        class FakeClient:
            def __init__(self, config):
                self.config = config

            async def login(self):
                return {"session-id": "test"}

            async def find_existing_object(self, payload):
                return {"object_id": "42", "confidence": 100, "matched_by": "mac_address"}

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client", "sysid": "SYS-42"}

            async def object_type_title(self, object_id):
                return "Client"

            async def update_object_title(self, object_id, title):
                return {"id": object_id, "title": title}

            async def resolve_operating_system(self, title, create_missing=False):
                self.assert_create_missing = create_missing
                return {"object_id": "99", "action": "matched", "title": title}

            async def save_category_best_effort(self, object_id, category, data):
                saved_categories.append((object_id, category, data))
                return {"status": "saved", "result": True}

            async def cleanup_lanlens_global_description(self, object_id):
                return None

            async def object_sysid(self, object_id):
                return "SYS-42"

        try:
            update_config(db, {
                "idoit_enabled": True,
                "idoit_base_url": "https://idoit.example.test",
                "idoit_api_key": "secret",
                "idoit_create_policy": "match_only",
            })
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
                os_info="Ubuntu 24.04 LTS",
                kernel_version="6.8.0-48-generic",
                is_registered=True,
            )
            db.add(device)
            db.commit()
            db.refresh(device)

            with patch("backend.services.idoit.IdoitClient", FakeClient):
                result = await sync_device_to_idoit(db, device, mode="manual")

            self.assertEqual(result["status"], "synced")
            operating_system_saves = [
                data for _object_id, category, data in saved_categories
                if category == "C__CATG__OPERATING_SYSTEM"
            ]
            self.assertEqual(operating_system_saves, [{
                "application": 99,
                "assigned_version": "24.04",
                "description": "Kernel: 6.8.0-48-generic",
            }])
        finally:
            db.close()

    async def test_sync_links_detected_software_to_existing_application_objects(self):
        db = self.Session()
        saved_categories = []

        class FakeClient:
            def __init__(self, config): pass
            async def login(self): return {"session-id": "test"}
            async def find_existing_object(self, payload): return {"object_id": "42", "confidence": 100, "matched_by": "mac_address"}
            async def read_object(self, object_id): return {"id": object_id, "type_title": "Client", "sysid": "SYS-42"}
            async def object_type_title(self, object_id): return "Client"
            async def update_object_title(self, object_id, title): return {"id": object_id}
            async def resolve_application(self, title, create_missing=False):
                if title == "Mozilla Firefox":
                    return {"object_id": "101", "action": "matched", "title": title}
                return {"object_id": None, "action": "match_required", "title": title}
            async def save_category_best_effort(self, object_id, category, data):
                saved_categories.append((category, data)); return {"status": "saved", "result": True}
            async def cleanup_lanlens_global_description(self, object_id): return None
            async def object_sysid(self, object_id): return "SYS-42"

        try:
            update_config(db, {"idoit_enabled": True, "idoit_base_url": "https://idoit.example.test", "idoit_api_key": "secret"})
            device = Device(mac_address="00:11:22:33:44:88", hostname="app-host", is_registered=True)
            db.add(device); db.commit()
            run = DeepScanRun(device_id=device.id, profile="windows_agent", status="done")
            db.add(run); db.commit()
            db.add(DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="software", key="installed_software", value_json=json.dumps([
                {"name": "Mozilla Firefox", "version": "132.0", "publisher": "Mozilla"},
                {"name": "7-Zip", "version": "24.09"},
            ])))
            db.commit()
            with patch("backend.services.idoit.IdoitClient", FakeClient):
                result = await sync_device_to_idoit(db, device, mode="manual")
            self.assertEqual(result["status"], "synced_with_warnings")
            applications = [data for category, data in saved_categories if category == "C__CATG__APPLICATION"]
            self.assertEqual(applications, [
                {"application": 101, "assigned_version": "132.0", "description": "Publisher: Mozilla"},
            ])
            self.assertEqual(len(result["warnings"]), 1)
            self.assertIn("1 installed application(s)", result["warnings"][0])
            self.assertIn("'7-Zip'", result["warnings"][0])
            self.assertNotIn("more", result["warnings"][0])
        finally:
            db.close()

    async def test_operating_system_resolution_uses_dedicated_object_type(self):
        calls = []

        class FakeSearchClient(IdoitClient):
            async def read_objects(self, params):
                calls.append(("search", params))
                return []

            async def create_object(self, title, object_type):
                calls.append(("create", title, object_type))
                return "99"

        client = FakeSearchClient(get_config(self.Session()))
        resolution = await client.resolve_operating_system("Ubuntu 24.04 LTS", create_missing=True)

        self.assertEqual(resolution["object_id"], "99")
        self.assertEqual(resolution["action"], "created")
        self.assertIn(("create", "Ubuntu 24.04 LTS", "C__OBJTYPE__OPERATING_SYSTEM"), calls)
        self.assertTrue(all(
            item[1].get("filter", {}).get("type") == "C__OBJTYPE__OPERATING_SYSTEM"
            or item[1].get("type") == "C__OBJTYPE__OPERATING_SYSTEM"
            for item in calls if item[0] == "search"
        ))

    async def test_operating_system_resolution_matches_unambiguous_normalized_title(self):
        class NormalizedSearchClient(IdoitClient):
            async def read_objects(self, params):
                return [{
                    "id": "99",
                    "title": "Ubuntu Linux 24.04 LTS",
                    "type_const": "C__OBJTYPE__OPERATING_SYSTEM",
                }]

        client = NormalizedSearchClient(get_config(self.Session()))
        resolution = await client.resolve_operating_system("Ubuntu 24.04.3 LTS")

        self.assertEqual(resolution, {
            "object_id": "99",
            "action": "matched_normalized",
            "title": "Ubuntu 24.04.3 LTS",
            "matched_title": "Ubuntu Linux 24.04 LTS",
        })

    async def test_operating_system_resolution_ignores_windows_wmi_build_suffix(self):
        class WindowsServerSearchClient(IdoitClient):
            async def read_objects(self, params):
                # Simulate the documented exact title filter and numeric type response.
                if params.get("filter", {}).get("title") != "Microsoft Windows Server 2022 Standard":
                    return []
                return [{
                    "id": "321",
                    "title": "Microsoft Windows Server 2022 Standard",
                    "type": "42",
                    "status": "2",
                }]

        client = WindowsServerSearchClient(get_config(self.Session()))
        resolution = await client.resolve_operating_system(
            "Microsoft Windows Server 2022 Standard 10.0.20348"
        )

        self.assertEqual(resolution, {
            "object_id": "321",
            "action": "matched_normalized",
            "title": "Microsoft Windows Server 2022 Standard 10.0.20348",
            "matched_title": "Microsoft Windows Server 2022 Standard",
        })

    async def test_application_lookup_uses_typed_title_and_rejects_ambiguity(self):
        class ApplicationSearchClient(IdoitClient):
            async def read_objects(self, params):
                self.assert_query = params
                return [
                    {"id": "101", "title": "Example Application", "type": "7", "status": "2"},
                    {"id": "102", "title": "Example Application", "type": "7", "status": "2"},
                    {"id": "103", "title": "Example Application", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"},
                ]
            async def create_object(self, title, object_type):
                raise AssertionError("ambiguous titles must not create another object")

        client = ApplicationSearchClient(get_config(self.Session()))
        result = await client.resolve_application("Example Application", create_missing=True)
        self.assertEqual(client.assert_query["filter"]["type"], "C__OBJTYPE__APPLICATION")
        self.assertEqual(client.assert_query["filter"]["title"], "Example Application")
        self.assertEqual(result["action"], "ambiguous_match")

    async def test_application_resolution_normalizes_display_suffixes(self):
        class SearchClient(IdoitClient):
            async def read_objects(self, params):
                self.last_query = params["filter"]
                catalog = {"Example Archive": "101", "Example Archive 2.0": "102",
                           "Example Suite 2024": "103", "Example Suite": "104"}
                return [{"id": oid, "title": name, "type_const": "C__OBJTYPE__APPLICATION"}
                        for name, oid in catalog.items()]

            async def create_object(self, title, object_type):
                raise AssertionError("existing product must be reused")

        client = SearchClient(get_config(self.Session()))
        for title in ("Example Archive 21.07 (x64)", "Example Archive (64-bit)", "Example Archive x64 21.07"):
            with self.subTest(title=title):
                self.assertEqual(await client.resolve_application(title, create_missing=True), {
                    "object_id": "101", "action": "matched_normalized", "title": title,
                    "matched_title": "Example Archive",
                })
                self.assertEqual(client.last_query["type"], "C__OBJTYPE__APPLICATION")
        exact = await client.resolve_application("Example Archive 2.0")
        self.assertEqual(exact["object_id"], "102")
        self.assertEqual(exact["action"], "matched")
        release = await client.resolve_application("Example Suite 2024 (x64)")
        self.assertEqual(release["object_id"], "103")
        for title in ("Example Suite 2025", "Example Suite Enterprise 2.0"):
            self.assertEqual((await client.resolve_application(title))["action"], "match_required")

    async def test_application_catalog_recovers_from_empty_title_filters(self):
        class CatalogClient(IdoitClient):
            catalog_calls = 0

            async def read_objects(self, params):
                self.assert_type = params["filter"]["type"]
                if "title" in params["filter"]:
                    return []
                self.catalog_calls += 1
                return {"data": {
                    "101": {"id": "101", "title": "Example Archive", "type": "7", "status": "2"},
                    "102": {"id": "102", "title": "Example Editor", "type": "7", "status": "2"},
                    "103": {"id": "103", "title": "Example Archive", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"},
                }}

            async def create_object(self, title, object_type):
                raise AssertionError("catalog match must be reused")

        client = CatalogClient(get_config(self.Session()))
        result = await client.resolve_application("Example Archive 21.07 (x64)", create_missing=True)
        self.assertEqual(result["object_id"], "101")
        self.assertEqual(result["lookup"], "typed_catalog")
        self.assertEqual((await client.resolve_application("Example Editor 4.1"))["object_id"], "102")
        self.assertEqual(client.catalog_calls, 1)
        self.assertEqual(client.assert_type, "C__OBJTYPE__APPLICATION")

    async def test_application_catalog_retries_verified_numeric_type(self):
        class NumericTypeClient(IdoitClient):
            async def call(self, method, params=None):
                self.assert_method = method
                return [{"id": "73", "const": "C__OBJTYPE__APPLICATION", "objectcount": "1"}]

            async def read_objects(self, params):
                if params["filter"]["type"] == 73:
                    return [
                        {"id": "101", "title": "Example Archive", "type": "73", "status": "2"},
                        {"id": "102", "title": "Example Archive", "type": "74", "status": "2"},
                    ]
                return []

            async def create_object(self, title, object_type):
                raise AssertionError("existing application must be reused")

        client = NumericTypeClient(get_config(self.Session()))
        result = await client.resolve_application("Example Archive 21.07 (x64)", create_missing=True)
        self.assertEqual(result["object_id"], "101")
        self.assertEqual(client.assert_method, "cmdb.object_types")
        self.assertEqual(client.application_lookup_debug["object_type_id"], "73")
        self.assertEqual(client.application_lookup_debug["catalog_size"], 1)

    async def test_application_catalog_locally_filters_normal_status(self):
        class StatusFilterClient(IdoitClient):
            async def call(self, method, params=None):
                return [{"id": "73", "const": "C__OBJTYPE__APPLICATION", "objectcount": "2"}]

            async def read_objects(self, params):
                filters = params["filter"]
                if filters.get("type") == 73 and "status" not in filters:
                    return [
                        {"id": "101", "title": "Example Archive", "type": "73", "status": "2"},
                        {"id": "102", "title": "Example Archive", "type": "73", "status": "3"},
                    ]
                return []

        client = StatusFilterClient(get_config(self.Session()))
        result = await client.diagnose_application("Example Archive 2.0 (x64)")
        self.assertEqual(result["resolution"]["object_id"], "101")
        self.assertFalse(result["upstream_write_performed"])
        self.assertEqual(result["catalog"]["catalog_size"], 1)

    async def test_application_catalog_refuses_creation_when_type_count_disagrees(self):
        class EmptyCatalogClient(IdoitClient):
            async def call(self, method, params=None):
                return [{"id": "73", "const": "C__OBJTYPE__APPLICATION", "objectcount": "10"}]

            async def read_objects(self, params):
                return []

            async def create_object(self, title, object_type):
                raise AssertionError("inconsistent catalog cannot create")

        client = EmptyCatalogClient(get_config(self.Session()))
        result = await client.resolve_application("Example Missing", create_missing=True)
        self.assertEqual(result["action"], "lookup_incomplete")
        self.assertFalse(client.application_lookup_debug["complete"])

    async def test_application_catalog_refuses_incomplete_pagination(self):
        class CatalogClient(IdoitClient):
            async def read_objects(self, params):
                if "title" in params["filter"]:
                    return []
                return [{"id": str(i), "title": f"Application {i}", "type": "7"} for i in range(1, 501)]

            async def create_object(self, title, object_type):
                raise AssertionError("incomplete lookup cannot create")

        client = CatalogClient(get_config(self.Session()))
        result = await client.resolve_application("Example Missing", create_missing=True)
        self.assertEqual(result["action"], "lookup_incomplete")

    async def test_application_resolution_rejects_ambiguous_fallback(self):
        class SearchClient(IdoitClient):
            async def read_objects(self, params):
                if params["filter"]["title"] != "Example Editor":
                    return []
                return [
                    {"id": "101", "title": "Example Editor", "type": "7", "status": "2"},
                    {"id": "102", "title": "Example Editor", "type": "7", "status": "2"},
                    {"id": "103", "title": "Example Editor", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"},
                ]

            async def create_object(self, title, object_type):
                raise AssertionError("ambiguous matches must not create new objects")

        client = SearchClient(get_config(self.Session()))
        result = await client.resolve_application("Example Editor 4.1 (x86)", create_missing=True)
        self.assertEqual(result["action"], "ambiguous_match")
        self.assertIsNone(result["object_id"])
        self.assertEqual(result["title"], "Example Editor 4.1 (x86)")

    async def test_application_resolution_rejects_wrong_type_and_archived_fallback(self):
        class SearchClient(IdoitClient):
            async def read_objects(self, params):
                return [
                    {"id": "103", "title": "Example Editor", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"},
                    {"id": "104", "title": "Example Editor", "type_const": "C__OBJTYPE__APPLICATION", "status": "3"},
                    {"id": "105", "title": "Example Editor 5.0", "type_const": "C__OBJTYPE__APPLICATION"},
                ]

        client = SearchClient(get_config(self.Session()))
        result = await client.resolve_application("Example Editor 4.1 (x86)")
        self.assertEqual(result["action"], "match_required")
        self.assertIsNone(result["object_id"])

    async def test_application_resolution_does_not_create_after_failed_lookup(self):
        class SearchClient(IdoitClient):
            async def read_objects(self, params):
                if params["filter"]["title"] == "Example Editor":
                    raise IdoitConnectionError("temporary outage", stage="read_objects")
                return []

            async def create_object(self, title, object_type):
                raise AssertionError("failed lookup must not create another object")

        client = SearchClient(get_config(self.Session()))
        with self.assertRaises(IdoitConnectionError):
            await client.resolve_application("Example Editor 4.1 (x86)", create_missing=True)

    async def test_operating_system_resolution_rejects_mismatched_windows_server_edition(self):
        class EditionSearchClient(IdoitClient):
            async def read_objects(self, params):
                return [{"id": "100", "title": "Windows Server 2025 Datacenter", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"}]

        client = EditionSearchClient(get_config(self.Session()))
        result = await client.resolve_operating_system("Windows Server 2025 Standard 10.0.26100")
        self.assertEqual(result["action"], "match_required")
        self.assertIsNone(result["object_id"])

    async def test_operating_system_resolution_does_not_guess_between_normalized_titles(self):
        class AmbiguousSearchClient(IdoitClient):
            async def read_objects(self, params):
                return [
                    {"id": "99", "title": "Windows Server 2022 Standard", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"},
                    {"id": "100", "title": "Windows Server 2022 Datacenter", "type_const": "C__OBJTYPE__OPERATING_SYSTEM"},
                ]

            async def create_object(self, title, object_type):
                raise AssertionError("ambiguous existing OS titles must not create a new object")

        client = AmbiguousSearchClient(get_config(self.Session()))
        resolution = await client.resolve_operating_system("Microsoft Windows Server 2022", create_missing=True)

        self.assertEqual(resolution["action"], "ambiguous_match")
        self.assertIsNone(resolution["object_id"])

    async def test_operating_system_resolution_does_not_create_after_failed_lookups(self):
        class FailedLookupClient(IdoitClient):
            async def read_objects(self, params):
                raise IdoitConnectionError("temporary i-doit outage", stage="read_objects")

            async def create_object(self, title, object_type):
                raise AssertionError("must not create an OS when every existence check failed")

        client = FailedLookupClient(get_config(self.Session()))
        with self.assertRaises(IdoitConnectionError):
            await client.resolve_operating_system("Ubuntu 24.04 LTS", create_missing=True)

    async def test_match_only_uses_manual_idoit_sysid_before_other_identity(self):
        db = self.Session()

        class FakeClient:
            def __init__(self, config):
                self.config = config

            async def login(self):
                return {"session-id": "test"}

            async def find_existing_object(self, payload):
                self.payload = payload
                if payload["identity"].get("idoit_sysid") == "SYS-EXISTING-42":
                    return {"object_id": "42", "confidence": 100, "matched_by": "idoit_sysid"}
                return None

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client", "sysid": "SYS-EXISTING-42"}

            async def object_type_title(self, object_id):
                return "Client"

            async def update_object_title(self, object_id, title):
                return {"id": object_id, "title": title}

            async def save_category_best_effort(self, object_id, category, data):
                return {"status": "saved", "result": True}

            async def cleanup_lanlens_global_description(self, object_id):
                return None

            async def object_sysid(self, object_id):
                return "SYS-EXISTING-42"

        try:
            update_config(db, {
                "idoit_enabled": True,
                "idoit_base_url": "https://idoit.example.test",
                "idoit_api_key": "secret",
                "idoit_create_policy": "match_only",
            })
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
                is_registered=True,
            )
            db.add(device)
            db.commit()
            db.refresh(device)
            db.add(IdoitDeviceSync(device_id=device.id, idoit_sysid="SYS-EXISTING-42"))
            db.commit()

            with patch("backend.services.idoit.IdoitClient", FakeClient):
                result = await sync_device_to_idoit(db, device, mode="manual")

            self.assertEqual(result["status"], "synced")
            self.assertEqual(result["action"], "link_existing")
            self.assertEqual(result["idoit_object_id"], "42")
            self.assertEqual(result["idoit_sysid"], "SYS-EXISTING-42")
            self.assertEqual(device.idoit_sync.idoit_object_id, "42")
        finally:
            db.close()

    async def test_client_matches_existing_object_by_exact_sysid(self):
        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params.get("filter", {}).get("sysid") == "SYS-EXISTING-42":
                    return [{"id": "42", "title": "Existing Client"}]
                return []

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client", "sysid": "SYS-EXISTING-42"}

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": "wrong-local-title",
                "objectType": "C__OBJTYPE__CLIENT",
                "identity": {
                    "idoit_sysid": "SYS-EXISTING-42",
                    "mac_address": "00:11:22:33:44:55",
                    "hostname": "wrong-local-title",
                    "ip_address": "192.0.2.10",
                },
            })

            self.assertEqual(match["object_id"], "42")
            self.assertEqual(match["matched_by"], "idoit_sysid")
            self.assertEqual(match["confidence"], 100)
        finally:
            db.close()

    async def test_client_matches_manual_sysid_from_accounting_inventory(self):
        test_sysid = "SYSID_TEST_0001"
        test_cmdb_id = "DEV-0001"
        test_hostname = "asset-01.example.test"
        test_mac = "02:00:00:00:00:42"
        test_ip = "192.0.2.42"

        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params.get("q") == test_sysid:
                    return [{"id": "42", "title": test_hostname}]
                return []

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Virtual server"}

            async def read_category(self, object_id, category):
                if category == "C__CATG__ACCOUNTING":
                    return [{"inventory_no": f"{test_sysid}\n{test_cmdb_id}"}]
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": test_hostname,
                "objectType": "C__OBJTYPE__VIRTUAL_SERVER",
                "identity": {
                    "idoit_sysid": test_sysid,
                    "cmdb_id": test_cmdb_id,
                    "mac_address": test_mac,
                    "hostname": test_hostname,
                    "ip_address": test_ip,
                },
            })

            self.assertEqual(match["object_id"], "42")
            self.assertEqual(match["matched_by"], "idoit_sysid")
            self.assertEqual(match["confidence"], 100)
            self.assertEqual(client.last_identity_match_debug["result"], match)
        finally:
            db.close()

    async def test_client_fallback_scans_objects_when_sysid_filters_return_nothing(self):
        test_sysid = "SYSID_TEST_0002"
        test_hostname = "asset-02.example.test"

        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params in (
                    {"filter": {"type": "C__OBJTYPE__VIRTUAL_SERVER"}, "limit": 500, "offset": 0},
                    {"type": "C__OBJTYPE__VIRTUAL_SERVER", "limit": 500, "offset": 0},
                    {"limit": 500, "offset": 0},
                ):
                    return [{"id": "84", "title": test_hostname}]
                return []

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Virtual server"}

            async def read_category(self, object_id, category):
                if category == "C__CATG__ACCOUNTING":
                    return [{"inventory_no": f"{test_sysid}\nDEV-0002"}]
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": test_hostname,
                "objectType": "C__OBJTYPE__VIRTUAL_SERVER",
                "identity": {
                    "idoit_sysid": test_sysid,
                    "hostname": test_hostname,
                },
            })

            self.assertEqual(match["object_id"], "84")
            self.assertEqual(match["matched_by"], "idoit_sysid")
            self.assertTrue(client.last_identity_match_debug["sysid_lookup"]["fallback_scan_performed"])
            self.assertEqual(client.last_identity_match_debug["sysid_lookup"]["result"]["matched_by"], "fallback_accounting_inventory_sysid")
        finally:
            db.close()

    async def test_client_fallback_scans_later_object_pages_for_sysid(self):
        test_sysid = "SYSID_1714817396"
        test_hostname = "asset-03.example.test"

        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params.get("q") == test_sysid or params.get("filter", {}).get("sysid") == test_sysid:
                    return []
                if params.get("limit") == 500 and params.get("offset") == 0:
                    return [{"id": str(index), "title": f"other-{index}"} for index in range(1, 501)]
                if params.get("limit") == 500 and params.get("offset") == 500:
                    return [{"id": "777", "title": test_hostname}]
                return []

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client"}

            async def read_category(self, object_id, category):
                if object_id == "777" and category == "C__CATG__ACCOUNTING":
                    return [{"inventory_no": test_sysid}]
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": test_hostname,
                "objectType": "C__OBJTYPE__CLIENT",
                "identity": {
                    "idoit_sysid": test_sysid,
                    "hostname": test_hostname,
                },
            })

            self.assertEqual(match["object_id"], "777")
            self.assertEqual(match["matched_by"], "idoit_sysid")
            self.assertTrue(client.last_identity_match_debug["sysid_lookup"]["fallback_scan_performed"])
        finally:
            db.close()

    async def test_client_fallback_uses_returned_page_size_for_sysid_offsets(self):
        test_sysid = "SYSID_1714817396"
        test_hostname = "asset-04.example.test"

        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params.get("q") == test_sysid or params.get("filter", {}).get("sysid") == test_sysid:
                    return []
                if params.get("limit") == 500 and params.get("offset") == 0:
                    return [{"id": str(index), "title": f"other-{index}"} for index in range(1, 101)]
                if params.get("limit") == 500 and params.get("offset") == 100:
                    return [{"id": "888", "title": test_hostname}]
                return []

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client"}

            async def read_category(self, object_id, category):
                if object_id == "888" and category == "C__CATG__ACCOUNTING":
                    return [{"inventory_no": test_sysid}]
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": test_hostname,
                "objectType": "C__OBJTYPE__CLIENT",
                "identity": {
                    "idoit_sysid": test_sysid,
                    "hostname": test_hostname,
                },
            })

            self.assertEqual(match["object_id"], "888")
            self.assertEqual(match["matched_by"], "idoit_sysid")
        finally:
            db.close()

    async def test_client_confirms_mac_identity_match_from_category(self):
        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                return [{"id": "42", "title": "Existing Client"}]

            async def read_category(self, object_id, category):
                if category == "C__CATG__NETWORK_PORT":
                    return [{"id": "5", "mac": "00:11:22:33:44:55"}]
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": "client-01",
                "objectType": "C__OBJTYPE__CLIENT",
                "identity": {
                    "mac_address": "00-11-22-33-44-55",
                    "hostname": "client-01",
                    "ip_address": "192.0.2.10",
                },
            })

            self.assertEqual(match["object_id"], "42")
            self.assertEqual(match["matched_by"], "mac_address")
            self.assertEqual(match["confidence"], 100)
        finally:
            db.close()

    async def test_client_fallback_scans_objects_for_mac_identity_when_search_misses_category(self):
        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params.get("q") or params.get("title") or params.get("filter", {}).get("title"):
                    return []
                if params in (
                    {"filter": {"type": "C__OBJTYPE__CLIENT"}, "limit": 500, "offset": 0},
                    {"type": "C__OBJTYPE__CLIENT", "limit": 500, "offset": 0},
                    {"limit": 500, "offset": 0},
                ):
                    return [{"id": "42", "title": "Inventory object"}]
                return []

            async def read_category(self, object_id, category):
                if category == "C__CATG__NETWORK_PORT":
                    return [{"id": "5", "mac": "00:11:22:33:44:55"}]
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": "client-01",
                "objectType": "C__OBJTYPE__CLIENT",
                "identity": {
                    "mac_address": "00-11-22-33-44-55",
                    "hostname": "client-01",
                    "ip_address": "192.0.2.10",
                },
            })

            self.assertEqual(match["object_id"], "42")
            self.assertEqual(match["matched_by"], "mac_address")
            self.assertEqual(match["confidence"], 100)
            fallback = client.last_identity_match_debug["fallback_identity_scan"]
            self.assertTrue(fallback["fallback_scan_performed"])
            self.assertEqual(fallback["result"], match)
        finally:
            db.close()

    async def test_sysid_lookup_records_direct_attempt_debug(self):
        class FakeSearchClient(IdoitClient):
            async def call(self, method, params=None):
                return None

            async def read_objects(self, params):
                if params.get("filter", {}).get("sysid") == "SYSID_MISSING_DEBUG":
                    return [{"id": "42", "title": "Wrong SYSID object", "sysid": "SYSID_OTHER"}]
                return []

            async def read_object(self, object_id):
                return {"id": object_id, "type_title": "Client", "sysid": "SYSID_OTHER"}

            async def read_category(self, object_id, category):
                return []

        db = self.Session()
        try:
            cfg = get_config(db)
            client = FakeSearchClient(cfg)
            match = await client.find_existing_object({
                "title": "client-01",
                "objectType": "C__OBJTYPE__CLIENT",
                "identity": {
                    "idoit_sysid": "SYSID_MISSING_DEBUG",
                    "hostname": "client-01",
                },
            })

            self.assertIsNone(match)
            lookup = client.last_identity_match_debug["sysid_lookup"]
            self.assertGreaterEqual(lookup["direct_candidate_count"], 1)
            first_candidate = next(
                candidate
                for attempt in lookup["attempts"]
                for candidate in attempt["candidates"]
                if candidate["object_id"] == "42"
            )
            self.assertEqual(first_candidate["entry_sysid"], "SYSID_OTHER")
            self.assertEqual(first_candidate["object_sysid"], "SYSID_OTHER")
            self.assertEqual(first_candidate["rejected_reason"], "no exact SYSID match on object entry, object read, or mapped identity categories")
        finally:
            db.close()

    async def test_client_logout_releases_session_and_is_best_effort(self):
        calls = []

        class RecordingClient(IdoitClient):
            async def call(self, method, params=None):
                calls.append((method, params))
                if method == "idoit.logout":
                    return {"success": True}
                return None

        client = RecordingClient(get_config(self.Session()))
        client._session_id = "session-that-may-hold-an-object-lock"

        await client.logout_best_effort()

        self.assertEqual(calls, [("idoit.logout", None)])
        self.assertIsNone(client._session_id)

        class FailingLogoutClient(RecordingClient):
            async def call(self, method, params=None):
                raise IdoitConnectionError("logout failed", stage="jsonrpc_error")

        failing = FailingLogoutClient(get_config(self.Session()))
        failing._session_id = "stale-session"
        await failing.logout_best_effort()
        self.assertIsNone(failing._session_id)

    async def test_category_fallback_preserves_title_and_returns_warning_on_rejection(self):
        attempts = []

        class RejectingClient(IdoitClient):
            async def find_reusable_category_entry(self, object_id, category, data):
                return "7"

            async def save_category(self, object_id, category, data, entry_id=None):
                attempts.append(dict(data))
                raise IdoitConnectionError(
                    "There was a validation error: title(int): Mandatory field is empty.",
                    stage="jsonrpc_error",
                )

        client = RejectingClient(get_config(self.Session()))
        result = await client.save_category_best_effort(
            "42",
            "C__CATG__MODEL",
            {"title": "Demo model", "manufacturer": "Demo vendor"},
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(attempts[0], {"title": "Demo model", "manufacturer": "Demo vendor"})
        self.assertEqual(attempts[1], {"title": "Demo model"})
        self.assertEqual(attempts[2], {"manufacturer": "Demo vendor", "title": "Demo model"})

    async def test_cpu_reuses_legacy_description_entry(self):
        class CpuClient(IdoitClient):
            async def read_category(self, object_id, category):
                return [{"id": "17", "title": "Old title", "description": json.dumps({
                    "Name": "Example CPU", "NumberOfCores": 4, "MaxClockSpeed": 3200,
                })}, {"id": "18", "title": "Other CPU"}]

        client = CpuClient(get_config(self.Session()))
        self.assertEqual(await client.find_reusable_category_entry(
            "42", "C__CATG__CPU", {"title": "Example CPU", "description": "Processor: Example CPU"}
        ), "17")

    async def test_cpu_description_rejection_is_not_silenced(self):
        class CpuClient(IdoitClient):
            async def find_reusable_category_entry(self, object_id, category, data):
                return "17"

            async def save_category(self, object_id, category, data, entry_id=None):
                if "description" in data:
                    raise IdoitConnectionError("description rejected", stage="jsonrpc_error")
                return {"success": True, "entry": 17}

        client = CpuClient(get_config(self.Session()))
        result = await client.save_category_best_effort("42", "C__CATG__CPU",
            {"title": "Example CPU", "description": "Processor: Example CPU"})
        self.assertEqual(result["status"], "partial")
        self.assertIn("description", result["failed_fields"])

    async def test_idoit_rejects_http_before_sending_credentials(self):
        from dataclasses import replace
        from backend.services.idoit import validate_idoit_https_url
        validate_idoit_https_url("https://example.test/idoit/src/jsonrpc.php")
        validate_idoit_https_url("http://example.test/idoit/src/jsonrpc.php", allow_insecure_http=True)
        with self.assertRaises(ValueError):
            validate_idoit_https_url("http://user:password@example.test", allow_insecure_http=True)
        for url in ("http://example.test", "https://user:password@example.test", "https://example.test/?key=x"):
            with self.assertRaises(ValueError):
                validate_idoit_https_url(url)
        cfg = replace(get_config(self.Session()), base_url="http://example.test", api_key="test")
        client = IdoitClient(cfg)
        with self.assertRaises(IdoitConnectionError) as error:
            await client.call("idoit.login")
        self.assertEqual(error.exception.stage, "url_validation")
        db = self.Session()
        try:
            cfg = update_config(db, {"idoit_allow_insecure_http": True, "idoit_base_url": "http://example.test"})
            self.assertTrue(cfg.allow_insecure_http)
            self.assertTrue(get_config(db).allow_insecure_http)
        finally:
            db.close()

    async def test_idoit_tls_verification_is_explicit_and_scoped(self):
        import ssl
        from dataclasses import replace
        from unittest.mock import AsyncMock
        from backend.services.notification import PinnedHttpResponse, _pinned_tls_context

        db = self.Session()
        try:
            cfg = replace(get_config(db), base_url="https://example.test", api_key="test")
            self.assertFalse(cfg.skip_tls_verification)
            with patch("backend.services.idoit.request_json_via_validated_url", new_callable=AsyncMock) as request:
                request.return_value = PinnedHttpResponse(200, '{"result": {"ok": true}}')
                await IdoitClient(cfg).call("idoit.login")
                self.assertTrue(request.call_args.kwargs["verify_tls"])
                await IdoitClient(replace(cfg, skip_tls_verification=True)).call("idoit.login")
                self.assertFalse(request.call_args.kwargs["verify_tls"])
            update_config(db, {"idoit_skip_tls_verification": True})
            self.assertTrue(get_config(db).skip_tls_verification)
            update_config(db, {"idoit_skip_tls_verification": False})
            self.assertFalse(get_config(db).skip_tls_verification)
            default = _pinned_tls_context("https")
            insecure = _pinned_tls_context("https", verify_tls=False)
            self.assertTrue(default.check_hostname)
            self.assertEqual(default.verify_mode, ssl.CERT_REQUIRED)
            self.assertFalse(insecure.check_hostname)
            self.assertEqual(insecure.verify_mode, ssl.CERT_NONE)
            self.assertEqual(_pinned_tls_context("https").verify_mode, ssl.CERT_REQUIRED)
            self.assertIsNone(_pinned_tls_context("http"))
        finally:
            db.close()

    async def test_drive_sync_creates_distinct_entries_and_updates_only_matching_disk(self):
        class DriveClient(IdoitClient):
            def __init__(self, config):
                super().__init__(config)
                self.rows = [{"id": "90", "title": "Example Virtual Disk"}]
                self.writes = []

            async def read_category(self, object_id, category):
                return [dict(row) for row in self.rows]

            async def save_category(self, object_id, category, data, entry_id=None):
                self.writes.append(entry_id)
                if entry_id:
                    row = next(row for row in self.rows if row["id"] == entry_id)
                    row.update(data)
                else:
                    row = {"id": str(90 + len(self.rows)), **data}
                    self.rows.append(row)
                return {"success": True, "entry": row["id"]}

        client = DriveClient(get_config(self.Session()))
        disks = _drive_entries([
            {"Model": "Example Virtual Disk", "Size": "100 GB", "Index": 0},
            {"Model": "Example Virtual Disk", "Size": "200 GB", "Index": 1},
        ])
        for _ in range(2):
            for disk in disks:
                result = await client.save_category_best_effort("42", "C__CATG__DRIVE", disk)
                self.assertEqual(result["status"], "saved")
        self.assertEqual(client.writes, [None, None, "91", "92"])
        self.assertEqual(len(client.rows), 3)
        self.assertEqual(client.rows[0], {"id": "90", "title": "Example Virtual Disk"})
        self.assertEqual([row["capacity"] for row in client.rows[1:]], [100.0, 200.0])

    async def test_drive_conflicting_serial_does_not_overwrite_and_ambiguous_match_does_not_write(self):
        class DriveClient(IdoitClient):
            async def read_category(self, object_id, category):
                return self.rows

            async def save_category(self, *args, **kwargs):
                raise AssertionError("ambiguous or failed identity lookup must not write")

        client = DriveClient(get_config(self.Session()))
        title = "Example [LanLens disk: Disk 0]"
        client.rows = [{"id": "10", "title": title, "serial": "OLD"}]
        self.assertIsNone(await client.find_reusable_category_entry("42", "C__CATG__DRIVE",
                                                                    {"title": title, "serial": "NEW"}))
        client.rows = [{"id": "10", "title": title}, {"id": "11", "title": title}]
        result = await client.save_category_best_effort("42", "C__CATG__DRIVE", {"title": title})
        self.assertEqual(result["status"], "failed")

    async def test_drive_rejected_write_is_not_retried_as_partial_rows(self):
        class DriveClient(IdoitClient):
            calls = 0

            async def read_category(self, object_id, category):
                return []

            async def save_category(self, object_id, category, data, entry_id=None):
                self.calls += 1
                raise IdoitConnectionError("Drive write rejected", stage="jsonrpc_error")

        client = DriveClient(get_config(self.Session()))
        result = await client.save_category_best_effort("42", "C__CATG__DRIVE",
            {"title": "Example [LanLens disk: Disk 0]", "capacity": 100, "unit": 3})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(client.calls, 1)

    async def test_application_link_survives_invalid_version(self):
        class Client(IdoitClient):
            linked = False
            async def read_category(self, object_id, category):
                return [{"id": 17, "application": {"id": 101}}] if self.linked else []
            async def save_category(self, object_id, category, data, entry_id=None):
                if "assigned_version" in data:
                    raise IdoitConnectionError("invalid version", stage="jsonrpc_error")
                self.linked = True
                return {"success": True, "entry": 17}
        client = Client(get_config(self.Session()))
        result = await client.save_category_best_effort("42", "C__CATG__APPLICATION", {"application": 101, "assigned_version": "1.2"})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["entry_id"], "17")
        self.assertIn("assigned_version", result["failed_fields"])

    async def test_application_save_checks_readback(self):
        class ReadbackClient(IdoitClient):
            async def save_category(self, object_id, category, data, entry_id=None):
                return {"success": True, "entry": 17}

            async def read_category(self, object_id, category):
                return []

        client = ReadbackClient(get_config(self.Session()))
        result = await client.save_category_best_effort("42", "C__CATG__APPLICATION", {"application": 101})
        self.assertEqual(result["status"], "verification_failed")

    async def test_category_save_rejects_explicit_unsuccessful_result(self):
        class RejectingClient(IdoitClient):
            async def call(self, method, params=None):
                return {"success": False, "message": "rejected"}

        client = RejectingClient(get_config(self.Session()))
        with self.assertRaises(IdoitConnectionError):
            await client.save_category("42", "C__CATG__CPU", {"title": "Example CPU"}, "17")

    async def test_listener_reuse_requires_same_transport_and_complete_port_range(self):
        class ListenerClient(IdoitClient):
            async def read_category(self, object_id, category):
                return [
                    {
                        "id": "10",
                        "protocol": {"title": "TCP"},
                        "port_from": 80,
                        "port_to": 80,
                    },
                    {
                        "id": "11",
                        "protocol": {"title": "TCP"},
                        "port_from": 443,
                        "port_to": 443,
                    },
                ]

        client = ListenerClient(get_config(self.Session()))

        self.assertEqual(
            await client.find_reusable_category_entry(
                "42",
                "C__CATG__NET_CONNECTIONS_FOLDER",
                {"protocol": "TCP", "port_from": 443, "port_to": 443},
            ),
            "11",
        )
        self.assertIsNone(
            await client.find_reusable_category_entry(
                "42",
                "C__CATG__NET_CONNECTIONS_FOLDER",
                {"protocol": "TCP", "port_from": 22, "port_to": 22},
            )
        )

    async def test_operating_system_assignment_reuses_object_reference(self):
        class OperatingSystemClient(IdoitClient):
            async def read_category(self, object_id, category):
                return [{
                    "id": "17",
                    "application": {"id": "99", "title": "Ubuntu 24.04 LTS"},
                    "assigned_version": "24.04",
                }]

        client = OperatingSystemClient(get_config(self.Session()))

        self.assertEqual(
            await client.find_reusable_category_entry(
                "42",
                "C__CATG__OPERATING_SYSTEM",
                {"application": 99, "assigned_version": "24.04"},
            ),
            "17",
        )

    async def test_operating_system_category_read_failure_prevents_duplicate_assignment(self):
        class UnavailableOperatingSystemClient(IdoitClient):
            async def read_category(self, object_id, category):
                raise IdoitConnectionError("temporary i-doit outage", stage="read_category")

        client = UnavailableOperatingSystemClient(get_config(self.Session()))
        with self.assertRaises(IdoitConnectionError):
            await client.find_reusable_category_entry(
                "42",
                "C__CATG__OPERATING_SYSTEM",
                {"application": 99},
            )

    def test_oversized_sync_log_is_valid_json(self):
        raw = _safe_log_details({"warnings": ["x" * 10000], "identity_match": {"debug": "y" * 20000}})
        self.assertLessEqual(len(raw), 8000)
        self.assertTrue(json.loads(raw)["truncated"])

    def test_legacy_invalid_sync_log_does_not_break_reader(self):
        from backend.routers.idoit import _read_log_details
        self.assertTrue(_read_log_details('{"warnings": ["unfinished')["invalid_legacy_details"])
        self.assertEqual(_read_log_details('{"warnings": ["test"]}'), {"warnings": ["test"]})

    def test_truncated_sync_log_keeps_identity_match_debug(self):
        details = {
            "payload": {"title": "client-01", "fields": {f"field_{index}": "x" * 100 for index in range(120)}},
            "identity_match": {
                "identity": {"idoit_sysid": "SYSID_1714817396"},
                "sysid_lookup": {"attempts": [{"candidate_count": 0}], "result": None},
                "result": None,
            },
            "match_required": True,
            "create_policy": "match_only",
            "upstream_write_performed": False,
        }

        encoded = _safe_log_details(details)

        self.assertIn("identity_match", encoded)
        self.assertIn("SYSID_1714817396", encoded)
        self.assertIn("match_only", encoded)


if __name__ == "__main__":
    unittest.main()
