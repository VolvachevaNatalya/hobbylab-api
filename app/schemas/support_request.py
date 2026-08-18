from pydantic import BaseModel
from datetime import datetime


class SupportRequestCreate(BaseModel):
    subject: str
    message: str


class SupportRequestResponse(BaseModel):
    id: int
    user_id: int
    subject: str
    message: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
