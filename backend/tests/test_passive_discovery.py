import os
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-passive-discovery-12345")

from backend.services.passive_discovery import parse_ssdp_payload


class PassiveDiscoveryTests(unittest.TestCase):
    def test_ssdp_location_service_name_is_bounded_to_database_column(self):
        long_location = "http://192.0.2.10:1400/" + ("device-description/" * 20)
        payload = "\r\n".join([
            "NOTIFY * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            f"LOCATION: {long_location}",
            "NT: urn:schemas-upnp-org:device:MediaRenderer:1",
            "NTS: ssdp:alive",
            "",
            "",
        ])

        observation = parse_ssdp_payload(payload)

        self.assertIsNotNone(observation)
        self.assertEqual(len(observation.service_name), 255)
        self.assertEqual(observation.service_name, long_location[:255])


if __name__ == "__main__":
    unittest.main()
