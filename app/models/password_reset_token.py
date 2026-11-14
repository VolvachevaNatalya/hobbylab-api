from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # HMAC-SHA256 hex digest of the 6-digit OTP — never store raw OTPs.
    otp_hash = Column(String(64), nullable=False)
    expires_at = Column(TIMESTAMP, nullable=False)
    used_at = Column(TIMESTAMP, nullable=True)
    # Counts wrong OTP submissions against this token. When this reaches
    # _MAX_OTP_ATTEMPTS the token is locked — including a correct OTP.
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
