import csv
import io
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Device, PassiveDiscoveryObservation, Service, SnmpInterface, SnmpMacTableEntry, SnmpSwitch
from backend.services.idoit import DEFAULT_MAPPING, device_payload, get_config, build_export_rows, rows_to_export_csv


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


if __name__ == "__main__":
    unittest.main()
