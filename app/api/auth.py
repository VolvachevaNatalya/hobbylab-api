import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.core.security import verify_password, create_access_token, hash_password
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    id_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):

    user = db.query(User).filter(User.email == form_data.username).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = create_access_token({"user_id": user.id})

    return {
        "access_token": token,
        "token_type": "bearer"
    }

@router.post("/auth/register", response_model=UserResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):

    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = hash_password(user.password)

    db_user = User(
        email=user.email,
        name=user.name,
        phone=user.phone,
        avatar_url=user.avatar_url,
        provider=user.provider,
        provider_user_id=user.provider_user_id,
        password_hash=hashed
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/auth/google-login")
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="Google login not configured on server")

    # --- TEMPORARY DEBUG ---
    import base64, json as _json
    print(f"[google-login] GOOGLE_CLIENT_ID = {client_id!r}", flush=True)
    try:
        _parts = payload.id_token.split(".")
        _pad = lambda s: s + "=" * (-len(s) % 4)
        _claims = _json.loads(base64.urlsafe_b64decode(_pad(_parts[1])))
        print(f"[google-login] token aud = {_claims.get('aud')!r}", flush=True)
        print(f"[google-login] token azp = {_claims.get('azp')!r}", flush=True)
    except Exception as _e:
        print(f"[google-login] could not decode token payload: {_e}", flush=True)
    # --- END TEMPORARY DEBUG ---

    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            client_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {e}")

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

    token = create_access_token({"user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}


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
    db.commit()
    return {"message": "Password changed successfully"}