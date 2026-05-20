from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

TLS_DIR = Path(os.getenv("LANLENS_TLS_DIR", "/data/tls"))
CONFIG_PATH = TLS_DIR / "config.json"
CERT_PATH = TLS_DIR / "lanlens.crt"
KEY_PATH = TLS_DIR / "lanlens.key"
CHAIN_PATH = TLS_DIR / "lanlens.chain.crt"
RENDER_SCRIPT = os.getenv("LANLENS_NGINX_RENDER_SCRIPT", "/usr/local/bin/render-lanlens-nginx")


def _default_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "port": int(os.getenv("LANLENS_PORT", "7765") or "7765"),
        "redirect_http": False,
        "certificate_path": str(CERT_PATH),
        "private_key_path": str(KEY_PATH),
        "updated_at": None,
    }


def load_https_config() -> dict[str, Any]:
    config = _default_config()
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                config.update(stored)
        except (OSError, json.JSONDecodeError):
            pass
    config["configured"] = CERT_PATH.exists() and KEY_PATH.exists()
    return config


def validate_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise ValueError("HTTPS port must be between 1 and 65535")
    return port


def validate_certificate_pair(certificate_path: Path, private_key_path: Path) -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(certificate_path), keyfile=str(private_key_path))


def _atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_https_config(
    *,
    enabled: bool,
    port: int,
    redirect_http: bool,
    certificate: Optional[bytes] = None,
    private_key: Optional[bytes] = None,
    chain: Optional[bytes] = None,
) -> dict[str, Any]:
    port = validate_port(port)
    TLS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(TLS_DIR)) as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        candidate_cert = tmp_dir / "lanlens.crt"
        candidate_key = tmp_dir / "lanlens.key"

        if certificate is not None:
            full_certificate = certificate.strip() + b"\n"
            if chain:
                full_certificate += chain.strip() + b"\n"
            _atomic_write(candidate_cert, full_certificate)
        elif CERT_PATH.exists():
            shutil.copyfile(CERT_PATH, candidate_cert)
            if chain:
                with candidate_cert.open("ab") as fh:
                    fh.write(chain.strip() + b"\n")

        if private_key is not None:
            _atomic_write(candidate_key, private_key.strip() + b"\n", mode=0o600)
        elif KEY_PATH.exists():
            shutil.copyfile(KEY_PATH, candidate_key)
            os.chmod(candidate_key, 0o600)

        configured = candidate_cert.exists() and candidate_key.exists()
        if enabled and not configured:
            raise ValueError("Certificate and private key are required before HTTPS can be enabled")
        if configured:
            try:
                validate_certificate_pair(candidate_cert, candidate_key)
            except ssl.SSLError as exc:
                raise ValueError(f"Certificate and private key could not be loaded: {exc}") from exc

        if candidate_cert.exists():
            shutil.copyfile(candidate_cert, CERT_PATH)
            os.chmod(CERT_PATH, 0o644)
        if candidate_key.exists():
            shutil.copyfile(candidate_key, KEY_PATH)
            os.chmod(KEY_PATH, 0o600)
        if chain is not None:
            _atomic_write(CHAIN_PATH, chain.strip() + b"\n")

    config = {
        "enabled": enabled,
        "port": port,
        "redirect_http": redirect_http,
        "certificate_path": str(CERT_PATH),
        "private_key_path": str(KEY_PATH),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(CONFIG_PATH, json.dumps(config, indent=2).encode("utf-8") + b"\n")
    config["configured"] = CERT_PATH.exists() and KEY_PATH.exists()
    return config


def apply_nginx_config() -> None:
    if not Path(RENDER_SCRIPT).exists():
        return
    subprocess.run([RENDER_SCRIPT], check=True)
    subprocess.run(["nginx", "-s", "reload"], check=True)
