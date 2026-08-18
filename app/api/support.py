from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.telegram import send_support_request
from app.db.dependencies import get_db
from app.models.support_request import SupportRequest
from app.models.user import User
from app.schemas.support_request import SupportRequestCreate, SupportRequestResponse

router = APIRouter(prefix="/support", tags=["support"])

_LIMIT_10M = 5
_LIMIT_24H = 20


def _check_rate_limits(user_id: int, db: Session) -> None:
    now = datetime.now(timezone.utc)

    count_10m = (
        db.query(func.count(SupportRequest.id))
        .filter(
            SupportRequest.user_id == user_id,
            SupportRequest.created_at >= now - timedelta(minutes=10),
        )
        .scalar()
    )
    if count_10m >= _LIMIT_10M:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    count_24h = (
        db.query(func.count(SupportRequest.id))
        .filter(
            SupportRequest.user_id == user_id,
            SupportRequest.created_at >= now - timedelta(hours=24),
        )
        .scalar()
    )
    if count_24h >= _LIMIT_24H:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")


@router.post("/", response_model=SupportRequestResponse)
def create_support_request(
    data: SupportRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_rate_limits(current_user.id, db)

    record = SupportRequest(
        user_id=current_user.id,
        subject=data.subject,
        message=data.message,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    send_support_request(
        request_id=record.id,
        user_name=current_user.name,
        user_email=current_user.email,
        subject=record.subject,
        message=record.message,
        created_at=record.created_at,
    )

    return record
