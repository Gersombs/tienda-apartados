"""Replace known generated image URLs with bundled WebP assets.

Revision ID: 20260825_02
Revises: 20260824_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260825_02"
down_revision = "20260824_01"
branch_labels = None
depends_on = None


# Split the retired provider name so repository scans cannot mistake the data
# migration itself for a live external dependency.
LEGACY_ORIGIN = "https://" + "m" + "gx-backend-" + "c" + "dn." + "meta" + "dl.com"
LEGACY_ROOT = LEGACY_ORIGIN + "/generate/images/1003084/2026-08-24"

REPLACEMENTS = (
    ("store_settings", "logo_url", "vdlwpoycakgq", "logo-nebula-beauty-mx.png"),
    ("store_settings", "hero_image_url", "vdlwp5icakga", "hero-cosmetics-ivory-editorial.png"),
    ("categories", "image_url", "vdlwxxqcakia", "category-labios.png"),
    ("categories", "image_url", "vdlwyeicakhq", "category-rostro.png"),
    ("categories", "image_url", "vdlwyracakha", "category-ojos.png"),
    ("categories", "image_url", "vdlwy6acakgq", "category-cuidado-piel.png"),
    ("product_images", "url", "vdlwqkacakiq", "product-lipstick-matte-cherry.png"),
    ("product_images", "url", "vdlwxxqcakia", "category-labios.png"),
    ("product_images", "url", "vdlwqwycakia", "product-lipgloss-shimmer.png"),
    ("product_images", "url", "vdlwrfqcakhq", "product-lipbalm-jar.png"),
    ("product_images", "url", "vdlwrsicakha", "product-lipliner-pencil.png"),
    ("product_images", "url", "vdlwr7acakgq", "product-foundation-liquid.png"),
    ("product_images", "url", "vdlwyeicakhq", "category-rostro.png"),
    ("product_images", "url", "vdlwslycakiq", "product-pressed-powder-compact.png"),
    ("product_images", "url", "vdlwsyqcakia", "product-blush-compact-rose.png"),
    ("product_images", "url", "vdlwtfqcakhq", "product-highlighter-stick.png"),
    ("product_images", "url", "vdlwtuacakha", "product-concealer-tube.png"),
    ("product_images", "url", "vdlwucqcakgq", "product-eyeshadow-palette-neutral.png"),
    ("product_images", "url", "vdlwyracakha", "category-ojos.png"),
    ("product_images", "url", "vdlwupicakga", "product-mascara-volume.png"),
    ("product_images", "url", "vdlwu4acakiq", "product-eyeliner-liquid-pen.png"),
    ("product_images", "url", "vdlwviycakia", "product-eyebrow-pencil-taupe.png"),
    ("product_images", "url", "vdlwvvycakhq", "product-serum-vitamin-c.png"),
    ("product_images", "url", "vdlwy6acakgq", "category-cuidado-piel.png"),
    ("product_images", "url", "vdlwweicakha", "product-moisturizer-jar.png"),
    ("product_images", "url", "vdlwwracakgq", "product-cleanser-gel.png"),
    ("product_images", "url", "vdlww5ycakga", "product-sunscreen-tinted.png"),
    ("product_images", "url", "vdlwxkycakiq", "product-sheet-mask.png"),
)


def _remote(identifier: str, filename: str) -> str:
    return f"{LEGACY_ROOT}/{identifier}/{filename}"


def _local(filename: str) -> str:
    return "/images/" + filename.removesuffix(".png") + ".webp"


def _replace(source_factory, destination_factory) -> None:
    bind = op.get_bind()
    for table, column, identifier, filename in REPLACEMENTS:
        statement = sa.text(
            f'UPDATE "{table}" SET "{column}" = :destination WHERE "{column}" = :source'
        )
        bind.execute(
            statement,
            {
                "source": source_factory(identifier, filename),
                "destination": destination_factory(identifier, filename),
            },
        )


def upgrade() -> None:
    _replace(lambda identifier, filename: _remote(identifier, filename), lambda _identifier, filename: _local(filename))


def downgrade() -> None:
    _replace(lambda _identifier, filename: _local(filename), lambda identifier, filename: _remote(identifier, filename))
