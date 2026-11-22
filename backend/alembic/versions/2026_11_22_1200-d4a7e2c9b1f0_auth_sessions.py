"""auth.sessions: one row per login, ``sid`` in every token (IMPLEMENTATION_PLAN T6.2)

Adds ``auth.sessions`` and ``auth.refresh_tokens.session_id`` (FK, ``ON DELETE CASCADE``).
Existing refresh tokens have no session and are deleted, so every user logs in once after the
upgrade (V2_DELTA Q24; RELEASE.md "v0.6.0"). ``downgrade`` drops the column and the table;
tokens issued meanwhile carry an extra ``sid`` claim, which older code ignores.

Revision ID: d4a7e2c9b1f0
Revises: c3f8a2d5e6b1
Create Date: 2026-11-22 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a7e2c9b1f0"
down_revision: Union[str, Sequence[str], None] = "c3f8a2d5e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("agent", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["username"], ["auth.users.username"]),
        sa.PrimaryKeyConstraint("id"),
        schema="auth",
    )
    op.create_index(
        op.f("ix_auth_sessions_username"), "sessions", ["username"], unique=False, schema="auth"
    )
    op.create_index(
        op.f("ix_auth_sessions_expires_at"), "sessions", ["expires_at"], unique=False, schema="auth"
    )
    # Pre-session refresh tokens cannot be attached to a session: everyone logs in once.
    op.execute("DELETE FROM auth.refresh_tokens")
    op.add_column(
        "refresh_tokens", sa.Column("session_id", sa.String(), nullable=False), schema="auth"
    )
    op.create_index(
        op.f("ix_auth_refresh_tokens_session_id"),
        "refresh_tokens",
        ["session_id"],
        unique=False,
        schema="auth",
    )
    op.create_foreign_key(
        "fk_refresh_tokens_session_id",
        "refresh_tokens",
        "sessions",
        ["session_id"],
        ["id"],
        source_schema="auth",
        referent_schema="auth",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_refresh_tokens_session_id", "refresh_tokens", schema="auth", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_auth_refresh_tokens_session_id"), table_name="refresh_tokens", schema="auth"
    )
    op.drop_column("refresh_tokens", "session_id", schema="auth")
    op.drop_index(op.f("ix_auth_sessions_expires_at"), table_name="sessions", schema="auth")
    op.drop_index(op.f("ix_auth_sessions_username"), table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
