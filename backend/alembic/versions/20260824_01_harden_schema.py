"""Harden authorization, confirmation tokens, relations and integrity.

Revision ID: 20260824_01
Revises: 3e67152dc4ff
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_01"
down_revision: Union[str, Sequence[str], None] = "3e67152dc4ff"
branch_labels = None
depends_on = None


def _scalar(sql: str, **params) -> int:
    return int(op.get_bind().execute(sa.text(sql), params).scalar() or 0)


def _assert_no_duplicates(table: str, expression: str, label: str, where: str = "1=1") -> None:
    duplicate_groups = _scalar(
        f"SELECT COUNT(*) FROM (SELECT {expression} FROM {table} WHERE {where} "
        f"GROUP BY {expression} HAVING COUNT(*) > 1) duplicates"
    )
    if duplicate_groups:
        raise RuntimeError(f"Migration stopped: {duplicate_groups} duplicate group(s) found for {label}.")


def _assert_no_orphans(child: str, child_key: str, parent: str, nullable: bool = True) -> None:
    null_filter = f"c.{child_key} IS NOT NULL AND " if nullable else ""
    count = _scalar(
        f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON p.id = c.{child_key} "
        f"WHERE {null_filter}p.id IS NULL"
    )
    if count:
        raise RuntimeError(
            f"Migration stopped: {count} orphan row(s) in {child}.{child_key}; repair them before retrying."
        )


def _preflight() -> None:
    _assert_no_duplicates("admin_accounts", "auth_user_id", "admin_accounts.auth_user_id")
    _assert_no_duplicates("categories", "slug", "categories.slug")
    _assert_no_duplicates("products", "slug", "products.slug")
    _assert_no_duplicates("customers", "lower(email)", "customers.email")
    _assert_no_duplicates("reservations", "folio", "reservations.folio")
    _assert_no_duplicates(
        "admin_accounts", "lower(email)", "admin_accounts.email", "email IS NOT NULL AND trim(email) <> ''"
    )
    _assert_no_duplicates(
        "product_variants", "sku", "product_variants.sku", "sku IS NOT NULL AND trim(sku) <> ''"
    )

    legacy_token_count = _scalar("SELECT COUNT(*) FROM reservations")
    if legacy_token_count and os.environ.get("ALLOW_LEGACY_TOKEN_INVALIDATION") != "1":
        raise RuntimeError(
            "Migration stopped before changing the schema: legacy reservation tokens exist. "
            "Review the data, then set ALLOW_LEGACY_TOKEN_INVALIDATION=1 to revoke those "
            "links without deleting reservations."
        )

    if _scalar("SELECT COUNT(*) FROM product_variants WHERE COALESCE(stock, 0) < 0 OR COALESCE(reserved_stock, 0) < 0 OR COALESCE(reserved_stock, 0) > COALESCE(stock, 0)"):
        raise RuntimeError("Migration stopped: invalid stock/reserved_stock values require manual repair.")
    if _scalar("SELECT COUNT(*) FROM reservations WHERE total_amount IS NULL OR total_amount < 0 OR item_count IS NULL OR item_count <= 0"):
        raise RuntimeError("Migration stopped: invalid reservation totals/item counts require manual repair.")
    if _scalar("SELECT COUNT(*) FROM reservation_items WHERE quantity <= 0 OR unit_price < 0"):
        raise RuntimeError("Migration stopped: invalid reservation item quantities/prices require manual repair.")
    if _scalar("SELECT COUNT(*) FROM products WHERE price < 0 OR COALESCE(sort_order, 0) < 0"):
        raise RuntimeError("Migration stopped: negative product prices/sort order require manual repair.")
    if _scalar("SELECT COUNT(*) FROM categories WHERE COALESCE(sort_order, 0) < 0"):
        raise RuntimeError("Migration stopped: negative category sort order requires manual repair.")
    if _scalar("SELECT COUNT(*) FROM delivery_points WHERE COALESCE(sort_order, 0) < 0"):
        raise RuntimeError("Migration stopped: negative delivery-point sort order requires manual repair.")
    if _scalar("SELECT COUNT(*) FROM delivery_slots WHERE weekday < 0 OR weekday > 6 OR COALESCE(capacity, 0) < 0"):
        raise RuntimeError("Migration stopped: invalid delivery-slot weekday/capacity requires manual repair.")
    if _scalar("SELECT COUNT(*) FROM inventory_movements WHERE quantity = 0"):
        raise RuntimeError("Migration stopped: zero-quantity inventory movements require manual repair.")
    if _scalar("SELECT COUNT(*) FROM notifications WHERE COALESCE(attempts, 0) < 0"):
        raise RuntimeError("Migration stopped: negative notification attempts require manual repair.")
    if _scalar("SELECT COUNT(*) FROM store_settings WHERE COALESCE(reservation_window_days, 7) <= 0 OR COALESCE(grace_period_hours, 2) < 0"):
        raise RuntimeError("Migration stopped: invalid reservation-window/grace settings require manual repair.")

    for child, key, parent, nullable in (
        ("delivery_slots", "delivery_point_id", "delivery_points", False),
        ("products", "category_id", "categories", True),
        ("product_variants", "product_id", "products", False),
        ("product_images", "product_id", "products", False),
        ("reservations", "customer_id", "customers", True),
        ("reservations", "delivery_point_id", "delivery_points", True),
        ("reservation_items", "reservation_id", "reservations", False),
        ("reservation_items", "product_id", "products", True),
        ("reservation_items", "variant_id", "product_variants", True),
        ("inventory_movements", "variant_id", "product_variants", True),
        ("inventory_movements", "product_id", "products", True),
        ("inventory_movements", "reservation_id", "reservations", True),
        ("reservation_status_history", "reservation_id", "reservations", False),
        ("notifications", "reservation_id", "reservations", True),
    ):
        _assert_no_orphans(child, key, parent, nullable)


def upgrade() -> None:
    _preflight()
    bind = op.get_bind()

    # Empty SKUs carry no identity and must remain nullable so the unique
    # constraint can represent multiple products without a configured SKU.
    bind.execute(sa.text("UPDATE product_variants SET sku=NULL WHERE trim(COALESCE(sku, ''))=''"))

    with op.batch_alter_table("admin_accounts") as batch:
        batch.add_column(sa.Column("normalized_email", sa.String(length=320), nullable=True))
        batch.add_column(sa.Column("password_hash", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    admins = bind.execute(sa.text("SELECT id, email FROM admin_accounts")).mappings().all()
    for admin in admins:
        normalized = (admin["email"] or "").strip().casefold()
        if not normalized:
            normalized = f"legacy-{admin['id']}@invalid.local"
        bind.execute(
            sa.text(
                "UPDATE admin_accounts SET email=:email, normalized_email=:normalized, "
                "password_hash=:password_hash, role=COALESCE(role, 'owner'), is_active=FALSE WHERE id=:id"
            ),
            {
                "id": admin["id"],
                "email": normalized,
                "normalized": normalized,
                "password_hash": "!legacy-account-disabled-run-create-admin!",
            },
        )
    with op.batch_alter_table("admin_accounts") as batch:
        batch.alter_column("auth_user_id", existing_type=sa.String(), nullable=False)
        batch.alter_column("email", existing_type=sa.String(), nullable=False)
        batch.alter_column("normalized_email", existing_type=sa.String(length=320), nullable=False)
        batch.alter_column("password_hash", existing_type=sa.String(length=512), nullable=False)
        batch.alter_column("role", existing_type=sa.String(), nullable=False)
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)
        batch.create_unique_constraint("uq_admin_accounts_auth_user_id", ["auth_user_id"])
        batch.create_unique_constraint("uq_admin_accounts_normalized_email", ["normalized_email"])

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_admin_sessions_token_hash"),
    )
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index("ix_admin_sessions_token_hash", "admin_sessions", ["token_hash"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])

    # Legacy raw confirmation tokens are never copied. Existing rows require an
    # explicit operator acknowledgement and are revoked with fresh random hashes.
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(sa.Column("private_token_hash", sa.String(length=64), nullable=True))
    legacy = bind.execute(sa.text("SELECT id, private_token FROM reservations")).mappings().all()
    for row in legacy:
        replacement_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE reservations SET private_token_hash=:token_hash, token_revoked=TRUE WHERE id=:id"
            ),
            {"id": row["id"], "token_hash": replacement_hash},
        )
    with op.batch_alter_table("reservations") as batch:
        batch.drop_column("private_token")
        batch.alter_column("private_token_hash", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint("uq_reservations_folio", ["folio"])
        batch.create_unique_constraint("uq_reservations_private_token_hash", ["private_token_hash"])
        batch.create_index("ix_reservations_private_token_hash", ["private_token_hash"], unique=False)
        batch.create_check_constraint("ck_reservations_total_nonnegative", "total_amount >= 0")
        batch.create_check_constraint("ck_reservations_item_count_positive", "item_count > 0")
        batch.create_foreign_key("fk_reservations_customer", "customers", ["customer_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_reservations_delivery_point", "delivery_points", ["delivery_point_id"], ["id"], ondelete="SET NULL")

    # Fill safe defaults before making previously optional operational columns mandatory.
    defaults = (
        ("categories", "sort_order=COALESCE(sort_order,0), is_active=COALESCE(is_active,TRUE)"),
        ("customers", "reservation_count=COALESCE(reservation_count,0), delivered_count=COALESCE(delivered_count,0)"),
        ("delivery_points", "sort_order=COALESCE(sort_order,0), is_active=COALESCE(is_active,TRUE)"),
        ("delivery_slots", "capacity=COALESCE(capacity,0), is_active=COALESCE(is_active,TRUE)"),
        ("products", "sort_order=COALESCE(sort_order,0), is_active=COALESCE(is_active,TRUE), is_featured=COALESCE(is_featured,FALSE), is_archived=COALESCE(is_archived,FALSE)"),
        ("product_variants", "stock=COALESCE(stock,0), reserved_stock=COALESCE(reserved_stock,0), price_delta=COALESCE(price_delta,0), is_active=COALESCE(is_active,TRUE)"),
        ("product_images", "sort_order=COALESCE(sort_order,0)"),
        ("reservations", "token_revoked=COALESCE(token_revoked,FALSE), is_unread=COALESCE(is_unread,TRUE), privacy_accepted=COALESCE(privacy_accepted,FALSE), stock_released=COALESCE(stock_released,FALSE)"),
        ("reservation_items", "line_total=COALESCE(line_total, unit_price * quantity)"),
        ("notifications", "attempts=COALESCE(attempts,0)"),
        ("store_settings", "reservation_window_days=COALESCE(reservation_window_days,7), grace_period_hours=COALESCE(grace_period_hours,2), is_active=COALESCE(is_active,TRUE)"),
    )
    for table, assignment in defaults:
        bind.execute(sa.text(f"UPDATE {table} SET {assignment}"))

    with op.batch_alter_table("reservations") as batch:
        batch.alter_column("token_revoked", existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("total_amount", existing_type=sa.Float(), nullable=False)
        batch.alter_column("item_count", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("is_unread", existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("privacy_accepted", existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("stock_released", existing_type=sa.Boolean(), nullable=False)

    with op.batch_alter_table("categories") as batch:
        batch.create_unique_constraint("uq_categories_slug", ["slug"])
        batch.create_check_constraint("ck_categories_sort_order_nonnegative", "sort_order >= 0")
        batch.alter_column("sort_order", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)
    with op.batch_alter_table("customers") as batch:
        batch.create_unique_constraint("uq_customers_email", ["email"])
        batch.create_check_constraint("ck_customers_reservation_count_nonnegative", "reservation_count >= 0")
        batch.create_check_constraint("ck_customers_delivered_count_nonnegative", "delivered_count >= 0")
        batch.alter_column("reservation_count", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("delivered_count", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("delivery_points") as batch:
        batch.create_check_constraint("ck_delivery_points_sort_order_nonnegative", "sort_order >= 0")
        batch.alter_column("sort_order", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)
    with op.batch_alter_table("delivery_slots") as batch:
        batch.create_check_constraint("ck_delivery_slots_weekday", "weekday >= 0 AND weekday <= 6")
        batch.create_check_constraint("ck_delivery_slots_capacity_nonnegative", "capacity >= 0")
        batch.create_foreign_key("fk_delivery_slots_point", "delivery_points", ["delivery_point_id"], ["id"], ondelete="CASCADE")
        batch.alter_column("capacity", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)
    with op.batch_alter_table("products") as batch:
        batch.create_unique_constraint("uq_products_slug", ["slug"])
        batch.create_check_constraint("ck_products_price_nonnegative", "price >= 0")
        batch.create_check_constraint("ck_products_sort_order_nonnegative", "sort_order >= 0")
        batch.create_foreign_key("fk_products_category", "categories", ["category_id"], ["id"], ondelete="SET NULL")
        for column in ("is_active", "is_featured", "is_archived"):
            batch.alter_column(column, existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("sort_order", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("product_variants") as batch:
        batch.create_unique_constraint("uq_product_variants_sku", ["sku"])
        batch.create_check_constraint("ck_product_variants_stock_nonnegative", "stock >= 0")
        batch.create_check_constraint("ck_product_variants_reserved_nonnegative", "reserved_stock >= 0")
        batch.create_check_constraint("ck_product_variants_reserved_lte_stock", "reserved_stock <= stock")
        batch.create_foreign_key("fk_product_variants_product", "products", ["product_id"], ["id"], ondelete="CASCADE")
        for column, type_ in (("stock", sa.Integer()), ("reserved_stock", sa.Integer()), ("price_delta", sa.Float()), ("is_active", sa.Boolean())):
            batch.alter_column(column, existing_type=type_, nullable=False)
    with op.batch_alter_table("product_images") as batch:
        batch.create_check_constraint("ck_product_images_sort_order_nonnegative", "sort_order >= 0")
        batch.create_foreign_key("fk_product_images_product", "products", ["product_id"], ["id"], ondelete="CASCADE")
        batch.alter_column("sort_order", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("reservation_items") as batch:
        batch.create_check_constraint("ck_reservation_items_quantity_positive", "quantity > 0")
        batch.create_check_constraint("ck_reservation_items_unit_price_nonnegative", "unit_price >= 0")
        batch.create_check_constraint("ck_reservation_items_line_total_nonnegative", "line_total >= 0")
        batch.create_foreign_key("fk_reservation_items_reservation", "reservations", ["reservation_id"], ["id"], ondelete="CASCADE")
        batch.create_foreign_key("fk_reservation_items_product", "products", ["product_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_reservation_items_variant", "product_variants", ["variant_id"], ["id"], ondelete="SET NULL")
        batch.alter_column("line_total", existing_type=sa.Float(), nullable=False)
    with op.batch_alter_table("inventory_movements") as batch:
        batch.create_check_constraint("ck_inventory_movements_quantity_nonzero", "quantity <> 0")
        batch.create_foreign_key("fk_inventory_movements_variant", "product_variants", ["variant_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_inventory_movements_product", "products", ["product_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_inventory_movements_reservation", "reservations", ["reservation_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_inventory_movements_admin", "admin_accounts", ["admin_user_id"], ["auth_user_id"], ondelete="SET NULL")
    with op.batch_alter_table("reservation_status_history") as batch:
        batch.create_foreign_key("fk_status_history_reservation", "reservations", ["reservation_id"], ["id"], ondelete="CASCADE")
        batch.create_foreign_key("fk_status_history_admin", "admin_accounts", ["admin_user_id"], ["auth_user_id"], ondelete="SET NULL")
    with op.batch_alter_table("notifications") as batch:
        batch.create_check_constraint("ck_notifications_attempts_nonnegative", "attempts >= 0")
        batch.create_foreign_key("fk_notifications_reservation", "reservations", ["reservation_id"], ["id"], ondelete="CASCADE")
        batch.alter_column("attempts", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("store_settings") as batch:
        batch.create_check_constraint("ck_store_settings_window_positive", "reservation_window_days > 0")
        batch.create_check_constraint("ck_store_settings_grace_nonnegative", "grace_period_hours >= 0")
        batch.alter_column("reservation_window_days", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("grace_period_hours", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)

    op.create_index("ix_reservations_folio", "reservations", ["folio"])
    op.create_index("ix_reservations_status_delivery_date", "reservations", ["status", "delivery_date"])
    op.create_index("ix_customers_email", "customers", ["email"])
    op.create_index("ix_products_slug", "products", ["slug"])


def downgrade() -> None:
    raise RuntimeError(
        "This security migration is intentionally irreversible because a downgrade would restore raw private-token storage."
    )
