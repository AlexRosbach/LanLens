import logging
import os
import unittest

from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-client-error-logs-12345")

from backend.main import app
from backend.routers import client_errors


class ClientErrorLogTests(unittest.TestCase):
    def setUp(self):
        client_errors._client_error_hits.clear()

    def test_client_error_endpoint_logs_sanitized_ui_error(self):
        client = TestClient(app)
        with self.assertLogs("lanlens.client_errors", level=logging.WARNING) as logs:
            response = client.post(
                "/api/client-errors",
                json={
                    "kind": "toast",
                    "message": "Save failed token=abc123 password:secret Authorization: Bearer top-secret-token",
                    "path": "/settings",
                    "source": "toast.error",
                    "status": 500,
                    "endpoint": "/settings/passive-discovery",
                },
                headers={"user-agent": "LanLens test"},
            )

        self.assertEqual(response.status_code, 200)
        output = "\n".join(logs.output)
        self.assertIn("Client UI error", output)
        self.assertIn("/settings/passive-discovery", output)
        self.assertIn("token=[redacted]", output)
        self.assertIn("password=[redacted]", output)
        self.assertIn("authorization=[redacted]", output)
        self.assertNotIn("abc123", output)
        self.assertNotIn("password:secret", output)
        self.assertNotIn("top-secret-token", output)

    def test_client_error_endpoint_throttles_log_spam_per_client(self):
        client = TestClient(app)
        payload = {
            "kind": "toast",
            "message": "Repeated failure",
            "path": "/settings",
            "source": "toast.error",
        }
        with self.assertLogs("lanlens.client_errors", level=logging.WARNING) as logs:
            for _ in range(client_errors.CLIENT_ERROR_RATE_LIMIT):
                response = client.post("/api/client-errors", json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("throttled", response.json())
            response = client.post("/api/client-errors", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["throttled"])
        self.assertEqual(len(logs.output), client_errors.CLIENT_ERROR_RATE_LIMIT)

    def test_client_error_endpoint_throttles_by_real_client_ip(self):
        client = TestClient(app)
        payload = {
            "kind": "toast",
            "message": "Repeated failure",
            "path": "/settings",
            "source": "toast.error",
        }

        with self.assertLogs("lanlens.client_errors", level=logging.WARNING) as logs:
            for _ in range(client_errors.CLIENT_ERROR_RATE_LIMIT):
                response = client.post(
                    "/api/client-errors",
                    json=payload,
                    headers={"x-real-ip": "203.0.113.10"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("throttled", response.json())

            response = client.post(
                "/api/client-errors",
                json=payload,
                headers={"x-real-ip": "203.0.113.11"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("throttled", response.json())
        self.assertEqual(len(logs.output), client_errors.CLIENT_ERROR_RATE_LIMIT + 1)
        self.assertIn("client_ip=203.0.113.10", "\n".join(logs.output))
        self.assertIn("client_ip=203.0.113.11", "\n".join(logs.output))

    def test_client_error_endpoint_uses_last_forwarded_hop(self):
        client = TestClient(app)
        response = client.post(
            "/api/client-errors",
            json={"message": "Forwarded request"},
            headers={"x-forwarded-for": "198.51.100.99, 203.0.113.20"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("203.0.113.20", client_errors._client_error_hits)
        self.assertNotIn("198.51.100.99", client_errors._client_error_hits)

    def test_client_error_rate_limit_prunes_expired_clients(self):
        old_hit = 1.0
        for index in range(client_errors.CLIENT_ERROR_RATE_MAX_CLIENTS + 5):
            client_errors._client_error_hits[f"198.51.100.{index}"] = [old_hit]

        self.assertFalse(client_errors._rate_limited("203.0.113.30", now=old_hit + client_errors.CLIENT_ERROR_RATE_WINDOW_SECONDS + 1))

        self.assertLessEqual(len(client_errors._client_error_hits), client_errors.CLIENT_ERROR_RATE_MAX_CLIENTS)
        self.assertIn("203.0.113.30", client_errors._client_error_hits)


if __name__ == "__main__":
    unittest.main()
