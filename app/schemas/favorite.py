from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class FavoriteType(str, Enum):
    class_item = "class"
    event = "event"
    organization = "organization"


class FavoriteCreate(BaseModel):
    entity_type: FavoriteType
    entity_id: int

class FavoriteResponse(BaseModel):
    id: int
    user_id: int
    entity_type: str
    entity_id: int
    created_at: datetime

    class Config:
        from_attributes = True