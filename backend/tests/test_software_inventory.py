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

    def test_parser_structured_and_linux(self):
        self.assertEqual(list(parse_software(json.dumps(json.dumps({"Name": "Grüße", "Version": "2"}))))[0][0], "Grüße")
        self.assertEqual(list(parse_software("example-package-1.2-r0"))[0][:3], ("example-package", "", "1.2-r0"))

    def test_api_requires_feature(self):
        with self.assertRaises(HTTPException) as error:
            get_applications(search="", offset=0, limit=25, application_id=None, db=self.db, _=User(username="test"))
        self.assertEqual(error.exception.status_code, 403)
