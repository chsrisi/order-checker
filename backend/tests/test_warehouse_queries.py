import pytest
from src.services.queries.warehouse import _first_token, _sku_candidate, _supplier_barcode


def test_first_token():
    assert _first_token("A01_001**x y\nz") == "A01_001**x"
    assert _first_token("") is None
    assert _first_token("\n  \n") is None


def test_sku_candidate():
    assert _sku_candidate("A01_001**META") == "A01_001"
    assert _sku_candidate("B12_345") == "B12_345"
    assert _sku_candidate("abc123") is None
    assert _sku_candidate("ABC123_45") is None
    assert _sku_candidate("12_345") is None


def test_supplier_barcode():
    # Backward compatibility (old formats)
    assert _supplier_barcode("BATCH-00123") == "00123"
    assert _supplier_barcode("BATCH-TYPE-001") == "TYPE-001"
    assert _supplier_barcode("00123") == "00123"
    assert _supplier_barcode("AB-12-CD-34") == "AB-12-CD-34"

    # New format: {alphanum:"prefix"}:[original hypen part]:{alphanum:"suffix"}
    assert _supplier_barcode("CONSUMER:BATCH-00123:1") == "00123"
    assert _supplier_barcode("CONSUMER:BATCH-TYPE-001:5") == "TYPE-001"
    assert _supplier_barcode("Shopee:BATCH-00123:123") == "00123"
    assert _supplier_barcode("Shopee:BATCH-TYPE-001:42") == "TYPE-001"
    assert _supplier_barcode("C01:BATCH-00123:BOX1") == "00123"
    assert _supplier_barcode("123:BATCH-TYPE-001:CTN2") == "TYPE-001"
    assert _supplier_barcode("CONSUMER:AB-12-CD-34:2") == "AB-12-CD-34"
    assert _supplier_barcode("CONSUMER:00123:10") == "00123"


def test_resolve_barcode_to_item_scenarios():
    from src.services.queries.warehouse import resolve_barcode_to_item, find_warehouse_items
    from src.models import WarehouseItem
    from unittest.mock import MagicMock, patch

    mock_item_sku = WarehouseItem(sku="A01_001", item_name="Item SKU Candidate", supplier_barcode="SUPP-999")
    mock_item_supp = WarehouseItem(sku="B02_002", item_name="Item Supp Barcode", supplier_barcode="00123")

    # Empty barcode returns None immediately
    assert resolve_barcode_to_item("") is None

    mock_db = MagicMock()

    def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        mock_result = MagicMock()
        # Compile statement to check bound parameter values if available
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        if "a01_001" in compiled:
            mock_result.scalars.return_value.first.return_value = mock_item_sku
        elif "00123" in compiled:
            mock_result.scalars.return_value.first.return_value = mock_item_supp
        else:
            mock_result.scalars.return_value.first.return_value = None
            mock_result.scalars.return_value.all.return_value = [mock_item_sku]
        return mock_result

    mock_db.execute.side_effect = mock_execute

    with patch("src.services.queries.warehouse.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__.return_value = mock_db
        
        # Test SKU candidate resolution
        res1 = resolve_barcode_to_item("A01_001**EXTRA_TEXT")
        assert res1 == mock_item_sku

        # Test supplier barcode resolution (old format)
        res2 = resolve_barcode_to_item("BATCH-00123")
        assert res2 == mock_item_supp

        # Test supplier barcode resolution (new format)
        res3 = resolve_barcode_to_item("CONSUMER:BATCH-00123:1")
        assert res3 == mock_item_supp

        # Test find_warehouse_items returns resolved barcode item
        items = find_warehouse_items("A01_001**EXTRA_TEXT")
        assert items == [mock_item_sku]


