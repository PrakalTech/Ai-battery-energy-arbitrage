#!/usr/bin/env python3
"""
Load validated CSVs into SQLite. Idempotent: DELETE then INSERT per table.

Workflow:
  1. Run validate_datasets.py on the source folder — abort if any errors.
  2. Open / initialise the SQLite database (DB_PATH from .env).
  3. For each present CSV, DELETE the existing rows and INSERT the new ones.
  4. Print a row-count table.

Usage:
    python scripts/load_data.py --source data/sample
    python scripts/load_data.py --source data/raw
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

# Resolve the project root and add it to sys.path so energy_agent is importable
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd
from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

import os
from energy_agent.db import get_connection, init_db

# ── CSV file → SQLite table mapping (order matters for FK dependencies) ────────
CSV_TABLE_MAP: list[tuple[str, str]] = [
    ("sites.csv",                  "sites"),
    ("price_history.csv",          "price_history"),
    ("renewable_generation.csv",   "renewable_generation"),
    ("forecasts.csv",              "forecasts"),
    ("site_status.csv",            "site_status"),
    ("optimization_runs.csv",      "optimization_runs"),
    ("backtest_results.csv",       "backtest_results"),
]


def load_csv(conn, csv_path: pathlib.Path, table: str) -> int:
    """
    Delete existing rows in `table` then bulk-insert from `csv_path`.
    Returns the number of rows inserted.
    """
    df = pd.read_csv(csv_path)
    conn.execute(f"DELETE FROM {table}")   # idempotent
    df.to_sql(table, conn, if_exists="append", index=False)
    return len(df)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and load CSVs into SQLite (idempotent)."
    )
    parser.add_argument(
        "--source", required=True,
        help="Source CSV folder, e.g. data/sample or data/raw"
    )
    args = parser.parse_args()

    source = pathlib.Path(args.source)
    if not source.is_dir():
        print(f"ERROR: Source directory not found: {source}")
        sys.exit(1)

    # ── Step 1: Validate ──────────────────────────────────────────────────────
    print(f"╔══ Validating {source} …")
    validator = _ROOT / "scripts" / "validate_datasets.py"
    result = subprocess.run(
        [sys.executable, str(validator), str(source)],
        capture_output=True,
        text=True,
    )
    # Print validator output (includes [ERROR]/[WARN] lines and summary)
    for line in result.stdout.strip().splitlines():
        print(f"║  {line}")
    if result.returncode != 0:
        print("╚══ ABORT: validation errors found. Fix them before loading.")
        sys.exit(1)
    print("╚══ Validation passed.\n")

    # ── Step 2: Open / initialise DB ─────────────────────────────────────────
    db_path = os.getenv("DB_PATH", "energy_agent.db")
    print(f"Database : {pathlib.Path(db_path).resolve()}")
    conn = get_connection(db_path)
    init_db(conn)

    # ── Step 3: Load each CSV ─────────────────────────────────────────────────
    print(f"\n{'Table':<32} {'Rows':>8}")
    print("─" * 42)
    total_rows = 0
    for csv_name, table in CSV_TABLE_MAP:
        csv_path = source / csv_name
        if not csv_path.exists():
            print(f"  {'[skipped] ' + table:<30} {'—':>8}")
            continue
        n = load_csv(conn, csv_path, table)
        print(f"  {table:<30} {n:>8}")
        total_rows += n

    conn.commit()
    conn.close()

    print("─" * 42)
    print(f"  {'TOTAL':<30} {total_rows:>8}")
    print("\nDone.")


if __name__ == "__main__":
    main()
