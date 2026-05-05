from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Numeric
from sqlalchemy.sql import func
from app.db.database import Base
from app.models.organization import Organization

class Class(Base):
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True)

    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False
    )

    category_id = Column(
        Integer,
        ForeignKey("categories.id"),
        nullable=False
    )

    name = Column(String(255), nullable=False)
    description = Column(Text)
    image_url = Column(Text)
    price = Column(Numeric(10, 2), nullable=True)
    price_type = Column(String(50), nullable=True)

    status = Column(String(50), server_default="active")

    created_at = Column(DateTime, server_default=func.now())