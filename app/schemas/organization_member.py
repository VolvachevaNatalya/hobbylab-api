from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class MemberResponse(BaseModel):
    user_id: int
    name: str
    email: Optional[str]
    role: str
    joined_at: Optional[datetime]


class MemberRoleUpdate(BaseModel):
    role: Literal["member", "admin"]
