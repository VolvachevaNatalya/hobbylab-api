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

router = APIRouter(
    prefix="/messages",
    tags=["messages"]
)


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

    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    message = Message(
        conversation_id=data.conversation_id,
        sender_type="user",
        sender_id=current_user.id,
        message_text=data.message_text
    )

    db.add(message)

    conversation.last_message_at = datetime.now(timezone.utc)

    notification = Notification(
        user_id=conversation.user_id,
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

    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    return db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at).all()