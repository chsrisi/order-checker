from sqlalchemy import create_engine, inspect

from .conftest import alembic_config, reset_schemas

EXPECTED_TABLES = {
    "auth": {"users", "refresh_tokens"},
    "orders": {"outbound_items", "tags", "pick_item_entries"},
    "shopee": {"orders", "order_info", "order_recipient_address", "order_item_list"},
    "warehouse": {"items", "stocks", "stocks_log", "bom_headers"},
}


def test_upgrade_from_empty_creates_every_schema_table(pg_engine):
    inspector = inspect(pg_engine)
    for schema, tables in EXPECTED_TABLES.items():
        assert tables <= set(inspector.get_table_names(schema=schema)), schema


def test_full_downgrade_and_reupgrade_round_trip(pg_url):
    """Every migration's downgrade() must work; ends at head so later tests see a fresh schema."""
    from alembic import command

    engine = create_engine(pg_url)
    try:
        reset_schemas(engine)
        cfg = alembic_config(pg_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        assert "stocks" in inspect(engine).get_table_names(schema="warehouse")
    finally:
        engine.dispose()


def test_session_factory_routes_queries_to_postgres(pg_session_factory):
    from src.services import queries

    queries.create_user("pg_user", "hash", scope="client")
    assert queries.get_user_data("pg_user").scope == "client"


def test_models_match_migrated_schema(pg_engine):
    """Autogenerate against head must find nothing: models and migrations agree."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from src.models import Base

    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={"include_schemas": True, "version_table_schema": "alembic"},
        )
        diff = [
            d
            for d in compare_metadata(ctx, Base.metadata)
            if not (d[0] == "remove_table" and d[1].schema == "alembic")
        ]
    assert diff == []


def test_timestamptz_migration_keeps_every_instant(pg_url):
    """V2_ORDERS_DELTA R4.3: stored values are UTC, whatever zone the migrating session uses."""
    from datetime import UTC, datetime

    from alembic import command
    from sqlalchemy import text

    zoned = create_engine(pg_url, connect_args={"options": "-c timezone=Asia/Jakarta"})
    database = zoned.url.database
    try:
        reset_schemas(zoned)
        cfg = alembic_config(pg_url)
        command.upgrade(cfg, "e5b8f3a1c2d4")
        with zoned.begin() as conn:
            conn.execute(text(f"ALTER DATABASE \"{database}\" SET timezone TO 'Asia/Jakarta'"))
            conn.execute(
                text(
                    "INSERT INTO shopee.orders (order_sn, split_up, ship_by, status, done)"
                    " VALUES ('S', false, '2026-11-24 16:30:00', 'PROCESSED', false)"
                )
            )
        command.upgrade(cfg, "head")
        with zoned.connect() as conn:
            ship_by = conn.execute(text("SELECT ship_by FROM shopee.orders")).scalar_one()
        assert ship_by == datetime(2026, 11, 24, 16, 30, tzinfo=UTC)
        command.downgrade(cfg, "e5b8f3a1c2d4")
        with zoned.connect() as conn:
            ship_by = conn.execute(text("SELECT ship_by FROM shopee.orders")).scalar_one()
        assert ship_by == datetime(2026, 11, 24, 16, 30)
    finally:
        with zoned.begin() as conn:
            conn.execute(text(f'ALTER DATABASE "{database}" RESET timezone'))
        reset_schemas(zoned)
        command.upgrade(alembic_config(pg_url), "head")
        zoned.dispose()


def test_tasks_downgrade_drops_task_picks_and_keeps_order_picks(pg_url):
    """T9.1: below the tasks revision no task pick may survive as a v1 unassigned pick."""
    from alembic import command
    from sqlalchemy import text

    engine = create_engine(pg_url)
    try:
        reset_schemas(engine)
        cfg = alembic_config(pg_url)
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO auth.users VALUES ('eko', 'x', 'client')"))
            task_id = conn.execute(
                text(
                    "INSERT INTO orders.tasks (type, status, created_by, created_at)"
                    " VALUES ('pick', 'open', 'boss', now()) RETURNING id"
                )
            ).scalar_one()
            line_id = conn.execute(
                text(
                    "INSERT INTO orders.task_lines (task_id, kind, sku, qty)"
                    " VALUES (:t, 'leaf', 'A01_001', 2) RETURNING id"
                ),
                {"t": task_id},
            ).scalar_one()
            for owner, line in (("eko", None), (None, line_id)):
                entry = conn.execute(
                    text(
                        "INSERT INTO orders.pick_item_entries"
                        " (sku, qty, timestamp, owner_user, task_line_id)"
                        " VALUES ('A01_001', 2, now(), :o, :l) RETURNING id"
                    ),
                    {"o": owner, "l": line},
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO orders.pick_stock_allocations"
                        " (pick_entry_id, sku, location, qty, created_at)"
                        " VALUES (:e, 'A01_001', 'A1', 2, now())"
                    ),
                    {"e": entry},
                )
        command.downgrade(cfg, "f6c9a4b2d3e5")
        with engine.connect() as conn:
            owners = conn.execute(text("SELECT owner_user FROM orders.pick_item_entries")).all()
            allocations = conn.execute(
                text("SELECT count(*) FROM orders.pick_stock_allocations")
            ).scalar_one()
        assert owners == [("eko",)] and allocations == 1
    finally:
        reset_schemas(engine)
        command.upgrade(alembic_config(pg_url), "head")
        engine.dispose()
