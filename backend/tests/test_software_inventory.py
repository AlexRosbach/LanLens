import json
import os
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-software-inventory-12345")
from backend.database import Base
from backend.models import Device, DeepScanFinding, DeepScanRun, User
from backend.routers.inventory import get_applications
from backend.services.software_inventory import list_software_inventory, parse_software
from fastapi import HTTPException

class SoftwareInventoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def device(self, n, archived=False):
        d = Device(mac_address=f"02:00:00:00:00:{n:02x}", hostname=f"host-{n}", is_archived=archived)
        self.db.add(d)
        self.db.flush()
        return d

    def finding(self, d, raw, hours=0, status="done", key="installed_software"):
        run = DeepScanRun(device_id=d.id, profile="full", status=status)
        self.db.add(run)
        self.db.flush()
        self.db.add(DeepScanFinding(device_id=d.id, run_id=run.id, key=key, finding_type="software",
                                   value_json=json.dumps(raw), observed_at=datetime.utcnow()-timedelta(hours=hours)))
        self.db.flush()

    def test_inventory_latest_software_not_latest_unrelated_scan(self):
        a, b, c = self.device(1), self.device(2), self.device(3, archived=True)
        self.finding(a, [{"Name": "Old"}], 4)
        self.finding(a, [{"Name": "Example", "Version": "1"}, {"Name": "Example", "Version": "1"}], 3)
        self.finding(a, "ignored", 2, key="processor")
        self.finding(a, [{"Name": "Failed"}], 1, status="error")
        self.finding(b, "Example\t2\tamd64")
        self.finding(c, [{"Name": "Archived"}])
        result = list_software_inventory(self.db)
        self.assertEqual(result["total"], 1)
        product = result["products"][0]
        self.assertEqual(product["device_count"], 2)
        self.assertEqual(product["versions"], ["1", "2"])
        detail = list_software_inventory(self.db, application_id=product["id"], limit=1)
        self.assertEqual(detail["total"], 2)
        self.assertEqual(len(detail["installations"]), 1)
        self.assertEqual(list_software_inventory(self.db, search="host-2")["total"], 1)

    def test_combined_filters_match_same_installation_and_details(self):
        a, b = self.device(1), self.device(2)
        a.device_class = "Server"
        b.device_class = "Client"
        self.finding(a, [{"Name": "Example App", "Publisher": "Example Corp", "Version": "1", "Architecture": "x64"}])
        self.finding(b, [{"Name": "Example App", "Publisher": "Example Corp", "Version": "2", "Architecture": "x86"}])
        result = list_software_inventory(self.db, device="host-1", application="EXAMPLE", publisher="corp",
                                         version="1", architecture="x64", device_class="server")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["device_count"], 1)
        product = result["products"][0]
        self.assertEqual(product["versions"], ["1"])
        self.assertEqual(product["installation_count"], 1)
        self.assertEqual(list_software_inventory(self.db, device="host-1", version="2")["total"], 0)
        detail = list_software_inventory(self.db, application_id=product["id"], device="host-1", version="1")
        self.assertEqual(detail["total"], 1)
        self.assertEqual(detail["installations"][0]["device_id"], a.id)
        self.assertEqual(list_software_inventory(self.db, application_id=product["id"], search="example")["total"], 2)

    def test_winrm_software_unicode_transport(self):
        import base64
        from backend.services.deep_scanner import _decode_software_transport
        original = json.dumps([{"Name": "Update f\u00fcr Beispiel"}], ensure_ascii=False)
        result = _decode_software_transport(base64.b64encode(original.encode("utf-8")))
        self.assertEqual(json.loads(result)[0]["Name"], "Update f\u00fcr Beispiel")
        with self.assertRaises(ValueError):
            _decode_software_transport(base64.b64encode(b'["invalid"]\xff'))

    def test_device_grouping_and_exact_device_drilldown(self):
        a, b = self.device(1), self.device(2)
        self.finding(a, [{"Name": "Example", "Version": "1"}, {"Name": "Other", "Version": "1"}])
        self.finding(b, [{"Name": "Example", "Version": "2"}])
        result = list_software_inventory(self.db, group_by="device")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["installation_count"], 3)
        self.assertEqual(result["devices"][0]["product_count"], 2)
        detail = list_software_inventory(self.db, selected_device_id=a.id)
        self.assertEqual(detail["total"], 2)
        self.assertEqual(detail["products"][0]["versions"], ["1"])
        filtered = list_software_inventory(self.db, group_by="device", version="2")
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["devices"][0]["id"], b.id)

    def test_parser_structured_and_linux(self):
        self.assertEqual(list(parse_software(json.dumps(json.dumps({"Name": "Grüße", "Version": "2"}))))[0][0], "Grüße")
        self.assertEqual(list(parse_software("example-package-1.2-r0"))[0][:3], ("example-package", "", "1.2-r0"))

    def test_api_requires_feature(self):
        with self.assertRaises(HTTPException) as error:
            get_applications(search="", offset=0, limit=25, application_id=None, db=self.db, _=User(username="test"))
        self.assertEqual(error.exception.status_code, 403)
