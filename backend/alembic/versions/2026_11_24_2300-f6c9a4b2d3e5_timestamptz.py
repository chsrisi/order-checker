"""Timestamps the app writes become timestamptz (V2_ORDERS_DELTA Q54, R4.3)

Existing values are UTC, which is how they were written, so the conversion names UTC and does
not depend on the server's TimeZone. Rewrites each table once under an exclusive lock: run it
in the deploy window. No rows or columns are lost, in either direction. The imported dates on
warehouse items, BOM tables and shopee_items stay as they are: their zone is unknown.

Revision ID: f6c9a4b2d3e5
Revises: e5b8f3a1c2d4
Create Date: 2026-11-24 23:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f6c9a4b2d3e5"
down_revision: Union[str, Sequence[str], None] = "e5b8f3a1c2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = {
    "auth.sessions": ("created_at", "expires_at", "last_seen_at", "revoked_at"),
    "auth.devices": ("enrolled_at", "last_seen_at"),
    "auth.refresh_tokens": ("created_at", "expires_at", "revoked_at"),
    "shopee.orders": ("ship_by", "done_at"),
    "orders.outbound_items": ("created_at", "closed_at"),
    "orders.pick_item_entries": ("timestamp",),
    "orders.pick_stock_allocations": ("created_at",),
    "warehouse.stocks_log": ("timestamp",),
}


def _alter(to: str) -> None:
    for table, columns in COLUMNS.items():
        changes = ", ".join(
            f'ALTER COLUMN "{c}" TYPE {to} USING "{c}" AT TIME ZONE \'UTC\'' for c in columns
        )
        op.execute(f"ALTER TABLE {table} {changes}")


def upgrade() -> None:
    _alter("timestamptz")


def downgrade() -> None:
    _alter("timestamp")
