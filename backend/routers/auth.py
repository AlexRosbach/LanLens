from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..auth.jwt_handler import create_access_token, decode_token
from ..auth.password import hash_password, verify_password
from ..config import settings
from ..database import get_db
from ..models import TokenBlacklist, User
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer()


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user.last_login = datetime.utcnow()
    db.commit()

    access_token = create_access_token(subject=user.username)
    return TokenResponse(
        access_token=access_token,
        force_password_change=user.force_password_change,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Blacklist the current JWT so it cannot be reused after logout."""
    payload = decode_token(credentials.credentials)
    if payload and payload.get("jti") and payload.get("exp"):
        expires_at = datetime.utcfromtimestamp(payload["exp"])
        # Avoid duplicates (idempotent logout)
        if not db.query(TokenBlacklist).filter(TokenBlacklist.jti == payload["jti"]).first():
            db.add(TokenBlacklist(jti=payload["jti"], expires_at=expires_at))
            db.commit()
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )

    current_user.password_hash = hash_password(request.new_password)
    current_user.force_password_change = False
    db.commit()

    return MessageResponse(message="Password changed successfully")
