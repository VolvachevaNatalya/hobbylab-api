from pydantic import BaseModel
from typing import Optional


class GroupCreate(BaseModel):
    class_id: int
    name: Optional[str] = None
    age_from: Optional[int] = None
    age_to: Optional[int] = None
    capacity: Optional[int] = None


class GroupResponse(BaseModel):
    id: int
    class_id: int
    name: Optional[str]
    age_from: Optional[int]
    age_to: Optional[int]
    capacity: Optional[int]
    status: str

    class Config:
        from_attributes = True

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    age_from: Optional[int] = None
    age_to: Optional[int] = None
    capacity: Optional[int] = None
    status: Optional[str] = None