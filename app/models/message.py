from sqlalchemy import Column, Integer, Text, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)

    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False
    )

    sender_type = Column(String(50), nullable=False)

    sender_id = Column(Integer, nullable=False)

    message_text = Column(Text)

    created_at = Column(DateTime, server_default=func.now())

    read_at = Column(DateTime)