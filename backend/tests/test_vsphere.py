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
from backend.services.vsphere import VsphereClient, VsphereError, reconcile_inventory, validate_endpoint, disk_inventory


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
