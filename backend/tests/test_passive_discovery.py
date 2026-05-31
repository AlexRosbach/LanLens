import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-passive-discovery-12345")

import backend.services.passive_discovery as passive_discovery
from backend.services.passive_discovery import capture_passive_discovery_report, parse_control_plane_packet, parse_mdns_packet, parse_ssdp_packet, parse_ssdp_payload

try:
    from scapy.layers.dns import DNS, DNSQR, DNSRR
    from scapy.layers.inet import IP, UDP
    from scapy.layers.l2 import Ether
    from scapy.packet import Raw
except Exception:
    DNS = DNSQR = DNSRR = Ether = IP = Raw = UDP = None


class PassiveDiscoveryTests(unittest.TestCase):
    @unittest.skipIf(DNS is None, "scapy is not installed")
    def test_capture_report_counts_seen_parsed_stored_and_duplicates(self):
        packet = (
            Ether(src="AA:BB:CC:DD:EE:FF")
            / IP(src="192.0.2.20", dst="224.0.0.251")
            / UDP(sport=5353, dport=5353)
            / DNS(qdcount=1, qd=DNSQR(qname="_anker_power._udp.local.", qtype="PTR"))
        )

        class FakeSession:
            def __init__(self):
                self.rows = []

            def add(self, row):
                self.rows.append(row)

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        def fake_sniff(prn, **_kwargs):
            prn(packet)
            prn(packet)

        with patch.object(passive_discovery, "SessionLocal", FakeSession), patch("scapy.sendrecv.sniff", fake_sniff):
            report = capture_passive_discovery_report(3, 10, {"mdns"}, reserved=True)

        self.assertEqual(report["filter"], "udp port 5353")
        self.assertEqual(report["protocols"], ["mdns"])
        self.assertEqual(report["packets_seen"], 2)
        self.assertEqual(report["packets_parsed"], 2)
        self.assertEqual(report["observations_stored"], 1)
        self.assertEqual(report["duplicates_skipped"], 1)
        self.assertEqual(report["errors"], [])

    @unittest.skipIf(DNS is None, "scapy is not installed")
    def test_mdns_packet_extracts_service_metadata_and_addresses(self):
        packet = (
            Ether(src="AA:BB:CC:DD:EE:FF")
            / IP(src="192.0.2.20", dst="224.0.0.251")
            / UDP(sport=5353, dport=5353)
            / DNS(
                qdcount=1,
                ancount=1,
                qd=DNSQR(qname="_services._dns-sd._udp.local.", qtype="PTR"),
                an=DNSRR(rrname="_http._tcp.local.", type="PTR", rdata="printer._http._tcp.local."),
            )
        )

        observation = parse_mdns_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "mdns")
        self.assertEqual(observation.source_ip, "192.0.2.20")
        self.assertEqual(observation.destination_ip, "224.0.0.251")
        self.assertEqual(observation.source_mac, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(observation.service_name, "_http._tcp.local")
        self.assertEqual(observation.service_type, "_http._tcp")
        self.assertIn("_http._tcp.local", observation.summary)

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

    def test_upnp_m_search_payload_extracts_search_target(self):
        payload = "\r\n".join([
            "M-SEARCH * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            'MAN: "ssdp:discover"',
            "MX: 1",
            "ST: urn:schemas-upnp-org:device:MediaServer:1",
            "",
            "",
        ])

        observation = parse_ssdp_payload(payload, source_ip="192.0.2.30", destination_ip="239.255.255.250")

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "ssdp")
        self.assertEqual(observation.source_ip, "192.0.2.30")
        self.assertEqual(observation.destination_ip, "239.255.255.250")
        self.assertEqual(observation.service_type, "urn:schemas-upnp-org:device:MediaServer:1")
        self.assertEqual(observation.summary, "M-SEARCH urn:schemas-upnp-org:device:MediaServer:1")

    @unittest.skipIf(Raw is None, "scapy is not installed")
    def test_upnp_response_packet_extracts_addresses_and_usn(self):
        payload = "\r\n".join([
            "HTTP/1.1 200 OK",
            "CACHE-CONTROL: max-age=1800",
            "LOCATION: http://192.0.2.40:80/rootDesc.xml",
            "ST: upnp:rootdevice",
            "USN: uuid:device-1::upnp:rootdevice",
            "",
            "",
        ])
        packet = (
            Ether(src="00:11:22:33:44:55")
            / IP(src="192.0.2.40", dst="192.0.2.30")
            / UDP(sport=1900, dport=49152)
            / Raw(load=payload.encode("utf-8"))
        )

        observation = parse_ssdp_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "ssdp")
        self.assertEqual(observation.source_ip, "192.0.2.40")
        self.assertEqual(observation.destination_ip, "192.0.2.30")
        self.assertEqual(observation.source_mac, "00:11:22:33:44:55".upper())
        self.assertEqual(observation.service_name, "uuid:device-1::upnp:rootdevice")
        self.assertEqual(observation.service_type, "upnp:rootdevice")
        self.assertEqual(observation.summary, "HTTP/1.1 200 OK upnp:rootdevice")

    @unittest.skipIf(Raw is None, "scapy is not installed")
    def test_generic_multicast_packet_is_stored_with_group_and_ports(self):
        packet = (
            Ether(src="66:77:88:99:AA:BB")
            / IP(src="192.0.2.50", dst="239.192.0.1")
            / UDP(sport=5353, dport=5353)
            / Raw(load=b"opaque multicast payload")
        )

        observation = parse_control_plane_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "multicast")
        self.assertEqual(observation.source_ip, "192.0.2.50")
        self.assertEqual(observation.source_mac, "66:77:88:99:AA:BB")
        self.assertEqual(observation.destination_ip, "239.192.0.1")
        self.assertEqual(observation.summary, "IPv4 multicast packet")
        self.assertIn('"destination_port": 5353', observation.metadata_json)


if __name__ == "__main__":
    unittest.main()
