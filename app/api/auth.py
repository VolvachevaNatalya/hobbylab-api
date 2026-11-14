import hmac
import logging
import os
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import decode_refresh_token, get_current_user
from app.core.email import send_password_reset_otp
from app.db.dependencies import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from fastapi.security import OAuth2PasswordRequestForm

logger = logging.getLogger(__name__)

router = APIRouter()

# --- In-process IP-based rate limiter for POST /auth/register ---
# Stores timestamps of recent attempts per IP; trimmed on every check.
# Works for single-process deployments (Railway default).
_REGISTRATION_RATE_LIMIT = 3            # max successful-attempt slots per IP
_REGISTRATION_RATE_WINDOW = timedelta(hours=1)

_reg_attempts: Dict[str, List[datetime]] = defaultdict(list)
_reg_lock = threading.Lock()

# --- In-process IP-based rate limiter for login and OAuth login endpoints ---
# Login attempts share one tight bucket (password-guessing prevention).
_LOGIN_RATE_LIMIT = 10
_LOGIN_RATE_WINDOW = timedelta(minutes=15)

_login_attempts: Dict[str, List[datetime]] = defaultdict(list)
_login_lock = threading.Lock()

# --- In-process IP-based rate limiter for POST /auth/refresh ---
# Separate, more lenient bucket: refresh is auto-triggered by the app (not a
# user action) and multiple users behind the same NAT legitimately refresh at
# the same time when their 60-minute tokens expire simultaneously.
_REFRESH_RATE_LIMIT = 30
_REFRESH_RATE_WINDOW = timedelta(minutes=15)

_refresh_attempts: Dict[str, List[datetime]] = defaultdict(list)
_refresh_lock = threading.Lock()

# --- In-process IP-based rate limiter for POST /auth/forgot-password ---
# Tight limit: prevents OTP generation abuse and email flooding.
_FORGOT_RATE_LIMIT = 3
_FORGOT_RATE_WINDOW = timedelta(minutes=15)

_forgot_attempts: Dict[str, List[datetime]] = defaultdict(list)
_forgot_lock = threading.Lock()

# --- In-process IP-based rate limiter for POST /auth/reset-password ---
# Separate from the forgot-password bucket so that requesting the OTP
# multiple times (e.g. waiting for a slow email) does not consume attempts
# for actually applying the reset.  Still tight enough to block guessing.
_RESET_RATE_LIMIT = 5
_RESET_RATE_WINDOW = timedelta(minutes=15)

_reset_attempts: Dict[str, List[datetime]] = defaultdict(list)
_reset_lock = threading.Lock()

_OTP_TTL = timedelta(minutes=15)

# Per-token wrong-guess limit stored in DB — cannot be bypassed by rotating
# IPs or restarting backend workers.  Only the reset challenge is locked;
# normal login is completely unaffected.
_MAX_OTP_ATTEMPTS = 10

# Maximum new reset tokens issued per account per hour.  Tokens are soft-
# expired (not deleted) so the hourly count accumulates across requests.
_OTP_HOURLY_ISSUANCE = 5

# HMAC key for OTP hashing.  A short-lived 6-digit OTP has only 10^6 possible
# values, so a plain SHA-256 is reversible in <1 ms if the token table is ever
# exfiltrated.  Keying the hash with a server secret makes it irreversible
# without the key even with a full DB dump.
#
# Set OTP_HMAC_KEY in production (high-entropy random string, separate from the
# JWT secret).  Falls back to JWT_SECRET so the app starts without extra config.
_OTP_HMAC_KEY: bytes = (
    os.getenv("OTP_HMAC_KEY") or os.getenv("JWT_SECRET", "change-me-in-production")
).encode()


def _hash_otp(otp: str) -> str:
    """HMAC-SHA256 of *otp* under the server secret key."""
    return hmac.new(_OTP_HMAC_KEY, otp.encode(), "sha256").hexdigest()


