from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ConversationCreate(BaseModel):
    organization_id: int


class ConversationResponse(BaseModel):
    id: int
    user_id: int
    organization_id: int
    organization_name: Optional[str] = None
    user_name: Optional[str] = None
    created_at: datetime
    last_message_at: Optional[datetime]
    class Config:
        from_attributes = True