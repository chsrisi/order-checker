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
