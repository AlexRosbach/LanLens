import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AgentEnrollmentToken, DeepScanFinding, Device, WindowsAgent
from backend.routers.agents import _active_token, _authenticated_agent, _find_or_create_device, _normalise_mac, _sha256, report_agent_inventory
from backend.routers.agents import AgentEnrollRequest, AgentReportRequest, enroll_agent, revoke_enrollment_token
from pydantic import ValidationError
from fastapi import HTTPException


class WindowsAgentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)

    def test_windows_installer_persists_explicit_certificate_trust(self):
        from pathlib import Path
        installer = (Path(__file__).resolve().parents[1] / "assets/windows_agent/install.ps1").read_text()
        agent = (Path(__file__).resolve().parents[1] / "assets/windows_agent/LanLensAgent.cs").read_text()
        self.assertIn("[switch]$TrustUntrustedCertificate", installer)
        self.assertIn("trust_untrusted_certificate = [bool]$TrustUntrustedCertificate", installer)
        self.assertNotIn("CertificateSha256", installer)
        self.assertEqual(installer.count('Invoke-LanLensInstallerRequest -Uri "$ServerUrl/api/agents/enroll"'), 1)
        self.assertIn("$request.ServerCertificateValidationCallback", installer)
        self.assertIn("$request.AllowAutoRedirect = $false", installer)
        self.assertNotIn("[Net.ServicePointManager]::ServerCertificateValidationCallback =", installer)
        self.assertIn('cfg.TryGetValue("certificate_sha256"', agent)
        self.assertIn('cfg.TryGetValue("trust_untrusted_certificate"', agent)
        self.assertIn("ValidateUntrustedCertificate(cert, errors, trustUntrusted)", agent)
        self.assertIn("AllowAutoRedirect = false", agent)
        self.assertIn("agent.log", agent)
        self.assertIn("today.AddDays(-29)", agent)
        self.assertIn("Report accepted HTTP", agent)
        self.assertIn("[switch]$UpdateExisting", installer)

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

    def test_linux_agent_stores_structured_findings(self):
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:55", hostname="linux-host")
            db.add(device)
            db.flush()
            credential = "linux-agent.linux-secret"
            db.add(WindowsAgent(agent_id="linux-agent", device_id=device.id, secret_hash=_sha256(credential)))
            db.commit()
            payload = AgentReportRequest(
                sequence=1, hostname="linux-host", primary_mac="00:11:22:33:44:55",
                os_info="Example Linux", kernel_version="6.12", platform="linux",
                software=[{"name": "example", "version": "1.0"}],
                findings=[{"finding_type": "hardware", "key": "cpu", "value": "CPU details"}],
            )
            result = report_agent_inventory(payload, authorization="Bearer " + credential, db=db)
            self.assertEqual(result["status"], "accepted")
            stored = db.query(DeepScanFinding).filter(DeepScanFinding.run_id == result["run_id"]).all()
            self.assertEqual({(finding.finding_type, finding.key) for finding in stored}, {
                ("os", "operating_system"), ("software", "installed_software"), ("hardware", "cpu"),
            })
            self.assertTrue(all(finding.source == "lanlens_linux_agent" for finding in stored))
        finally:
            db.close()

    def test_enrollment_is_single_use_and_cannot_replace_active_agent(self):
        db = self.Session()
        try:
            first, second = 'a' * 32, 'b' * 32
            for raw in (first, second):
                db.add(AgentEnrollmentToken(name='test', token_hash=_sha256(raw)))
            db.commit()
            def enroll(raw):
                return enroll_agent(AgentEnrollRequest(token=raw, hostname='host', primary_mac='00:11:22:33:44:55'), db)
            initial = enroll(first)
            with self.assertRaises(HTTPException) as reused:
                enroll(first)
            self.assertEqual(reused.exception.status_code, 401)
            with self.assertRaises(HTTPException) as replacement:
                enroll(second)
            self.assertEqual(replacement.exception.status_code, 409)
            token_id = db.query(AgentEnrollmentToken).filter_by(token_hash=_sha256(first)).one().id
            revoke_enrollment_token(token_id, db, None)
            with self.assertRaises(HTTPException):
                _authenticated_agent('Bearer ' + initial['agent_id'] + '.' + initial['agent_secret'], db)
            self.assertNotEqual(enroll(second)['agent_id'], initial['agent_id'])
        finally:
            db.close()

    def test_agent_reports_visible_without_credential_scan_and_timeline_on_changes(self):
        from backend.models import DeviceChangeEvent, DeepScanRun
        from backend.routers.deep_scan import get_findings, get_agent_status
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:77")
            db.add(device)
            db.flush()
            credential = "test-agent.test-secret"
            agent = WindowsAgent(agent_id="test-agent", device_id=device.id, platform="windows", secret_hash=_sha256(credential))
            db.add(agent)
            db.commit()
            payload = AgentReportRequest(sequence=1, hostname="test", primary_mac=device.mac_address,
                                         os_info="Windows Server", software=[{"name":"Example", "version":"1"}])
            result = report_agent_inventory(payload, authorization="Bearer " + credential, db=db)
            self.assertEqual(result["finding_count"], 2)
            self.assertEqual(db.query(DeviceChangeEvent).filter_by(device_id=device.id, source="lanlens_windows_agent", event_type="agent_inventory_received").count(), 1)
            run = DeepScanRun(device_id=device.id, profile="full", status="done", triggered_by="manual")
            db.add(run)
            db.flush()
            db.add(DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="os", key="operating_system", value_json='"WinRM observation"', source="winrm/ps"))
            db.commit()
            findings = get_findings(device.id, finding_type=None, db=db, _=None)
            self.assertEqual({f.collection_source for f in findings}, {"windows_agent", "winrm"})
            status = get_agent_status(device.id, db=db, _=None)
            self.assertEqual(status["last_run_id"], result["run_id"])
            self.assertNotIn("secret_hash", status)
            agent.last_seen_at = datetime.utcnow() - timedelta(minutes=1)
            db.commit()
            payload.sequence = 2
            report_agent_inventory(payload, authorization="Bearer " + credential, db=db)
            self.assertEqual(db.query(DeviceChangeEvent).filter_by(device_id=device.id, source="lanlens_windows_agent", event_type="agent_inventory_received").count(), 1)
            # Simulate a pre-upgrade installation with accepted reports but no timeline.
            db.query(DeviceChangeEvent).filter_by(device_id=device.id).delete()
            agent.last_seen_at = datetime.utcnow() - timedelta(minutes=1)
            db.commit()
            payload.sequence = 3
            report_agent_inventory(payload, authorization="Bearer " + credential, db=db)
            self.assertEqual(db.query(DeviceChangeEvent).filter_by(device_id=device.id, source="lanlens_windows_agent", event_type="agent_inventory_received").count(), 1)
            agent.last_seen_at = datetime.utcnow() - timedelta(minutes=1)
            db.commit()
            payload.sequence = 4
            payload.software = [{"name":"Example", "version":"2"}]
            report_agent_inventory(payload, authorization="Bearer " + credential, db=db)
            self.assertEqual(db.query(DeviceChangeEvent).filter_by(device_id=device.id, source="lanlens_windows_agent", event_type="agent_inventory_received").count(), 2)
            change = db.query(DeviceChangeEvent).filter_by(device_id=device.id, source="lanlens_windows_agent",
                event_type="inventory_finding_changed", field_name="software/installed_software").one()
            self.assertIn("Example 2", change.message)
            self.assertIn("Example 1", change.message)
        finally:
            db.close()

    def test_credential_scan_timeline_keeps_independent_source(self):
        import json
        from backend.models import DeepScanRun, DeviceChangeEvent
        from backend.services.inventory_timeline import record_inventory_changes
        db = self.Session()
        try:
            device = Device(mac_address="00:11:22:33:44:98")
            db.add(device)
            db.flush()
            for value, transport, event_source in [("8 GB", "ssh", "ssh"), ("16 GB", "winrm", "winrm"), ("8 GB", "ssh", "ssh"), ("32 GB", "ssh", "ssh")]:
                run = DeepScanRun(device_id=device.id, profile="full", status="done")
                db.add(run)
                db.flush()
                db.add(DeepScanFinding(device_id=device.id, run_id=run.id, finding_type="hardware", key="memory", value_json=json.dumps(value), source="winrm/ps" if transport == "winrm" else "free"))
                record_inventory_changes(db, run, transport, event_source)
                db.commit()
            events = db.query(DeviceChangeEvent).filter_by(device_id=device.id, source="ssh").order_by(DeviceChangeEvent.id).all()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[-1].old_value, "8 GB")
            self.assertEqual(events[-1].new_value, "32 GB")
        finally:
            db.close()

    def test_agent_can_unenroll_without_deleting_device(self):
        from backend.routers.agents import unenroll_agent
        db = self.Session()
        try:
            raw = "u" * 32
            db.add(AgentEnrollmentToken(name="test", token_hash=_sha256(raw)))
            db.commit()
            enrolled = enroll_agent(AgentEnrollRequest(token=raw, hostname="test", primary_mac="00:11:22:33:44:88"), db)
            credential = enrolled["agent_id"] + "." + enrolled["agent_secret"]
            self.assertEqual(unenroll_agent(authorization="Bearer " + credential, db=db)["status"], "revoked")
            self.assertIsNotNone(db.get(Device, enrolled["device_id"]))
            with self.assertRaises(HTTPException):
                _authenticated_agent("Bearer " + credential, db)
            self.assertIsNotNone(db.query(AgentEnrollmentToken).filter_by(token_hash=_sha256(raw)).one().revoked_at)
        finally:
            db.close()

    def test_report_rejects_oversized_findings(self):
        with self.assertRaises(ValidationError):
            AgentReportRequest(sequence=1, hostname='host', primary_mac='00:11:22:33:44:55',
                               findings=[{'finding_type': 'hardware', 'key': 'cpu', 'value': 'x' * 160001}])
