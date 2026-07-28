import sys
from types import SimpleNamespace

import pytest

from backend.routers.credentials import _load_private_key
from backend.services.deep_scanner import _load_ssh_private_key


class _AcceptedKey:
    @classmethod
    def from_private_key(cls, key_file):
        return ("accepted", key_file.read())


class _RejectedKey:
    @classmethod
    def from_private_key(cls, key_file):
        raise ValueError("wrong key type")


@pytest.mark.parametrize("loader", [_load_private_key, _load_ssh_private_key])
def test_private_key_loader_works_without_removed_dss_key(monkeypatch, loader):
    paramiko_without_dss = SimpleNamespace(
        RSAKey=_AcceptedKey,
        Ed25519Key=_RejectedKey,
        ECDSAKey=_RejectedKey,
    )
    monkeypatch.setitem(sys.modules, "paramiko", paramiko_without_dss)

    assert loader("private-key-data") == ("accepted", "private-key-data")
