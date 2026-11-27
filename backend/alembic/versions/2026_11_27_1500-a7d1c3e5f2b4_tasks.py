"""orders.tasks, orders.task_lines and task picks (IMPLEMENTATION_PLAN T9.1, V2_TASKS_DELTA)

Additive: two new tables and a nullable ``pick_item_entries.task_line_id``. One existing column
changes: ``pick_item_entries.owner_user`` becomes nullable, guarded by the CHECK
``ck_pick_item_entries_owner`` (``owner_user IS NOT NULL OR task_line_id IS NOT NULL``), so only
a task pick can lose its owner, when its worker is deleted (P-32). Order and v1 picks keep
their owner as before. Code before this revision never writes NULL there.

Downgrade deletes task picks and their allocations **without returning stock** (like the D5
cutover clear; the goods left with the task), then drops the tables. Without that, task picks
would become v1 unassigned picks.

Revision ID: a7d1c3e5f2b4
Revises: f6c9a4b2d3e5
Create Date: 2026-11-27 15:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d1c3e5f2b4"
down_revision: Union[str, Sequence[str], None] = "f6c9a4b2d3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("assigned_to", sa.String(), nullable=True),
        sa.Column("assigned_name", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("blocked_reason", sa.String(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.CheckConstraint("type IN ('count', 'pick')", name="ck_tasks_type"),
        sa.CheckConstraint(
            "status IN ('open', 'blocked', 'done', 'cancelled')", name="ck_tasks_status"
        ),
        sa.ForeignKeyConstraint(["assigned_to"], ["auth.users.username"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="orders",
    )
    op.create_index(op.f("ix_orders_tasks_status"), "tasks", ["status"], schema="orders")
    op.create_index(op.f("ix_orders_tasks_assigned_to"), "tasks", ["assigned_to"], schema="orders")

    op.create_table(
        "task_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("counted_qty", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('count', 'entered', 'leaf')", name="ck_task_lines_kind"),
        sa.ForeignKeyConstraint(["task_id"], ["orders.tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="orders",
    )
    op.create_index(
        op.f("ix_orders_task_lines_task_id"), "task_lines", ["task_id"], schema="orders"
    )

    op.add_column(
        "pick_item_entries",
        sa.Column("task_line_id", sa.Integer(), nullable=True),
        schema="orders",
    )
    op.create_index(
        op.f("ix_orders_pick_item_entries_task_line_id"),
        "pick_item_entries",
        ["task_line_id"],
        schema="orders",
    )
    op.create_foreign_key(
        "fk_pick_item_entries_task_line_id",
        "pick_item_entries",
        "task_lines",
        ["task_line_id"],
        ["id"],
        source_schema="orders",
        referent_schema="orders",
    )
    op.alter_column(
        "pick_item_entries", "owner_user", existing_type=sa.String(), nullable=True, schema="orders"
    )
    op.create_check_constraint(
        "ck_pick_item_entries_owner",
        "pick_item_entries",
        "owner_user IS NOT NULL OR task_line_id IS NOT NULL",
        schema="orders",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM orders.pick_stock_allocations WHERE pick_entry_id IN "
        "(SELECT id FROM orders.pick_item_entries WHERE task_line_id IS NOT NULL)"
    )
    op.execute("DELETE FROM orders.pick_item_entries WHERE task_line_id IS NOT NULL")
    op.drop_constraint(
        "ck_pick_item_entries_owner", "pick_item_entries", schema="orders", type_="check"
    )
    op.alter_column(
        "pick_item_entries",
        "owner_user",
        existing_type=sa.String(),
        nullable=False,
        schema="orders",
    )
    op.drop_constraint(
        "fk_pick_item_entries_task_line_id",
        "pick_item_entries",
        schema="orders",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_orders_pick_item_entries_task_line_id"),
        table_name="pick_item_entries",
        schema="orders",
    )
    op.drop_column("pick_item_entries", "task_line_id", schema="orders")
    op.drop_index(op.f("ix_orders_task_lines_task_id"), table_name="task_lines", schema="orders")
    op.drop_table("task_lines", schema="orders")
    op.drop_index(op.f("ix_orders_tasks_assigned_to"), table_name="tasks", schema="orders")
    op.drop_index(op.f("ix_orders_tasks_status"), table_name="tasks", schema="orders")
    op.drop_table("tasks", schema="orders")
