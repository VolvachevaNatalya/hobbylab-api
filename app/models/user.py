from sqlalchemy import Column, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func
from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)

    phone = Column(String(50))
    avatar_url = Column(Text)

    provider = Column(String(50))
    provider_user_id = Column(String(255))

    password_hash = Column(Text)

    created_at = Column(TIMESTAMP, server_default=func.now())

    status = Column(String(50), default="active")