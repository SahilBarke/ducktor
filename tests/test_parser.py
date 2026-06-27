"""
Tests for ducktor.parser
"""

import pytest
from pathlib import Path

from ducktor.parser import parse, ContractParseError
from ducktor.models import ContractDefinition, SourceType

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_parse_valid_contract():
    contract = parse(FIXTURES / "valid_contract.yaml")

    assert isinstance(contract, ContractDefinition)
    assert contract.name == "orders"
    assert contract.version == 1
    assert contract.source.type == SourceType.parquet
    assert contract.source.path == "data/orders.parquet"


def test_parse_valid_columns():
    contract = parse(FIXTURES / "valid_contract.yaml")

    assert "order_id" in contract.columns
    assert "status" in contract.columns
    assert "amount" in contract.columns
    assert "created_at" in contract.columns

    order_id = contract.columns["order_id"]
    assert order_id.type == "INTEGER"
    assert order_id.nullable is False
    assert order_id.unique is True

    status = contract.columns["status"]
    assert status.allowed_values == ["pending", "shipped", "delivered", "cancelled"]

    amount = contract.columns["amount"]
    assert amount.min == 0.0
    assert amount.max == 100000.0


def test_parse_valid_dataset_checks():
    contract = parse(FIXTURES / "valid_contract.yaml")

    assert contract.dataset is not None
    assert contract.dataset.min_rows == 100
    assert contract.dataset.max_rows == 1000000
    assert contract.dataset.max_null_rate == {"status": 0.05, "amount": 0.0}
    assert contract.dataset.freshness.column == "created_at"
    assert contract.dataset.freshness.max_age_hours == 48


def test_parse_minimal_contract():
    """A contract with just name + source and no columns is valid."""
    contract = parse(FIXTURES / "minimal_contract.yaml")

    assert contract.name == "minimal"
    assert contract.source.type == SourceType.csv
    assert contract.columns == {}
    assert contract.dataset is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_parse_file_not_found():
    with pytest.raises(ContractParseError, match="not found"):
        parse("nonexistent/path/contract.yaml")


def test_parse_missing_source_field():
    with pytest.raises(ContractParseError, match="Missing required field"):
        parse(FIXTURES / "invalid_missing_source.yaml")


def test_parse_invalid_null_rate_column():
    """max_null_rate referencing an undefined column should fail."""
    with pytest.raises(ContractParseError, match="unknown column"):
        parse(FIXTURES / "invalid_bad_null_rate_col.yaml")


def test_parse_invalid_yaml(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("name: [unclosed bracket\n  bad: indent")
    with pytest.raises(ContractParseError, match="Invalid YAML"):
        parse(bad_yaml)


def test_parse_non_mapping_yaml(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- item1\n- item2\n")
    with pytest.raises(ContractParseError, match="YAML mapping"):
        parse(bad)


def test_parse_invalid_source_type(tmp_path):
    bad = tmp_path / "bad_source.yaml"
    bad.write_text("name: test\nsource:\n  type: excel\n  path: data.xlsx\n")
    with pytest.raises(ContractParseError, match="Contract validation failed"):
        parse(bad)
