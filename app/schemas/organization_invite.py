from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class InviteCodeCreate(BaseModel):
    default_role: Literal["member", "admin"] = "member"
    requires_approval: bool = True
    expires_at: Optional[datetime] = None


class InviteCodeResponse(BaseModel):
    id: int
    organization_id: int
    code: str
    default_role: str
    requires_approval: bool
    is_active: bool
    expires_at: Optional[datetime]
    created_by_user_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class JoinRequestCreate(BaseModel):
    code: str


class JoinRequestResponse(BaseModel):
    id: int
    organization_id: int
    user_id: int
    user_name: str
    user_email: str
    invite_code_id: Optional[int]
    created_at: datetime


class JoinResponse(BaseModel):
    requires_approval: bool
    join_request_id: Optional[int] = None
    role: Optional[str] = None
