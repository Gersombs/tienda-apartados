from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String


class Store_settings(Base):
    __tablename__ = "store_settings"
    __table_args__ = (
        CheckConstraint("reservation_window_days > 0", name="ck_store_settings_window_positive"),
        CheckConstraint("grace_period_hours >= 0", name="ck_store_settings_grace_nonnegative"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    shop_name = Column(String, nullable=False)
    tagline = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    hero_image_url = Column(String, nullable=True)
    color_bg = Column(String, nullable=True)
    color_text = Column(String, nullable=True)
    color_accent = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_whatsapp = Column(String, nullable=True)
    instagram_url = Column(String, nullable=True)
    tiktok_url = Column(String, nullable=True)
    facebook_url = Column(String, nullable=True)
    how_it_works = Column(String, nullable=True)
    faq_content = Column(String, nullable=True)
    privacy_policy = Column(String, nullable=True)
    reservation_policy = Column(String, nullable=True)
    delivery_instructions = Column(String, nullable=True)
    reservation_window_days = Column(Integer, nullable=False, default=7)
    grace_period_hours = Column(Integer, nullable=False, default=2)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
