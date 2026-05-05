from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PaymentCreate(BaseModel):
    organization_id: int
    subscription_id: Optional[int] = None
    amount: float
    currency: Optional[str] = None
    payment_provider: Optional[str] = None
    payment_provider_id: Optional[str] = None
    status: Optional[str] = None


class PaymentResponse(BaseModel):
    id: int
    organization_id: int
    subscription_id: Optional[int]
    amount: float
    currency: Optional[str]
    payment_provider: Optional[str]
    payment_provider_id: Optional[str]
    status: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentUpdate(BaseModel):
    status: Optional[str] = None
    payment_provider_id: Optional[str] = None