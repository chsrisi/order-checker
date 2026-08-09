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
    assert _supplier_barcode("BATCH-00123") == "00123"
    assert _supplier_barcode("BATCH-TYPE-001") == "TYPE-001"
    assert _supplier_barcode("00123") == "00123"
    assert _supplier_barcode("AB-12-CD-34") == "AB-12-CD-34"
