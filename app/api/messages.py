from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone

from app.db.dependencies import get_db
from app.models.message import Message
from app.models.conversation import Conversation
from app.schemas.message import MessageCreate, MessageResponse
from app.models.user import User
from app.core.auth import get_current_user
from app.models.notification import Notification
from app.models.organization_user import OrganizationUser

router = APIRouter(
    prefix="/messages",
    tags=["messages"]
)


def _is_org_member(db: Session, organization_id: int, user_id: int) -> bool:
    return db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == organization_id,
        OrganizationUser.user_id == user_id
    ).first() is not None


def _has_conversation_access(conversation: Conversation, current_user: User, db: Session) -> bool:
    if conversation.user_id == current_user.id:
        return True
    return _is_org_member(db, conversation.organization_id, current_user.id)


@router.post("/", response_model=MessageResponse)
def create_message(
    data: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    conversation = db.query(Conversation).filter(
        Conversation.id == data.conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not _has_conversation_access(conversation, current_user, db):
        raise HTTPException(status_code=403, detail="No permission")

    message = Message(
        conversation_id=data.conversation_id,
        sender_type="user",
        sender_id=current_user.id,
        message_text=data.message_text
    )

    db.add(message)

    conversation.last_message_at = datetime.now(timezone.utc)

    is_sender_the_user = current_user.id == conversation.user_id
    if is_sender_the_user:
        org_owner = db.query(OrganizationUser).filter(
            OrganizationUser.organization_id == conversation.organization_id,
            OrganizationUser.role.in_(["owner", "admin"])
        ).first()
        notify_user_id = org_owner.user_id if org_owner else None
    else:
        notify_user_id = conversation.user_id

    if notify_user_id:
        notification = Notification(
            user_id=notify_user_id,
            conversation_id=data.conversation_id,
            organization_id=conversation.organization_id,
            title="New message",
            message="You have a new message",
            type="message"
        )
        db.add(notification)

    db.commit()
    db.refresh(message)
    return message


@router.get("/conversation/{conversation_id}", response_model=List[MessageResponse])
def get_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not _has_conversation_access(conversation, current_user, db):
        raise HTTPException(status_code=403, detail="No permission")

    return db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at).all()