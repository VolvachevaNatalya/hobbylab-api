from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationResponse

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _enrich(conversation: Conversation, org_name: str, user_name: str) -> ConversationResponse:
    return ConversationResponse.model_validate(conversation).model_copy(
        update={"organization_name": org_name, "user_name": user_name}
    )


@router.post("/", response_model=ConversationResponse)
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.organization_id == data.organization_id,
    ).first()

    if not existing:
        conversation = Conversation(
            user_id=current_user.id,
            organization_id=data.organization_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    else:
        conversation = existing

    org_name = db.query(Organization.name).filter(
        Organization.id == conversation.organization_id
    ).scalar()
    user_name = current_user.name  # current_user IS conversation.user_id
    return _enrich(conversation, org_name, user_name)


@router.get("/", response_model=List[ConversationResponse])
def get_user_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import exists

    owned_org_ids = db.query(OrganizationUser.organization_id).filter(
        OrganizationUser.user_id == current_user.id
    ).subquery()

    conversations = (
        db.query(Conversation)
        .filter(
            or_(
                Conversation.user_id == current_user.id,
                Conversation.organization_id.in_(owned_org_ids),
            ),
            exists().where(Message.conversation_id == Conversation.id),
        )
        .all()
    )
    if not conversations:
        return []

    org_ids = list({c.organization_id for c in conversations})
    org_name_map = {
        r.id: r.name
        for r in db.query(Organization.id, Organization.name)
        .filter(Organization.id.in_(org_ids))
        .all()
    }

    user_ids = list({c.user_id for c in conversations})
    user_name_map = {
        r.id: r.name
        for r in db.query(User.id, User.name)
        .filter(User.id.in_(user_ids))
        .all()
    }

    return [
        _enrich(c, org_name_map.get(c.organization_id), user_name_map.get(c.user_id))
        for c in conversations
    ]


@router.post("/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    is_user_side = conversation.user_id == current_user.id
    is_org_side = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == conversation.organization_id,
        OrganizationUser.user_id == current_user.id,
    ).first() is not None

    if not is_user_side and not is_org_side:
        raise HTTPException(status_code=403, detail="No permission")

    now = datetime.now(timezone.utc)

    # Mark the incoming side's messages as read, using sender_type for unambiguous matching.
    # (sender_id alone can't disambiguate: user IDs and org IDs are independent sequences
    #  and may share the same integer value.)
    #
    # User-side reading: mark org-sent messages as read.
    #   New format: sender_type="organization"
    #   Old format (pre-migration): sender_type="user", sender_id != conversation.user_id
    # Org-side reading: mark user-sent messages as read.
    #   sender_type="user" (covers both current and any legacy org replies)
    if is_user_side:
        read_filter = or_(
            Message.sender_type == "organization",
            and_(
                Message.sender_type == "user",
                Message.sender_id != conversation.user_id,
            ),
        )
    else:
        read_filter = Message.sender_type == "user"

    db.query(Message).filter(
        Message.conversation_id == conversation_id,
        read_filter,
        Message.read_at.is_(None),
    ).update({"read_at": now}, synchronize_session="evaluate")

    # Clear message notifications.
    # User-side: clear only their own notifications.
    # Org-side: clear notifications for ALL members of the org (shared inbox).
    if is_user_side:
        notif_user_ids = [current_user.id]
    else:
        notif_user_ids = [
            row.user_id
            for row in db.query(OrganizationUser.user_id)
            .filter(OrganizationUser.organization_id == conversation.organization_id)
            .all()
        ]

    db.query(Notification).filter(
        Notification.user_id.in_(notif_user_ids),
        Notification.type == "message",
        Notification.conversation_id == conversation_id,
        Notification.is_read == False,
    ).update({"is_read": True}, synchronize_session="evaluate")

    db.commit()
    return {"status": "ok"}
