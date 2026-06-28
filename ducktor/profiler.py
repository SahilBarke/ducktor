"""
ducktor.profiler
----------------
Scans a DuckDB-queryable source and generates a starter contract YAML.

Infers:
  - Column types
  - Nullability
  - Uniqueness (for low-cardinality or integer columns)
  - Min / max (for numeric columns)
  - Allowed values (for low-cardinality string columns)
  - Row count → min_rows
  - Null rates → max_null_rate
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import duckdb
import yaml

# Cardinality threshold — columns with <= this many distinct values
# get emitted as allowed_values
ENUM_THRESHOLD = 20


class ProfilerError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def profile_source(source_path: str, source_type: str) -> str:
    """
    Profile a data source and return a contract YAML string.

    Args:
        source_path: path or URI to the data file
        source_type: one of parquet | csv | json

    Returns:
        YAML string ready to write to a .yaml file
    """
    src = _build_source_expr(source_path, source_type)

    try:
        con = duckdb.connect(":memory:")
        profile = _run_profile(con, src, source_path, source_type)
        con.close()
    except Exception as e:
        raise ProfilerError(f"Failed to profile '{source_path}': {e}") from e

    return _render_yaml(profile)


# ---------------------------------------------------------------------------
# Source expression (mirrors engine.py but kept local to avoid coupling)
# ---------------------------------------------------------------------------


def _build_source_expr(path: str, source_type: str) -> str:
    match source_type.lower():
        case "parquet":
            return f"read_parquet('{path}')"
        case "csv":
            return f"read_csv_auto('{path}')"
        case "json":
            return f"read_json_auto('{path}')"
        case _:
            raise ProfilerError(f"Unsupported source type: {source_type}")


# ---------------------------------------------------------------------------
# Profiling logic
# ---------------------------------------------------------------------------


def _run_profile(
    con: duckdb.DuckDBPyConnection,
    src: str,
    source_path: str,
    source_type: str,
) -> dict:
    """Run all profiling queries and return a structured profile dict."""

    # --- Row count ---
    row_count = con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]

    # --- Schema: column names + types ---
    schema_rows = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    # Returns: (column_name, column_type, null, key, default, extra)

    columns = {}
    null_rates = {}

    for row in schema_rows:
        col_name = row[0]
        col_type = row[1]

        col_profile = _profile_column(con, src, col_name, col_type, row_count)
        columns[col_name] = col_profile

        if col_profile.get("null_rate", 0) > 0:
            null_rates[col_name] = round(col_profile["null_rate"], 4)

    return {
        "source_path": source_path,
        "source_type": source_type,
        "row_count": row_count,
        "columns": columns,
        "null_rates": null_rates,
    }


def _profile_column(
    con: duckdb.DuckDBPyConnection,
    src: str,
    col: str,
    col_type: str,
    row_count: int,
) -> dict:
    """Profile a single column — returns a dict of inferred contract fields."""
    result: dict[str, Any] = {"type": _normalize_type(col_type)}

    if row_count == 0:
        return result

    # --- Null rate ---
    null_count = con.execute(
        f'SELECT COUNT(*) FROM {src} WHERE "{col}" IS NULL'
    ).fetchone()[0]
    null_rate = null_count / row_count if row_count > 0 else 0
    result["null_rate"] = null_rate
    result["nullable"] = null_count > 0

    non_null_count = row_count - null_count
    if non_null_count == 0:
        return result

    # --- Uniqueness (only infer for integer/varchar, not floats/timestamps) ---
    distinct_count = con.execute(
        f'SELECT COUNT(DISTINCT "{col}") FROM {src}'
    ).fetchone()[0]
    _unique_eligible = _normalize_type(col_type) in ("INTEGER", "BIGINT", "VARCHAR")
    result["unique"] = (
        _unique_eligible and distinct_count == non_null_count and non_null_count > 1
    )

    # --- Numeric stats ---
    base_type = _normalize_type(col_type)
    if base_type in ("INTEGER", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL"):
        stats = con.execute(
            f'SELECT MIN("{col}"), MAX("{col}") FROM {src} WHERE "{col}" IS NOT NULL'
        ).fetchone()
        if stats[0] is not None:
            result["min"] = _clean_number(stats[0])
            result["max"] = _clean_number(stats[1])

    # --- Allowed values (low cardinality strings) ---
    if base_type == "VARCHAR" and distinct_count <= ENUM_THRESHOLD:
        vals = con.execute(
            f'SELECT DISTINCT "{col}" FROM {src} '
            f'WHERE "{col}" IS NOT NULL ORDER BY "{col}"'
        ).fetchall()
        result["allowed_values"] = [r[0] for r in vals]

    return result


def _normalize_type(duckdb_type: str) -> str:
    """Map DuckDB internal types to contract-friendly type names."""
    t = duckdb_type.upper()
    if t.startswith("DECIMAL") or t.startswith("NUMERIC"):
        return "DOUBLE"
    if "INT" in t:
        return "INTEGER" if t in ("INTEGER", "INT", "INT4", "INT32") else "BIGINT"
    if t in ("FLOAT", "REAL", "FLOAT4"):
        return "FLOAT"
    if t in ("DOUBLE", "FLOAT8"):
        return "DOUBLE"
    if t in ("VARCHAR", "TEXT", "STRING", "CHAR", "BPCHAR"):
        return "VARCHAR"
    if "TIMESTAMP" in t:
        return "TIMESTAMP"
    if t == "DATE":
        return "DATE"
    if t == "BOOLEAN":
        return "BOOLEAN"
    return t  # pass through unknowns


def _clean_number(val) -> float | int:
    """Return int if whole number, float otherwise. Handles Decimal types."""
    import decimal

    if isinstance(val, decimal.Decimal):
        val = float(val)
    if isinstance(val, float):
        if math.isfinite(val) and val == int(val):
            return int(val)
        return round(val, 6)
    if isinstance(val, int):
        return val
    return float(val)


# ---------------------------------------------------------------------------
# YAML rendering
# ---------------------------------------------------------------------------


def _render_yaml(profile: dict) -> str:
    """Build the contract dict and render it as clean YAML."""
    source_type = profile["source_type"]
    source_path = profile["source_path"]
    row_count = profile["row_count"]
    columns = profile["columns"]
    null_rates = profile["null_rates"]

    # --- Build contract structure ---
    contract: dict[str, Any] = {
        "version": 1,
        "name": Path(source_path).stem,
        "source": {
            "type": source_type,
            "path": source_path,
        },
        "columns": {},
        "dataset": {},
    }

    for col_name, col in columns.items():
        col_def: dict[str, Any] = {}

        if "type" in col:
            col_def["type"] = col["type"]

        col_def["nullable"] = col.get("nullable", True)

        if col.get("unique"):
            col_def["unique"] = True

        if "min" in col:
            col_def["min"] = col["min"]
        if "max" in col:
            col_def["max"] = col["max"]

        if "allowed_values" in col:
            col_def["allowed_values"] = col["allowed_values"]

        contract["columns"][col_name] = col_def

    # --- Dataset section ---
    dataset: dict[str, Any] = {}
    if row_count > 0:
        # suggest min_rows as 80% of current count (conservative)
        dataset["min_rows"] = max(1, int(row_count * 0.8))

    if null_rates:
        dataset["max_null_rate"] = {
            col: round(rate + 0.05, 4)  # add 5% buffer
            for col, rate in null_rates.items()
        }

    if dataset:
        contract["dataset"] = dataset
    else:
        del contract["dataset"]

    return _dump_yaml(contract)


def _dump_yaml(contract: dict) -> str:
    """Render dict to YAML with clean formatting."""
    return yaml.dump(
        contract,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        indent=2,
    )
