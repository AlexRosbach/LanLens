import csv
import io
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Device, IdoitDeviceSync, PassiveDiscoveryObservation, PortScan, Service, SnmpInterface, SnmpMacTableEntry, SnmpSwitch
from backend.services.idoit import DEFAULT_MAPPING, IdoitClient, device_payload, get_config, build_export_rows, rows_to_export_csv, sync_device_to_idoit, update_config


class IdoitExportCsvTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

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

    def test_default_idoit_payload_maps_notes_and_os_to_standard_text_fields(self):
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

            self.assertEqual(fields["C__CATG__OPERATING_SYSTEM.description"], "Ubuntu 24.04 LTS")
            self.assertIn("Runs the workshop dashboard", fields["C__CATG__GLOBAL.description"])
            self.assertIn("Rack shelf 2, patch planned", fields["C__CATG__GLOBAL.description"])
            self.assertEqual(DEFAULT_MAPPING["fields"]["notes"], "C__CATG__GLOBAL.description")
        finally:
            db.close()

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
            self.assertTrue(any(entry["title"] == "443/tcp https" for entry in connection_entries))
            self.assertTrue(any(entry["title"] == "Admin UI" for entry in connection_entries))
            self.assertEqual(certificate_entries[0]["subject"], "CN=client-01.example.test")
            self.assertEqual(certificate_entries[0]["valid_to"], "2026-07-01T12:00:00")
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


if __name__ == "__main__":
    unittest.main()
