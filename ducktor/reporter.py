"""
ducktor.reporter
----------------
Turns a ValidationResult into human or machine output.

Two modes:
  table  → Rich colored table for terminal output
  json   → Structured JSON for CI consumption
"""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from ducktor.result import ValidationResult, CheckResult, CheckStatus

# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def report_table(result: ValidationResult, console: Console | None = None) -> None:
    """Print a Rich colored table to stdout (or supplied console)."""
    con = console or Console()

    _print_header(result, con)
    _print_table(result, con)
    _print_summary(result, con)


def report_json(result: ValidationResult) -> str:
    """Return a JSON string of the full validation result."""
    payload = {
        "contract": result.contract_name,
        "source": result.source_path,
        "passed": result.passed,
        "summary": result.summary,
        "checks": [_check_to_dict(c) for c in result.checks],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# Table output helpers
# ---------------------------------------------------------------------------


def _print_header(result: ValidationResult, con: Console) -> None:
    status_text = "[bold green]PASSED[/]" if result.passed else "[bold red]FAILED[/]"
    con.print()
    con.print(
        f"  [bold]{result.contract_name}[/] → [dim]{result.source_path}[/]  {status_text}"
    )
    con.print()


def _print_table(result: ValidationResult, con: Console) -> None:
    if not result.checks:
        con.print("  [dim]No checks defined.[/]")
        return

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        padding=(0, 2),
    )

    table.add_column("Check", style="", min_width=36)
    table.add_column("Status", min_width=8, justify="left")
    table.add_column("Detail", style="dim")

    for check in result.checks:
        table.add_row(
            check.name,
            _status_text(check.status),
            check.detail or "",
        )

    con.print(table)


def _print_summary(result: ValidationResult, con: Console) -> None:
    s = result.summary
    total = s["total"]
    passed = s["passed"]
    failed = s["failed"]

    parts = [
        f"[dim]{total} checks[/]",
        f"[green]{passed} passed[/]",
    ]
    if failed:
        parts.append(f"[red]{failed} failed[/]")

    con.print("  " + "  |  ".join(parts))
    con.print()


def _status_text(status: CheckStatus) -> Text:
    match status:
        case CheckStatus.PASS:
            return Text("PASS", style="bold green")
        case CheckStatus.FAIL:
            return Text("FAIL", style="bold red")
        case CheckStatus.ERROR:
            return Text("ERROR", style="bold yellow")
        case _:
            return Text(str(status))


# ---------------------------------------------------------------------------
# JSON output helpers
# ---------------------------------------------------------------------------


def _check_to_dict(check: CheckResult) -> dict:
    return {
        "name": check.name,
        "status": check.status.value,
        "detail": check.detail,
        "sql": check.sql,
    }
