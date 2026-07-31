import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-routed-identity-12345")

from backend.database import Base
from backend.models import Device, ScanRun, Setting
from backend.services.scanner import DiscoveryResult, _nmap_ping_scan, run_scan


NMAP_SHARED_MAC_XML = """\
<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="10.10.50.60" addrtype="ipv4"/>
    <address addr="02:42:AC:11:00:02" addrtype="mac"/>
  </host>
  <host>
    <status state="up"/>
    <address addr="10.10.50.61" addrtype="ipv4"/>
    <address addr="02:42:AC:11:00:02" addrtype="mac"/>
  </host>
</nmaprun>
"""


class RoutedDeviceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_nmap_results_do_not_use_shared_mac_as_routed_identity(self):
        completed = Mock(returncode=0, stdout=NMAP_SHARED_MAC_XML, stderr="")
        with patch("backend.services.scanner.subprocess.run", return_value=completed):
            results = _nmap_ping_scan(["10.10.50.0/24"])

        self.assertEqual(
            results,
            [
                DiscoveryResult(ip="10.10.50.60"),
                DiscoveryResult(ip="10.10.50.61"),
            ],
        )

    def test_scan_keeps_routed_hosts_as_separate_inventory_entries(self):
        db = self.Session()
        db.add_all([
            Setting(key="scan_start", value="192.0.2.1"),
            Setting(key="scan_end", value="192.0.2.254"),
            Setting(key="scan_additional_targets", value="10.10.50.0/24"),
            Setting(key="notify_on_new_device", value="false"),
        ])
        db.commit()
        db.close()

        routed_results = [
            DiscoveryResult(ip="10.10.50.60"),
            DiscoveryResult(ip="10.10.50.61"),
            DiscoveryResult(ip="10.10.50.62"),
        ]
        hostnames = {
            "10.10.50.60": "iperf3",
            "10.10.50.61": "it-tools",
            "10.10.50.62": "vaultwarden",
        }

        with patch("backend.services.scanner.SessionLocal", self.Session), patch(
            "backend.services.scanner._arp_scan",
            return_value=[],
        ), patch(
            "backend.services.scanner._nmap_ping_scan",
            return_value=routed_results,
        ), patch(
            "backend.services.scanner._detect_local_host_result",
            return_value=None,
        ), patch(
            "backend.services.scanner._measure_scan_latencies",
            new=AsyncMock(return_value={}),
        ), patch(
            "backend.services.scanner._get_hostname",
            side_effect=lambda ip: hostnames[ip],
        ), patch(
            "backend.services.scanner._send_notification_deliveries",
            new=AsyncMock(),
        ):
            self.assertIsNotNone(asyncio.run(run_scan("test")))

        db = self.Session()
        try:
            scan_run = db.query(ScanRun).order_by(ScanRun.id.desc()).one()
            self.assertEqual(scan_run.status, "done")
            self.assertEqual(scan_run.devices_found, 3)
            self.assertEqual(scan_run.devices_new, 3)
            devices = db.query(Device).order_by(Device.ip_address).all()
            self.assertEqual(
                [(row.ip_address, row.hostname) for row in devices],
                [
                    ("10.10.50.60", "iperf3"),
                    ("10.10.50.61", "it-tools"),
                    ("10.10.50.62", "vaultwarden"),
                ],
            )
            self.assertEqual(len({row.mac_address for row in devices}), 3)
            self.assertTrue(all(row.mac_address.startswith("ip:") for row in devices))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
