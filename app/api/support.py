from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.telegram import send_support_request
from app.db.dependencies import get_db
from app.models.support_request import SupportRequest
from app.models.user import User
from app.schemas.support_request import SupportRequestCreate, SupportRequestResponse

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/", response_model=SupportRequestResponse)
def create_support_request(
    data: SupportRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
