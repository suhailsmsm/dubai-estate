"""dim_building + building_id on facts + project building-geo columns

Adds the building layer (docs/PROJECT_GEO_ENRICHMENT.md §6): a `dim_building`
carrying a Makani-geocoded `location` plus physical attributes enriched from the
data.dubai building CSVs, a `building_id` FK on both fact tables, and two
building-derived confidence columns on `dim_project` (`geo_building_count`,
`geo_spread_m`). Also seeds the `makani` and `datadubai_buildings` sources.

The new table is created from its model definition (like 0001) so the column
list stays in one place; the ALTERs are explicit.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from dxb_core.models import Base

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # IF NOT EXISTS guard: migration 0001 uses create_all() which already
    # creates all tables/columns on a fresh volume. These guards handle
    # migration of older schemas only.
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "dim_building" not in existing_tables:
        Base.metadata.tables["dim_building"].create(bind=bind)

    for table in ("fact_sale_transaction", "fact_rent_contract"):
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if "building_id" not in existing_cols:
            op.add_column(
                table,
                sa.Column(
                    "building_id",
                    sa.BigInteger(),
                    sa.ForeignKey("dim_building.id"),
                    nullable=True,
                ),
            )

    proj_cols = {c["name"] for c in inspector.get_columns("dim_project")}
    if "geo_building_count" not in proj_cols:
        op.add_column(
            "dim_project", sa.Column("geo_building_count", sa.Integer(), nullable=True)
        )
    if "geo_spread_m" not in proj_cols:
        op.add_column(
            "dim_project", sa.Column("geo_spread_m", sa.Numeric(10, 1), nullable=True)
        )

    # Seed the two new sources (idempotent — skips any that already exist).
    from sqlalchemy.orm import Session

    from dxb.db.engine import seed_sources

    seed_sources(Session(bind=bind))


def downgrade() -> None:
    op.drop_column("dim_project", "geo_spread_m")
    op.drop_column("dim_project", "geo_building_count")
    op.drop_column("fact_rent_contract", "building_id")
    op.drop_column("fact_sale_transaction", "building_id")
    op.drop_table("dim_building")
