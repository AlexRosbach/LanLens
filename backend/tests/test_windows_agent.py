import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AgentEnrollmentToken, Device, WindowsAgent
from backend.routers.agents import _active_token, _authenticated_agent, _find_or_create_device, _normalise_mac, _sha256
from backend.routers.agents import AgentEnrollRequest, AgentReportRequest
from fastapi import HTTPException


class WindowsAgentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_mac_normalisation_and_existing_device_reuse(self):
        db = self.Session()
        try:
            self.assertEqual(_normalise_mac("00-11-22-33-44-55"), "00:11:22:33:44:55")
            existing = Device(mac_address="00:11:22:33:44:55", hostname="old")
            db.add(existing)
            db.commit()
            payload = AgentEnrollRequest(token="a" * 20, hostname="new-name", primary_mac="001122334455", ip_addresses=["198.51.100.7"])
            device = _find_or_create_device(payload, db)
            self.assertEqual(device.id, existing.id)
            self.assertEqual(device.hostname, "new-name")
            self.assertEqual(device.ip_address, "198.51.100.7")
        finally:
            db.close()

    def test_expired_or_revoked_enrollment_token_is_rejected(self):
        db = self.Session()
        try:
            raw = "a" * 32
            db.add(AgentEnrollmentToken(name="expired", token_hash=_sha256(raw), expires_at=datetime.utcnow() - timedelta(seconds=1)))
            db.commit()
            with self.assertRaises(HTTPException) as raised:
                _active_token(raw, db)
            self.assertEqual(raised.exception.status_code, 401)
        finally:
            db.close()

    def test_agent_bearer_secret_must_match_stored_hash(self):
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55")
            db.add(device)
            db.flush()
            credential = "agent-id.agent-secret"
            db.add(WindowsAgent(agent_id="agent-id", device_id=device.id, secret_hash=_sha256(credential)))
            db.commit()
            self.assertEqual(_authenticated_agent("Bearer " + credential, db).agent_id, "agent-id")
            with self.assertRaises(HTTPException):
                _authenticated_agent("Bearer agent-id.bad", db)
        finally:
            db.close()
