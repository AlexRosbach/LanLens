import struct
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.agents import router


class WindowsAgentIconTests(unittest.TestCase):
    def test_installer_can_download_complete_multisize_icon_without_session(self):
        app = FastAPI()
        app.include_router(router)
        response = TestClient(app).get("/api/agents/windows/LanLensAgent.ico")
        expected = (Path(__file__).resolve().parents[1] / "assets/windows_agent/LanLensAgent.ico").read_bytes()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/x-icon")
        self.assertEqual(response.content, expected)

        # Windows selects different frames for Explorer and Installed Apps.
        reserved, kind, count = struct.unpack_from("<HHH", response.content)
        self.assertEqual((reserved, kind, count), (0, 1, 7))
        sizes = set()
        for index in range(count):
            width, height, _, _, planes, bits, length, offset = struct.unpack_from(
                "<BBBBHHII", response.content, 6 + 16 * index,
            )
            self.assertEqual(width, height)
            self.assertEqual((planes, bits), (1, 32))
            self.assertGreater(length, 0)
            self.assertGreaterEqual(offset, 6 + 16 * count)
            self.assertLessEqual(offset + length, len(response.content))
            sizes.add(width or 256)
        self.assertEqual(sizes, {16, 24, 32, 48, 64, 128, 256})
