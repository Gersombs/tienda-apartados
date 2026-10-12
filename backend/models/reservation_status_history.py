from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String


class Reservation_status_history(Base):
    __tablename__ = "reservation_status_history"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), index=True, nullable=False)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False)
    admin_user_id = Column(String, ForeignKey("admin_accounts.auth_user_id", ondelete="SET NULL"), index=True, nullable=True)
    admin_email = Column(String, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
