#!/usr/bin/env python3
"""
Validate a dataset folder against the energy-ops-agent data contract (§8.3).

Usage:
    python scripts/validate_datasets.py data/sample
    python scripts/validate_datasets.py data/raw

Exits 0 if zero errors, 1 if any errors.
Warnings are printed but do not affect the exit code.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Optional

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Contract definition (mirrors §8.3)
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_COLS: dict[str, list[str]] = {
    "sites": [
        "site_id", "site_name", "location", "market_zone", "status",
        "capacity_mwh", "power_mw", "round_trip_efficiency",
        "soc_min_pct", "soc_max_pct", "reserve_soc_pct",
        "max_daily_discharge_mwh", "degradation_cost_inr_per_mwh", "initial_soc_pct",
    ],
    "price_history": ["timestamp", "market_zone", "price_inr_per_mwh"],
    "renewable_generation": ["timestamp", "market_zone", "solar_mw", "wind_mw"],
    "forecasts": [
        "forecast_id", "market_zone", "created_at", "timestamp",
        "predicted_price_inr_per_mwh", "model_version",
    ],
    "site_status": [
        "site_id", "timestamp", "soc_pct", "operating_status",
        "available_power_mw", "cycles_today", "temperature_c", "active_alarms",
    ],
    "optimization_runs": [
        "optimization_run_id", "site_id", "created_at", "forecast_id",
        "solver_status", "runtime_s", "initial_soc_mwh",
        "expected_revenue_inr", "charging_cost_inr", "degradation_cost_inr",
        "expected_profit_inr", "throughput_mwh", "binding_constraints", "schedule_json",
    ],
    "backtest_results": [
        "backtest_run_id", "site_id", "period_start", "period_end",
        "actual_profit_inr", "perfect_foresight_profit_inr", "regret_inr",
        "regret_percent", "throughput_mwh", "degradation_cost_inr",
        "forecast_mae_inr_per_mwh", "optimization_runtime_s",
    ],
}

REQUIRED_FILES: set[str] = {"sites", "price_history"}
OPTIONAL_FILES: set[str] = {
    "renewable_generation", "forecasts", "site_status",
    "optimization_runs", "backtest_results",
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "sites":              ["site_id"],
    "price_history":      ["timestamp", "market_zone"],
    "renewable_generation": ["timestamp", "market_zone"],
    "forecasts":          ["forecast_id", "timestamp"],
    "site_status":        ["site_id", "timestamp"],
    "optimization_runs":  ["optimization_run_id"],
    "backtest_results":   ["backtest_run_id"],
}

# Numeric columns with expected bounds [low, high, inclusive]
NUMERIC_BOUNDS: dict[str, list[tuple[str, Optional[float], Optional[float]]]] = {
    "sites": [
        ("capacity_mwh",                  0, None),
        ("power_mw",                      0, None),
        ("round_trip_efficiency",         0, 1),
        ("soc_min_pct",                   0, 100),
        ("soc_max_pct",                   0, 100),
        ("reserve_soc_pct",               0, 100),
        ("initial_soc_pct",               0, 100),
        ("max_daily_discharge_mwh",       0, None),
        ("degradation_cost_inr_per_mwh",  0, None),
    ],
    "price_history": [
        ("price_inr_per_mwh", 0, 10_000),
    ],
    "site_status": [
        ("soc_pct",            0, 100),
        ("active_alarms",      0, None),
    ],
}


def _err(msgs: list[str], msg: str) -> None:
    print(f"[ERROR] {msg}")
    msgs.append(msg)


def _warn(msg: str) -> None:
    print(f"[WARN ] {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Main validator
# ─────────────────────────────────────────────────────────────────────────────

def validate(folder: pathlib.Path) -> int:
    """Return the number of errors found."""
    errors: list[str] = []
    dfs: dict[str, pd.DataFrame] = {}

    # ── 1. File existence ─────────────────────────────────────────────────────
    for stem in REQUIRED_FILES:
        p = folder / f"{stem}.csv"
        if not p.exists():
            _err(errors, f"Required file missing: {p}")

    for stem in OPTIONAL_FILES:
        p = folder / f"{stem}.csv"
        if not p.exists():
            _warn(f"Optional file missing: {p}")

    # ── 2. Load and validate each present file ────────────────────────────────
    for stem, required_cols in REQUIRED_COLS.items():
        p = folder / f"{stem}.csv"
        if not p.exists():
            continue

        # Load as strings to check nulls before type conversion
        try:
            df = pd.read_csv(p, dtype=str, keep_default_na=False)
        except Exception as exc:
            _err(errors, f"{stem}.csv: cannot read file — {exc}")
            continue
        dfs[stem] = df

        # Column presence
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            _err(errors, f"{stem}.csv: missing columns {missing}")

        # No empty/null in required columns that are present
        present = [c for c in required_cols if c in df.columns]
        null_cols = [c for c in present if df[c].isin(["", "nan", "None"]).any()]
        if null_cols:
            _err(errors, f"{stem}.csv: empty or null values in {null_cols}")

        # Primary key uniqueness
        pks = [c for c in PRIMARY_KEYS.get(stem, []) if c in df.columns]
        if pks and df.duplicated(subset=pks).any():
            n_dup = int(df.duplicated(subset=pks).sum())
            _err(errors, f"{stem}.csv: {n_dup} duplicate primary key row(s) on {pks}")

        # Numeric bounds
        for col, lo, hi in NUMERIC_BOUNDS.get(stem, []):
            if col not in df.columns:
                continue
            vals = pd.to_numeric(df[col], errors="coerce")
            if vals.isna().any():
                _err(errors, f"{stem}.csv: non-numeric values in '{col}'")
                continue
            if lo is not None and (vals < lo).any():
                bad = int((vals < lo).sum())
                _err(errors, f"{stem}.csv: {bad} row(s) in '{col}' below minimum {lo}")
            if hi is not None and (vals > hi).any():
                bad = int((vals > hi).sum())
                if stem == "price_history" and col == "price_inr_per_mwh":
                    # Prices above 10 000 are capped in the generator; warn only
                    _warn(f"{stem}.csv: {bad} price(s) exceed {hi} INR/MWh (expected: capped)")
                else:
                    _err(errors, f"{stem}.csv: {bad} row(s) in '{col}' above maximum {hi}")

    # ── 3. Cross-references ───────────────────────────────────────────────────
    if "sites" in dfs and "price_history" in dfs:
        site_zones  = set(dfs["sites"]["market_zone"].unique())
        price_zones = set(dfs["price_history"]["market_zone"].unique())
        missing_zones = site_zones - price_zones
        if missing_zones:
            _err(errors, f"market_zone(s) {missing_zones} in sites.csv have no rows in price_history.csv")

    if "sites" in dfs and "site_status" in dfs:
        known   = set(dfs["sites"]["site_id"].unique())
        in_stat = set(dfs["site_status"]["site_id"].unique())
        unknown = in_stat - known
        if unknown:
            _err(errors, f"site_id(s) {unknown} in site_status.csv not found in sites.csv")

    if "sites" in dfs and "optimization_runs" in dfs:
        known  = set(dfs["sites"]["site_id"].unique())
        in_opt = set(dfs["optimization_runs"]["site_id"].unique())
        unknown = in_opt - known
        if unknown:
            _err(errors, f"site_id(s) {unknown} in optimization_runs.csv not found in sites.csv")

    # ── 4. Price history coverage ─────────────────────────────────────────────
    if "price_history" in dfs and "timestamp" in dfs["price_history"].columns:
        try:
            ts = pd.to_datetime(dfs["price_history"]["timestamp"])
            n_days = int((ts.max() - ts.min()).days) + 1
            if n_days < 14:
                _err(errors, f"price_history.csv: only {n_days} day(s) of data (minimum 14 required)")
            elif n_days < 30:
                _warn(f"price_history.csv: {n_days} days of data (30+ days recommended)")
        except Exception:
            _warn("price_history.csv: could not parse timestamps for coverage check")

    # ── 5. Timestamp format (spot-check first 5 rows) ─────────────────────────
    for stem in ["price_history", "forecasts", "site_status"]:
        if stem not in dfs or "timestamp" not in dfs[stem].columns:
            continue
        sample = dfs[stem]["timestamp"].head(5)
        try:
            pd.to_datetime(sample)
        except Exception:
            _err(errors, f"{stem}.csv: timestamp column is not parseable as datetime")

    # ── 6. Summary ────────────────────────────────────────────────────────────
    n_err  = len(errors)
    n_warn = 0  # tracked via print only
    print(f"\n{n_err} error(s)")
    return n_err


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_datasets.py <data_folder>")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"[ERROR] Not a directory: {folder}")
        sys.exit(1)

    n_errors = validate(folder)
    sys.exit(0 if n_errors == 0 else 1)


if __name__ == "__main__":
    main()
