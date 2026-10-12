from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Column, DateTime, Integer, String


class Private_settings(Base):
    __tablename__ = "private_settings"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    bank_name = Column(String, nullable=True)
    account_holder = Column(String, nullable=True)
    clabe = Column(String, nullable=True)
    account_number = Column(String, nullable=True)
    transfer_instructions = Column(String, nullable=True)
    alert_recipients = Column(String, nullable=True)
    notification_from_email = Column(String, nullable=True)
    notification_from_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
