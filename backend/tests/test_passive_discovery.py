import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-passive-discovery-12345")

import backend.services.passive_discovery as passive_discovery
from backend.database import Base
from backend.models import Device, DeviceChangeEvent, DeviceIpHistory, PassiveDiscoveryObservation
from backend.models import Setting
from backend.services.passive_discovery import apply_passive_device_class, apply_passive_hostname, capture_passive_discovery_report, deduplicate_observations, find_linked_device, ha_groups_for_observations, infer_device_class_from_observation, observation_to_response, parse_cdp_packet, parse_control_plane_packet, parse_lldp_packet, parse_mdns_packet, parse_packet, parse_ssdp_packet, parse_ssdp_payload, parse_stp_packet, upsert_passive_observation
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.routers.devices import get_device_passive_discovery
except Exception:
    get_device_passive_discovery = None

try:
    from scapy.layers.dns import DNS, DNSQR, DNSRR
    from scapy.layers.inet import IP, UDP
    from scapy.layers.l2 import Ether, LLC, SNAP
    from scapy.packet import Raw
except Exception:
    DNS = DNSQR = DNSRR = Ether = IP = LLC = Raw = SNAP = UDP = None

try:
    from scapy.layers.vrrp import VRRP
except Exception:
    VRRP = None


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

    @staticmethod
    def _lldp_tlv(tlv_type: int, value: bytes) -> bytes:
        return (((tlv_type << 9) | len(value)).to_bytes(2, "big") + value)

    @staticmethod
    def _cdp_tlv(tlv_type: int, value: bytes) -> bytes:
        return tlv_type.to_bytes(2, "big") + (len(value) + 4).to_bytes(2, "big") + value

    @unittest.skipIf(Raw is None, "scapy is not installed")
    def test_lldp_packet_extracts_capabilities_and_infers_switch(self):
        payload = b"".join([
            self._lldp_tlv(1, b"\x04" + bytes.fromhex("001122334455")),
            self._lldp_tlv(2, b"\x05Gi1/0/1"),
            self._lldp_tlv(5, b"lab-sg500x"),
            self._lldp_tlv(6, b"Cisco SG500X stack"),
            self._lldp_tlv(7, (0x0004).to_bytes(2, "big") + (0x0004).to_bytes(2, "big")),
            b"\x00\x00",
        ])
        packet = Ether(src="00:11:22:33:44:55", dst="01:80:C2:00:00:0E", type=0x88CC) / Raw(load=payload)

        observation = parse_lldp_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "lldp")
        self.assertEqual(observation.source_mac, "00:11:22:33:44:55")
        self.assertEqual(observation.service_name, "lab-sg500x")
        self.assertEqual(observation.service_type, "bridge")
        self.assertIn("Gi1/0/1", observation.summary)
        inference = infer_device_class_from_observation(observation)
        self.assertEqual(inference["inferred_device_class"], "Switch")
        self.assertEqual(inference["inference_confidence"], "high")

    @unittest.skipIf(Raw is None or LLC is None or SNAP is None, "scapy is not installed")
    def test_cdp_packet_extracts_capabilities_and_infers_switch(self):
        cdp_body = b"\x02\xb4\x00\x00" + b"".join([
            self._cdp_tlv(0x0001, b"lab-sg500x"),
            self._cdp_tlv(0x0003, b"gi1/1/1"),
            self._cdp_tlv(0x0004, (0x00000008).to_bytes(4, "big")),
            self._cdp_tlv(0x0006, b"Cisco SG500X"),
        ])
        packet = (
            Ether(src="00:11:22:33:44:55", dst="01:00:0C:CC:CC:CC")
            / LLC(dsap=0xAA, ssap=0xAA, ctrl=3)
            / SNAP(OUI=0x00000C, code=0x2000)
            / Raw(load=cdp_body)
        )

        observation = parse_cdp_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "cdp")
        self.assertEqual(observation.service_name, "lab-sg500x")
        self.assertEqual(observation.service_type, "switch")
        self.assertIn("gi1/1/1", observation.summary)
        inference = infer_device_class_from_observation(observation)
        self.assertEqual(inference["inferred_device_class"], "Switch")
        self.assertEqual(inference["inference_confidence"], "high")

    @unittest.skipIf(Raw is None, "scapy is not installed")
    def test_multicast_passive_discovery_accepts_lldp_for_device_class_updates(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.70", device_class="Unknown")
            db.add(device)
            db.commit()
            payload = b"".join([
                self._lldp_tlv(1, b"\x04" + bytes.fromhex("001122334455")),
                self._lldp_tlv(2, b"\x05Gi1/0/1"),
                self._lldp_tlv(5, b"lab-sg500x"),
                self._lldp_tlv(7, (0x0004).to_bytes(2, "big") + (0x0004).to_bytes(2, "big")),
                b"\x00\x00",
            ])
            packet = Ether(src="00:11:22:33:44:55", dst="01:80:C2:00:00:0E", type=0x88CC) / Raw(load=payload)
            observation = parse_packet(packet, {"multicast"})

            self.assertIsNotNone(observation)
            self.assertEqual(find_linked_device(db, observation).id, device.id)
            self.assertTrue(apply_passive_device_class(db, device, observation))
            db.commit()

            self.assertEqual(device.device_class, "Switch")
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    @unittest.skipIf(Raw is None or LLC is None, "scapy is not installed")
    def test_stp_packet_extracts_bridge_topology_and_infers_switch(self):
        root_bridge = bytes.fromhex("8000001122334455")
        local_bridge = bytes.fromhex("8000aabbccddeeff")
        bpdu = (
            b"\x00\x00"
            + b"\x02"
            + b"\x02"
            + b"\x00"
            + root_bridge
            + (4).to_bytes(4, "big")
            + local_bridge
            + (0x8001).to_bytes(2, "big")
            + (1 * 256).to_bytes(2, "big")
            + (20 * 256).to_bytes(2, "big")
            + (2 * 256).to_bytes(2, "big")
            + (15 * 256).to_bytes(2, "big")
        )
        packet = (
            Ether(src="AA:BB:CC:DD:EE:FF", dst="01:80:C2:00:00:00")
            / LLC(dsap=0x42, ssap=0x42, ctrl=3)
            / Raw(load=bpdu)
        )

        observation = parse_stp_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "stp")
        metadata = observation_to_response(observation)["metadata"]
        self.assertEqual(metadata["bpdu_type_label"], "RSTP/MSTP BPDU")
        self.assertEqual(metadata["root_bridge_id"], "32768.00:11:22:33:44:55")
        self.assertEqual(metadata["bridge_id"], "32768.aa:bb:cc:dd:ee:ff")
        inference = infer_device_class_from_observation(observation)
        self.assertEqual(inference["inferred_device_class"], "Switch")
        self.assertEqual(inference["inference_confidence"], "high")

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

    def test_passive_discovery_does_not_infer_printer_from_generic_ipp(self):
        observation = PassiveDiscoveryObservation(
            protocol="mdns",
            service_name="Alexs MacBook Pro._ipp._tcp.local",
            service_type="_ipp._tcp",
            summary="Alexs MacBook Pro._ipp._tcp.local",
            metadata_json='{"answers": [{"name": "_ipp._tcp.local"}]}',
        )

        inference = infer_device_class_from_observation(observation)

        self.assertIsNone(inference["inferred_device_class"])
        self.assertIsNone(inference["inference_confidence"])

    def test_passive_discovery_keeps_generic_file_sharing_low_confidence(self):
        observation = PassiveDiscoveryObservation(
            protocol="mdns",
            service_name="Alexs MacBook Pro._smb._tcp.local",
            service_type="_smb._tcp",
            summary="Alexs MacBook Pro._smb._tcp.local",
        )

        inference = infer_device_class_from_observation(observation)

        self.assertEqual(inference["inferred_device_class"], "NAS")
        self.assertEqual(inference["inference_confidence"], "low")

    def test_passive_discovery_keeps_generic_airplay_low_confidence(self):
        observation = PassiveDiscoveryObservation(
            protocol="mdns",
            service_name="Alexs MacBook Pro._airplay._tcp.local",
            service_type="_airplay._tcp",
            summary="Alexs MacBook Pro._airplay._tcp.local",
        )

        inference = infer_device_class_from_observation(observation)

        self.assertEqual(inference["inferred_device_class"], "TV")
        self.assertEqual(inference["inference_confidence"], "low")

    def test_passive_discovery_infers_nas_from_specific_nas_signal(self):
        observation = PassiveDiscoveryObservation(
            protocol="mdns",
            service_name="DiskStation._smb._tcp.local",
            service_type="_smb._tcp",
            summary="Synology DiskStation._smb._tcp.local",
        )

        inference = infer_device_class_from_observation(observation)

        self.assertEqual(inference["inferred_device_class"], "NAS")
        self.assertEqual(inference["inference_confidence"], "high")

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

    def test_passive_discovery_does_not_replace_specific_class_with_weak_hint(self):
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

    def test_passive_discovery_does_not_apply_low_confidence_to_unknown_device(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.20", device_class="Unknown")
            db.add(device)
            db.commit()
            observation = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                service_name="Alexs MacBook Pro._smb._tcp.local",
                service_type="_smb._tcp",
                summary="Alexs MacBook Pro._smb._tcp.local",
            )

            self.assertFalse(apply_passive_device_class(db, device, observation))

            self.assertEqual(device.device_class, "Unknown")
            self.assertEqual(db.query(DeviceChangeEvent).count(), 0)
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_passive_discovery_fills_missing_hostname_from_mdns_local_name(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.20", hostname=None)
            db.add(device)
            db.commit()
            observation = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                service_name="printer.local",
                summary="printer.local",
                metadata_json='{"answers": [{"name": "printer.local", "data": "192.0.2.20"}]}',
            )

            self.assertTrue(apply_passive_hostname(db, device, observation))
            db.commit()

            self.assertEqual(device.hostname, "printer.local")
            event = db.query(DeviceChangeEvent).one()
            self.assertEqual(event.field_name, "hostname")
            self.assertEqual(event.new_value, "printer.local")
            self.assertEqual(event.source, "passive_discovery")
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_passive_discovery_keeps_existing_usable_hostname(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.20", hostname="dns-name.example")
            db.add(device)
            db.commit()
            observation = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                service_name="printer.local",
                summary="printer.local",
            )

            self.assertFalse(apply_passive_hostname(db, device, observation))

            self.assertEqual(device.hostname, "dns-name.example")
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

    @unittest.skipIf(get_device_passive_discovery is None, "router dependencies are not installed")
    def test_device_passive_discovery_endpoint_includes_ip_history_observations(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", ip_address="192.0.2.99")
            db.add(device)
            db.commit()
            db.add_all([
                DeviceIpHistory(device_id=device.id, ip_address="192.0.2.20"),
                PassiveDiscoveryObservation(protocol="mdns", source_ip="192.0.2.20", service_name="printer.local"),
                Setting(key="advanced_view_enabled", value="true"),
                Setting(key="show_plugin_api", value="true"),
                Setting(key="show_passive_discovery", value="true"),
            ])
            db.commit()

            response = get_device_passive_discovery(device.id, db=db, _=None)

            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["source_ip"], "192.0.2.20")
            self.assertEqual(response[0]["linked_device_id"], device.id)
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

    def test_mdns_deduplicates_same_service_with_changing_summary(self):
        older = PassiveDiscoveryObservation(
            id=1,
            protocol="mdns",
            source_ip="192.0.2.20",
            destination_ip="224.0.0.251",
            service_name="Printer._ipp._tcp.local",
            service_type="_ipp._tcp",
            summary="Printer._ipp._tcp.local",
        )
        newer = PassiveDiscoveryObservation(
            id=2,
            protocol="mdns",
            source_ip="192.0.2.20",
            destination_ip="224.0.0.251",
            service_name="_ipp._tcp.local",
            service_type="_ipp._tcp",
            summary="_services._dns-sd._udp.local, _ipp._tcp.local",
        )
        newer.observed_at = datetime.utcnow()
        older.observed_at = newer.observed_at - timedelta(minutes=5)

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

    def test_mdns_upsert_updates_existing_service_with_changing_summary(self):
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
                service_name="Printer._ipp._tcp.local",
                service_type="_ipp._tcp",
                summary="Printer._ipp._tcp.local",
            )
            second = PassiveDiscoveryObservation(
                protocol="mdns",
                source_ip="192.0.2.20",
                destination_ip="224.0.0.251",
                service_name="_ipp._tcp.local",
                service_type="_ipp._tcp",
                summary="_services._dns-sd._udp.local, _ipp._tcp.local",
            )

            self.assertTrue(upsert_passive_observation(db, first))
            db.commit()
            self.assertFalse(upsert_passive_observation(db, second))
            db.commit()

            rows = db.query(PassiveDiscoveryObservation).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].summary, "_services._dns-sd._udp.local, _ipp._tcp.local")
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    def test_ha_groups_link_vrrp_members_to_devices(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            device = Device(
                mac_address="AA:BB:CC:DD:EE:01",
                ip_address="192.0.2.1",
                label="edge-router-a",
                device_class="Router",
            )
            row = PassiveDiscoveryObservation(
                protocol="vrrp",
                source_ip="192.0.2.1",
                source_mac="AA:BB:CC:DD:EE:01",
                destination_ip="224.0.0.18",
                summary="VRRP multicast",
                metadata_json='{"vrid": 10, "virtual_ip": "192.0.2.254"}',
                observed_at=datetime.utcnow(),
            )
            db.add_all([device, row])
            db.commit()

            groups = ha_groups_for_observations(db)

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["protocol"], "vrrp")
            self.assertEqual(groups[0]["virtual_ip"], "192.0.2.254")
            self.assertEqual(groups[0]["member_count"], 1)
            self.assertEqual(groups[0]["active_device_label"], "edge-router-a")
        finally:
            db.close()
            Base.metadata.drop_all(engine)

    @unittest.skipIf(VRRP is None or Ether is None or IP is None, "scapy VRRP is not installed")
    def test_vrrp_control_plane_metadata_includes_group_identity(self):
        packet = (
            Ether(src="AA:BB:CC:DD:EE:01")
            / IP(src="192.0.2.1", dst="224.0.0.18", proto=112)
            / VRRP(vrid=10, addrlist=["192.0.2.254"])
        )

        observation = parse_control_plane_packet(packet)

        self.assertIsNotNone(observation)
        metadata = observation_to_response(observation)["metadata"]
        self.assertEqual(metadata["vrid"], 10)
        self.assertEqual(metadata["virtual_ip"], "192.0.2.254")

    @unittest.skipIf(Ether is None or IP is None or Raw is None, "scapy is not installed")
    def test_ospf_hello_metadata_includes_router_area_and_neighbors(self):
        ospf_hello = (
            b"\x02\x01\x00\x34"
            + bytes([192, 0, 2, 1])
            + bytes([0, 0, 0, 0])
            + b"\x00\x00\x00\x00"
            + b"\x00" * 8
            + bytes([255, 255, 255, 0])
            + (10).to_bytes(2, "big")
            + b"\x02"
            + b"\x01"
            + (40).to_bytes(4, "big")
            + bytes([192, 0, 2, 1])
            + bytes([192, 0, 2, 2])
            + bytes([192, 0, 2, 3])
        )
        packet = (
            Ether(src="AA:BB:CC:DD:EE:01")
            / IP(src="192.0.2.1", dst="224.0.0.5", proto=89)
            / Raw(load=ospf_hello)
        )

        observation = parse_control_plane_packet(packet)

        self.assertIsNotNone(observation)
        self.assertEqual(observation.protocol, "ospf")
        metadata = observation_to_response(observation)["metadata"]
        self.assertEqual(metadata["ospf_type_label"], "OSPF hello")
        self.assertEqual(metadata["router_id"], "192.0.2.1")
        self.assertEqual(metadata["area_id"], "0.0.0.0")
        self.assertEqual(metadata["network_mask"], "255.255.255.0")
        self.assertEqual(metadata["neighbors"], ["192.0.2.3"])

    @unittest.skipIf(Ether is None or IP is None or UDP is None or Raw is None, "scapy is not installed")
    def test_hsrp_control_plane_metadata_includes_group_identity(self):
        payload = bytes([
            0, 0, 16, 3, 10, 30, 42, 0,
            *b"cisco123",
            192, 0, 2, 254,
        ])
        packet = (
            Ether(src="AA:BB:CC:DD:EE:02")
            / IP(src="192.0.2.2", dst="224.0.0.2")
            / UDP(sport=1985, dport=1985)
            / Raw(load=payload)
        )

        observation = parse_control_plane_packet(packet)

        self.assertIsNotNone(observation)
        metadata = observation_to_response(observation)["metadata"]
        self.assertEqual(metadata["group"], 42)
        self.assertEqual(metadata["virtual_ip"], "192.0.2.254")


if __name__ == "__main__":
    unittest.main()
