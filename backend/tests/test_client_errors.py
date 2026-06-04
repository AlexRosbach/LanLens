import logging
import os
import unittest

from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-client-error-logs-12345")

from backend.main import app


class ClientErrorLogTests(unittest.TestCase):
    def test_client_error_endpoint_logs_sanitized_ui_error(self):
        client = TestClient(app)
        with self.assertLogs("lanlens.client_errors", level=logging.WARNING) as logs:
            response = client.post(
                "/api/client-errors",
                json={
                    "kind": "toast",
                    "message": "Save failed token=abc123 password:secret",
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
        self.assertNotIn("abc123", output)
        self.assertNotIn("password:secret", output)


if __name__ == "__main__":
    unittest.main()
