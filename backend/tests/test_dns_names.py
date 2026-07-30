import unittest
from unittest.mock import patch

import dns.zone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Device, DeviceDnsName, Setting
from backend.services.dns_names import (
    AxfrDnsConfig,
    device_display_name,
    fetch_axfr_dns_records,
    get_axfr_dns_config,
    record_dns_name,
    save_axfr_dns_config,
    synchronize_axfr_dns,
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
        first = record_dns_name(self.db, device, "Alias.Example.Test.", "CNAME", "dns_axfr", canonical_name="server.example.test")
        self.db.flush()
        second = record_dns_name(self.db, device, "alias.example.test", "CNAME", "dns_axfr", canonical_name="server.example.test")
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

    def test_config_has_separate_feature_and_axfr_switches(self):
        save_axfr_dns_config(
            self.db,
            AxfrDnsConfig(
                dns_names_enabled=True,
                enabled=False,
                server="dns01.example.test",
                zones=["example.test"],
                port=5353,
                interval_minutes=30,
            ),
        )
        self.db.commit()
        config = get_axfr_dns_config(self.db)
        self.assertTrue(config.dns_names_enabled)
        self.assertFalse(config.enabled)
        self.assertEqual(config.zones, ["example.test"])
        self.assertEqual(config.port, 5353)

    @patch("backend.services.dns_names.fetch_axfr_dns_records")
    def test_axfr_records_are_correlated_without_changing_primary_name(self, fetch_records):
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
        result = synchronize_axfr_dns(
            self.db,
            AxfrDnsConfig(dns_names_enabled=True, enabled=True, zones=["example.test"]),
        )
        self.assertEqual(result["names"], 2)
        self.assertEqual({row.name for row in device.dns_names}, {"server.example.test", "app.example.test"})
        self.assertEqual(device_display_name(device), "production-server")

    def test_disabled_axfr_sync_does_nothing(self):
        result = synchronize_axfr_dns(
            self.db,
            AxfrDnsConfig(dns_names_enabled=True, enabled=False),
        )
        self.assertEqual(result, {"records": 0, "names": 0, "devices": 0})

    def test_tsig_secret_is_encrypted_and_not_lost_when_loaded(self):
        save_axfr_dns_config(
            self.db,
            AxfrDnsConfig(
                dns_names_enabled=True,
                enabled=True,
                server="dns01.example.test",
                zones=["example.test"],
                tsig_key_name="lanlens-key",
                tsig_secret="dGVzdC1zZWNyZXQ=",
            ),
        )
        self.db.commit()
        config = get_axfr_dns_config(self.db)
        self.assertEqual(config.tsig_secret, "dGVzdC1zZWNyZXQ=")
        stored = self.db.query(Setting).filter(Setting.key == "axfr_dns_tsig_secret").one().value
        self.assertNotEqual(stored, config.tsig_secret)

    @patch("backend.services.dns_names._transfer_zone")
    def test_axfr_zone_is_parsed_without_windows_access(self, transfer_zone):
        transfer_zone.return_value = dns.zone.from_text(
            "@ 300 IN SOA ns1.example.test. hostmaster.example.test. 1 3600 600 86400 300\n"
            "@ 300 IN NS ns1.example.test.\n"
            "server 300 IN A 192.0.2.10\n"
            "portal 300 IN CNAME server.example.test.\n",
            origin="example.test.",
            relativize=False,
        )
        records = fetch_axfr_dns_records(
            AxfrDnsConfig(enabled=True, server="dns01.example.test", zones=["example.test"])
        )
        self.assertEqual(
            {(row["record_type"], row["name"]) for row in records},
            {("A", "server.example.test"), ("CNAME", "portal.example.test")},
        )
        transfer_zone.assert_called_once()


if __name__ == "__main__":
    unittest.main()
