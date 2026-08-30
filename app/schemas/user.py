from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class UserCreate(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: Optional[str] = None
    provider_user_id: Optional[str] = None

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