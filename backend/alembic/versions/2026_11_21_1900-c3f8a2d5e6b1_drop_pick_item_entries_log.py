"""drop the unused orders.pick_item_entries_log table

The table was created by the initial schema but never written or read (STOCK_MODEL_DISCUSSION
§2). Pick audit lives in ``warehouse.stocks_log`` (``ref_type='pick_entry'``) since b7c4e1a9d2f3.
v0.4.0 code never touches the table either, so a code rollback does not need the downgrade.
``downgrade`` recreates the empty table.

Revision ID: c3f8a2d5e6b1
Revises: b7c4e1a9d2f3
Create Date: 2026-11-21 19:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8a2d5e6b1"
down_revision: Union[str, Sequence[str], None] = "b7c4e1a9d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "ix_orders_pick_item_entries_log_id", table_name="pick_item_entries_log", schema="orders"
    )
    op.drop_table("pick_item_entries_log", schema="orders")


def downgrade() -> None:
    op.create_table(
        "pick_item_entries_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="orders",
    )
    op.create_index(
        "ix_orders_pick_item_entries_log_id",
        "pick_item_entries_log",
        ["id"],
        unique=False,
        schema="orders",
    )
