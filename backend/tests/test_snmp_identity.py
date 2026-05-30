from datetime import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-snmp-identity-tests-12345")

from backend.database import Base
from backend.models import Device, Setting, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch
from backend.routers.snmp import _build_switch_port_visualization, _require_snmp_enabled, delete_profile, delete_switch
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

    def _enable_advanced_view(self, db):
        db.add(Setting(key="advanced_view_enabled", value="true"))
        db.commit()

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

    def test_delete_profile_detaches_assigned_switches(self):
        db = self.Session()
        try:
            self._enable_advanced_view(db)
            profile = SnmpProfile(name="default", version="2c", community="public")
            switch = SnmpSwitch(name="core-switch", host="192.0.2.1", profile=profile)
            db.add_all([profile, switch])
            db.commit()
            db.refresh(profile)
            db.refresh(switch)

            result = delete_profile(profile.id, db, None)
            db.refresh(switch)

            self.assertTrue(result.success)
            self.assertIsNone(db.query(SnmpProfile).filter(SnmpProfile.id == profile.id).first())
            self.assertIsNone(switch.profile_id)
        finally:
            db.close()

    def test_delete_switch_removes_learned_snmp_data(self):
        db = self.Session()
        try:
            self._enable_advanced_view(db)
            switch = SnmpSwitch(name="core-switch", host="192.0.2.1")
            db.add(switch)
            db.commit()
            db.refresh(switch)

            db.add(SnmpInterface(
                switch_id=switch.id,
                if_index=1,
                name="Gi1/0/1",
                last_seen_at=datetime.utcnow(),
            ))
            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address="00:11:22:33:44:55",
                if_index=1,
                last_seen_at=datetime.utcnow(),
            ))
            db.commit()

            result = delete_switch(switch.id, db, None)

            self.assertTrue(result.success)
            self.assertIsNone(db.query(SnmpSwitch).filter(SnmpSwitch.id == switch.id).first())
            self.assertEqual(db.query(SnmpInterface).count(), 0)
            self.assertEqual(db.query(SnmpMacTableEntry).count(), 0)
        finally:
            db.close()

    def test_switch_port_visualization_requires_mac_table_and_links_devices(self):
        db = self.Session()
        try:
            switch_device = Device(
                mac_address="00:aa:bb:cc:dd:ee",
                ip_address="192.0.2.2",
                hostname="core-switch",
                is_registered=True,
            )
            client_device = Device(
                mac_address="00:11:22:33:44:55",
                ip_address="192.0.2.10",
                hostname="client-01",
                is_registered=True,
            )
            db.add_all([switch_device, client_device])
            db.commit()

            switch = SnmpSwitch(name="core-switch", host="192.0.2.2", device_id=switch_device.id)
            db.add(switch)
            db.commit()
            db.refresh(switch)

            db.add_all([
                SnmpInterface(
                    switch_id=switch.id,
                    if_index=1,
                    name="Gi1/0/1",
                    oper_status="up",
                    last_seen_at=datetime.utcnow(),
                ),
                SnmpInterface(
                    switch_id=switch.id,
                    if_index=2,
                    name="Gi1/0/2",
                    oper_status="down",
                    last_seen_at=datetime.utcnow(),
                ),
            ])
            db.commit()

            empty_result = _build_switch_port_visualization(db, switch)
            self.assertFalse(empty_result["has_visualization"])
            self.assertEqual(len(empty_result["ports"]), 2)

            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address=client_device.mac_address,
                if_index=1,
                vlan="20",
                last_seen_at=datetime.utcnow(),
            ))
            db.commit()

            result = _build_switch_port_visualization(db, switch)

            self.assertTrue(result["has_visualization"])
            self.assertEqual(len(result["ports"]), 2)
            self.assertTrue(result["ports"][0]["is_active"])
            self.assertFalse(result["ports"][1]["is_active"])
            self.assertEqual(result["ports"][0]["endpoints"][0]["device_id"], client_device.id)
            self.assertEqual(result["ports"][0]["endpoints"][0]["vlan"], "20")
        finally:
            db.close()

    def test_snmp_router_requires_advanced_view(self):
        db = self.Session()
        try:
            with self.assertRaises(Exception) as ctx:
                _require_snmp_enabled(db)

            self.assertEqual(ctx.exception.status_code, 403)

            self._enable_advanced_view(db)
            _require_snmp_enabled(db)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
