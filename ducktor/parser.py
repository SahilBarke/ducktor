"""
ducktor.parser
--------------
Reads a contract YAML file and returns a validated ContractDefinition.
All user-facing parse errors are raised as ContractParseError with clear messages — no raw Pydantic or YAML tracebacks exposed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ducktor.models import ContractDefinition


class ContractParseError(Exception):
    """Raised when a contract YAML is malformed or fails validation."""

    pass


def parse(contract_path: str | Path) -> ContractDefinition:
    """
    Parse a YAML contract file into a ContractDefinition.

    Args:
        contract_path: path to the .yaml contract file

    Returns:
        ContractDefinition — fully validated

    Raises:
        ContractParseError — on missing file, invalid YAML, or schema violations
    """
    path = Path(contract_path)

    # --- File existence ---
    if not path.exists():
        raise ContractParseError(f"Contract file not found: {path}")

    if not path.is_file():
        raise ContractParseError(f"Path is not a file: {path}")

    # --- YAML parsing ---
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ContractParseError(f"Invalid YAML in '{path}':\n  {e}") from e

    if not isinstance(raw, dict):
        raise ContractParseError(
            f"Contract must be a YAML mapping (got {type(raw).__name__})"
        )

    # --- Required top-level fields ---
    _require_fields(raw, ["name", "source"], context="contract")

    # --- Pydantic validation ---
    try:
        contract = ContractDefinition.model_validate(raw)
    except ValidationError as e:
        raise ContractParseError(_format_pydantic_error(e, path)) from e

    return contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_fields(data: dict, fields: list[str], context: str) -> None:
    missing = [f for f in fields if f not in data]
    if missing:
        raise ContractParseError(
            f"Missing required field(s) in {context}: {', '.join(missing)}"
        )


def _format_pydantic_error(e: ValidationError, path: Path) -> str:
    """Turn a Pydantic ValidationError into a readable message."""
    lines = [f"Contract validation failed in '{path}':"]
    for err in e.errors():
        loc = " → ".join(str(x) for x in err["loc"]) if err["loc"] else "root"
        lines.append(f"  [{loc}] {err['msg']}")
    return "\n".join(lines)
