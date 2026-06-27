"""
Tests for ducktor.compiler
Each test asserts the correct SQL is generated for a given check type.
"""

import pytest
from ducktor.compiler import compile_contract, CompiledCheck
from ducktor.models import (
    ContractDefinition,
    ColumnContract,
    DatasetContract,
    FreshnessCheck,
    SourceDefinition,
    SourceType,
)

SRC = "read_parquet('data/orders.parquet')"


def make_contract(columns=None, dataset=None):
    return ContractDefinition(
        name="test",
        source=SourceDefinition(type=SourceType.parquet, path="data/orders.parquet"),
        columns=columns or {},
        dataset=dataset,
    )


def find(checks, name_fragment) -> CompiledCheck:
    for c in checks:
        if name_fragment in c.name:
            return c
    raise AssertionError(
        f"No check matching '{name_fragment}' in {[c.name for c in checks]}"
    )


# ---------------------------------------------------------------------------
# Column checks
# ---------------------------------------------------------------------------


def test_not_null_sql():
    contract = make_contract({"id": ColumnContract(nullable=False)})
    checks = compile_contract(contract, SRC)
    c = find(checks, "not_null")
    assert "WHERE id IS NULL" in c.sql
    assert c.result_mode == "count"


def test_unique_sql():
    contract = make_contract({"id": ColumnContract(unique=True)})
    checks = compile_contract(contract, SRC)
    c = find(checks, "unique")
    assert "GROUP BY id" in c.sql
    assert "HAVING COUNT(*) > 1" in c.sql
    assert c.result_mode == "count"


def test_type_check_sql():
    contract = make_contract({"id": ColumnContract(type="INTEGER")})
    checks = compile_contract(contract, SRC)
    c = find(checks, "type[INTEGER]")
    assert "TRY_CAST(id AS INTEGER)" in c.sql
    assert c.result_mode == "count"


def test_min_check_sql():
    contract = make_contract({"amount": ColumnContract(min=0.0)})
    checks = compile_contract(contract, SRC)
    c = find(checks, "min[0.0]")
    assert "amount < 0.0" in c.sql
    assert c.result_mode == "count"


def test_max_check_sql():
    contract = make_contract({"amount": ColumnContract(max=1000.0)})
    checks = compile_contract(contract, SRC)
    c = find(checks, "max[1000.0]")
    assert "amount > 1000.0" in c.sql
    assert c.result_mode == "count"


def test_allowed_values_sql_strings():
    contract = make_contract(
        {"status": ColumnContract(allowed_values=["pending", "shipped"])}
    )
    checks = compile_contract(contract, SRC)
    c = find(checks, "allowed_values")
    assert "'pending'" in c.sql
    assert "'shipped'" in c.sql
    assert "NOT IN" in c.sql


def test_allowed_values_sql_integers():
    contract = make_contract({"code": ColumnContract(allowed_values=[1, 2, 3])})
    checks = compile_contract(contract, SRC)
    c = find(checks, "allowed_values")
    assert "NOT IN (1, 2, 3)" in c.sql


def test_pattern_check_sql():
    contract = make_contract({"email": ColumnContract(pattern=r"^[^@]+@[^@]+\.[^@]+$")})
    checks = compile_contract(contract, SRC)
    c = find(checks, "pattern")
    assert "regexp_matches" in c.sql
    assert c.result_mode == "count"


def test_custom_sql_check():
    contract = make_contract(
        {"amount": ColumnContract(custom_sql="amount > 0 AND amount < total")}
    )
    checks = compile_contract(contract, SRC)
    c = find(checks, "custom_sql")
    assert "amount > 0 AND amount < total" in c.sql
    assert c.result_mode == "count"


# ---------------------------------------------------------------------------
# Dataset checks
# ---------------------------------------------------------------------------


def test_min_rows_sql():
    contract = make_contract(dataset=DatasetContract(min_rows=100))
    checks = compile_contract(contract, SRC)
    c = find(checks, "min_rows")
    assert "COUNT(*)" in c.sql
    assert c.result_mode == "scalar"
    assert c.expected_value == 100
    assert c.comparator == ">="


def test_max_rows_sql():
    contract = make_contract(dataset=DatasetContract(max_rows=1000000))
    checks = compile_contract(contract, SRC)
    c = find(checks, "max_rows")
    assert c.expected_value == 1000000
    assert c.comparator == "<="


def test_null_rate_sql():
    contract = make_contract(
        columns={"amount": ColumnContract()},
        dataset=DatasetContract(max_null_rate={"amount": 0.05}),
    )
    checks = compile_contract(contract, SRC)
    c = find(checks, "null_rate")
    assert "SUM(CASE WHEN amount IS NULL" in c.sql
    assert c.result_mode == "scalar"
    assert c.expected_value == 0.05
    assert c.comparator == "<="


def test_freshness_sql():
    contract = make_contract(
        columns={"created_at": ColumnContract(type="TIMESTAMP")},
        dataset=DatasetContract(
            freshness=FreshnessCheck(column="created_at", max_age_hours=48)
        ),
    )
    checks = compile_contract(contract, SRC)
    c = find(checks, "freshness")
    assert "MAX(created_at)" in c.sql
    assert "3600.0" in c.sql
    assert c.expected_value == 48
    assert c.comparator == "<="


# ---------------------------------------------------------------------------
# Order and count
# ---------------------------------------------------------------------------


def test_column_checks_before_dataset_checks():
    contract = make_contract(
        columns={"id": ColumnContract(nullable=False)},
        dataset=DatasetContract(min_rows=10),
    )
    checks = compile_contract(contract, SRC)
    names = [c.name for c in checks]
    col_idx = next(i for i, n in enumerate(names) if "id" in n)
    dataset_idx = next(i for i, n in enumerate(names) if "dataset" in n)
    assert col_idx < dataset_idx


def test_no_checks_for_empty_contract():
    contract = make_contract()
    checks = compile_contract(contract, SRC)
    assert checks == []


def test_multiple_checks_per_column():
    contract = make_contract(
        {"amount": ColumnContract(nullable=False, min=0.0, max=1000.0, type="DOUBLE")}
    )
    checks = compile_contract(contract, SRC)
    names = [c.name for c in checks]
    assert any("not_null" in n for n in names)
    assert any("min" in n for n in names)
    assert any("max" in n for n in names)
    assert any("type" in n for n in names)
