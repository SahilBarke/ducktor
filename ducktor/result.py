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
    ERROR = "ERROR"  # For example, if the check could not be executed due to a missing column


@dataclass
class CheckResult:
    """The result of a single check on a single column"""

    name: str  # e.g. "order_id :: not_null"
    status: CheckStatus
    sql: str  # the exact SQL that ran
    detail: str = ""  # human-readable failure reason or empty on pass

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASS


@dataclass
class ValidationResult:
    """Aggregated result of all checks for one contract run"""

    contract_name: str
    source_path: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]

    @property
    def summary(self) -> str:
        total = len(self.checks)
        failed = len(self.failed_checks)
        return {
            "total_checks": total,
            "passed_checks": total - failed,
            "failed_checks": failed,
            "overall_status": CheckStatus.PASS if failed == 0 else CheckStatus.FAIL,
        }
