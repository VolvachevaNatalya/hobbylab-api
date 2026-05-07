from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, DECIMAL
from sqlalchemy.sql import func
from app.db.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text)

    logo_url = Column(Text)
    banner_url = Column(Text)

    email = Column(String(255))
    phone = Column(String(50))
    website = Column(Text)

    instagram_url = Column(Text)
    facebook_url = Column(Text)

    address = Column(Text)
    city = Column(String(100))

    latitude = Column(DECIMAL(10, 8))
    longitude = Column(DECIMAL(11, 8))

    verified = Column(Boolean, server_default="false", default=False)

    status = Column(String(50), server_default="pending", default="pending")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())