"""Generate fixture parquet and CSV files for engine tests."""

import duckdb

con = duckdb.connect()

# --- orders.parquet: clean data, all checks should pass ---
con.execute("""
COPY (
    SELECT
        i AS order_id,
        CASE (i % 4)
            WHEN 0 THEN 'pending'
            WHEN 1 THEN 'shipped'
            WHEN 2 THEN 'delivered'
            ELSE 'cancelled'
        END AS status,
        (i * 13.75) % 9000 + 10.0 AS amount,
        TIMESTAMPTZ '2026-06-20 10:00:00' + INTERVAL (i) MINUTE AS created_at
    FROM generate_series(1, 500) t(i)
) TO 'tests/fixtures/orders_clean.parquet' (FORMAT PARQUET)
""")

# --- orders_dirty.parquet: intentional violations ---
con.execute("""
COPY (
    SELECT
        CASE WHEN i = 50 THEN NULL ELSE i END AS order_id,  -- 1 null
        CASE WHEN i = 10 THEN 'refunded' ELSE               -- 1 bad allowed_value
            CASE (i % 4)
                WHEN 0 THEN 'pending'
                WHEN 1 THEN 'shipped'
                WHEN 2 THEN 'delivered'
                ELSE 'cancelled'
            END
        END AS status,
        CASE WHEN i = 20 THEN -99.0 ELSE (i * 13.75) % 9000 + 10.0 END AS amount, -- 1 below min
        TIMESTAMPTZ '2026-06-20 10:00:00' + INTERVAL (i) MINUTE AS created_at
    FROM generate_series(1, 500) t(i)
) TO 'tests/fixtures/orders_dirty.parquet' (FORMAT PARQUET)
""")

# --- minimal.csv ---
con.execute("""
COPY (SELECT i AS id, 'value_' || i AS label FROM generate_series(1,10) t(i))
TO 'tests/fixtures/minimal.csv' (FORMAT CSV, HEADER TRUE)
""")

print("Fixtures written.")
