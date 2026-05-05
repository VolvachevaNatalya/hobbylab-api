from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"))

    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10))

    payment_provider = Column(String(50))
    payment_provider_id = Column(String(255))

    status = Column(String(50))

    created_at = Column(DateTime(timezone=True), server_default=func.now())