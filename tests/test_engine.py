"""
Tests for ducktor.engine
Runs real DuckDB queries against fixture parquet/csv files.
"""

import pytest
from pathlib import Path

from ducktor.engine import run, EngineError
from ducktor.models import (
    ContractDefinition,
    ColumnContract,
    DatasetContract,
    FreshnessCheck,
    SourceDefinition,
    SourceType,
)
from ducktor.result import CheckStatus, ValidationResult

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN = str(FIXTURES / "orders_clean.parquet")
DIRTY = str(FIXTURES / "orders_dirty.parquet")
CSV = str(FIXTURES / "minimal.csv")


def make_contract(path, stype, columns=None, dataset=None):
    return ContractDefinition(
        name="test",
        source=SourceDefinition(type=stype, path=path),
        columns=columns or {},
        dataset=dataset,
    )


# ---------------------------------------------------------------------------
# Returns correct type
# ---------------------------------------------------------------------------


def test_returns_validation_result():
    contract = make_contract(CLEAN, SourceType.parquet)
    result = run(contract)
    assert isinstance(result, ValidationResult)
    assert result.contract_name == "test"
    assert result.source_path == CLEAN


# ---------------------------------------------------------------------------
# Clean data — all checks should pass
# ---------------------------------------------------------------------------


def test_clean_not_null_passes():
    contract = make_contract(
        CLEAN,
        SourceType.parquet,
        {
            "order_id": ColumnContract(nullable=False),
        },
    )
    result = run(contract)
    assert result.passed


def test_clean_unique_passes():
    contract = make_contract(
        CLEAN,
        SourceType.parquet,
        {
            "order_id": ColumnContract(unique=True),
        },
    )
    result = run(contract)
    assert result.passed


def test_clean_allowed_values_passes():
    contract = make_contract(
        CLEAN,
        SourceType.parquet,
        {
            "status": ColumnContract(
                allowed_values=["pending", "shipped", "delivered", "cancelled"]
            ),
        },
    )
    result = run(contract)
    assert result.passed


def test_clean_min_max_passes():
    contract = make_contract(
        CLEAN,
        SourceType.parquet,
        {
            "amount": ColumnContract(min=0.0, max=100000.0),
        },
    )
    result = run(contract)
    assert result.passed


def test_clean_min_rows_passes():
    contract = make_contract(
        CLEAN, SourceType.parquet, dataset=DatasetContract(min_rows=100)
    )
    result = run(contract)
    assert result.passed


def test_clean_null_rate_passes():
    contract = make_contract(
        CLEAN,
        SourceType.parquet,
        columns={"amount": ColumnContract()},
        dataset=DatasetContract(max_null_rate={"amount": 0.05}),
    )
    result = run(contract)
    assert result.passed


# ---------------------------------------------------------------------------
# Dirty data — specific checks should fail
# ---------------------------------------------------------------------------


def test_dirty_not_null_fails():
    contract = make_contract(
        DIRTY,
        SourceType.parquet,
        {
            "order_id": ColumnContract(nullable=False),
        },
    )
    result = run(contract)
    assert not result.passed
    assert any("not_null" in c.name for c in result.failed_checks)


def test_dirty_allowed_values_fails():
    contract = make_contract(
        DIRTY,
        SourceType.parquet,
        {
            "status": ColumnContract(
                allowed_values=["pending", "shipped", "delivered", "cancelled"]
            ),
        },
    )
    result = run(contract)
    assert not result.passed
    assert any("allowed_values" in c.name for c in result.failed_checks)


def test_dirty_min_fails():
    contract = make_contract(
        DIRTY,
        SourceType.parquet,
        {
            "amount": ColumnContract(min=0.0),
        },
    )
    result = run(contract)
    assert not result.passed
    failed_names = [c.name for c in result.failed_checks]
    assert any("min" in n for n in failed_names)


def test_dirty_failure_has_detail():
    contract = make_contract(
        DIRTY,
        SourceType.parquet,
        {
            "order_id": ColumnContract(nullable=False),
        },
    )
    result = run(contract)
    failed = result.failed_checks[0]
    assert failed.detail != ""


def test_dirty_failure_has_sql():
    contract = make_contract(
        DIRTY,
        SourceType.parquet,
        {
            "order_id": ColumnContract(nullable=False),
        },
    )
    result = run(contract)
    failed = result.failed_checks[0]
    assert "SELECT" in failed.sql


# ---------------------------------------------------------------------------
# CSV source
# ---------------------------------------------------------------------------


def test_csv_source_runs():
    contract = make_contract(
        CSV,
        SourceType.csv,
        {
            "id": ColumnContract(nullable=False),
        },
    )
    result = run(contract)
    assert isinstance(result, ValidationResult)
    assert result.passed


# ---------------------------------------------------------------------------
# Source override
# ---------------------------------------------------------------------------


def test_source_override():
    contract = make_contract(CLEAN, SourceType.parquet)
    # Override to dirty — result should reflect dirty file
    result = run(contract, source_override=DIRTY)
    assert result.source_path == DIRTY


# ---------------------------------------------------------------------------
# Bad column name — engine error, not crash
# ---------------------------------------------------------------------------


def test_bad_column_name_returns_error_status():
    contract = make_contract(
        CLEAN,
        SourceType.parquet,
        {
            "nonexistent_column": ColumnContract(nullable=False),
        },
    )
    result = run(contract)
    assert not result.passed
    assert any(c.status == CheckStatus.ERROR for c in result.checks)


# ---------------------------------------------------------------------------
# Empty contract — no checks, always passes
# ---------------------------------------------------------------------------


def test_empty_contract_passes():
    contract = make_contract(CLEAN, SourceType.parquet)
    result = run(contract)
    assert result.passed
    assert result.summary["total"] == 0


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_summary_counts_correct():
    contract = make_contract(
        DIRTY,
        SourceType.parquet,
        {
            "order_id": ColumnContract(nullable=False),  # FAIL
            "status": ColumnContract(
                allowed_values=["pending", "shipped", "delivered", "cancelled"]
            ),  # FAIL
            "amount": ColumnContract(min=0.0, max=100000.0),  # FAIL (min) + PASS (max)
        },
    )
    result = run(contract)
    total = result.summary["total"]
    passed = result.summary["passed"]
    failed = result.summary["failed"]
    assert total == passed + failed
