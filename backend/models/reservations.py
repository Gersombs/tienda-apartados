from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint


class Reservations(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("folio", name="uq_reservations_folio"),
        UniqueConstraint("private_token_hash", name="uq_reservations_private_token_hash"),
        Index("ix_reservations_folio", "folio"),
        Index("ix_reservations_status_delivery_date", "status", "delivery_date"),
        CheckConstraint("total_amount >= 0", name="ck_reservations_total_nonnegative"),
        CheckConstraint("item_count > 0", name="ck_reservations_item_count_positive"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    folio = Column(String, nullable=False)
    private_token_hash = Column(String(64), index=True, nullable=False)
    token_revoked = Column(Boolean, nullable=False, default=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True)
    customer_name = Column(String, nullable=True)
    customer_whatsapp = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    delivery_point_id = Column(Integer, ForeignKey("delivery_points.id", ondelete="SET NULL"), index=True, nullable=True)
    delivery_point_name = Column(String, nullable=True)
    delivery_point_reference = Column(String, nullable=True)
    delivery_date = Column(String, nullable=True)
    slot_start = Column(String, nullable=True)
    slot_end = Column(String, nullable=True)
    status = Column(String, nullable=False)
    total_amount = Column(Float, nullable=False)
    item_count = Column(Integer, nullable=False)
    customer_notes = Column(String, nullable=True)
    internal_notes = Column(String, nullable=True)
    is_unread = Column(Boolean, nullable=False, default=True)
    privacy_accepted = Column(Boolean, nullable=False)
    expires_at = Column(String, nullable=True)
    delivered_at = Column(String, nullable=True)
    cancelled_at = Column(String, nullable=True)
    cancel_reason = Column(String, nullable=True)
    stock_released = Column(Boolean, nullable=False, default=False)
    client_fingerprint = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
