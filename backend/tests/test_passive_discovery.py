import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-passive-discovery-12345")

import backend.services.passive_discovery as passive_discovery
from backend.database import Base
from backend.models import Device, DeviceChangeEvent, DeviceIpHistory, PassiveDiscoveryObservation
from backend.services.passive_discovery import apply_passive_device_class, capture_passive_discovery_report, deduplicate_observations, find_linked_device, infer_device_class_from_observation, observation_to_response, parse_control_plane_packet, parse_mdns_packet, parse_ssdp_packet, parse_ssdp_payload, upsert_passive_observation
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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

            def query(self, _model):
                class Query:
                    def filter(self, *_args):
                        return self

                    def order_by(self, *_args):
                        return self

                    def limit(self, *_args):
                        return self

                    def all(self):
                        return []

                return Query()

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
        self.assertEqual(report["observations_linked"], 0)
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

    def test_passive_discovery_infers_printer_from_mdns_service(self):
        observation = PassiveDiscoveryObservation(
            protocol="mdns",
            service_name="Office Printer._ipp._tcp.local",
            service_type="_ipp._tcp",
            summary="Office Printer._ipp._tcp.local",
            metadata_json='{"answers": [{"name": "_ipp._tcp.local"}]}',
        )

        inference = infer_device_class_from_observation(observation)

        self.assertEqual(inference["inferred_device_class"], "Printer")
        self.assertEqual(inference["inference_confidence"], "high")
        self.assertTrue(inference["inference_reasons"])

    def test_passive_discovery_infers_router_from_upnp_gateway(self):
        observation = parse_ssdp_payload("\r\n".join([
            "NOTIFY * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            "NT: urn:schemas-upnp-org:device:InternetGatewayDevice:1",
            "NTS: ssdp:alive",
            "",
            "",
        ]))

        self.assertIsNotNone(observation)
        inference = infer_device_class_from_observation(observation)

        self.assertEqual(inference["inferred_device_class"], "Router")
        self.assertEqual(inference["inference_confidence"], "high")

    def test_passive_discovery_applies_high_confidence_class_to_unknown_device(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.1", device_class="Unknown")
            db.add(device)
            db.commit()
            observation = parse_ssdp_payload(
                "\r\n".join([
                    "NOTIFY * HTTP/1.1",
                    "HOST: 239.255.255.250:1900",
                    "NT: urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                    "NTS: ssdp:alive",
                    "",
                    "",
                ]),
                source_ip="192.0.2.1",
            )

            self.assertTrue(apply_passive_device_class(db, device, observation))
            db.commit()

            self.assertEqual(device.device_class, "Router")
            event = db.query(DeviceChangeEvent).one()
            self.assertEqual(event.field_name, "device_class")
            self.assertEqual(event.old_value, "Unknown")
            self.assertEqual(event.new_value, "Router")
            self.assertEqual(event.source, "passive_discovery")
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_passive_discovery_does_not_replace_specific_class_with_medium_hint(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.20", device_class="Linux Server")
            db.add(device)
            db.commit()
            observation = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                service_name="_smb._tcp.local",
                service_type="_smb._tcp",
                summary="_smb._tcp.local",
            )

            self.assertFalse(apply_passive_device_class(db, device, observation))

            self.assertEqual(device.device_class, "Linux Server")
            self.assertEqual(db.query(DeviceChangeEvent).count(), 0)
        finally:
            db.close()
            Base.metadata.drop_all(engine)

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

    def test_observation_response_links_current_device_by_source_ip(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.20", hostname="plug.local")
            db.add(device)
            db.commit()
            observation = PassiveDiscoveryObservation(protocol="mdns", source_ip="192.0.2.20")

            response = observation_to_response(observation, db)

            self.assertEqual(response["linked_device_id"], device.id)
            self.assertEqual(response["linked_device_label"], "plug.local")
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_observation_matching_uses_ip_history_when_current_ip_changed(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.99")
            db.add(device)
            db.commit()
            db.add(DeviceIpHistory(device_id=device.id, ip_address="192.0.2.20"))
            db.commit()
            observation = PassiveDiscoveryObservation(protocol="mdns", source_ip="192.0.2.20")

            self.assertEqual(find_linked_device(db, observation).id, device.id)
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_passive_observation_upsert_updates_existing_last_seen(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            first = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                destination_ip="224.0.0.251",
                source_mac="AA:BB:CC:DD:EE:FF",
                service_name="_http._tcp.local",
                service_type="_http._tcp",
                summary="mDNS _http._tcp.local",
            )
            second = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                destination_ip="224.0.0.251",
                source_mac="AA:BB:CC:DD:EE:FF",
                service_name="_http._tcp.local",
                service_type="_http._tcp",
                summary="mDNS _http._tcp.local",
            )

            self.assertTrue(upsert_passive_observation(db, first))
            db.commit()
            self.assertFalse(upsert_passive_observation(db, second))
            db.commit()

            rows = db.query(PassiveDiscoveryObservation).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, first.id)
            self.assertEqual(rows[0].observed_at, second.observed_at)
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_deduplicate_observations_keeps_latest_row(self):
        older = PassiveDiscoveryObservation(
            id=1,
            protocol="ssdp",
            source_ip="192.0.2.30",
            destination_ip="239.255.255.250",
            service_type="upnp:rootdevice",
            summary="HTTP/1.1 200 OK upnp:rootdevice",
        )
        newer = PassiveDiscoveryObservation(
            id=2,
            protocol="ssdp",
            source_ip="192.0.2.30",
            destination_ip="239.255.255.250",
            service_type="upnp:rootdevice",
            summary="HTTP/1.1 200 OK upnp:rootdevice",
        )
        newer.observed_at = datetime.utcnow()
        older.observed_at = newer.observed_at - timedelta(days=1)

        rows = deduplicate_observations([older, newer], 20)

        self.assertEqual([row.id for row in rows], [2])

    def test_generic_multicast_deduplicates_source_port_churn(self):
        older = PassiveDiscoveryObservation(
            id=1,
            protocol="multicast",
            source_ip="192.0.2.40",
            source_mac="AA:BB:CC:DD:EE:FF",
            destination_ip="239.1.1.1",
            summary="IPv4 multicast packet",
            metadata_json='{"transport": "udp", "source_port": 42000, "destination_port": 9999}',
        )
        newer = PassiveDiscoveryObservation(
            id=2,
            protocol="multicast",
            source_ip="192.0.2.40",
            destination_ip="239.1.1.1",
            summary="IPv4 multicast packet",
            metadata_json='{"transport": "udp", "source_port": 43000, "destination_port": 9999}',
        )
        newer.observed_at = datetime.utcnow()
        older.observed_at = newer.observed_at - timedelta(minutes=5)

        rows = deduplicate_observations([older, newer], 20)

        self.assertEqual([row.id for row in rows], [2])

    def test_generic_multicast_upsert_updates_source_port_churn(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            first = PassiveDiscoveryObservation(
                protocol="multicast",
                source_ip="192.0.2.40",
                source_mac="AA:BB:CC:DD:EE:FF",
                destination_ip="239.1.1.1",
                summary="IPv4 multicast packet",
                metadata_json='{"transport": "udp", "source_port": 42000, "destination_port": 9999}',
            )
            second = PassiveDiscoveryObservation(
                protocol="multicast",
                source_ip="192.0.2.40",
                destination_ip="239.1.1.1",
                summary="IPv4 multicast packet",
                metadata_json='{"transport": "udp", "source_port": 43000, "destination_port": 9999}',
            )

            self.assertTrue(upsert_passive_observation(db, first))
            db.commit()
            self.assertFalse(upsert_passive_observation(db, second))
            db.commit()

            rows = db.query(PassiveDiscoveryObservation).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].observed_at, second.observed_at)
            self.assertIn("43000", rows[0].metadata_json)
        finally:
            db.close()
            Base.metadata.drop_all(engine)


if __name__ == "__main__":
    unittest.main()
