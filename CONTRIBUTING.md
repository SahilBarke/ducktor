# Contributing to ducktor

Thanks for your interest. ducktor is intentionally small and focused —
contributions that keep it that way are most welcome.

## Setup

```bash
git clone https://github.com/yourusername/ducktor
cd ducktor
pip install -e ".[dev]"
```

## Running tests

```bash
pytest                   # all tests
pytest tests/test_engine.py -v   # single file
pytest -k "not_null"     # by keyword
```

## Project structure

```
ducktor/
├── ducktor/
│   ├── models.py     # Pydantic dataclasses — contract schema
│   ├── parser.py     # YAML → ContractDefinition
│   ├── compiler.py   # ContractDefinition → SQL checks
│   ├── engine.py     # executes checks via DuckDB
│   ├── result.py     # CheckResult / ValidationResult containers
│   ├── reporter.py   # Rich table + JSON output
│   ├── profiler.py   # source → starter contract YAML
│   ├── differ.py     # contract A vs B → breaking/additive changes
│   └── cli.py        # Click commands
└── tests/
    ├── fixtures/     # sample parquet/csv + contract YAMLs
    └── test_*.py
```

## Adding a new check type

1. Add the field to `ColumnContract` or `DatasetContract` in `models.py`
2. Add a compiler function in `compiler.py` that returns a `CompiledCheck`
3. Call it from `_compile_column()` or `_compile_dataset()`
4. Add a diff rule in `differ.py` if the check has tighter/looser semantics
5. Add tests in `test_compiler.py` and `test_engine.py`
6. Document in `README.md`

## Adding a new source type

1. Add the value to `SourceType` enum in `models.py`
2. Handle it in `_build_source_expr()` in `engine.py`
3. Handle it in `_build_source_expr()` in `profiler.py`
4. Install any required DuckDB extension in `_install_extensions()` in `engine.py`

## Guidelines

- Keep check SQL transparent — users must be able to copy and run it
- No persistent state — each `validate` run is ephemeral
- Fail fast on parse errors, never on check failures (those are reported)
- Every new check type needs a compiler test AND an engine test
- Keep the CLI surface small — resist adding flags that belong in the contract

## Pull request checklist

- [ ] Tests pass: `pytest`
- [ ] New feature has tests
- [ ] README updated if user-facing behavior changed
- [ ] No new required dependencies without discussion
