from datetime import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Device, SnmpInterface, SnmpMacTableEntry, SnmpSwitch
from backend.services.snmp import _parse_bridge_port_map, _parse_mac_suffix, identity_for_device


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
