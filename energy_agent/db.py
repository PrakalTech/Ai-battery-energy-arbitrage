"""
Database layer for energy-ops-agent.

Responsibilities:
  - Connection management (reads DB_PATH from .env / environment)
  - All DDL (8 tables from README §8.2)
  - insert_agent_run() — called on EVERY run including failures (invariant 6)

Nothing outside this module touches raw SQL DDL.
Tools use parameterised queries via sqlite3 connections from get_connection().
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_DEFAULT_DB = "energy_agent.db"


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Return a SQLite connection.

    Priority: argument > DB_PATH env var > 'energy_agent.db' in cwd.
    WAL mode and FK enforcement are always enabled.
    row_factory = sqlite3.Row so callers can access columns by name.
    """
    path = db_path or os.getenv("DB_PATH", _DEFAULT_DB)
    # Create parent directories if needed (e.g. data/db.sqlite)
    resolved = pathlib.Path(path)
    if resolved.parent != pathlib.Path("."):
        resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# DDL — §8.2 (exact schema, no deviations)
# ─────────────────────────────────────────────────────────────────────────────

_DDL = """\
CREATE TABLE IF NOT EXISTS sites (
    site_id                     TEXT PRIMARY KEY,
    site_name                   TEXT,
    location                    TEXT,
    market_zone                 TEXT,
    status                      TEXT,
    capacity_mwh                REAL,
    power_mw                    REAL,
    round_trip_efficiency       REAL,
    soc_min_pct                 REAL,
    soc_max_pct                 REAL,
    reserve_soc_pct             REAL,
    max_daily_discharge_mwh     REAL,
    degradation_cost_inr_per_mwh REAL,
    initial_soc_pct             REAL
);

CREATE TABLE IF NOT EXISTS price_history (
    timestamp       TIMESTAMP,
    market_zone     TEXT,
    price_inr_per_mwh REAL,
    PRIMARY KEY (timestamp, market_zone)
);

CREATE TABLE IF NOT EXISTS renewable_generation (
    timestamp       TIMESTAMP,
    market_zone     TEXT,
    solar_mw        REAL,
    wind_mw         REAL,
    PRIMARY KEY (timestamp, market_zone)
);

CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id                 TEXT,
    market_zone                 TEXT,
    created_at                  TIMESTAMP,
    timestamp                   TIMESTAMP,
    predicted_price_inr_per_mwh REAL,
    model_version               TEXT,
    PRIMARY KEY (forecast_id, timestamp)
);

CREATE TABLE IF NOT EXISTS site_status (
    site_id             TEXT,
    timestamp           TIMESTAMP,
    soc_pct             REAL,
    operating_status    TEXT,
    available_power_mw  REAL,
    cycles_today        REAL,
    temperature_c       REAL,
    active_alarms       INTEGER,
    PRIMARY KEY (site_id, timestamp)
);

CREATE TABLE IF NOT EXISTS optimization_runs (
    optimization_run_id     TEXT PRIMARY KEY,
    site_id                 TEXT,
    created_at              TIMESTAMP,
    forecast_id             TEXT,
    solver_status           TEXT,
    runtime_s               REAL,
    initial_soc_mwh         REAL,
    expected_revenue_inr    REAL,
    charging_cost_inr       REAL,
    degradation_cost_inr    REAL,
    expected_profit_inr     REAL,
    throughput_mwh          REAL,
    binding_constraints     TEXT,   -- JSON array
    schedule_json           TEXT    -- JSON array of 24 hourly rows
);

CREATE TABLE IF NOT EXISTS backtest_results (
    backtest_run_id             TEXT PRIMARY KEY,
    site_id                     TEXT,
    period_start                DATE,
    period_end                  DATE,
    actual_profit_inr           REAL,
    perfect_foresight_profit_inr REAL,
    regret_inr                  REAL,
    regret_percent              REAL,
    throughput_mwh              REAL,
    degradation_cost_inr        REAL,
    forecast_mae_inr_per_mwh    REAL,
    optimization_runtime_s      REAL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id              TEXT PRIMARY KEY,
    timestamp           TIMESTAMP NOT NULL,
    site_id             TEXT,           -- comma-joined; NULL for fleet-wide queries
    user_query          TEXT NOT NULL,
    intent              TEXT,
    tools_used          TEXT,           -- JSON array of tool names
    scenario            TEXT,
    result_summary      TEXT,
    optimization_run_id TEXT,
    backtest_run_id     TEXT,
    status              TEXT            -- ok | error
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """
    Create all 8 tables if they don't already exist.
    Safe to call multiple times (IF NOT EXISTS guards).
    """
    conn.executescript(_DDL)
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# agent_runs insert — called on EVERY run (invariant 6)
# ─────────────────────────────────────────────────────────────────────────────

def insert_agent_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    timestamp: str,
    site_id: Optional[str],
    user_query: str,
    intent: Optional[str],
    tools_used: list,
    scenario: Optional[str] = None,
    result_summary: Optional[str] = None,
    optimization_run_id: Optional[str] = None,
    backtest_run_id: Optional[str] = None,
    status: str,
) -> None:
    """
    Insert a row into agent_runs.

    Must be called on every execution path, including errors and refusals.
    `tools_used` is serialised as a JSON array.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO agent_runs (
            run_id, timestamp, site_id, user_query, intent, tools_used,
            scenario, result_summary, optimization_run_id, backtest_run_id, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            timestamp,
            site_id,
            user_query,
            intent,
            json.dumps(tools_used),
            scenario,
            result_summary,
            optimization_run_id,
            backtest_run_id,
            status,
        ),
    )
    conn.commit()
