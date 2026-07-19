import importlib.util
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic" / "versions" / "2026_07_19_1934-d862d86e8707_.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_d862d86e8707", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_item_rename_uses_warehouse_schema(monkeypatch, operation):
    migration = _load_migration()
    calls = []
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    operation(migration)

    item_call = next(call for call in calls if call[0][0] == "items")
    assert item_call[1]["schema"] == "warehouse"


def test_item_rename_upgrade_is_schema_qualified(monkeypatch):
    _assert_item_rename_uses_warehouse_schema(monkeypatch, lambda migration: migration.upgrade())


def test_item_rename_downgrade_is_schema_qualified(monkeypatch):
    _assert_item_rename_uses_warehouse_schema(monkeypatch, lambda migration: migration.downgrade())
