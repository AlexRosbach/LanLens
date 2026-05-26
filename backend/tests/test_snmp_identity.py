from datetime import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Device, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch
from backend.services.snmp import (
    _parse_bridge_port_map,
    _parse_mac_suffix,
    _parse_q_bridge_suffix,
    _format_snmp_error,
    _snmp_command,
    detect_vendor,
    identity_for_device,
)


class SnmpIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_parses_snmp_mac_suffix(self):
        self.assertEqual(_parse_mac_suffix("0.17.34.51.68.85"), "00:11:22:33:44:55")
        self.assertIsNone(_parse_mac_suffix("not.a.mac"))

    def test_parses_bridge_port_to_interface_index_map(self):
        self.assertEqual(
            _parse_bridge_port_map({"1": "INTEGER: 10001", "2": "INTEGER: 10002", "x": "INTEGER: 3"}),
            {1: 10001, 2: 10002},
        )

    def test_parses_q_bridge_vlan_mac_suffix(self):
        self.assertEqual(_parse_q_bridge_suffix("20.0.17.34.51.68.85"), ("20", "00:11:22:33:44:55"))
        self.assertEqual(_parse_q_bridge_suffix("x.0.17.34.51.68.85"), (None, "00:11:22:33:44:55"))
        self.assertEqual(_parse_q_bridge_suffix("short"), (None, None))

    def test_detects_supported_snmp_vendors(self):
        self.assertEqual(detect_vendor("Cisco IOS Software", "1.3.6.1.4.1.9.1.516").key, "cisco")
        self.assertEqual(detect_vendor("UniFi Switch", "1.3.6.1.4.1.41112.1.6").key, "unifi")
        self.assertEqual(detect_vendor("SFOS Sophos Firewall", "1.3.6.1.4.1.2604.5").key, "sophos")
        self.assertEqual(detect_vendor("Other", "1.3.6.1.4.1.999").key, "generic")

    def test_formats_snmp_timeout_with_actionable_hint(self):
        message = _format_snmp_error("192.0.2.1", 161, "Timeout: No Response from 192.0.2.1:161")

        self.assertIn("SNMP timeout", message)
        self.assertIn("UDP/161", message)
        self.assertIn("SNMPv3 credentials", message)

    def test_builds_snmp_v2c_command(self):
        profile = SnmpProfile(version="2c", community="public")

        self.assertEqual(
            _snmp_command(profile, "192.0.2.1", "1.3.6.1.2.1.1.5.0", 161),
            [
                "snmpwalk",
                "-On",
                "-t",
                "2",
                "-r",
                "1",
                "-v2c",
                "-c",
                "public",
                "192.0.2.1:161",
                "1.3.6.1.2.1.1.5.0",
            ],
        )

    def test_builds_snmp_v3_auth_priv_command(self):
        profile = SnmpProfile(
            version="3",
            username="lanlens",
            security_level="authPriv",
            auth_protocol="SHA",
            auth_password="authpass",
            privacy_protocol="AES",
            privacy_password="privpass",
        )

        self.assertEqual(
            _snmp_command(profile, "192.0.2.1", "1.3.6.1.2.1.1.5.0", 161),
            [
                "snmpwalk",
                "-On",
                "-t",
                "2",
                "-r",
                "1",
                "-v3",
                "-l",
                "authPriv",
                "-u",
                "lanlens",
                "-a",
                "SHA",
                "-A",
                "authpass",
                "-x",
                "AES",
                "-X",
                "privpass",
                "192.0.2.1:161",
                "1.3.6.1.2.1.1.5.0",
            ],
        )

    def test_identity_uses_latest_snmp_mac_entry(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
                is_registered=True,
            )
            switch = SnmpSwitch(name="core-switch", host="192.0.2.1")
            db.add_all([device, switch])
            db.commit()
            db.refresh(switch)

            db.add(SnmpInterface(
                switch_id=switch.id,
                if_index=12,
                name="Gi1/0/12",
                alias="desk-port",
                last_seen_at=datetime.utcnow(),
            ))
            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address="00:11:22:33:44:55",
                if_index=12,
                vlan="20",
                last_seen_at=datetime.utcnow(),
            ))
            db.commit()

            identity = identity_for_device(db, device)

            self.assertIsNotNone(identity)
            self.assertEqual(identity["switch_device_id"], switch.device_id)
            self.assertEqual(identity["switch_name"], "core-switch")
            self.assertEqual(identity["interface_name"], "Gi1/0/12")
            self.assertEqual(identity["vlan"], "20")
            self.assertEqual(identity["confidence"], "high")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
