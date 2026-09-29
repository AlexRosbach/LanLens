"""Shared SSH host-key verification for credential tests and deep scans."""
from __future__ import annotations

import os

DEFAULT_KNOWN_HOSTS_PATH = "/data/ssh_known_hosts"


def create_verified_ssh_client():
    import paramiko  # type: ignore

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    known_hosts_path = os.getenv("LANLENS_SSH_KNOWN_HOSTS", DEFAULT_KNOWN_HOSTS_PATH)
    if known_hosts_path and os.path.isfile(known_hosts_path):
        client.load_host_keys(known_hosts_path)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    return client
