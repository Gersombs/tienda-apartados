from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String


class Notifications(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_notifications_attempts_nonnegative"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), index=True, nullable=True)
    recipient_type = Column(String, nullable=False)
    recipient_email = Column(String, nullable=True)
    template = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    status = Column(String, nullable=False)
    error_message = Column(String, nullable=True)
    provider_message_id = Column(String, index=True, nullable=True)
    sent_at = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
