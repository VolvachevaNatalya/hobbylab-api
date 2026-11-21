from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    phone: Optional[str]
    avatar_url: Optional[str]
    provider: Optional[str]
    provider_user_id: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True