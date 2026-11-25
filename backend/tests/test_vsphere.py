import os
import unittest
from datetime import datetime
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-vsphere-inventory-123456")
from backend.services.notification import PinnedHttpResponse
from backend.routers.vsphere import _client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import Device, DeviceHostRelationship, VsphereConnection, VsphereInventoryObject
from backend.services.vsphere import VsphereClient, VsphereError, reconcile_inventory, validate_endpoint, disk_inventory, idoit_vsphere_values, sysid_annotation, writeback_idoit_sysid


class VsphereTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(VsphereConnection(id=1))
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_endpoint(self):
        self.assertEqual(validate_endpoint("https://vc.example.test/"), "https://vc.example.test")
        for url in ("http://vc.example.test", "https://u:p@vc.example.test", "https://vc.example.test/path"):
            with self.assertRaises(VsphereError):
                validate_endpoint(url)

    async def test_collect_with_missing_tools(self):
        class Client(VsphereClient):
            async def _request(self, method, path, login=False, optional=False):
                if path == "/api/session":
                    return "test-session" if login else None
                if path.startswith("/api/vcenter/host"):
                    return [{"host":"host-1","name":"esxi.example.test"}]
                if path.startswith("/api/vcenter/datacenter"):
                    return [{"datacenter":"datacenter-1","name":"DC"}]
                if path.startswith("/api/vcenter/cluster"):
                    return [{"cluster":"domain-c1","name":"Cluster"}]
                if path.startswith("/api/vcenter/vm?") or path == "/api/vcenter/vm":
                    return [{"vm":"vm-1","name":"VM 1","power_state":"POWERED_OFF"}]
                if path.endswith("/guest/networking/interfaces"):
                    return None
                if path == "/api/vcenter/vm/vm-1":
                    return {"identity":{"instance_uuid":"11111111-2222-3333-4444-555555555555"},
                            "nics":{"4000":{"mac_address":"00:50:56:12:34:56"}}}
                raise AssertionError(path)
            async def vi_login(self):
                return True

            async def _vi_request(self, method, path, payload=None):
                return {"hardware":{"device":[{"_typeName":"VirtualDisk","key":2000,"backing":{"uuid":"6000c290-1234-5678-9012-123456789abc"}}]}}, None

        client = Client("https://vc.example.test","test","test")
        data, warnings = await client.collect()
        self.assertIsNone(client.session)
        self.assertEqual(data[1]["macs"], ["00:50:56:12:34:56"])
        self.assertEqual(data[1]["ips"], [])
        self.assertEqual(data[1]["host_id"], "host-1")
        self.assertEqual(warnings, [])
        self.assertEqual(data[1]["power_state"], "POWERED_OFF")
        self.assertEqual(data[1]["cluster_id"], "domain-c1")
        self.assertEqual(data[1]["datacenter_id"], "datacenter-1")
        self.assertEqual(data[1]["disks"][0]["uuid"], "6000c290-1234-5678-9012-123456789abc")

    def test_reconcile_creates_once_and_preserves_user_data(self):
        host = Device(mac_address="02:00:00:00:00:01", hostname="esxi.example.test")
        self.db.add(host)
        self.db.flush()
        items = [
            {"kind":"host","external_id":"host-1","name":"esxi.example.test"},
            {"kind":"vm","external_id":"vm-1","name":"Example VM","host_id":"host-1",
             "instance_uuid":"11111111-2222-3333-4444-555555555555","macs":["00:50:56:12:34:56"],"ips":["192.0.2.5"]},
        ]
        self.assertEqual(reconcile_inventory(self.db,1,items,datetime.utcnow())["created"],1)
        d = self.db.query(Device).filter_by(mac_address="00:50:56:12:34:56").one()
        d.label = "Operator label"
        self.assertFalse(d.is_online)
        self.assertEqual(self.db.query(DeviceHostRelationship).count(),1)
        reconcile_inventory(self.db,1,items,datetime.utcnow())
        self.assertEqual(self.db.query(Device).count(),2)
        self.assertEqual(d.label,"Operator label")
        self.assertEqual(self.db.query(DeviceHostRelationship).count(),1)
        self.assertEqual(self.db.query(VsphereInventoryObject).count(),2)

    def test_reconcile_ip_only_device_is_enriched(self):
        d = Device(mac_address="ip:existing", ip_address="192.0.2.5", hostname="guest.example.test")
        self.db.add(d)
        self.db.flush()
        result = reconcile_inventory(self.db, 1, [{"kind":"vm", "external_id":"vm-1", "name":"Guest",
                    "macs":["00:50:56:12:34:56"], "ips":["192.0.2.5"]}], datetime.utcnow())
        self.assertEqual(result["existing"], 1)
        self.assertEqual(self.db.query(Device).count(), 1)
        self.assertEqual(d.mac_address, "00:50:56:12:34:56")

    def test_reconcile_hostname_and_conflicts(self):
        d = Device(mac_address="ip:existing", hostname="guest.example.test", ip_address="192.0.2.5")
        self.db.add(d)
        self.db.flush()
        item = {"kind":"vm", "external_id":"vm-1", "name":"GUEST.EXAMPLE.TEST.",
                "macs":["00:50:56:12:34:56"], "ips":[]}
        self.assertEqual(reconcile_inventory(self.db,1,[item],datetime.utcnow())["existing"], 1)
        item["macs"] = ["00:50:56:12:34:57"]
        self.assertEqual(reconcile_inventory(self.db,1,[item],datetime.utcnow())["ambiguous"], 1)
        self.assertEqual(self.db.query(Device).count(), 1)

    def test_conflicting_ip_and_mac_do_not_merge(self):
        self.db.add_all([Device(mac_address="00:50:56:12:34:56", ip_address="192.0.2.5"),
                         Device(mac_address="00:50:56:12:34:57", ip_address="192.0.2.6")])
        self.db.flush()
        item = {"kind":"vm","external_id":"vm-1","name":"Guest","macs":["00:50:56:12:34:56"],"ips":["192.0.2.6"]}
        self.assertEqual(reconcile_inventory(self.db,1,[item],datetime.utcnow())["ambiguous"], 1)
        self.assertEqual(self.db.query(Device).count(), 2)

    def test_annotation_preserves_notes_and_is_idempotent(self):
        old = "Existing notes\nOwner: IT"
        new = sysid_annotation(old, "SYSID_123")
        self.assertEqual(new, old + "\nLanLens i-doit SYS-ID: SYSID_123")
        self.assertEqual(sysid_annotation(new, "SYSID_123"), new)
        self.assertEqual(sysid_annotation(new, "SYSID_456"), old + "\nLanLens i-doit SYS-ID: SYSID_456")
        with self.assertRaises(VsphereError):
            sysid_annotation(new, "invalid\nannotation")

    async def test_annotation_write_checks_uuid_and_task(self):
        uid = "11111111-2222-3333-4444-555555555555"
        client = VsphereClient("https://vc.example.test", "user", "pass")
        client.vi_login = AsyncMock(return_value=True)
        client.vi_logout = AsyncMock()
        client._vi_request = AsyncMock(side_effect=[
            ({"instanceUuid":uid, "changeVersion":"123", "annotation":"Existing notes"}, None),
            ({"type":"Task","value":"task-1"}, None),
            ({"state":"success"}, None),
        ])
        self.assertEqual(await client.write_sysid_annotation("vm-1", uid, "SYSID_123"), "updated")
        self.assertEqual(client._vi_request.call_args_list[1].args[2],
                         {"spec":{"changeVersion":"123","annotation":"Existing notes\nLanLens i-doit SYS-ID: SYSID_123"}})
        client._vi_request = AsyncMock(return_value=({"instanceUuid":"99999999-2222-3333-4444-555555555555"}, None))
        with self.assertRaises(VsphereError):
            await client.write_sysid_annotation("vm-1", uid, "SYSID_123")
        self.assertEqual(client._vi_request.await_count, 1)

    async def test_custom_attribute_writeback_verifies_vm_and_value(self):
        uid = "11111111-2222-3333-4444-555555555555"
        client = VsphereClient("https://vc.example.test", "user", "pass")
        client.vi_login = AsyncMock(return_value=True)
        client.vi_logout = AsyncMock()
        client.custom_fields_manager = "CustomFieldsManager"
        client._vi_request = AsyncMock(side_effect=[
            ({"instanceUuid": uid}, None),
            ([{"key": 7, "name": "CMDB", "managedObjectType": "VirtualMachine"}], None),
            ([], None), (None, None),
            ([{"key": 7, "value": "SYSID_123"}], None),
        ])
        self.assertEqual(await client.write_sysid_custom_field("vm-1", uid, "SYSID_123", 7), "updated")
        self.assertEqual(client._vi_request.call_args_list[3].args[2],
                         {"entity": {"type": "VirtualMachine", "value": "vm-1"}, "key": 7, "value": "SYSID_123"})

    async def test_writeback_is_disabled_by_default(self):
        row = self.db.get(VsphereConnection, 1)
        row.enabled = True
        self.assertFalse(row.writeback_sysid)
        self.assertIsNone(await writeback_idoit_sysid(self.db, 1, "SYSID_123"))

    def test_changed_nic_does_not_create_duplicate_on_repeated_scan(self):
        item = {"kind":"vm","external_id":"vm-1","name":"Example",
                "instance_uuid":"11111111-2222-3333-4444-555555555555",
                "macs":["00:50:56:12:34:56"],"ips":[]}
        reconcile_inventory(self.db,1,[item],datetime.utcnow())
        item["macs"] = ["00:50:56:12:34:57"]
        for _ in range(2):
            result = reconcile_inventory(self.db,1,[item],datetime.utcnow())
            self.assertEqual(result["ambiguous"],1)
        self.assertEqual(self.db.query(Device).count(),1)

    def test_ambiguous_and_macless_remain_inventory_only(self):
        items = [{"kind":"vm","external_id":"vm-"+str(i),"name":"Example","macs":["00:50:56:12:34:56"],"ips":[]}
                 for i in range(2)]
        items.append({"kind":"vm","external_id":"vm-3","name":"No NIC","macs":[],"ips":[]})
        result = reconcile_inventory(self.db,1,items,datetime.utcnow())
        self.assertEqual(result["ambiguous"],2)
        self.assertEqual(result["no_mac"],1)
        self.assertEqual(self.db.query(Device).count(),0)

    async def test_tls_opt_out_is_per_client(self):
        with patch("backend.services.vsphere.request_json_via_validated_url", new_callable=AsyncMock) as request:
            request.return_value = PinnedHttpResponse(200, '"session-token"')
            await VsphereClient("https://vc.example.test", "user", "pass").login()
            self.assertTrue(request.call_args.kwargs["verify_tls"])
            await VsphereClient("https://vc.example.test", "user", "pass", verify_tls=False).login()
            self.assertFalse(request.call_args.kwargs["verify_tls"])

    def test_disabled_integration_blocks_discovery(self):
        row = self.db.get(VsphereConnection, 1)
        self.assertFalse(row.enabled)
        self.assertTrue(row.verify_tls)
        with self.assertRaises(HTTPException):
            _client(row)

    def test_disk_uuid_is_not_a_unique_record_key(self):
        disks = disk_inventory({"2000":{"label":"Disk 1","capacity":100},
                                "2001":{"label":"Disk 2","capacity":200}}, {"hardware":{"device":[
            {"_typeName":"VirtualDisk","key":2000,"backing":{"uuid":"6000c290-1234-5678-9012-123456789abc"}},
            {"_typeName":"VirtualDisk","key":2001,"backing":{"uuid":"6000c290-1234-5678-9012-123456789abc"}}]}})
        self.assertEqual(len(disks), 2)
        self.assertEqual(disks[0]["uuid"], disks[1]["uuid"])
        self.assertIsNone(disk_inventory({"2000":{"capacity":10}}, None)[0]["uuid"])

    def test_mapping_ignores_disabled_and_stale_inventory(self):
        row = self.db.get(VsphereConnection, 1)
        item = {"kind":"vm","external_id":"vm-1","name":"Example","power_state":"POWERED_OFF",
                "instance_uuid":"11111111-2222-3333-4444-555555555555","macs":["00:50:56:12:34:56"],"ips":[]}
        reconcile_inventory(self.db,1,[item],datetime.utcnow())
        device = self.db.query(Device).one()
        self.assertEqual(idoit_vsphere_values(self.db, device), {})
        row.enabled = True
        self.db.flush()
        self.assertEqual(idoit_vsphere_values(self.db, device)["vsphere_power_state"], "POWERED_OFF")
        reconcile_inventory(self.db,1,[],datetime.utcnow())
        self.assertEqual(idoit_vsphere_values(self.db, device), {})
