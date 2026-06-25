"""
ducktor.models
-----------------
All Pydantic dataclasses that represent a parsed data contract.
These are the internal representation - not raw YAML dict
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    parquet = "parquet"
    csv = "csv"
    json = "json"
    s3 = "s3"
    postgres = "postgres"


class OutputFormat(str, Enum):
    table = "table"
    json = "json"


# ---------------------------------------------------------------------------
# Source definition
# ---------------------------------------------------------------------------


class SourceDefinition(BaseModel):
    """Where ducktor reads data from"""

    type: SourceType
    path: str  # file path, s3 path, or postgres connection string

    model_config = {"extra": "forbid"}  # Forbid extra fields in the model


# ---------------------------------------------------------------------------
# Column-level checks
# ---------------------------------------------------------------------------


class ColumnContract(BaseModel):
    """All the checks that can be applied to a single column"""

    # Type assertion
    type: str | None = None  # e.g. INTEGER, VARCHAR, DOUBLE, TIMESTAMP

    # Nullability
    nullable: bool = True  # Whether the column can contain null values

    # Uniqueness
    unique: bool = False  # Whether the column values must be unique

    # Value constraints
    min: float | int | None = None  # Minimum value for numeric columns
    max: float | int | None = None  # Maximum value for numeric columns
    allowed_values: list[Any] | None = None  # List of allowed values for the column

    # Pattern match (regex applied via Duckdb regexp_matches)
    pattern: str | None = None  # Regex pattern that the column values must match

    # Custom SQL expression — must evaluate to TRUE for valid rows
    custom_sql: str | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Dataset-level checks
# ---------------------------------------------------------------------------


class FreshnessCheck(BaseModel):
    """Asserts a timestamp column is not too old."""

    column: str
    max_age_hours: float
    model_config = {"extra": "forbid"}


class DatasetContract(BaseModel):
    """All the checks that can be applied to a dataset"""

    min_rows: int | None = None
    max_rows: int | None = None

    # Per-column max null rate, e.g. {"amount": 0.0, "status": 0.05}
    max_null_rate: dict[str, float] | None = None

    # Freshness on a timestamp column
    freshness: FreshnessCheck | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Top-level contract
# ---------------------------------------------------------------------------


class ContractDefinition(BaseModel):
    """
    The full parsed and validated data contract.
    Produced by parser.py, consumed by compiler.py.
    """

    version: int = Field(default=1)
    name: str
    source: SourceDefinition
    columns: dict[str, ColumnContract] = Field(default_factory=dict)
    dataset: DatasetContract | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_null_rate_columns_exist(self) -> "ContractDefinition":
        """Ensure max_null_rate keys reference real columns."""
        if self.dataset and self.dataset.max_null_rate:
            for col in self.dataset.max_null_rate:
                if col not in self.columns:
                    raise ValueError(
                        f"max_null_rate references unknown column '{col}'. "
                        f"Defined columns: {list(self.columns.keys())}"
                    )
        return self

    @model_validator(mode="after")
    def validate_freshness_column_exists(self) -> "ContractDefinition":
        """Ensure freshness.column references a real column."""
        if self.dataset and self.dataset.freshness:
            col = self.dataset.freshness.column
            if col not in self.columns:
                raise ValueError(
                    f"freshness.column references unknown column '{col}'. "
                    f"Defined columns: {list(self.columns.keys())}"
                )
        return self
