"""
ducktor.result
--------------
Lightweight result containers. No business logic here —
just data structures that the engine writes and the reporter reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"  # check couldn't run (e.g. column missing)


@dataclass
class CheckResult:
    """Result of a single check."""

    name: str           # e.g. "order_id :: not_null"
    status: CheckStatus
    sql: str            # the exact SQL that ran
    detail: str = ""    # human-readable failure reason or empty on pass

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS


@dataclass
class ValidationResult:
    """Aggregated result of all checks for one contract run."""

    contract_name: str
    source_path: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def summary(self) -> dict:
        total = len(self.checks)
        failed = len(self.failed_checks)
        return {
            "total": total,
            "passed": total - failed,
            "failed": failed,
        }