import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Credential, Device, DeviceDnsName
from backend.services.dns_names import (
    MicrosoftDnsConfig,
    device_display_name,
    get_microsoft_dns_config,
    record_dns_name,
    save_microsoft_dns_config,
    synchronize_microsoft_dns,
)


class DnsNamesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_record_dns_name_updates_existing_observation(self):
        device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.10", hostname="server.example.test")
        self.db.add(device)
        self.db.flush()
        first = record_dns_name(self.db, device, "Alias.Example.Test.", "CNAME", "microsoft_dns", canonical_name="server.example.test")
        self.db.flush()
        second = record_dns_name(self.db, device, "alias.example.test", "CNAME", "microsoft_dns", canonical_name="server.example.test")
        self.db.flush()
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(DeviceDnsName).count(), 1)

    def test_preferred_name_wins_without_destroying_hostname(self):
        device = Device(
            mac_address="00:11:22:33:44:55",
            hostname="automatic.example.test",
            preferred_name="chosen.example.test",
            preferred_name_mode="manual",
        )
        self.assertEqual(device_display_name(device), "chosen.example.test")
        self.assertEqual(device.hostname, "automatic.example.test")

    def test_config_has_separate_feature_and_microsoft_dns_switches(self):
        save_microsoft_dns_config(
            self.db,
            MicrosoftDnsConfig(
                dns_names_enabled=True,
                enabled=False,
                server="dns01.example.test",
                zones=["example.test"],
                interval_minutes=30,
            ),
        )
        self.db.commit()
        config = get_microsoft_dns_config(self.db)
        self.assertTrue(config.dns_names_enabled)
        self.assertFalse(config.enabled)
        self.assertEqual(config.zones, ["example.test"])

    @patch("backend.services.dns_names.fetch_microsoft_dns_records")
    def test_microsoft_dns_records_are_correlated_without_changing_primary_name(self, fetch_records):
        fetch_records.return_value = [
            {
                "zone": "example.test",
                "host_name": "server",
                "record_type": "A",
                "address": "192.0.2.10",
                "canonical_name": None,
            },
            {
                "zone": "example.test",
                "host_name": "app",
                "record_type": "CNAME",
                "address": None,
                "canonical_name": "server.example.test.",
            },
        ]
        device = Device(
            mac_address="00:11:22:33:44:55",
            ip_address="192.0.2.10",
            hostname="server.example.test",
            preferred_name="production-server",
            preferred_name_mode="manual",
        )
        self.db.add(device)
        self.db.commit()
        result = synchronize_microsoft_dns(
            self.db,
            MicrosoftDnsConfig(dns_names_enabled=True, enabled=True, zones=["example.test"]),
        )
        self.assertEqual(result["names"], 2)
        self.assertEqual({row.name for row in device.dns_names}, {"server.example.test", "app.example.test"})
        self.assertEqual(device_display_name(device), "production-server")

    def test_disabled_microsoft_dns_sync_does_nothing(self):
        result = synchronize_microsoft_dns(
            self.db,
            MicrosoftDnsConfig(dns_names_enabled=True, enabled=False),
        )
        self.assertEqual(result, {"records": 0, "names": 0, "devices": 0})


if __name__ == "__main__":
    unittest.main()
