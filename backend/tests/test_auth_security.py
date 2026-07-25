import os

import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-auth-security-12345")

from backend.auth.jwt_handler import create_access_token, decode_token
from backend.config import settings


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
