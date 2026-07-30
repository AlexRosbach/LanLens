import os
from unittest.mock import MagicMock, patch

import jwt
import paramiko

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-auth-security-12345")

from backend.auth.jwt_handler import create_access_token, decode_token
from backend.config import settings
from backend.services.ssh_security import create_verified_ssh_client


def test_access_token_round_trip_uses_hs256():
    token = create_access_token("admin")
    header = jwt.get_unverified_header(token)

    assert header["alg"] == "HS256"
    assert decode_token(token)["sub"] == "admin"


def test_decode_rejects_token_signed_with_other_algorithm():
    token = jwt.encode(
        {"sub": "admin", "type": "access"},
        settings.secret_key,
        algorithm="HS384",
    )

    assert decode_token(token) is None


def test_ssh_client_rejects_unknown_hosts_and_loads_persisted_known_hosts():
    client = MagicMock()
    with (
        patch("paramiko.SSHClient", return_value=client),
        patch("backend.services.ssh_security.os.path.isfile", return_value=True),
        patch.dict(os.environ, {"LANLENS_SSH_KNOWN_HOSTS": "/data/test_known_hosts"}),
    ):
        result = create_verified_ssh_client()

    assert result is client
    client.load_system_host_keys.assert_called_once_with()
    client.load_host_keys.assert_called_once_with("/data/test_known_hosts")
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)
