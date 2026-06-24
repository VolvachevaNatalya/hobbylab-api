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


class FacebookLoginRequest(BaseModel):
    access_token: str


class AppleLoginRequest(BaseModel):
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


@router.post("/auth/facebook-login")
def facebook_login(payload: FacebookLoginRequest, db: Session = Depends(get_db)):
    import httpx

    try:
        response = httpx.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,name,email", "access_token": payload.access_token},
            timeout=10,
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Facebook API: {e}")

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

    token = create_access_token({"user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/apple-login")
def apple_login(payload: AppleLoginRequest, db: Session = Depends(get_db)):
    import httpx
    from jose import jwt, JWTError

    APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
    APPLE_ISSUER = "https://appleid.apple.com"
    APPLE_CLIENT_ID = "il.co.hobbylab.app"

    try:
        jwks_response = httpx.get(APPLE_JWKS_URL, timeout=10)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Apple JWKS endpoint: {e}")

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
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {e}")

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