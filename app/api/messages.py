from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.notification import Notification
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.message import MessageCreate, MessageResponse

router = APIRouter(prefix="/messages", tags=["messages"])


def _is_org_member(db: Session, organization_id: int, user_id: int) -> bool:
    return db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == organization_id,
        OrganizationUser.user_id == user_id,
    ).first() is not None


def _has_conversation_access(conversation: Conversation, current_user: User, db: Session) -> bool:
    if conversation.user_id == current_user.id:
        return True
    return _is_org_member(db, conversation.organization_id, current_user.id)


@router.post("/", response_model=MessageResponse)
def create_message(
    data: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == data.conversation_id
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not _has_conversation_access(conversation, current_user, db):
        raise HTTPException(status_code=403, detail="No permission")

    # Determine which side of the conversation this user is on.
    # Only membership in THIS conversation's organization qualifies as org-side.
    is_user_side = current_user.id == conversation.user_id
    # (access check above already verified org membership for non-user-side senders)

    if is_user_side:
        sender_type = "user"
        sender_id = conversation.user_id
    else:
        sender_type = "organization"
        sender_id = conversation.organization_id

    message = Message(
        conversation_id=data.conversation_id,
        sender_type=sender_type,
        sender_id=sender_id,
        message_text=data.message_text,
    )
    db.add(message)

    conversation.last_message_at = datetime.now(timezone.utc)

    if is_user_side:
        # Notify ALL owner/admin members of the organization.
        org_members = db.query(OrganizationUser).filter(
            OrganizationUser.organization_id == conversation.organization_id,
            OrganizationUser.role.in_(["owner", "admin"]),
        ).all()
        for member in org_members:
            db.add(Notification(
                user_id=member.user_id,
                conversation_id=data.conversation_id,
                organization_id=conversation.organization_id,
                title="notification.new_message.title",
                message="notification.new_message.body",
                type="message",
            ))
    else:
        # Org-side reply: notify the user who owns the conversation.
        db.add(Notification(
            user_id=conversation.user_id,
            conversation_id=data.conversation_id,
            organization_id=conversation.organization_id,
            title="notification.new_message.title",
            message="notification.new_message.body",
            type="message",
        ))

    db.commit()
    db.refresh(message)
    return message


@router.get("/conversation/{conversation_id}", response_model=List[MessageResponse])
def get_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not _has_conversation_access(conversation, current_user, db):
        raise HTTPException(status_code=403, detail="No permission")

    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
