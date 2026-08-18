from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class SupportRequestCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=10000)

    @field_validator("subject", "message", mode="before")
    @classmethod
    def strip_and_require(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class SupportRequestResponse(BaseModel):
    id: int
    user_id: int
    subject: str
    message: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
