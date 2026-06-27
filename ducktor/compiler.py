"""
ducktor.compiler
----------------
Turns a ContractDefinition into a list of CompiledChecks.
Each check is a named SQL query that returns a count of violating rows
(or a scalar for dataset-level checks).

Design rule: every check compiles to SQL that DuckDB can run directly.
No magic — users can copy the SQL and run it themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from ducktor.models import ContractDefinition, ColumnContract, DatasetContract

# ---------------------------------------------------------------------------
# CompiledCheck — the unit of work the engine executes
# ---------------------------------------------------------------------------


@dataclass
class CompiledCheck:
    """A single check ready to be executed against DuckDB."""

    name: str  # e.g. "order_id :: not_null"
    sql: str  # exact SQL to run
    check_type: str  # e.g. "not_null", "unique", "min", ...

    # How to interpret the query result:
    # "count"  → result must be 0 (zero violating rows)
    # "scalar" → result is compared via expected_value + comparator
    result_mode: str = "count"
    expected_value: float | int | None = None
    comparator: str | None = None  # ">=", "<=", "==", etc.


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile_contract(
    contract: ContractDefinition, source_expr: str
) -> list[CompiledCheck]:
    """
    Compile a ContractDefinition into a list of CompiledChecks.

    Args:
        contract:    parsed ContractDefinition
        source_expr: DuckDB-readable source expression, e.g.
                     "read_parquet('data/orders.parquet')"

    Returns:
        Ordered list of CompiledChecks — column checks first, dataset checks last.
    """
    checks: list[CompiledCheck] = []

    for col_name, col_contract in contract.columns.items():
        checks.extend(_compile_column(col_name, col_contract, source_expr))

    if contract.dataset:
        checks.extend(_compile_dataset(contract.dataset, source_expr))

    return checks


# ---------------------------------------------------------------------------
# Column-level compilers
# ---------------------------------------------------------------------------


def _compile_column(
    col: str, contract: ColumnContract, src: str
) -> list[CompiledCheck]:
    checks = []

    if contract.nullable is False:
        checks.append(_not_null(col, src))

    if contract.unique:
        checks.append(_unique(col, src))

    if contract.type is not None:
        checks.append(_type_check(col, contract.type, src))

    if contract.min is not None:
        checks.append(_min_check(col, contract.min, src))

    if contract.max is not None:
        checks.append(_max_check(col, contract.max, src))

    if contract.allowed_values is not None:
        checks.append(_allowed_values(col, contract.allowed_values, src))

    if contract.pattern is not None:
        checks.append(_pattern_check(col, contract.pattern, src))

    if contract.custom_sql is not None:
        checks.append(_custom_sql(col, contract.custom_sql, src))

    return checks


def _not_null(col: str, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: not_null",
        check_type="not_null",
        sql=f"SELECT COUNT(*) FROM {src} WHERE {col} IS NULL",
        result_mode="count",
    )


def _unique(col: str, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: unique",
        check_type="unique",
        sql=(
            f"SELECT COUNT(*) FROM ("
            f"SELECT {col} FROM {src} "
            f"WHERE {col} IS NOT NULL "
            f"GROUP BY {col} HAVING COUNT(*) > 1"
            f") dupes"
        ),
        result_mode="count",
    )


def _type_check(col: str, expected_type: str, src: str) -> CompiledCheck:
    # DuckDB will raise an error if a cast fails — we count cast failures
    # by attempting a TRY_CAST and counting NULLs that weren't originally NULL
    return CompiledCheck(
        name=f"{col} :: type[{expected_type}]",
        check_type="type",
        sql=(
            f"SELECT COUNT(*) FROM {src} "
            f"WHERE {col} IS NOT NULL "
            f"AND TRY_CAST({col} AS {expected_type}) IS NULL"
        ),
        result_mode="count",
    )


def _min_check(col: str, min_val: float | int, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: min[{min_val}]",
        check_type="min",
        sql=f"SELECT COUNT(*) FROM {src} WHERE {col} IS NOT NULL AND {col} < {min_val}",
        result_mode="count",
    )


def _max_check(col: str, max_val: float | int, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: max[{max_val}]",
        check_type="max",
        sql=f"SELECT COUNT(*) FROM {src} WHERE {col} IS NOT NULL AND {col} > {max_val}",
        result_mode="count",
    )


def _allowed_values(col: str, values: list, src: str) -> CompiledCheck:
    # Format values as SQL literals
    formatted = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in values)
    return CompiledCheck(
        name=f"{col} :: allowed_values",
        check_type="allowed_values",
        sql=(
            f"SELECT COUNT(*) FROM {src} "
            f"WHERE {col} IS NOT NULL "
            f"AND {col} NOT IN ({formatted})"
        ),
        result_mode="count",
    )


def _pattern_check(col: str, pattern: str, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: pattern",
        check_type="pattern",
        sql=(
            f"SELECT COUNT(*) FROM {src} "
            f"WHERE {col} IS NOT NULL "
            f"AND NOT regexp_matches(CAST({col} AS VARCHAR), '{pattern}')"
        ),
        result_mode="count",
    )


def _custom_sql(col: str, expression: str, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: custom_sql",
        check_type="custom_sql",
        sql=(f"SELECT COUNT(*) FROM {src} " f"WHERE NOT ({expression})"),
        result_mode="count",
    )


# ---------------------------------------------------------------------------
# Dataset-level compilers
# ---------------------------------------------------------------------------


def _compile_dataset(dataset: DatasetContract, src: str) -> list[CompiledCheck]:
    checks = []

    if dataset.min_rows is not None:
        checks.append(_min_rows(dataset.min_rows, src))

    if dataset.max_rows is not None:
        checks.append(_max_rows(dataset.max_rows, src))

    if dataset.max_null_rate:
        for col, rate in dataset.max_null_rate.items():
            checks.append(_null_rate(col, rate, src))

    if dataset.freshness:
        checks.append(
            _freshness(
                dataset.freshness.column,
                dataset.freshness.max_age_hours,
                src,
            )
        )

    return checks


def _min_rows(min_rows: int, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"dataset :: min_rows[{min_rows}]",
        check_type="min_rows",
        sql=f"SELECT COUNT(*) FROM {src}",
        result_mode="scalar",
        expected_value=min_rows,
        comparator=">=",
    )


def _max_rows(max_rows: int, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"dataset :: max_rows[{max_rows}]",
        check_type="max_rows",
        sql=f"SELECT COUNT(*) FROM {src}",
        result_mode="scalar",
        expected_value=max_rows,
        comparator="<=",
    )


def _null_rate(col: str, max_rate: float, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: null_rate[<={max_rate}]",
        check_type="null_rate",
        sql=(
            f"SELECT CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS DOUBLE) "
            f"/ NULLIF(COUNT(*), 0) "
            f"FROM {src}"
        ),
        result_mode="scalar",
        expected_value=max_rate,
        comparator="<=",
    )


def _freshness(col: str, max_age_hours: float, src: str) -> CompiledCheck:
    return CompiledCheck(
        name=f"{col} :: freshness[<={max_age_hours}h]",
        check_type="freshness",
        sql=(
            f"SELECT EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600.0 " f"FROM {src}"
        ),
        result_mode="scalar",
        expected_value=max_age_hours,
        comparator="<=",
    )
