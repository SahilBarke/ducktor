"""
ducktor.cli
-----------
Click-based CLI. Three commands:
  ducktor validate <contract>   — run checks, report results
  ducktor profile  <source>     — scan a source, emit a starter contract
  ducktor diff     <a> <b>      — compare two contracts for breaking changes
"""

from __future__ import annotations

import sys
import json as _json
from pathlib import Path

import click
from rich.console import Console

from ducktor.parser import parse, ContractParseError
from ducktor.engine import run, EngineError
from ducktor.reporter import report_table, report_json

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="ducktor")
def main():
    """ducktor — DuckDB-native data contract validator."""
    pass


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@main.command()
@click.argument("contract", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--source",
    "-s",
    default=None,
    help="Override the source path defined in the contract (e.g. for CI runs against a specific partition).",
)
def validate(contract: str, output: str, source: str | None):
    """Validate a dataset against a YAML contract.

    \b
    Examples:
      ducktor validate orders_contract.yaml
      ducktor validate orders_contract.yaml --output json
      ducktor validate orders_contract.yaml --source s3://bucket/orders.parquet
    """
    # --- Parse ---
    try:
        contract_def = parse(contract)
    except ContractParseError as e:
        err_console.print(f"[bold red]Parse error:[/] {e}")
        sys.exit(2)

    # --- Run ---
    try:
        result = run(contract_def, source_override=source)
    except EngineError as e:
        err_console.print(f"[bold red]Engine error:[/] {e}")
        sys.exit(2)

    # --- Report ---
    if output == "json":
        click.echo(report_json(result))
    else:
        report_table(result, console=console)

    sys.exit(0 if result.passed else 1)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@main.command()
@click.argument("source", type=str)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Write the generated contract to this file (default: print to stdout).",
)
@click.option(
    "--type",
    "-t",
    "source_type",
    type=click.Choice(["parquet", "csv", "json"], case_sensitive=False),
    default=None,
    help="Source type (auto-detected from extension if not set).",
)
def profile(source: str, output: str | None, source_type: str | None):
    """Profile a data source and generate a starter contract YAML.

    \b
    Examples:
      ducktor profile data/orders.parquet
      ducktor profile data/orders.parquet --output orders_contract.yaml
      ducktor profile data/orders.csv --type csv
    """
    from ducktor.profiler import profile_source, ProfilerError

    detected_type = source_type or _detect_type(source)
    if detected_type is None:
        err_console.print(
            "[bold red]Cannot detect source type.[/] " "Use --type parquet|csv|json"
        )
        sys.exit(2)

    try:
        yaml_str = profile_source(source, detected_type)
    except ProfilerError as e:
        err_console.print(f"[bold red]Profiler error:[/] {e}")
        sys.exit(2)

    if output:
        Path(output).write_text(yaml_str, encoding="utf-8")
        console.print(f"[green]Contract written to[/] {output}")
    else:
        click.echo(yaml_str)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@main.command()
@click.argument("contract_a", type=click.Path(exists=True, dir_okay=False))
@click.argument("contract_b", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    show_default=True,
)
def diff(contract_a: str, contract_b: str, output: str):
    """Diff two contracts and report breaking changes.

    \b
    Examples:
      ducktor diff contracts/v1.yaml contracts/v2.yaml
      ducktor diff contracts/v1.yaml contracts/v2.yaml --output json
    """
    from ducktor.differ import diff_contracts, DiffResult

    try:
        a = parse(contract_a)
        b = parse(contract_b)
    except ContractParseError as e:
        err_console.print(f"[bold red]Parse error:[/] {e}")
        sys.exit(2)

    result: DiffResult = diff_contracts(a, b)

    if output == "json":
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        _print_diff_table(result, contract_a, contract_b)

    sys.exit(1 if result.has_breaking_changes else 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_type(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    return {".parquet": "parquet", ".csv": "csv", ".json": "json"}.get(ext)


def _print_diff_table(result, path_a: str, path_b: str) -> None:
    from rich.table import Table
    from rich import box

    console.print()
    console.print(f"  [bold]Contract diff:[/] [dim]{path_a}[/] → [dim]{path_b}[/]")
    console.print()

    if not result.changes:
        console.print("  [green]No changes detected.[/]")
        console.print()
        return

    table = Table(
        box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 2)
    )
    table.add_column("Change", min_width=44)
    table.add_column("Type", min_width=12)
    table.add_column("", min_width=6)

    for change in result.changes:
        if change.breaking:
            label = "[bold red]BREAKING[/]"
            icon = "[red]✗[/]"
        else:
            label = "[green]ADDITIVE[/]"
            icon = "[green]✔[/]"
        table.add_row(change.description, label, icon)

    console.print(table)

    if result.has_breaking_changes:
        n = sum(1 for c in result.changes if c.breaking)
        console.print(f"  [bold red]{n} breaking change(s) detected[/]")
    else:
        console.print("  [green]All changes are backward compatible.[/]")
    console.print()
