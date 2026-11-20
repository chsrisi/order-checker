"""stock allocations, structured stock log, unique (sku, location) (T4.3)

Expand-only. Duplicate (sku, location) stock rows are merged into the oldest row (their
quantities summed, one ``migration_merge`` log row per group) before the unique index is
created. The merge is not undone by ``downgrade``.

Revision ID: b7c4e1a9d2f3
Revises: d862d86e8707
Create Date: 2026-11-20 22:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c4e1a9d2f3"
down_revision: Union[str, Sequence[str], None] = "d862d86e8707"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOG_COLUMNS = [
    ("sku", sa.String()),
    ("location", sa.String()),
    ("delta", sa.Integer()),
    ("before", sa.Integer()),
    ("after", sa.Integer()),
    ("reason", sa.String()),
    ("actor", sa.String()),
    ("ref_type", sa.String()),
    ("ref_id", sa.String()),
]


def upgrade() -> None:
    op.create_table(
        "pick_stock_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pick_entry_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pick_entry_id"], ["orders.pick_item_entries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="orders",
    )
    op.create_index(
        op.f("ix_orders_pick_stock_allocations_pick_entry_id"),
        "pick_stock_allocations",
        ["pick_entry_id"],
        unique=False,
        schema="orders",
    )

    for name, type_ in LOG_COLUMNS:
        op.add_column("stocks_log", sa.Column(name, type_, nullable=True), schema="warehouse")
    op.create_index(
        op.f("ix_warehouse_stocks_log_sku"), "stocks_log", ["sku"], unique=False, schema="warehouse"
    )

    op.execute(
        """
        INSERT INTO warehouse.stocks_log (message, timestamp, sku, location, after, reason, actor)
        SELECT 'migration merge of duplicate stock rows: sku=' || sku
                   || ', location=' || coalesce(location, '<none>') || ', rows=' || count(*),
               now() AT TIME ZONE 'utc', sku, location, sum(stock), 'migration_merge', 'migration'
        FROM warehouse.stocks
        GROUP BY sku, location
        HAVING count(*) > 1
        """
    )
    op.execute(
        """
        WITH g AS (
            SELECT sku, coalesce(location, '') AS loc, min(id) AS keep, sum(stock) AS total
            FROM warehouse.stocks GROUP BY sku, coalesce(location, '') HAVING count(*) > 1
        )
        UPDATE warehouse.stocks s SET stock = g.total FROM g WHERE s.id = g.keep
        """
    )
    op.execute(
        """
        DELETE FROM warehouse.stocks s
        USING (
            SELECT sku, coalesce(location, '') AS loc, min(id) AS keep
            FROM warehouse.stocks GROUP BY sku, coalesce(location, '') HAVING count(*) > 1
        ) g
        WHERE s.sku = g.sku AND coalesce(s.location, '') = g.loc AND s.id <> g.keep
        """
    )
    op.create_index(
        "uq_stocks_sku_location",
        "stocks",
        ["sku", sa.text("coalesce(location, '')")],
        unique=True,
        schema="warehouse",
    )


def downgrade() -> None:
    op.drop_index("uq_stocks_sku_location", table_name="stocks", schema="warehouse")
    op.drop_index(op.f("ix_warehouse_stocks_log_sku"), table_name="stocks_log", schema="warehouse")
    for name, _ in reversed(LOG_COLUMNS):
        op.drop_column("stocks_log", name, schema="warehouse")
    op.drop_index(
        op.f("ix_orders_pick_stock_allocations_pick_entry_id"),
        table_name="pick_stock_allocations",
        schema="orders",
    )
    op.drop_table("pick_stock_allocations", schema="orders")
