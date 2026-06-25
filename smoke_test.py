"""
Smoke test for the ducktor package.
This file is not part of the main package, but is used to verify that the package can be imported and that the main classes can be instantiated.
"""

from ducktor.models import (
    ContractDefinition,
    ColumnContract,
    SourceDefinition,
    SourceType,
)
from ducktor.result import ValidationResult, CheckResult, CheckStatus

print("models.py — OK")
print("result.py  — OK")

contract = ContractDefinition(
    name="test",
    source=SourceDefinition(type=SourceType.parquet, path="data/test.parquet"),
    columns={
        "id": ColumnContract(type="INTEGER", nullable=False, unique=True),
        "amount": ColumnContract(type="DOUBLE", min=0.0, max=1000.0),
    },
)

print(f"ContractDefinition OK — columns: {list(contract.columns.keys())}")

r = ValidationResult(contract_name="test", source_path="data/test.parquet")

r.checks.append(
    CheckResult(
        name="id :: not_null",
        status=CheckStatus.PASS,
        sql="SELECT COUNT(*) FROM t WHERE id IS NULL",
    )
)

r.checks.append(
    CheckResult(
        name="amount :: max",
        status=CheckStatus.FAIL,
        sql="SELECT COUNT(*) FROM t WHERE amount > 1000",
        detail="3 rows violated",
    )
)

print(f"ValidationResult OK — passed={r.passed}, summary={r.summary}")
