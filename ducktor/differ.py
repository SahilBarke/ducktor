"""
ducktor.differ
--------------
Compares two ContractDefinitions and classifies every change as
ADDITIVE (safe) or BREAKING (may break downstream consumers).

Breaking change rules:
  - Column removed
  - Column type changed
  - nullable: true → false  (stricter, existing NULLs would now fail)
  - unique added            (existing duplicates would now fail)
  - min raised              (existing low values would now fail)
  - max lowered             (existing high values would now fail)
  - allowed_values narrowed (existing values may no longer be valid)
  - pattern added/changed   (existing values may no longer match)
  - min_rows raised
  - max_rows lowered
  - max_null_rate lowered   (stricter tolerance)
  - freshness max_age_hours lowered

Additive change rules:
  - Column added
  - nullable: false → true  (more permissive)
  - unique removed
  - min lowered / max raised (more permissive)
  - allowed_values widened
  - pattern removed
  - min_rows lowered / max_rows raised
  - max_null_rate raised
  - freshness max_age_hours raised
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ducktor.models import ContractDefinition, ColumnContract, DatasetContract

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Change:
    description: str
    breaking: bool

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "breaking": self.breaking,
            "type": "BREAKING" if self.breaking else "ADDITIVE",
        }


@dataclass
class DiffResult:
    changes: list[Change] = field(default_factory=list)

    @property
    def has_breaking_changes(self) -> bool:
        return any(c.breaking for c in self.changes)

    @property
    def breaking_changes(self) -> list[Change]:
        return [c for c in self.changes if c.breaking]

    @property
    def additive_changes(self) -> list[Change]:
        return [c for c in self.changes if not c.breaking]

    def to_dict(self) -> dict:
        return {
            "has_breaking_changes": self.has_breaking_changes,
            "summary": {
                "total": len(self.changes),
                "breaking": len(self.breaking_changes),
                "additive": len(self.additive_changes),
            },
            "changes": [c.to_dict() for c in self.changes],
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def diff_contracts(a: ContractDefinition, b: ContractDefinition) -> DiffResult:
    """
    Compare contract A (old) to contract B (new) and return a DiffResult.

    Args:
        a: the old / baseline contract
        b: the new / proposed contract

    Returns:
        DiffResult with classified changes
    """
    result = DiffResult()

    _diff_columns(a, b, result)
    _diff_dataset(a.dataset, b.dataset, result)

    return result


# ---------------------------------------------------------------------------
# Column diffing
# ---------------------------------------------------------------------------


def _diff_columns(
    a: ContractDefinition,
    b: ContractDefinition,
    result: DiffResult,
) -> None:
    a_cols = a.columns
    b_cols = b.columns

    all_cols = set(a_cols) | set(b_cols)

    for col in sorted(all_cols):
        in_a = col in a_cols
        in_b = col in b_cols

        if in_a and not in_b:
            result.changes.append(
                Change(
                    description=f"column '{col}' removed",
                    breaking=True,
                )
            )
        elif not in_a and in_b:
            result.changes.append(
                Change(
                    description=f"column '{col}' added",
                    breaking=False,
                )
            )
        else:
            _diff_column_contract(col, a_cols[col], b_cols[col], result)


def _diff_column_contract(
    col: str,
    a: ColumnContract,
    b: ColumnContract,
    result: DiffResult,
) -> None:

    # --- Type ---
    if a.type != b.type and a.type is not None and b.type is not None:
        result.changes.append(
            Change(
                description=f"'{col}' type changed: {a.type} → {b.type}",
                breaking=True,
            )
        )

    # --- Nullable ---
    if a.nullable is True and b.nullable is False:
        result.changes.append(
            Change(
                description=f"'{col}' nullable: true → false (stricter)",
                breaking=True,
            )
        )
    elif a.nullable is False and b.nullable is True:
        result.changes.append(
            Change(
                description=f"'{col}' nullable: false → true (more permissive)",
                breaking=False,
            )
        )

    # --- Unique ---
    if not a.unique and b.unique:
        result.changes.append(
            Change(
                description=f"'{col}' unique constraint added",
                breaking=True,
            )
        )
    elif a.unique and not b.unique:
        result.changes.append(
            Change(
                description=f"'{col}' unique constraint removed",
                breaking=False,
            )
        )

    # --- Min ---
    if a.min is None and b.min is not None:
        result.changes.append(
            Change(
                description=f"'{col}' min added: {b.min}",
                breaking=True,
            )
        )
    elif a.min is not None and b.min is None:
        result.changes.append(
            Change(
                description=f"'{col}' min removed",
                breaking=False,
            )
        )
    elif a.min is not None and b.min is not None and b.min > a.min:
        result.changes.append(
            Change(
                description=f"'{col}' min raised: {a.min} → {b.min}",
                breaking=True,
            )
        )
    elif a.min is not None and b.min is not None and b.min < a.min:
        result.changes.append(
            Change(
                description=f"'{col}' min lowered: {a.min} → {b.min}",
                breaking=False,
            )
        )

    # --- Max ---
    if a.max is None and b.max is not None:
        result.changes.append(
            Change(
                description=f"'{col}' max added: {b.max}",
                breaking=True,
            )
        )
    elif a.max is not None and b.max is None:
        result.changes.append(
            Change(
                description=f"'{col}' max removed",
                breaking=False,
            )
        )
    elif a.max is not None and b.max is not None and b.max < a.max:
        result.changes.append(
            Change(
                description=f"'{col}' max lowered: {a.max} → {b.max}",
                breaking=True,
            )
        )
    elif a.max is not None and b.max is not None and b.max > a.max:
        result.changes.append(
            Change(
                description=f"'{col}' max raised: {a.max} → {b.max}",
                breaking=False,
            )
        )

    # --- Allowed values ---
    if a.allowed_values is None and b.allowed_values is not None:
        result.changes.append(
            Change(
                description=f"'{col}' allowed_values added: {b.allowed_values}",
                breaking=True,
            )
        )
    elif a.allowed_values is not None and b.allowed_values is None:
        result.changes.append(
            Change(
                description=f"'{col}' allowed_values removed (unconstrained)",
                breaking=False,
            )
        )
    elif a.allowed_values is not None and b.allowed_values is not None:
        a_set = set(a.allowed_values)
        b_set = set(b.allowed_values)
        removed = a_set - b_set
        added = b_set - a_set
        if removed:
            result.changes.append(
                Change(
                    description=f"'{col}' allowed_values narrowed: removed {sorted(removed)}",
                    breaking=True,
                )
            )
        if added:
            result.changes.append(
                Change(
                    description=f"'{col}' allowed_values widened: added {sorted(added)}",
                    breaking=False,
                )
            )

    # --- Pattern ---
    if a.pattern is None and b.pattern is not None:
        result.changes.append(
            Change(
                description=f"'{col}' pattern added: '{b.pattern}'",
                breaking=True,
            )
        )
    elif a.pattern is not None and b.pattern is None:
        result.changes.append(
            Change(
                description=f"'{col}' pattern removed",
                breaking=False,
            )
        )
    elif a.pattern != b.pattern:
        result.changes.append(
            Change(
                description=f"'{col}' pattern changed: '{a.pattern}' → '{b.pattern}'",
                breaking=True,
            )
        )


# ---------------------------------------------------------------------------
# Dataset diffing
# ---------------------------------------------------------------------------


def _diff_dataset(
    a: DatasetContract | None,
    b: DatasetContract | None,
    result: DiffResult,
) -> None:
    # Both absent — nothing to diff
    if a is None and b is None:
        return

    # Dataset section added or removed entirely
    if a is None and b is not None:
        result.changes.append(
            Change(
                description="dataset checks added",
                breaking=False,
            )
        )
        a = DatasetContract()  # compare against empty defaults

    if b is None and a is not None:
        result.changes.append(
            Change(
                description="dataset checks removed",
                breaking=False,
            )
        )
        return

    # --- min_rows ---
    if a.min_rows is None and b.min_rows is not None:
        result.changes.append(
            Change(
                description=f"dataset min_rows added: {b.min_rows}",
                breaking=True,
            )
        )
    elif a.min_rows is not None and b.min_rows is None:
        result.changes.append(
            Change(
                description="dataset min_rows removed",
                breaking=False,
            )
        )
    elif a.min_rows is not None and b.min_rows is not None and b.min_rows > a.min_rows:
        result.changes.append(
            Change(
                description=f"dataset min_rows raised: {a.min_rows} → {b.min_rows}",
                breaking=True,
            )
        )
    elif a.min_rows is not None and b.min_rows is not None and b.min_rows < a.min_rows:
        result.changes.append(
            Change(
                description=f"dataset min_rows lowered: {a.min_rows} → {b.min_rows}",
                breaking=False,
            )
        )

    # --- max_rows ---
    if a.max_rows is None and b.max_rows is not None:
        result.changes.append(
            Change(
                description=f"dataset max_rows added: {b.max_rows}",
                breaking=True,
            )
        )
    elif a.max_rows is not None and b.max_rows is None:
        result.changes.append(
            Change(
                description="dataset max_rows removed",
                breaking=False,
            )
        )
    elif a.max_rows is not None and b.max_rows is not None and b.max_rows < a.max_rows:
        result.changes.append(
            Change(
                description=f"dataset max_rows lowered: {a.max_rows} → {b.max_rows}",
                breaking=True,
            )
        )
    elif a.max_rows is not None and b.max_rows is not None and b.max_rows > a.max_rows:
        result.changes.append(
            Change(
                description=f"dataset max_rows raised: {a.max_rows} → {b.max_rows}",
                breaking=False,
            )
        )

    # --- max_null_rate ---
    a_nr = a.max_null_rate or {}
    b_nr = b.max_null_rate or {}
    all_nr_cols = set(a_nr) | set(b_nr)
    for col in sorted(all_nr_cols):
        if col not in a_nr and col in b_nr:
            result.changes.append(
                Change(
                    description=f"max_null_rate added for '{col}': {b_nr[col]}",
                    breaking=True,
                )
            )
        elif col in a_nr and col not in b_nr:
            result.changes.append(
                Change(
                    description=f"max_null_rate removed for '{col}'",
                    breaking=False,
                )
            )
        elif b_nr[col] < a_nr[col]:
            result.changes.append(
                Change(
                    description=f"max_null_rate tightened for '{col}': {a_nr[col]} → {b_nr[col]}",
                    breaking=True,
                )
            )
        elif b_nr[col] > a_nr[col]:
            result.changes.append(
                Change(
                    description=f"max_null_rate loosened for '{col}': {a_nr[col]} → {b_nr[col]}",
                    breaking=False,
                )
            )

    # --- Freshness ---
    a_fr = a.freshness
    b_fr = b.freshness
    if a_fr is None and b_fr is not None:
        result.changes.append(
            Change(
                description=f"freshness check added: {b_fr.column} max {b_fr.max_age_hours}h",
                breaking=True,
            )
        )
    elif a_fr is not None and b_fr is None:
        result.changes.append(
            Change(
                description="freshness check removed",
                breaking=False,
            )
        )
    elif a_fr is not None and b_fr is not None:
        if b_fr.max_age_hours < a_fr.max_age_hours:
            result.changes.append(
                Change(
                    description=f"freshness tightened: {a_fr.max_age_hours}h → {b_fr.max_age_hours}h",
                    breaking=True,
                )
            )
        elif b_fr.max_age_hours > a_fr.max_age_hours:
            result.changes.append(
                Change(
                    description=f"freshness loosened: {a_fr.max_age_hours}h → {b_fr.max_age_hours}h",
                    breaking=False,
                )
            )
        if a_fr.column != b_fr.column:
            result.changes.append(
                Change(
                    description=f"freshness column changed: '{a_fr.column}' → '{b_fr.column}'",
                    breaking=True,
                )
            )
