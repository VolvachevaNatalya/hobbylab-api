from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import exists, or_
from typing import List

from app.db.dependencies import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.conversation import ConversationCreate, ConversationResponse
from app.models.user import User
from app.models.organization_user import OrganizationUser
from app.core.auth import get_current_user


router = APIRouter(
    prefix="/conversations",
    tags=["conversations"]
)


@router.post("/", response_model=ConversationResponse)
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    existing = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.organization_id == data.organization_id
    ).first()

    if existing:
        return existing

    conversation = Conversation(
        user_id=current_user.id,
        organization_id=data.organization_id
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.get("/", response_model=List[ConversationResponse])
def get_user_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    owned_org_ids = db.query(OrganizationUser.organization_id).filter(
        OrganizationUser.user_id == current_user.id
    ).subquery()

    return (
        db.query(Conversation)
        .filter(
            or_(
                Conversation.user_id == current_user.id,
                Conversation.organization_id.in_(owned_org_ids)
            ),
            exists().where(Message.conversation_id == Conversation.id)
        )
        .all()
    )