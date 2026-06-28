"""
Tests for ducktor.reporter
"""

import json
import pytest

from rich.console import Console
from io import StringIO

from ducktor.reporter import report_table, report_json
from ducktor.result import ValidationResult, CheckResult, CheckStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_result(checks: list[CheckResult]) -> ValidationResult:
    return ValidationResult(
        contract_name="orders",
        source_path="data/orders.parquet",
        checks=checks,
    )


def capture_table(result: ValidationResult) -> str:
    """Render the Rich table to a string."""
    buf = StringIO()
    con = Console(file=buf, highlight=False, markup=True, width=120)
    report_table(result, console=con)
    return buf.getvalue()


PASS_CHECK = CheckResult(
    name="order_id :: not_null",
    status=CheckStatus.PASS,
    sql="SELECT COUNT(*) FROM t WHERE order_id IS NULL",
)
FAIL_CHECK = CheckResult(
    name="amount :: min[0.0]",
    status=CheckStatus.FAIL,
    sql="SELECT COUNT(*) FROM t WHERE amount < 0.0",
    detail="3 row(s) violated",
)
ERROR_CHECK = CheckResult(
    name="bad_col :: not_null",
    status=CheckStatus.ERROR,
    sql="SELECT COUNT(*) FROM t WHERE bad_col IS NULL",
    detail="Query error: column not found",
)


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------


def test_table_contains_contract_name():
    result = make_result([PASS_CHECK])
    output = capture_table(result)
    assert "orders" in output


def test_table_contains_source_path():
    result = make_result([PASS_CHECK])
    output = capture_table(result)
    assert "data/orders.parquet" in output


def test_table_shows_pass():
    result = make_result([PASS_CHECK])
    output = capture_table(result)
    assert "PASS" in output
    assert "order_id :: not_null" in output


def test_table_shows_fail():
    result = make_result([FAIL_CHECK])
    output = capture_table(result)
    assert "FAIL" in output
    assert "3 row(s) violated" in output


def test_table_shows_error():
    result = make_result([ERROR_CHECK])
    output = capture_table(result)
    assert "ERROR" in output


def test_table_summary_counts():
    result = make_result([PASS_CHECK, FAIL_CHECK])
    output = capture_table(result)
    assert "2 checks" in output
    assert "1 passed" in output
    assert "1 failed" in output


def test_table_no_checks():
    result = make_result([])
    output = capture_table(result)
    assert "No checks" in output


def test_table_overall_passed_label():
    result = make_result([PASS_CHECK])
    output = capture_table(result)
    assert "PASSED" in output


def test_table_overall_failed_label():
    result = make_result([FAIL_CHECK])
    output = capture_table(result)
    assert "FAILED" in output


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_json_is_valid():
    result = make_result([PASS_CHECK, FAIL_CHECK])
    output = report_json(result)
    parsed = json.loads(output)
    assert isinstance(parsed, dict)


def test_json_top_level_fields():
    result = make_result([PASS_CHECK])
    parsed = json.loads(report_json(result))
    assert parsed["contract"] == "orders"
    assert parsed["source"] == "data/orders.parquet"
    assert "passed" in parsed
    assert "summary" in parsed
    assert "checks" in parsed


def test_json_passed_false_on_failure():
    result = make_result([FAIL_CHECK])
    parsed = json.loads(report_json(result))
    assert parsed["passed"] is False


def test_json_passed_true_on_all_pass():
    result = make_result([PASS_CHECK])
    parsed = json.loads(report_json(result))
    assert parsed["passed"] is True


def test_json_check_fields():
    result = make_result([FAIL_CHECK])
    parsed = json.loads(report_json(result))
    check = parsed["checks"][0]
    assert check["name"] == "amount :: min[0.0]"
    assert check["status"] == "FAIL"
    assert check["detail"] == "3 row(s) violated"
    assert "SELECT" in check["sql"]


def test_json_summary_counts():
    result = make_result([PASS_CHECK, FAIL_CHECK, ERROR_CHECK])
    parsed = json.loads(report_json(result))
    assert parsed["summary"]["total"] == 3
    assert parsed["summary"]["passed"] == 1
    assert parsed["summary"]["failed"] == 2
