from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String


class Inventory_movements(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0", name="ck_inventory_movements_quantity_nonzero"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="SET NULL"), index=True, nullable=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), index=True, nullable=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="SET NULL"), index=True, nullable=True)
    movement_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    stock_after = Column(Integer, nullable=True)
    reserved_after = Column(Integer, nullable=True)
    note = Column(String, nullable=True)
    admin_user_id = Column(String, ForeignKey("admin_accounts.auth_user_id", ondelete="SET NULL"), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
