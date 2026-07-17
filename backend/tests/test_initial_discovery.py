import ipaddress
import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-initial-discovery-12345")

from backend.database import Base
from backend.models import Device, ScanRun, Setting
from backend.services.initial_discovery import (
    BOOTSTRAP_NETWORK_KEY,
    BOOTSTRAP_STATUS_KEY,
    prepare_initial_scan_bootstrap,
)
from backend.services.scanner import _is_ignored_detection_interface, _is_ignored_detection_network


class InitialDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def _settings(self, db):
        return {row.key: row.value for row in db.query(Setting).all()}

    def test_prepare_initial_scan_bootstrap_persists_detected_range(self):
        db = self.Session()
        try:
            with patch(
                "backend.services.initial_discovery._detect_host_network",
                return_value=ipaddress.IPv4Network("192.168.50.0/24"),
            ):
                self.assertTrue(prepare_initial_scan_bootstrap(db))

            settings = self._settings(db)
            self.assertEqual(settings["scan_start"], "192.168.50.1")
            self.assertEqual(settings["scan_end"], "192.168.50.254")
            self.assertEqual(settings[BOOTSTRAP_NETWORK_KEY], "192.168.50.0/24")
            self.assertEqual(settings[BOOTSTRAP_STATUS_KEY], "scheduled")
        finally:
            db.close()

    def test_prepare_initial_scan_bootstrap_keeps_existing_scan_range(self):
        db = self.Session()
        try:
            db.add_all([
                Setting(key="scan_start", value="10.20.30.1"),
                Setting(key="scan_end", value="10.20.30.254"),
            ])
            db.commit()

            with patch(
                "backend.services.initial_discovery._detect_host_network",
                return_value=ipaddress.IPv4Network("192.168.50.0/24"),
            ):
                self.assertFalse(prepare_initial_scan_bootstrap(db))

            settings = self._settings(db)
            self.assertEqual(settings["scan_start"], "10.20.30.1")
            self.assertEqual(settings["scan_end"], "10.20.30.254")
            self.assertNotIn(BOOTSTRAP_STATUS_KEY, settings)
        finally:
            db.close()

    def test_prepare_initial_scan_bootstrap_skips_non_empty_inventory(self):
        db = self.Session()
        try:
            db.add(Device(mac_address="00:11:22:33:44:55", ip_address="192.168.50.10"))
            db.commit()

            with patch(
                "backend.services.initial_discovery._detect_host_network",
                return_value=ipaddress.IPv4Network("192.168.50.0/24"),
            ):
                self.assertFalse(prepare_initial_scan_bootstrap(db))

            self.assertEqual(self._settings(db), {})
        finally:
            db.close()

    def test_prepare_initial_scan_bootstrap_skips_existing_scan_history(self):
        db = self.Session()
        try:
            db.add(ScanRun(scan_type="manual", status="done"))
            db.commit()

            with patch(
                "backend.services.initial_discovery._detect_host_network",
                return_value=ipaddress.IPv4Network("192.168.50.0/24"),
            ):
                self.assertFalse(prepare_initial_scan_bootstrap(db))

            self.assertEqual(self._settings(db), {})
        finally:
            db.close()

    def test_prepare_initial_scan_bootstrap_records_detection_failure_without_blocking(self):
        db = self.Session()
        try:
            with patch("backend.services.initial_discovery._detect_host_network", return_value=None):
                self.assertFalse(prepare_initial_scan_bootstrap(db))

            settings = self._settings(db)
            self.assertEqual(settings[BOOTSTRAP_STATUS_KEY], "detect_failed")
            self.assertNotIn("scan_start", settings)
            self.assertNotIn("scan_end", settings)
        finally:
            db.close()

    def test_detection_helpers_ignore_virtual_or_unusable_networks(self):
        self.assertTrue(_is_ignored_detection_interface("docker0"))
        self.assertTrue(_is_ignored_detection_interface("br-a1b2"))
        self.assertTrue(_is_ignored_detection_interface("br0"))
        self.assertTrue(_is_ignored_detection_interface("bridge0"))
        self.assertFalse(_is_ignored_detection_interface("eth0"))
        self.assertTrue(_is_ignored_detection_network(ipaddress.IPv4Network("169.254.10.0/24")))
        self.assertTrue(_is_ignored_detection_network(ipaddress.IPv4Network("0.0.0.0/0")))
        self.assertFalse(_is_ignored_detection_network(ipaddress.IPv4Network("192.168.50.0/24")))
