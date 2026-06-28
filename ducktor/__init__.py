"""
ducktor — DuckDB-native data contract validator.

Library usage:
    from ducktor import validate
    result = validate("orders_contract.yaml")
"""

from ducktor.parser import parse, ContractParseError
from ducktor.engine import run, EngineError
from ducktor.result import ValidationResult, CheckResult, CheckStatus


def validate(contract_path: str, source: str | None = None) -> ValidationResult:
    """
    Parse and validate a contract in one call.

    Args:
        contract_path: path to the YAML contract file
        source: optional source path override

    Returns:
        ValidationResult

    Raises:
        ContractParseError — if the contract YAML is invalid
        EngineError — if the source cannot be read
    """
    contract = parse(contract_path)
    return run(contract, source_override=source)


__all__ = [
    "validate",
    "parse",
    "run",
    "ContractParseError",
    "EngineError",
    "ValidationResult",
    "CheckResult",
    "CheckStatus",
]
