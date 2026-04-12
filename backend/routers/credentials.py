"""Credential vault CRUD — encrypted SSH and WinRM credentials."""

import asyncio
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Credential, DeviceDeepScanConfig, User
from ..schemas import (
    CredentialCreate,
    CredentialResponse,
    CredentialTestRequest,
    CredentialTestResponse,
    CredentialUpdate,
    CREDENTIAL_TYPES,
    MessageResponse,
)
from ..services.crypto import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def _to_response(cred: Credential) -> CredentialResponse:
    return CredentialResponse(
        id=cred.id,
        name=cred.name,
        credential_type=cred.credential_type,
        auth_method=getattr(cred, "auth_method", "password") or "password",
        username=cred.username,
        description=cred.description,
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


@router.get("", response_model=List[CredentialResponse])
def list_credentials(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[CredentialResponse]:
    creds = db.query(Credential).order_by(Credential.name).all()
    return [_to_response(c) for c in creds]


@router.post("", response_model=CredentialResponse, status_code=201)
def create_credential(
    data: CredentialCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CredentialResponse:
    if data.credential_type not in CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid credential_type. Must be one of: {CREDENTIAL_TYPES}",
        )
    if not data.secret.strip():
        raise HTTPException(status_code=400, detail="secret must not be empty")
    if not data.username.strip():
        raise HTTPException(status_code=400, detail="username must not be empty")

    cred = Credential(
        name=data.name,
        credential_type=data.credential_type,
        auth_method=data.auth_method or "password",
        username=data.username,
        encrypted_secret=encrypt_secret(data.secret),
        description=data.description,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return _to_response(cred)


@router.get("/{credential_id}", response_model=CredentialResponse)
def get_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CredentialResponse:
    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    return _to_response(cred)


@router.put("/{credential_id}", response_model=CredentialResponse)
def update_credential(
    credential_id: int,
    data: CredentialUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CredentialResponse:
    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    if data.credential_type is not None and data.credential_type not in CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid credential_type. Must be one of: {CREDENTIAL_TYPES}",
        )

    if data.name is not None:
        cred.name = data.name
    if data.credential_type is not None:
        cred.credential_type = data.credential_type
    if data.auth_method is not None:
        cred.auth_method = data.auth_method
    if data.username is not None:
        cred.username = data.username
    if data.description is not None:
        cred.description = data.description
    if data.secret and data.secret.strip():
        cred.encrypted_secret = encrypt_secret(data.secret)

    db.commit()
    db.refresh(cred)
    return _to_response(cred)


@router.delete("/{credential_id}", response_model=MessageResponse)
def delete_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MessageResponse:
    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    in_use = (
        db.query(DeviceDeepScanConfig)
        .filter(DeviceDeepScanConfig.credential_id == credential_id)
        .count()
    )
    if in_use:
        raise HTTPException(
            status_code=400,
            detail=f"Credential is assigned to {in_use} device(s). Unassign it first.",
        )

    db.delete(cred)
    db.commit()
    return MessageResponse(message="Credential deleted")


@router.post("/{credential_id}/test", response_model=CredentialTestResponse)
async def test_credential(
    credential_id: int,
    body: CredentialTestRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CredentialTestResponse:
    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        secret = decrypt_secret(cred.encrypted_secret)
    except ValueError as exc:
        return CredentialTestResponse(success=False, message=str(exc))

    target_ip = body.target_ip.strip()
    if not target_ip:
        raise HTTPException(status_code=400, detail="target_ip must not be empty")

    auth_method = getattr(cred, "auth_method", "password") or "password"
    if cred.credential_type == "linux_ssh":
        result = await asyncio.get_event_loop().run_in_executor(
            None, _test_ssh, target_ip, cred.username, secret, auth_method
        )
    elif cred.credential_type == "windows_winrm":
        result = await asyncio.get_event_loop().run_in_executor(
            None, _test_winrm, target_ip, cred.username, secret
        )
    else:
        return CredentialTestResponse(
            success=False, message=f"Unknown credential type: {cred.credential_type}"
        )

    return result


def _load_private_key(key_text: str):
    """Try to load an SSH private key from PEM string. Returns paramiko PKey or None."""
    try:
        import paramiko  # type: ignore
        import io
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey):
            try:
                return cls.from_private_key(io.StringIO(key_text))
            except Exception:
                continue
    except ImportError:
        pass
    return None


def _test_ssh(ip: str, username: str, secret: str, auth_method: str = "password") -> CredentialTestResponse:
    try:
        import paramiko  # type: ignore
    except ImportError:
        return CredentialTestResponse(
            success=False,
            message="paramiko is not installed. Cannot test SSH connection.",
        )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    start = time.monotonic()
    try:
        if auth_method == "key":
            pkey = _load_private_key(secret)
            if pkey is None:
                return CredentialTestResponse(success=False, message="Could not parse SSH private key. Ensure it is a valid PEM-format key.")
            client.connect(
                hostname=ip,
                username=username,
                pkey=pkey,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
        else:
            client.connect(
                hostname=ip,
                username=username,
                password=secret,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
        _, stdout, _ = client.exec_command("echo ok", timeout=5)
        stdout.read()
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return CredentialTestResponse(
            success=True,
            message=f"SSH connection to {ip} successful",
            latency_ms=latency_ms,
        )
    except Exception as exc:
        return CredentialTestResponse(success=False, message=str(exc))
    finally:
        client.close()


def _test_winrm(ip: str, username: str, secret: str) -> CredentialTestResponse:
    try:
        import winrm  # type: ignore
    except ImportError:
        return CredentialTestResponse(
            success=False,
            message="pywinrm is not installed. Cannot test WinRM connection.",
        )
    start = time.monotonic()
    try:
        session = winrm.Session(
            f"http://{ip}:5985/wsman",
            auth=(username, secret),
            transport="ntlm",
            server_cert_validation="ignore",
            read_timeout_sec=15,
            operation_timeout_sec=12,
        )
        result = session.run_ps("echo ok")
        if result.status_code != 0:
            raise RuntimeError(result.std_err.decode(errors="replace").strip())
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return CredentialTestResponse(
            success=True,
            message=f"WinRM connection to {ip} successful",
            latency_ms=latency_ms,
        )
    except Exception as exc:
        return CredentialTestResponse(success=False, message=str(exc))
