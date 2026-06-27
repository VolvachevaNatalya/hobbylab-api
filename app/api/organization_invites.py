from __future__ import annotations

import secrets
import string
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.org_permissions import require_owner_or_admin
from app.db.dependencies import get_db
from app.models.organization import Organization
from app.models.organization_invite_code import OrganizationInviteCode
from app.models.organization_join_request import OrganizationJoinRequest
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.organization_invite import (
    InviteCodeCreate,
    InviteCodeResponse,
    JoinRequestCreate,
    JoinRequestResponse,
    JoinResponse,
)

router = APIRouter(prefix="/organizations", tags=["organization-invites"])

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _get_org_or_404(org_id: int, db: Session) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


# ── Invite codes ──────────────────────────────────────────────────────────────

@router.post("/{org_id}/invite-codes", response_model=InviteCodeResponse, status_code=201)
def create_invite_code(
    org_id: int,
    payload: InviteCodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    for _ in range(5):
        invite = OrganizationInviteCode(
            organization_id=org_id,
            code=_generate_code(),
            default_role=payload.default_role,
            requires_approval=payload.requires_approval,
            expires_at=payload.expires_at,
            created_by_user_id=current_user.id,
        )
        db.add(invite)
        try:
            db.commit()
            db.refresh(invite)
            return invite
        except IntegrityError:
            db.rollback()

    raise HTTPException(status_code=500, detail="Could not generate a unique invite code")


@router.get("/{org_id}/invite-codes", response_model=List[InviteCodeResponse])
def list_invite_codes(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    return (
        db.query(OrganizationInviteCode)
        .filter(OrganizationInviteCode.organization_id == org_id)
        .order_by(OrganizationInviteCode.created_at.desc())
        .all()
    )


@router.patch("/{org_id}/invite-codes/{code_id}/deactivate", response_model=InviteCodeResponse)
def deactivate_invite_code(
    org_id: int,
    code_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    invite = db.query(OrganizationInviteCode).filter(
        OrganizationInviteCode.id == code_id,
        OrganizationInviteCode.organization_id == org_id,
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite code not found")

    invite.is_active = False
    db.commit()
    db.refresh(invite)
    return invite


# ── Join requests ─────────────────────────────────────────────────────────────

@router.post("/{org_id}/join-requests", response_model=JoinResponse, status_code=201)
def submit_join_request(
    org_id: int,
    payload: JoinRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)

    invite = db.query(OrganizationInviteCode).filter(
        OrganizationInviteCode.code == payload.code,
        OrganizationInviteCode.organization_id == org_id,
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite code not found")
    if not invite.is_active:
        raise HTTPException(status_code=400, detail="Invite code is inactive")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite code has expired")

    existing_member = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if existing_member:
        raise HTTPException(status_code=409, detail="You are already a member of this organization")

    if not invite.requires_approval:
        # Auto-approve: clean up any pending requests, then create membership directly.
        db.query(OrganizationJoinRequest).filter(
            OrganizationJoinRequest.organization_id == org_id,
            OrganizationJoinRequest.user_id == current_user.id,
        ).delete()
        db.add(OrganizationUser(
            organization_id=org_id,
            user_id=current_user.id,
            role=invite.default_role,
        ))
        db.commit()
        return JoinResponse(requires_approval=False, role=invite.default_role)

    existing_request = db.query(OrganizationJoinRequest).filter(
        OrganizationJoinRequest.organization_id == org_id,
        OrganizationJoinRequest.user_id == current_user.id,
    ).first()
    if existing_request:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending join request for this organization",
        )

    request = OrganizationJoinRequest(
        organization_id=org_id,
        user_id=current_user.id,
        invite_code_id=invite.id,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return JoinResponse(requires_approval=True, join_request_id=request.id)


@router.get("/{org_id}/join-requests", response_model=List[JoinRequestResponse])
def list_join_requests(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    rows = (
        db.query(OrganizationJoinRequest, User)
        .join(User, User.id == OrganizationJoinRequest.user_id)
        .filter(OrganizationJoinRequest.organization_id == org_id)
        .order_by(OrganizationJoinRequest.created_at.asc())
        .all()
    )

    return [
        JoinRequestResponse(
            id=req.id,
            organization_id=req.organization_id,
            user_id=req.user_id,
            user_name=user.name,
            user_email=user.email,
            invite_code_id=req.invite_code_id,
            created_at=req.created_at,
        )
        for req, user in rows
    ]


@router.post("/{org_id}/join-requests/{request_id}/approve")
def approve_join_request(
    org_id: int,
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    request = db.query(OrganizationJoinRequest).filter(
        OrganizationJoinRequest.id == request_id,
        OrganizationJoinRequest.organization_id == org_id,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Join request not found")

    role = "member"
    if request.invite_code_id:
        invite = db.query(OrganizationInviteCode).filter(
            OrganizationInviteCode.id == request.invite_code_id
        ).first()
        if invite:
            role = invite.default_role

    already_member = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == request.user_id,
    ).first()
    if not already_member:
        db.add(OrganizationUser(
            organization_id=org_id,
            user_id=request.user_id,
            role=role,
        ))

    db.delete(request)
    db.commit()
    return {"message": "Join request approved"}


@router.post("/{org_id}/join-requests/{request_id}/reject")
def reject_join_request(
    org_id: int,
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    request = db.query(OrganizationJoinRequest).filter(
        OrganizationJoinRequest.id == request_id,
        OrganizationJoinRequest.organization_id == org_id,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Join request not found")

    db.delete(request)
    db.commit()
    return {"message": "Join request rejected"}
