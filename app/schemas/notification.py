from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NotificationCreate(BaseModel):
    title: str
    message: Optional[str] = None
    type: str


class NotificationResponse(BaseModel):
    id: int
    user_id: Optional[int]
    organization_id: Optional[int]
    conversation_id: Optional[int]
    title: str
    message: Optional[str]
    type: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
