from pydantic import BaseModel
from datetime import datetime


class OrganizationPhotoCreate(BaseModel):
    photo_url: str


class OrganizationPhotoResponse(BaseModel):
    id: int
    organization_id: int
    photo_url: str
    created_at: datetime

    class Config:
        from_attributes = True