def _get_client_ip(request: Request) -> str:
    # Railway's routing layer sets X-Real-IP to the actual client IP before
    # forwarding the request to the dyno.  The dyno port is not publicly
    # reachable, so only Railway's proxy can set this header in production.
    # Trusting it without an explicit allowlist is acceptable for a Railway
    # single-dyno deployment; revisit if the app is ever exposed via a
    # different ingress path.
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_registration_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _REGISTRATION_RATE_WINDOW
    with _reg_lock:
        recent = [t for t in _reg_attempts[ip] if t > cutoff]
        if len(recent) >= _REGISTRATION_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many registration attempts. Try again later.",
            )
        recent.append(now)
        _reg_attempts[ip] = recent


def _check_login_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _LOGIN_RATE_WINDOW
    with _login_lock:
        recent = [t for t in _login_attempts[ip] if t > cutoff]
        if len(recent) >= _LOGIN_RATE_LIMIT:
            oldest = min(recent)
            retry_after = max(1, int((oldest + _LOGIN_RATE_WINDOW - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _login_attempts[ip] = recent


def _check_forgot_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _FORGOT_RATE_WINDOW
    with _forgot_lock:
        recent = [t for t in _forgot_attempts[ip] if t > cutoff]
        if len(recent) >= _FORGOT_RATE_LIMIT:
            oldest = min(recent)
            retry_after = max(1, int((oldest + _FORGOT_RATE_WINDOW - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many reset attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _forgot_attempts[ip] = recent


def _check_reset_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _RESET_RATE_WINDOW
    with _reset_lock:
        recent = [t for t in _reset_attempts[ip] if t > cutoff]
        if len(recent) >= _RESET_RATE_LIMIT:
            oldest = min(recent)
            retry_after = max(1, int((oldest + _RESET_RATE_WINDOW - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many reset attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _reset_attempts[ip] = recent


def _check_refresh_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _REFRESH_RATE_WINDOW
    with _refresh_lock:
        recent = [t for t in _refresh_attempts[ip] if t > cutoff]
        if len(recent) >= _REFRESH_RATE_LIMIT:
            oldest = min(recent)
            retry_after = max(1, int((oldest + _REFRESH_RATE_WINDOW - now).total_seconds()) + 1)
            raise HTTPException(
                status_code=429,
                detail="Too many refresh attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _refresh_attempts[ip] = recent


class GoogleLoginRequest(BaseModel):
    id_token: str


class FacebookLoginRequest(BaseModel):
    access_token: str


class AppleLoginRequest(BaseModel):
    id_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str


@router.post("/auth/login")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    user = db.query(User).filter(User.email == form_data.username).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/refresh")
def refresh_tokens(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access token and rotated refresh token."""
    _check_refresh_rate_limit(_get_client_ip(request))
    user = decode_refresh_token(payload.refresh_token, db)
    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }

@router.post("/auth/register", response_model=UserResponse)
def create_user(user: UserCreate, request: Request, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    ua = request.headers.get("User-Agent", "")[:200]

    _check_registration_rate_limit(ip)

    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        logger.warning(
            "registration duplicate | endpoint=POST /auth/register | ip=%s | ua=%s | email=%s",
            ip, ua, user.email,
        )
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = hash_password(user.password)

    db_user = User(
        email=user.email,
        name=user.name,
        phone=user.phone,
        avatar_url=user.avatar_url,
        provider=user.provider,
        provider_user_id=user.provider_user_id,
        password_hash=hashed,
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    logger.info(
        "registration success | endpoint=POST /auth/register | ip=%s | ua=%s | email=%s | user_id=%d",
        ip, ua, db_user.email, db_user.id,
    )

    return db_user


@router.post("/auth/google-login")
def google_login(request: Request, payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    client_ids = [cid.strip() for cid in os.getenv("GOOGLE_CLIENT_ID", "").split(",") if cid.strip()]
    if not client_ids:
        raise HTTPException(status_code=500, detail="Google login not configured on server")

    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            client_ids,
        )
    except ValueError as e:
        logger.warning("google_token_validation_failed | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    email: str = id_info.get("email", "")
    name: str = id_info.get("name") or email.split("@")[0]
    google_sub: str = id_info.get("sub", "")

    if not email:
        raise HTTPException(status_code=400, detail="Google token did not include an email address")

    user = db.query(User).filter(User.email == email).first()

    if not user:
        user = User(
            email=email,
            name=name,
            provider="google",
            provider_user_id=google_sub,
            password_hash=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/facebook-login")
def facebook_login(request: Request, payload: FacebookLoginRequest, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    import httpx

    try:
        response = httpx.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,name,email", "access_token": payload.access_token},
            timeout=10,
        )
    except httpx.RequestError as e:
        logger.warning("facebook_api_unreachable | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=502, detail="Could not reach Facebook API")

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    data = response.json()

    if "error" in data:
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    email: str = data.get("email", "")
    name: str = data.get("name") or ""
    facebook_id: str = data.get("id", "")

    if email:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                name=name or email.split("@")[0],
                provider="facebook",
                provider_user_id=facebook_id,
                password_hash=None,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    else:
        fallback_email = f"facebook_{facebook_id}@facebook.local"
        user = db.query(User).filter(
            User.provider == "facebook",
            User.provider_user_id == facebook_id,
        ).first()
        if not user:
            user = User(
                email=fallback_email,
                name=name or fallback_email,
                provider="facebook",
                provider_user_id=facebook_id,
                password_hash=None,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/apple-login")
def apple_login(request: Request, payload: AppleLoginRequest, db: Session = Depends(get_db)):
    ip = _get_client_ip(request)
    _check_login_rate_limit(ip)

    import httpx
    from jose import jwt, JWTError

    APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
    APPLE_ISSUER = "https://appleid.apple.com"
    APPLE_CLIENT_ID = "il.co.hobbylab.app"

    try:
        jwks_response = httpx.get(APPLE_JWKS_URL, timeout=10)
    except httpx.RequestError as e:
        logger.warning("apple_jwks_unreachable | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=502, detail="Could not reach Apple authentication service")

    if jwks_response.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch Apple public keys")

    jwks = jwks_response.json()

    try:
        claims = jwt.decode(
            payload.id_token,
            jwks,
            algorithms=["RS256"],
            audience=APPLE_CLIENT_ID,
            issuer=APPLE_ISSUER,
        )
    except JWTError as e:
        logger.warning("apple_token_validation_failed | ip=%s | error=%s", ip, e)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    apple_sub: str = claims.get("sub", "")
    email: str = claims.get("email", "")

    if not apple_sub:
        raise HTTPException(status_code=400, detail="Apple token missing sub claim")

    if email:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                name=email.split("@")[0],
                provider="apple",
                provider_user_id=apple_sub,
                password_hash=None,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    else:
        fallback_email = f"apple_{apple_sub}@apple.local"
        user = db.query(User).filter(
            User.provider == "apple",
            User.provider_user_id == apple_sub,
        ).first()
        if not user:
            user = User(
                email=fallback_email,
                name=fallback_email,
                provider="apple",
                provider_user_id=apple_sub,
                password_hash=None,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is not active")

    tv = user.token_version or 0
    return {
        "access_token": create_access_token({"user_id": user.id, "tv": tv}),
        "refresh_token": create_refresh_token({"user_id": user.id, "tv": tv}),
        "token_type": "bearer",
    }


@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = hash_password(payload.new_password)
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()
    return {"message": "Password changed successfully"}


@router.post("/auth/forgot-password")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password-reset OTP.

    Always returns 200 regardless of whether the email exists so that callers
    cannot enumerate registered accounts by observing different responses.
    The OTP is delivered by email when SMTP is configured; without SMTP the
    token is still stored in the database but no message is sent.
    """
    ip = _get_client_ip(request)
    _check_forgot_rate_limit(ip)

    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user and user.status == "active":
        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)

        # Serialize concurrent requests for the same user via a row-level lock.
        #
        # Without this, two concurrent transactions can both read the same
        # stale hourly count (READ COMMITTED snapshot), both pass the < limit
        # check, and both insert — leaving the hourly cap exceeded AND two
        # simultaneously active tokens.  The double-token problem arises because
        # the second transaction's soft-expire UPDATE runs after the first has
        # committed its new token, but the UPDATE only sees rows that existed
        # at statement-start (PostgreSQL READ COMMITTED), so it misses the
        # first transaction's freshly inserted token.
        #
        # SELECT … FOR UPDATE acquires an exclusive row lock on the user row.
        # The second concurrent transaction blocks here until the first commits,
        # then re-reads a current count — preventing both overruns.
        #
        # SQLAlchemy silently drops FOR UPDATE on SQLite, which is safe because
        # the test pool (StaticPool) uses a single connection.
        db.query(User).filter(User.id == user.id).with_for_update().first()

        # Per-account hourly issuance limit (IP-resistant).
        # Tokens are soft-expired rather than deleted so this count accumulates
        # across requests and cannot be reset by an attacker rotating IPs.
        recent_count = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at > hour_ago,
        ).count()

        if recent_count < _OTP_HOURLY_ISSUANCE:
            # Soft-expire (do not delete) any currently active token so the
            # created_at history needed for the hourly count stays in the DB.
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            ).update({"expires_at": now}, synchronize_session="evaluate")
            db.flush()

            otp = f"{secrets.randbelow(10 ** 6):06d}"
            otp_hash = _hash_otp(otp)
            token_row = PasswordResetToken(
                user_id=user.id,
                otp_hash=otp_hash,
                expires_at=now + _OTP_TTL,
            )
            db.add(token_row)
            db.commit()

            # Fire-and-forget: errors are logged inside send_password_reset_otp.
            send_password_reset_otp(user.email, otp)
        # else: silently refuse — same 200 response (enumeration prevention).

    # Always return the same response — do not reveal whether the email exists.
    return {"message": "If that email is registered, a reset code has been sent."}


@router.post("/auth/reset-password")
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Apply a password reset using an OTP from /auth/forgot-password."""
    _check_reset_rate_limit(_get_client_ip(request))

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or user.status != "active":
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    otp_hash = _hash_otp(payload.otp.strip())
    now = datetime.utcnow()

    # Atomic consume: a single UPDATE avoids the TOCTOU race where two
    # concurrent requests both pass a SELECT … WHERE used_at IS NULL check
    # before either commits.  Only one transaction can update a given row;
    # the other gets rowcount=0 and is rejected.
    # failed_attempts < _MAX_OTP_ATTEMPTS gates access so a locked token
    # cannot be consumed even with the correct OTP — IP rotation is irrelevant.
    rowcount = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.otp_hash == otp_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
            PasswordResetToken.failed_attempts < _MAX_OTP_ATTEMPTS,
        )
        .update({"used_at": now}, synchronize_session="evaluate")
    )

    if rowcount == 0:
        # Atomically increment failed_attempts on the still-active, still-
        # unlocked token.  The WHERE clause caps the counter at _MAX_OTP_ATTEMPTS
        # so it never overshoots even under concurrent requests.
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
            PasswordResetToken.failed_attempts < _MAX_OTP_ATTEMPTS,
        ).update(
            {"failed_attempts": PasswordResetToken.failed_attempts + 1},
            synchronize_session="evaluate",
        )
        db.commit()  # Must commit before raising; the exception rolls back otherwise.
        logger.warning(
            "password_reset_invalid_otp | ip=%s | user_id=%s",
            _get_client_ip(request), user.id,
        )
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    user.password_hash = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    db.commit()

    logger.info("password_reset_success | user_id=%s", user.id)
    return {"message": "Password reset successfully"}