from datetime import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-snmp-identity-tests-12345")

from backend.database import Base
from backend.models import Device, Setting, SnmpCustomQuery, SnmpCustomResult, SnmpInterface, SnmpMacTableEntry, SnmpProfile, SnmpSwitch
from backend.routers.snmp import (
    SnmpSwitchPayload,
    _build_switch_port_visualization,
    _is_real_switch_port,
    _require_snmp_enabled,
    delete_profile,
    delete_switch,
    get_device_switch_ports,
    update_switch,
)
from backend.services.snmp import (
    OID_DOT1D_BASE_PORT_IF_INDEX,
    OID_DOT1D_TP_FDB_PORT,
    OID_DOT1Q_BASE_PORT_IF_INDEX,
    OID_DOT1Q_TP_FDB_PORT,
    OID_IF_ADMIN_STATUS,
    OID_IF_ALIAS,
    OID_IF_DESCR,
    OID_IF_NAME,
    OID_IF_OPER_STATUS,
    OID_IF_PHYS_ADDRESS,
    OID_IF_SPEED,
    OID_SYS_DESCR,
    OID_SYS_NAME,
    OID_SYS_OBJECT_ID,
    _parse_bridge_port_map,
    _parse_mac_suffix,
    _parse_q_bridge_suffix,
    _format_snmp_error,
    _snmp_command,
    bulk_identities_for_devices,
    detect_vendor,
    identity_for_device,
    poll_custom_queries,
    poll_switch,
)
from unittest.mock import patch


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

    def test_polls_custom_queries_for_matching_device_class(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="ip:printer-01",
                ip_address="192.0.2.50",
                hostname="printer-01",
                device_class="Printer",
            )
            profile = SnmpProfile(name="office", version="2c", community="public", port=161)
            switch = SnmpSwitch(name="printer-snmp", host="192.0.2.50", profile=profile, device=device)
            toner = SnmpCustomQuery(
                name="Printer toner",
                target_tag="printer",
                oid="1.3.6.1.2.1.43.11.1.1.9",
                query_type="table",
                value_type="integer",
            )
            ups = SnmpCustomQuery(
                name="UPS runtime",
                target_tag="ups",
                oid="1.3.6.1.2.1.33.1.2.3.0",
                query_type="scalar",
                value_type="integer",
            )
            db.add_all([device, profile, switch, toner, ups])
            db.commit()
            db.refresh(switch)

            def fake_walk(_profile, _host, oid, _port=161, _timeout=8):
                self.assertEqual(oid, "1.3.6.1.2.1.43.11.1.1.9")
                return {"1.1": "INTEGER: 71"}

            with patch("backend.services.snmp._snmpwalk", side_effect=fake_walk):
                result = poll_custom_queries(db, switch)

            self.assertEqual(result, {"matched": 1, "stored": 1, "failed": 0})
            row = db.query(SnmpCustomResult).one()
            self.assertEqual(row.query_id, toner.id)
            self.assertEqual(row.device_id, device.id)
            self.assertEqual(row.oid_suffix, "1.1")
            self.assertEqual(row.value, "71")
            self.assertEqual(row.numeric_value, 71)
        finally:
            db.close()
        self.assertEqual(detect_vendor("SFOS Sophos Firewall", "1.3.6.1.4.1.2604.5").key, "sophos")
        self.assertEqual(detect_vendor("Juniper Networks JUNOS", "1.3.6.1.4.1.2636.1.1").key, "juniper")
        self.assertEqual(detect_vendor("MikroTik RouterOS", "1.3.6.1.4.1.14988.1").key, "mikrotik")
        self.assertEqual(detect_vendor("Fortinet FortiGate", "1.3.6.1.4.1.12356.101").key, "fortinet")
        self.assertEqual(detect_vendor("Aruba CX Switch", "1.3.6.1.4.1.11.2.3.7.11").key, "aruba")
        self.assertEqual(detect_vendor("NETGEAR Smart Managed Switch", "1.3.6.1.4.1.4526.100").key, "netgear")
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

    def test_poll_switch_records_diagnostics_for_optional_mac_table_failures(self):
        db = self.Session()
        try:
            profile = SnmpProfile(name="core", version="2c", community="public", port=161)
            switch = SnmpSwitch(name="core-switch", host="192.0.2.1", profile=profile)
            db.add_all([profile, switch])
            db.commit()
            db.refresh(switch)

            def fake_walk(_profile, _host, oid, _port=161, _timeout=8):
                required = {
                    OID_SYS_DESCR: {"": "STRING: Cisco IOS"},
                    OID_SYS_OBJECT_ID: {"": "OID: 1.3.6.1.4.1.9.1.1"},
                    OID_SYS_NAME: {"": "STRING: core-sw-01"},
                    OID_IF_DESCR: {"1": "STRING: GigabitEthernet1"},
                    OID_IF_SPEED: {"1": "INTEGER: 1000000000"},
                    OID_IF_PHYS_ADDRESS: {"1": "STRING: 00 11 22 33 44 55"},
                    OID_IF_ADMIN_STATUS: {"1": "INTEGER: 1"},
                    OID_IF_OPER_STATUS: {"1": "INTEGER: 1"},
                    OID_IF_NAME: {"1": "STRING: Gi1/0/1"},
                    OID_IF_ALIAS: {"1": "STRING: uplink"},
                }
                if oid in required:
                    return required[oid]
                if oid in {
                    OID_DOT1D_BASE_PORT_IF_INDEX,
                    OID_DOT1Q_BASE_PORT_IF_INDEX,
                    OID_DOT1D_TP_FDB_PORT,
                    OID_DOT1Q_TP_FDB_PORT,
                }:
                    raise RuntimeError("No Such Object available on this agent")
                return {}

            with patch("backend.services.snmp._snmpwalk", side_effect=fake_walk):
                result = poll_switch(db, switch)

            self.assertEqual(result.interfaces, 1)
            self.assertEqual(result.mac_entries, 0)
            self.assertIn("SNMP poll target:", result.diagnostics)
            self.assertIn("OK: IF-MIB interface descriptions", result.diagnostics)
            self.assertIn("FAILED: BRIDGE-MIB MAC forwarding table", result.diagnostics)
            self.assertIsNone(switch.last_error)
            self.assertIn("FAILED: BRIDGE-MIB MAC forwarding table", switch.last_diagnostics)
        finally:
            db.close()

    def test_poll_switch_classifies_ip_scan_cisco_sg_target_as_switch_without_mac_table(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="ip:cisco-sg500x",
                ip_address="192.0.2.10",
                hostname="sg500x-01",
                device_class="Unknown",
                is_registered=True,
            )
            profile = SnmpProfile(name="core", version="2c", community="public", port=161)
            switch = SnmpSwitch(name="core-sg500x", host="192.0.2.10", profile=profile)
            db.add_all([device, profile, switch])
            db.commit()
            db.refresh(switch)

            def fake_walk(_profile, _host, oid, _port=161, _timeout=8):
                required = {
                    OID_SYS_DESCR: {"": "STRING: Cisco SG500X-24P 24-Port Gigabit Stackable Managed Switch"},
                    OID_SYS_OBJECT_ID: {"": "OID: 1.3.6.1.4.1.9.6.1.89.24"},
                    OID_SYS_NAME: {"": "STRING: core-sg500x"},
                    OID_IF_DESCR: {"1": "STRING: GigabitEthernet1/1/1"},
                    OID_IF_ADMIN_STATUS: {"1": "INTEGER: 1"},
                    OID_IF_OPER_STATUS: {"1": "INTEGER: 1"},
                    OID_IF_NAME: {"1": "STRING: gi1/1/1"},
                }
                if oid in required:
                    return required[oid]
                raise RuntimeError("No Such Object available on this agent")

            with patch("backend.services.snmp._snmpwalk", side_effect=fake_walk):
                result = poll_switch(db, switch)
            db.flush()
            db.refresh(device)
            db.refresh(switch)

            self.assertEqual(result.interfaces, 1)
            self.assertEqual(result.mac_entries, 0)
            self.assertEqual(device.device_class, "Switch")
            self.assertEqual(device.vendor, "Cisco")
            self.assertIsNone(switch.last_error)
            self.assertIn("FAILED: BRIDGE-MIB MAC forwarding table", switch.last_diagnostics)
        finally:
            db.close()

    def test_poll_switch_classifies_common_network_devices_from_standard_identity(self):
        scenarios = [
            ("juniper", "Juniper Networks EX4300 Ethernet Switch", "1.3.6.1.4.1.2636.1.1", "Switch", "Juniper"),
            ("mikrotik", "MikroTik RouterOS CCR2004", "1.3.6.1.4.1.14988.1", "Router", "MikroTik"),
            ("fortigate", "Fortinet FortiGate 100F Firewall", "1.3.6.1.4.1.12356.101", "Firewall", "Fortinet"),
            ("unifi-ap", "Ubiquiti UniFi AP U6-Pro", "1.3.6.1.4.1.41112.1.6", "AP", "UniFi / Ubiquiti"),
        ]
        for offset, (hostname, sys_descr, sys_object_id, expected_class, expected_vendor) in enumerate(scenarios, start=10):
            db = self.Session()
            try:
                device = Device(
                    mac_address=f"ip:{hostname}",
                    ip_address=f"192.0.2.{offset}",
                    hostname=hostname,
                    device_class="Unknown",
                    is_registered=True,
                )
                profile = SnmpProfile(name=f"profile-{hostname}", version="2c", community="public", port=161)
                target = SnmpSwitch(name=hostname, host=device.ip_address, profile=profile)
                db.add_all([device, profile, target])
                db.commit()
                db.refresh(target)

                def fake_walk(_profile, _host, oid, _port=161, _timeout=8):
                    required = {
                        OID_SYS_DESCR: {"": f"STRING: {sys_descr}"},
                        OID_SYS_OBJECT_ID: {"": f"OID: {sys_object_id}"},
                        OID_SYS_NAME: {"": f"STRING: {hostname}"},
                        OID_IF_DESCR: {"1": "STRING: ge-0/0/1"},
                        OID_IF_ADMIN_STATUS: {"1": "INTEGER: 1"},
                        OID_IF_OPER_STATUS: {"1": "INTEGER: 1"},
                        OID_IF_NAME: {"1": "STRING: ge-0/0/1"},
                    }
                    if oid in required:
                        return required[oid]
                    raise RuntimeError("No Such Object available on this agent")

                with patch("backend.services.snmp._snmpwalk", side_effect=fake_walk):
                    result = poll_switch(db, target)
                db.flush()
                db.refresh(device)

                self.assertEqual(result.interfaces, 1)
                self.assertEqual(device.device_class, expected_class)
                self.assertEqual(device.vendor, expected_vendor)
            finally:
                db.close()

    def test_poll_switch_required_failure_includes_troubleshooting_steps(self):
        db = self.Session()
        try:
            profile = SnmpProfile(name="core", version="2c", community="public", port=161)
            switch = SnmpSwitch(name="core-switch", host="192.0.2.1", profile=profile)
            db.add_all([profile, switch])
            db.commit()
            db.refresh(switch)

            with patch("backend.services.snmp._snmpwalk", side_effect=RuntimeError("SNMP timeout: no response")):
                with self.assertRaises(RuntimeError) as ctx:
                    poll_switch(db, switch)

            self.assertIn("did not return any system identity values", str(ctx.exception))
            self.assertIn("SNMP poll target:", str(ctx.exception))
            self.assertIn("FAILED: System description", str(ctx.exception))
        finally:
            db.close()

    def test_poll_switch_accepts_non_switch_snmp_target_without_if_mib(self):
        db = self.Session()
        try:
            profile = SnmpProfile(name="printer", version="2c", community="public", port=161)
            target = SnmpSwitch(name="office-printer", host="192.0.2.44", profile=profile)
            db.add_all([profile, target])
            db.commit()
            db.refresh(target)

            def fake_walk(_profile, _host, oid, _port=161, _timeout=8):
                if oid == OID_SYS_DESCR:
                    return {"": "Office Printer SNMP Agent"}
                if oid == OID_SYS_NAME:
                    return {"": "prn-01"}
                raise RuntimeError("No Such Object available on this agent")

            with patch("backend.services.snmp._snmpwalk", side_effect=fake_walk):
                result = poll_switch(db, target)

            self.assertEqual(result.interfaces, 0)
            self.assertEqual(result.mac_entries, 0)
            self.assertIn("OK: System description", result.diagnostics)
            self.assertIn("FAILED: IF-MIB interface descriptions", result.diagnostics)
            self.assertIsNone(target.last_error)
            self.assertEqual(target.sys_name, "prn-01")
        finally:
            db.close()

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

    def test_identity_uses_linked_snmp_target_without_mac_table(self):
        db = self.Session()
        try:
            last_poll = datetime.utcnow()
            device = Device(
                mac_address="ip:192.0.2.44",
                ip_address="192.0.2.44",
                hostname="printer-01",
                is_registered=True,
            )
            target = SnmpSwitch(
                name="office-printer",
                host="192.0.2.44",
                sys_name="prn-01",
                last_poll_at=last_poll,
            )
            db.add_all([device, target])
            db.commit()
            db.refresh(device)

            identity = identity_for_device(db, device)

            self.assertIsNotNone(identity)
            self.assertEqual(identity["switch_name"], "office-printer")
            self.assertEqual(identity["switch_host"], "192.0.2.44")
            self.assertEqual(identity["confidence"], "target")
            self.assertEqual(identity["last_seen_at"], last_poll.isoformat())
        finally:
            db.close()

    def test_bulk_identity_uses_linked_snmp_target_without_mac_table(self):
        db = self.Session()
        try:
            device = Device(
                mac_address="ip:192.0.2.45",
                ip_address="192.0.2.45",
                hostname="firewall-01",
                is_registered=True,
            )
            target = SnmpSwitch(name="edge-firewall", host="192.0.2.45", device=device)
            db.add_all([device, target])
            db.commit()
            db.refresh(device)

            identities = bulk_identities_for_devices(db, [device])

            self.assertEqual(identities[device.id]["switch_name"], "edge-firewall")
            self.assertEqual(identities[device.id]["switch_host"], "192.0.2.45")
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

    def test_update_switch_edits_identity_and_preserves_learned_data(self):
        db = self.Session()
        try:
            self._enable_advanced_view(db)
            profile = SnmpProfile(name="core", version="2c", community="public", port=161)
            next_profile = SnmpProfile(name="backup", version="2c", community="private", port=161)
            switch = SnmpSwitch(name="core-switch", host="192.0.2.1", profile=profile)
            db.add_all([profile, next_profile, switch])
            db.commit()
            db.refresh(switch)
            db.refresh(next_profile)

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

            response = update_switch(
                switch.id,
                SnmpSwitchPayload(
                    name="edge-switch",
                    host="192.0.2.50",
                    profile_id=next_profile.id,
                    enabled=False,
                ),
                db,
                None,
            )
            db.refresh(switch)

            self.assertEqual(response["name"], "edge-switch")
            self.assertEqual(response["host"], "192.0.2.50")
            self.assertEqual(response["profile_id"], next_profile.id)
            self.assertFalse(response["enabled"])
            self.assertEqual(response["interface_count"], 1)
            self.assertEqual(response["mac_count"], 1)
            self.assertEqual(switch.name, "edge-switch")
            self.assertEqual(switch.host, "192.0.2.50")
            self.assertEqual(switch.profile_id, next_profile.id)
            self.assertFalse(switch.enabled)
        finally:
            db.close()

    def test_switch_port_visualization_shows_interfaces_and_links_mac_table_devices(self):
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
            self.assertTrue(empty_result["has_visualization"])
            self.assertEqual(len(empty_result["ports"]), 2)

            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address=client_device.mac_address,
                if_index=1,
                last_seen_at=datetime.utcnow(),
            ))
            db.commit()

            interface_only_result = _build_switch_port_visualization(db, switch)
            self.assertTrue(interface_only_result["has_visualization"])

            db.add(SnmpMacTableEntry(
                switch_id=switch.id,
                mac_address=client_device.mac_address.upper(),
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

    def test_device_ports_find_snmp_target_by_device_ip(self):
        db = self.Session()
        try:
            self._enable_advanced_view(db)
            device = Device(
                mac_address="ip:192.0.2.60",
                ip_address="192.0.2.60",
                hostname="router-01",
                is_registered=True,
            )
            target = SnmpSwitch(name="edge-router", host="192.0.2.60")
            db.add_all([device, target])
            db.commit()
            db.refresh(device)
            db.refresh(target)
            db.add(SnmpInterface(
                switch_id=target.id,
                if_index=2,
                name="wan0",
                oper_status="up",
                last_seen_at=datetime.utcnow(),
            ))
            db.commit()

            result = get_device_switch_ports(device.id, db, None)

            self.assertEqual(result["switch"]["name"], "edge-router")
            self.assertEqual(result["ports"][0]["name"], "wan0")
            self.assertTrue(result["has_visualization"])
        finally:
            db.close()

    def test_switch_port_visualization_filters_virtual_ports_and_returns_stats(self):
        db = self.Session()
        try:
            switch = SnmpSwitch(name="core-switch", host="192.0.2.10")
            db.add(switch)
            db.commit()
            db.refresh(switch)
            db.add_all([
                SnmpInterface(
                    switch_id=switch.id,
                    if_index=1,
                    name="Loopback0",
                    if_type=24,
                    oper_status="up",
                    last_seen_at=datetime.utcnow(),
                ),
                SnmpInterface(
                    switch_id=switch.id,
                    if_index=2,
                    name="Vlan1",
                    if_type=135,
                    oper_status="up",
                    last_seen_at=datetime.utcnow(),
                ),
                SnmpInterface(
                    switch_id=switch.id,
                    if_index=3,
                    name="Gi1/0/1",
                    if_type=6,
                    oper_status="up",
                    speed_bps=1000000000,
                    in_unicast_packets=120,
                    in_non_unicast_packets=8,
                    out_unicast_packets=240,
                    out_non_unicast_packets=12,
                    crc_errors=2,
                    collision_errors=1,
                    fragment_errors=0,
                    last_seen_at=datetime.utcnow(),
                ),
            ])
            db.commit()

            result = _build_switch_port_visualization(db, switch)

            self.assertTrue(result["has_visualization"])
            self.assertEqual(len(result["ports"]), 1)
            self.assertEqual(result["ports"][0]["name"], "Gi1/0/1")
            self.assertEqual(result["ports"][0]["speed_bps"], 1000000000)
            self.assertEqual(result["ports"][0]["crc_errors"], 2)
            self.assertEqual(result["ports"][0]["collision_errors"], 1)
        finally:
            db.close()

    def test_real_port_detection_accepts_common_vendor_names_and_filters_virtual_interfaces(self):
        real_ports = [
            SnmpInterface(name="GigabitEthernet1/0/1", if_type=6),
            SnmpInterface(name="TenGigabitEthernet1/1", if_type=6),
            SnmpInterface(name="FastEthernet0/24", if_type=62),
            SnmpInterface(name="Ethernet1", if_type=6),
            SnmpInterface(name="ge-0/0/1", if_type=6),
            SnmpInterface(name="xe-1/0/48", if_type=6),
            SnmpInterface(name="ether1", if_type=6),
            SnmpInterface(name="port24", if_type=6),
            SnmpInterface(name="SFP1", if_type=6),
            SnmpInterface(name="wlan0", if_type=71),
            SnmpInterface(name="ppp0", if_type=23),
        ]
        virtual_ports = [
            SnmpInterface(name="Loopback0", if_type=24),
            SnmpInterface(name="Vlan100", if_type=135),
            SnmpInterface(name="ae1", if_type=161),
            SnmpInterface(name="Port-Channel10", if_type=161),
            SnmpInterface(name="br0", if_type=6),
            SnmpInterface(name="mgmt0", if_type=6),
            SnmpInterface(name="Tunnel0", if_type=131),
        ]

        for iface in real_ports:
            self.assertTrue(_is_real_switch_port(iface), iface.name)
        for iface in virtual_ports:
            self.assertFalse(_is_real_switch_port(iface), iface.name)

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
