"""auth.devices and sessions.device_id: minimal v2 device registration (IMPLEMENTATION_PLAN T6.6)

Additive: a new table and a nullable column; no data changes. v0.6.0 code before this revision
never reads them, so a code rollback works without the downgrade.

Revision ID: e5b8f3a1c2d4
Revises: d4a7e2c9b1f0
Create Date: 2026-11-22 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b8f3a1c2d4"
down_revision: Union[str, Sequence[str], None] = "d4a7e2c9b1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("android_version", sa.String(), nullable=True),
        sa.Column("app_version_code", sa.Integer(), nullable=True),
        sa.Column("public_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=True),
        sa.Column("current_username", sa.String(), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'active', 'revoked')", name="ck_devices_status"),
        sa.ForeignKeyConstraint(["current_username"], ["auth.users.username"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_key"),
        schema="auth",
    )
    op.add_column("sessions", sa.Column("device_id", sa.String(), nullable=True), schema="auth")
    op.create_index(
        op.f("ix_auth_sessions_device_id"), "sessions", ["device_id"], unique=False, schema="auth"
    )
    op.create_foreign_key(
        "fk_sessions_device_id",
        "sessions",
        "devices",
        ["device_id"],
        ["id"],
        source_schema="auth",
        referent_schema="auth",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_device_id", "sessions", schema="auth", type_="foreignkey")
    op.drop_index(op.f("ix_auth_sessions_device_id"), table_name="sessions", schema="auth")
    op.drop_column("sessions", "device_id", schema="auth")
    op.drop_table("devices", schema="auth")
