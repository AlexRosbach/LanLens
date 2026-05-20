import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.services import https_config


class HttpsConfigTests(unittest.TestCase):
    def test_save_https_config_validates_and_persists_key_pair(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_dir = Path(tmp_name)
            source_cert = tmp_dir / "source.crt"
            source_key = tmp_dir / "source.key"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(source_key),
                    "-out",
                    str(source_cert),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=lanlens.local",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            original_paths = (
                https_config.TLS_DIR,
                https_config.CONFIG_PATH,
                https_config.CERT_PATH,
                https_config.KEY_PATH,
                https_config.CHAIN_PATH,
            )
            https_config.TLS_DIR = tmp_dir / "tls"
            https_config.CONFIG_PATH = https_config.TLS_DIR / "config.json"
            https_config.CERT_PATH = https_config.TLS_DIR / "lanlens.crt"
            https_config.KEY_PATH = https_config.TLS_DIR / "lanlens.key"
            https_config.CHAIN_PATH = https_config.TLS_DIR / "lanlens.chain.crt"
            try:
                result = https_config.save_https_config(
                    enabled=True,
                    port=9443,
                    redirect_http=True,
                    certificate=source_cert.read_bytes(),
                    private_key=source_key.read_bytes(),
                )
            finally:
                (
                    https_config.TLS_DIR,
                    https_config.CONFIG_PATH,
                    https_config.CERT_PATH,
                    https_config.KEY_PATH,
                    https_config.CHAIN_PATH,
                ) = original_paths

            self.assertTrue(result["enabled"])
            self.assertTrue(result["configured"])
            self.assertEqual(result["port"], 9443)

    def test_rejects_enabling_https_without_certificate_pair(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_dir = Path(tmp_name)
            original_paths = (
                https_config.TLS_DIR,
                https_config.CONFIG_PATH,
                https_config.CERT_PATH,
                https_config.KEY_PATH,
                https_config.CHAIN_PATH,
            )
            https_config.TLS_DIR = tmp_dir / "tls"
            https_config.CONFIG_PATH = https_config.TLS_DIR / "config.json"
            https_config.CERT_PATH = https_config.TLS_DIR / "lanlens.crt"
            https_config.KEY_PATH = https_config.TLS_DIR / "lanlens.key"
            https_config.CHAIN_PATH = https_config.TLS_DIR / "lanlens.chain.crt"
            try:
                with self.assertRaises(ValueError):
                    https_config.save_https_config(enabled=True, port=9443, redirect_http=False)
            finally:
                (
                    https_config.TLS_DIR,
                    https_config.CONFIG_PATH,
                    https_config.CERT_PATH,
                    https_config.KEY_PATH,
                    https_config.CHAIN_PATH,
                ) = original_paths


if __name__ == "__main__":
    unittest.main()
