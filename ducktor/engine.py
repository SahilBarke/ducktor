"""
ducktor.engine
--------------
Executes compiled checks against DuckDB and returns a ValidationResult.

Design rules:
- One ephemeral in-memory DuckDB connection per run (no persistent state)
- Source is registered once, checks run against it
- DuckDB errors are caught and surfaced as CheckStatus.ERROR (never crash the run)
- Every CheckResult carries the exact SQL that ran
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ducktor.compiler import CompiledCheck, compile_contract
from ducktor.models import ContractDefinition, SourceType
from ducktor.result import CheckResult, CheckStatus, ValidationResult

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    contract: ContractDefinition,
    source_override: str | None = None,
) -> ValidationResult:
    """
    Execute all checks for a contract and return a ValidationResult.

    Args:
        contract:        parsed ContractDefinition
        source_override: optional path/URI to override contract.source.path
                         (useful for CI runs against different partitions)

    Returns:
        ValidationResult with one CheckResult per compiled check
    """
    source_path = source_override or contract.source.path
    source_expr = _build_source_expr(contract.source.type, source_path)

    compiled_checks = compile_contract(contract, source_expr)

    con = duckdb.connect(database=":memory:")
    _install_extensions(con, contract.source.type)

    check_results: list[CheckResult] = []
    for check in compiled_checks:
        result = _execute_check(con, check)
        check_results.append(result)

    con.close()

    return ValidationResult(
        contract_name=contract.name,
        source_path=source_path,
        checks=check_results,
    )


# ---------------------------------------------------------------------------
# Source expression builder
# ---------------------------------------------------------------------------


def _build_source_expr(source_type: SourceType, path: str) -> str:
    """
    Turn a source type + path into a DuckDB-readable table expression.
    This is what gets substituted into every SQL check as the FROM clause.
    """
    match source_type:
        case SourceType.parquet:
            return f"read_parquet('{path}')"
        case SourceType.csv:
            return f"read_csv_auto('{path}')"
        case SourceType.json:
            return f"read_json_auto('{path}')"
        case SourceType.s3:
            # S3 paths are parquet by convention; can be extended
            return f"read_parquet('{path}')"
        case SourceType.postgres:
            # Postgres uses the postgres_scan extension
            # path format: "postgresql://user:pass@host/db::schema.table"
            if "::" not in path:
                raise EngineError(
                    f"Postgres path must include table reference after '::'\n"
                    f"  Expected: postgresql://user:pass@host/db::schema.table\n"
                    f"  Got: {path}"
                )
            conn_str, table = path.rsplit("::", 1)
            return f"postgres_scan('{conn_str}', '{table}')"
        case _:
            raise EngineError(f"Unsupported source type: {source_type}")


def _install_extensions(
    con: duckdb.DuckDBPyConnection, source_type: SourceType
) -> None:
    """Install DuckDB extensions required for the source type."""
    if source_type == SourceType.s3:
        try:
            con.execute("INSTALL httpfs; LOAD httpfs;")
        except Exception as e:
            raise EngineError(f"Failed to load httpfs extension for S3: {e}") from e

    if source_type == SourceType.postgres:
        try:
            con.execute("INSTALL postgres_scanner; LOAD postgres_scanner;")
        except Exception as e:
            raise EngineError(f"Failed to load postgres_scanner extension: {e}") from e


# ---------------------------------------------------------------------------
# Check executor
# ---------------------------------------------------------------------------


def _execute_check(
    con: duckdb.DuckDBPyConnection,
    check: CompiledCheck,
) -> CheckResult:
    """
    Execute a single CompiledCheck and return a CheckResult.
    Never raises — DuckDB errors become CheckStatus.ERROR results.
    """
    try:
        row = con.execute(check.sql).fetchone()
        value = row[0] if row else None
    except Exception as e:
        return CheckResult(
            name=check.name,
            status=CheckStatus.ERROR,
            sql=check.sql,
            detail=f"Query error: {e}",
        )

    if value is None:
        # NULL result usually means empty table — treat as pass for scalar checks
        return CheckResult(
            name=check.name,
            status=CheckStatus.PASS,
            sql=check.sql,
            detail="No rows — skipped",
        )

    passed, detail = _evaluate(check, value)
    return CheckResult(
        name=check.name,
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        sql=check.sql,
        detail=detail,
    )


def _evaluate(check: CompiledCheck, value: float | int) -> tuple[bool, str]:
    """
    Determine pass/fail from a query result value.
    Returns (passed: bool, detail: str)
    """
    if check.result_mode == "count":
        # Zero violating rows = pass
        count = int(value)
        if count == 0:
            return True, ""
        return False, f"{count} row(s) violated"

    if check.result_mode == "scalar":
        actual = float(value)
        expected = float(check.expected_value)
        passed = _compare(actual, expected, check.comparator)
        if passed:
            return True, ""
        detail = f"got {_fmt(actual)}, expected {check.comparator} {_fmt(expected)}"
        return False, detail

    raise EngineError(f"Unknown result_mode: {check.result_mode!r}")


def _compare(actual: float, expected: float, comparator: str) -> bool:
    match comparator:
        case ">=":
            return actual >= expected
        case "<=":
            return actual <= expected
        case "==":
            return actual == expected
        case ">":
            return actual > expected
        case "<":
            return actual < expected
        case _:
            raise EngineError(f"Unknown comparator: {comparator!r}")


def _fmt(value: float) -> str:
    """Format a number cleanly — drop unnecessary decimal places."""
    return f"{value:g}"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EngineError(Exception):
    """Raised for unrecoverable engine-level errors (bad source, bad extension)."""

    pass
