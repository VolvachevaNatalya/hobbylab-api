from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)

    plan_type = Column(String(50), nullable=False)
    status = Column(String(50), default="active")

    start_date = Column(DateTime)
    end_date = Column(DateTime)

    created_at = Column(DateTime(timezone=True), server_default=func.now())