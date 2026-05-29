import csv
import io
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Device, Service, SnmpInterface, SnmpMacTableEntry, SnmpSwitch
from backend.services.idoit import get_config, build_export_rows, rows_to_export_csv


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


if __name__ == "__main__":
    unittest.main()
