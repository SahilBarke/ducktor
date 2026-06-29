# ducktor 🦆

**DuckDB-native data contract validator.**

Define what your data *must* look like in a YAML file. Run one command. Get a pass or fail.

No server. No account. No boilerplate. Just DuckDB.

```bash
pip install ducktor
ducktor validate orders_contract.yaml
```

```
  orders → data/orders.parquet  PASSED

  Check                              Status    Detail
  ────────────────────────────────── ───────── ──────────────────────────────
  order_id :: not_null               PASS
  order_id :: unique                 PASS
  status :: allowed_values           PASS
  amount :: not_null                 PASS
  amount :: min[0.0]                 PASS
  amount :: max[100000.0]            FAIL      3 row(s) violated
  created_at :: freshness[<=48h]     FAIL      got 73.2, expected <= 48

  7 checks  |  5 passed  |  2 failed
```

---

## Why ducktor

| | ducktor | Great Expectations | dbt tests | Soda Cloud |
|---|---|---|---|---|
| Setup | `pip install` | Data Context + config | dbt only | Cloud account |
| Source | Any DuckDB-readable | Connectors | dbt models | Connectors |
| Contract format | YAML | Python classes | YAML (limited) | YAML + cloud |
| CI-friendly | ✅ exit code | ✅ | ✅ | Paid |
| Show SQL | ✅ always | ✗ | ✗ | ✗ |
| Local-first | ✅ | ✗ | ✗ | ✗ |

---

## Install

```bash
pip install ducktor
```

Requires Python 3.10+. DuckDB is bundled — no extra installs.

---

## Quickstart

### 1. Profile your data (generate a starter contract)

```bash
ducktor profile data/orders.parquet --output orders_contract.yaml
```

This scans your file and infers column types, null rates, value ranges, and allowed values.

### 2. Tweak the contract

```yaml
version: 1
name: orders
source:
  type: parquet
  path: data/orders.parquet

columns:
  order_id:
    type: INTEGER
    nullable: false
    unique: true
  status:
    type: VARCHAR
    nullable: false
    allowed_values: [pending, shipped, delivered, cancelled]
  amount:
    type: DOUBLE
    nullable: false
    min: 0.0
    max: 100000.0
  created_at:
    type: TIMESTAMP
    nullable: false

dataset:
  min_rows: 1000
  max_null_rate:
    amount: 0.0
    status: 0.05
  freshness:
    column: created_at
    max_age_hours: 48
```

### 3. Validate

```bash
ducktor validate orders_contract.yaml
```

### 4. Diff contracts before deploying changes

```bash
ducktor diff orders_v1.yaml orders_v2.yaml
```

---

## Contract Reference

### Source types

```yaml
source:
  type: parquet   # local .parquet file
  path: data/orders.parquet

# or
source:
  type: csv
  path: data/orders.csv

# or
source:
  type: json
  path: data/orders.json

# or — S3 / GCS / R2 (requires httpfs)
source:
  type: s3
  path: s3://my-bucket/orders/2026-06-28.parquet

# or — Postgres
source:
  type: postgres
  path: postgresql://user:pass@host/dbname::public.orders
```

### Column checks

| Check | YAML key | Description |
|---|---|---|
| Type assertion | `type: INTEGER` | Column must be castable to this type |
| Not null | `nullable: false` | Zero nulls allowed |
| Unique | `unique: true` | All non-null values must be distinct |
| Minimum | `min: 0.0` | No values below this |
| Maximum | `max: 100000.0` | No values above this |
| Allowed values | `allowed_values: [a, b, c]` | Only these values permitted |
| Pattern | `pattern: "^[A-Z]{2}\\d{4}$"` | All values must match regex |
| Custom SQL | `custom_sql: "amount > 0 AND amount < total"` | Expression must be true for all rows |

### Dataset checks

| Check | YAML key | Description |
|---|---|---|
| Min rows | `min_rows: 1000` | Dataset must have at least N rows |
| Max rows | `max_rows: 10000000` | Dataset must have at most N rows |
| Null rate | `max_null_rate: {col: 0.05}` | Column null rate must not exceed threshold |
| Freshness | `freshness: {column: ts, max_age_hours: 48}` | Most recent timestamp must be within N hours |

---

## CLI Reference

```bash
# Validate a contract
ducktor validate orders_contract.yaml

# Validate with JSON output (for CI)
ducktor validate orders_contract.yaml --output json

# Override source path at runtime
ducktor validate orders_contract.yaml --source s3://bucket/orders/2026-06-28.parquet

# Profile a source and generate a starter contract
ducktor profile data/orders.parquet
ducktor profile data/orders.parquet --output orders_contract.yaml
ducktor profile data/orders.csv --type csv

# Diff two contracts
ducktor diff orders_v1.yaml orders_v2.yaml
ducktor diff orders_v1.yaml orders_v2.yaml --output json
```

**Exit codes:**
- `0` — all checks passed (or no breaking changes for `diff`)
- `1` — one or more checks failed (or breaking changes detected)
- `2` — parse or engine error (bad YAML, file not found, etc.)

---

## Python Library

```python
from ducktor import validate

# Simple
result = validate("orders_contract.yaml")
print(result.passed)       # True / False
print(result.summary)      # {"total": 9, "passed": 8, "failed": 1}

# With source override
result = validate(
    "orders_contract.yaml",
    source="s3://prod-bucket/orders/2026-06-28.parquet",
)

# Inspect individual checks
for check in result.failed_checks:
    print(f"FAILED: {check.name}")
    print(f"  detail: {check.detail}")
    print(f"  sql:    {check.sql}")   # exact SQL that ran
```

### Using in Airflow

```python
from airflow.operators.python import PythonOperator
from ducktor import validate

def validate_orders(**context):
    result = validate(
        "contracts/orders_contract.yaml",
        source=f"s3://bucket/orders/{context['ds']}.parquet",
    )
    if not result.passed:
        failed = [c.name for c in result.failed_checks]
        raise ValueError(f"Contract failed: {failed}")

validate_task = PythonOperator(
    task_id="validate_orders",
    python_callable=validate_orders,
)
```

### Using in Prefect

```python
from prefect import task
from ducktor import validate

@task
def validate_orders(partition: str):
    result = validate(
        "contracts/orders_contract.yaml",
        source=f"s3://bucket/orders/{partition}.parquet",
    )
    if not result.passed:
        raise RuntimeError(f"{result.summary['failed']} checks failed")
    return result.summary
```

---

## CI / CD

### GitHub Actions

```yaml
name: Data Contract Validation
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ducktor
      - run: ducktor validate contracts/orders_contract.yaml
```

### JSON output for downstream steps

```yaml
      - run: ducktor validate contracts/orders_contract.yaml --output json > validation.json
      - name: Upload validation report
        uses: actions/upload-artifact@v4
        with:
          name: validation-report
          path: validation.json
```

### Pre-commit hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: ducktor
        name: Validate data contracts
        entry: ducktor validate
        args: [contracts/orders_contract.yaml]
        language: system
        pass_filenames: false
```

---

## How it works

Every check compiles down to a DuckDB SQL query. You can always see exactly what ran:

```python
from ducktor import validate

result = validate("orders_contract.yaml")
for check in result.checks:
    print(f"{check.name}: {check.status.value}")
    print(f"  {check.sql}")
```

Example SQL for a `not_null` check:
```sql
SELECT COUNT(*) FROM read_parquet('data/orders.parquet') WHERE order_id IS NULL
```

Zero violating rows = PASS. No magic, no hidden logic.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/yourusername/ducktor
cd ducktor
pip install -e ".[dev]"
pytest
```

---

## License

MIT
