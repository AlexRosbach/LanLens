"""An installer can inspect its enrollment without bypassing revocation."""
import json
import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("SECRET_KEY", "agent-recovery-tests-secret-key-1234567890")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AgentEnrollmentToken, DeepScanFinding, DeepScanRun, Device, DeviceChangeEvent, WindowsAgent
from backend.routers.agents import (
    AgentEnrollRequest, AgentReportRequest, _sha256, enroll_agent, get_agent_identity,
    report_agent_inventory, revoke_enrollment_token, unenroll_agent,
)


class AgentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.device = Device(mac_address="02:00:00:00:12:34", hostname="recovery-test")
        self.db.add(self.device)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def token(self, raw, **properties):
        token = AgentEnrollmentToken(name="Recovery test", token_hash=_sha256(raw), **properties)
        self.db.add(token)
        self.db.commit()
        return token

    def enroll(self, raw):
        return enroll_agent(AgentEnrollRequest(token=raw, hostname="recovery-test",
                            primary_mac="02-00-00-00-12-34", platform="windows"), db=self.db)

    @staticmethod
    def bearer(enrollment):
        return "Bearer " + enrollment["agent_id"] + "." + enrollment["agent_secret"]

    def identity(self, enrollment):
        return get_agent_identity(authorization=self.bearer(enrollment), db=self.db)

    def report(self, enrollment, **overrides):
        payload = {"sequence": 1, "hostname": "recovery-test", "primary_mac": self.device.mac_address,
                   "platform": "windows", "os_info": "Example Windows",
                   "software": [{"name": "Example program", "version": "1.0"}]}
        payload.update(overrides)
        return report_agent_inventory(AgentReportRequest(**payload), authorization=self.bearer(enrollment), db=self.db)

    def agent_state(self):
        self.db.expire_all()
        row = self.db.query(WindowsAgent).filter_by(device_id=self.device.id).one()
        return (row.agent_id, row.secret_hash, row.enrollment_token_id, row.revoked_at,
                row.last_sequence, row.last_seen_at, row.platform)

    def test_identity_is_read_only_and_does_not_require_unused_install_token(self):
        token = self.token("a" * 32)
        enrollment = self.enroll("a" * 32)
        # Enrollment-token expiry only governs enrollment, not an installed
        # agent's continuing authenticated access.
        self.db.refresh(token)
        used_at = token.last_used_at
        token.expires_at = datetime.utcnow() - timedelta(minutes=1)
        self.db.commit()
        before = self.agent_state()
        for _ in range(2):
            status = self.identity(enrollment)
            self.assertEqual(status["status"], "active")
            self.assertEqual(status["agent_id"], enrollment["agent_id"])
            self.assertEqual(status["device_id"], self.device.id)
            self.assertEqual(status["platform"], "windows")
            self.assertEqual(status["primary_mac"], self.device.mac_address)
            self.assertEqual(status["last_sequence"], 0)
            self.assertNotIn("agent_secret", status)
            self.assertNotIn("secret_hash", status)
            self.assertNotIn(enrollment["agent_secret"], json.dumps(status))
        self.assertEqual(self.agent_state(), before)
        self.db.refresh(token)
        self.assertEqual(token.last_used_at, used_at)
        self.assertEqual(self.db.query(DeepScanRun).count(), 0)
        self.assertEqual(self.db.query(DeviceChangeEvent).count(), 0)
        result = self.report(enrollment)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.identity(enrollment)["last_sequence"], 1)

    def test_revoked_identity_requires_new_token_and_preserves_device_and_inventory(self):
        old_token = self.token("a" * 32)
        initial = self.enroll("a" * 32)
        self.report(initial)
        old_finding_ids = {row.id for row in self.db.query(DeepScanFinding).all()}
        revoke_enrollment_token(old_token.id, db=self.db, _=None)
        with self.assertRaises(HTTPException) as revoked:
            self.identity(initial)
        self.assertEqual(revoked.exception.status_code, 401)

        new_token = self.token("b" * 32)
        replacement = self.enroll("b" * 32)
        self.assertEqual(replacement["device_id"], initial["device_id"])
        self.assertNotEqual(replacement["agent_id"], initial["agent_id"])
        self.assertNotEqual(replacement["agent_secret"], initial["agent_secret"])
        self.assertEqual(self.db.query(Device).count(), 1)
        self.assertEqual(self.db.query(WindowsAgent).count(), 1)
        self.assertEqual(self.identity(replacement)["last_sequence"], 0)
        self.db.refresh(new_token)
        self.assertIsNotNone(new_token.last_used_at)
        self.assertIsNone(new_token.revoked_at)
        with self.assertRaises(HTTPException) as old_identity:
            self.identity(initial)
        self.assertEqual(old_identity.exception.status_code, 401)
        with self.assertRaises(HTTPException):
            unenroll_agent(authorization=self.bearer(initial), db=self.db)
        with self.assertRaises(HTTPException) as reused:
            self.enroll("b" * 32)
        self.assertEqual(reused.exception.status_code, 401)
        self.assertEqual(self.report(replacement)["status"], "accepted")
        self.assertEqual(self.identity(replacement)["last_sequence"], 1)
        self.assertTrue(old_finding_ids.issubset({row.id for row in self.db.query(DeepScanFinding).all()}))

    def test_failed_recovery_token_does_not_modify_or_unrevoke_saved_identity(self):
        original_token = self.token("a" * 32)
        original = self.enroll("a" * 32)
        revoke_enrollment_token(original_token.id, db=self.db, _=None)
        expired = self.token("e" * 32, expires_at=datetime.utcnow() - timedelta(minutes=1))
        before = self.agent_state()
        for raw in ("a" * 32, "e" * 32, "unknown-token-12345678901234567890"):
            with self.subTest(token_kind=raw[0]):
                with self.assertRaises(HTTPException) as failure:
                    self.enroll(raw)
                self.assertEqual(failure.exception.status_code, 401)
                self.assertEqual(self.agent_state(), before)
                with self.assertRaises(HTTPException):
                    self.identity(original)
        self.db.refresh(expired)
        self.assertIsNone(expired.last_used_at)
        self.assertEqual(self.db.query(Device).count(), 1)

    def test_new_token_cannot_replace_an_active_identity_after_a_stale_local_secret(self):
        self.token("a" * 32)
        active = self.enroll("a" * 32)
        new_token = self.token("b" * 32)
        before = self.agent_state()
        with self.assertRaises(HTTPException):
            get_agent_identity(authorization="Bearer unknown-agent.old-secret", db=self.db)
        with self.assertRaises(HTTPException) as conflict:
            self.enroll("b" * 32)
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(self.agent_state(), before)
        self.db.refresh(new_token)
        self.assertIsNone(new_token.last_used_at)
        self.assertEqual(self.identity(active)["status"], "active")
        self.assertEqual(self.report(active)["status"], "accepted")

    def test_unknown_wrong_and_revoked_secrets_do_not_expose_identity(self):
        token = self.token("a" * 32)
        active = self.enroll("a" * 32)
        errors = []
        for authorization in ("Bearer unknown-agent.bad-secret", "Bearer " + active["agent_id"] + ".bad-secret"):
            with self.assertRaises(HTTPException) as rejected:
                get_agent_identity(authorization=authorization, db=self.db)
            self.assertEqual(rejected.exception.status_code, 401)
            errors.append(rejected.exception.detail)
        revoke_enrollment_token(token.id, db=self.db, _=None)
        with self.assertRaises(HTTPException) as revoked:
            self.identity(active)
        self.assertEqual(revoked.exception.status_code, 401)
        errors.append(revoked.exception.detail)
        self.assertEqual(len(set(errors)), 1)
        for detail in errors:
            self.assertNotIn(active["agent_id"], str(detail))
            self.assertNotIn(active["agent_secret"], str(detail))
            self.assertNotIn(self.device.mac_address, str(detail))

    def test_recovered_agent_still_enforces_platform_mac_and_sequence(self):
        old_token = self.token("a" * 32)
        self.enroll("a" * 32)
        revoke_enrollment_token(old_token.id, db=self.db, _=None)
        self.token("b" * 32)
        recovered = self.enroll("b" * 32)
        before = self.agent_state()
        for overrides in ({"platform": "linux"}, {"primary_mac": "02:00:00:00:12:35"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(HTTPException) as conflict:
                    self.report(recovered, **overrides)
                self.assertEqual(conflict.exception.status_code, 409)
                self.assertEqual(self.agent_state(), before)
        self.assertEqual(self.report(recovered)["status"], "accepted")
        with self.assertRaises(HTTPException) as replay:
            self.report(recovered)
        self.assertEqual(replay.exception.status_code, 409)
        self.assertEqual(self.identity(recovered)["last_sequence"], 1)
