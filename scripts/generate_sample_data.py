#!/usr/bin/env python3
"""
Synthetic sample-data generator for energy-ops-agent.

Deterministic, seed 42.  Do NOT modify this file unless explicitly instructed.
The solve_lp function in this file is the reference implementation that
energy_agent/tools/optimizer.py must reproduce within 1 %.

Usage:
    python scripts/generate_sample_data.py --out data/sample
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog

# ─────────────────────────────────────────────────────────────────────────────
# Seed
# ─────────────────────────────────────────────────────────────────────────────
SEED = 42

# ─────────────────────────────────────────────────────────────────────────────
# Site definitions  (server-side config — never editable via chat)
# ─────────────────────────────────────────────────────────────────────────────
SITES: list[dict[str, Any]] = [
    dict(
        site_id="S001",
        site_name="Chennai Coastal BESS (sample)",
        location="Tamil Nadu",
        market_zone="SR",
        status="active",
        capacity_mwh=100.0,
        power_mw=25.0,
        round_trip_efficiency=0.88,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        reserve_soc_pct=20.0,
        max_daily_discharge_mwh=200.0,
        degradation_cost_inr_per_mwh=600.0,
        initial_soc_pct=50.0,
    ),
    dict(
        site_id="S002",
        site_name="Bengaluru East BESS (sample)",
        location="Karnataka",
        market_zone="SR",
        status="active",
        capacity_mwh=50.0,
        power_mw=12.5,
        round_trip_efficiency=0.87,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        reserve_soc_pct=20.0,
        max_daily_discharge_mwh=100.0,
        degradation_cost_inr_per_mwh=650.0,
        initial_soc_pct=50.0,
    ),
    dict(
        site_id="S003",
        site_name="Pune West BESS (sample)",
        location="Maharashtra",
        market_zone="WR",
        status="active",
        capacity_mwh=200.0,
        power_mw=50.0,
        round_trip_efficiency=0.86,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        reserve_soc_pct=15.0,
        max_daily_discharge_mwh=400.0,
        degradation_cost_inr_per_mwh=550.0,
        initial_soc_pct=50.0,
    ),
]

# Live SOC snapshot for the optimization run (from site_status)
SITE_STATUS_NOW: dict[str, dict[str, Any]] = {
    "S001": dict(soc_pct=72.0, operating_status="idle",
                 available_power_mw=25.0, cycles_today=0.6,
                 temperature_c=31.5, active_alarms=0),
    "S002": dict(soc_pct=41.0, operating_status="idle",
                 available_power_mw=12.5, cycles_today=0.4,
                 temperature_c=29.2, active_alarms=0),
    "S003": dict(soc_pct=58.0, operating_status="idle",
                 available_power_mw=50.0, cycles_today=0.8,
                 temperature_c=33.1, active_alarms=0),
}

# ─────────────────────────────────────────────────────────────────────────────
# Date ranges
# ─────────────────────────────────────────────────────────────────────────────
PRICE_START = pd.Timestamp("2026-08-20")
PRICE_END   = pd.Timestamp("2026-09-18")   # inclusive last day
FCST_START  = pd.Timestamp("2026-09-12")
FCST_END    = pd.Timestamp("2026-09-19")   # inclusive last forecast day
STATUS_TS   = "2026-09-18 23:00:00"
MODEL_VER   = "seasonal_naive_7d_v0"
OPT_DATE    = pd.Timestamp("2026-09-19")   # "tomorrow" in the demo

# ─────────────────────────────────────────────────────────────────────────────
# Price generation parameters
# ─────────────────────────────────────────────────────────────────────────────
# Hourly multipliers relative to the zone's daily base price.
# Profile captures: morning ramp/peak · midday solar dip · evening peak.
SR_BASE = 5000.0   # INR/MWh daily base price for SR zone
WR_BASE = 4800.0   # INR/MWh daily base price for WR zone

HOUR_MULT_SR = np.array([
    0.74, 0.70, 0.68, 0.67, 0.68, 0.75,   # 00-05  night
    0.90, 1.08, 1.20, 1.25, 1.15, 1.00,   # 06-11  morning ramp / peak
    0.88, 0.85, 0.87, 0.96, 1.06, 1.16,   # 12-17  midday solar dip / afternoon
    1.24, 1.36, 1.40, 1.33, 1.14, 0.88,   # 18-23  evening peak
], dtype=float)

HOUR_MULT_WR = np.array([
    0.76, 0.72, 0.70, 0.69, 0.70, 0.77,   # 00-05
    0.92, 1.06, 1.18, 1.22, 1.12, 0.97,   # 06-11
    0.87, 0.84, 0.86, 0.95, 1.04, 1.14,   # 12-17
    1.21, 1.33, 1.37, 1.30, 1.10, 0.87,   # 18-23
], dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# Data generators
# ─────────────────────────────────────────────────────────────────────────────

def _price_series(
    timestamps: pd.DatetimeIndex,
    hour_mult: np.ndarray,
    base: float,
    rng: np.random.Generator,
) -> list[float]:
    """Generate a hourly price series for one market zone."""
    prices: list[float] = []
    for ts in timestamps:
        h     = ts.hour
        dow   = ts.dayofweek          # 0=Mon, 6=Sun
        wkend = 0.87 if dow >= 5 else 1.0
        trend = 1.0 + 0.0008 * (ts - PRICE_START).days   # gentle upward drift
        noise = float(rng.normal(1.0, 0.05))
        p = base * float(hour_mult[h]) * wkend * trend * noise
        if rng.random() < 0.01:                            # ~1 % rare spike
            p *= float(rng.uniform(1.8, 2.5))
        p = float(np.clip(p, 500.0, 10_000.0))
        prices.append(round(p, 2))
    return prices


def make_prices(rng: np.random.Generator) -> pd.DataFrame:
    """1 440 rows: 30 days × 24 h × 2 zones (SR, WR)."""
    ts = pd.date_range(PRICE_START, PRICE_END + pd.Timedelta(hours=23), freq="h")
    df_sr = pd.DataFrame({
        "timestamp":         ts.strftime("%Y-%m-%d %H:%M:%S"),
        "market_zone":       "SR",
        "price_inr_per_mwh": _price_series(ts, HOUR_MULT_SR, SR_BASE, rng),
    })
    df_wr = pd.DataFrame({
        "timestamp":         ts.strftime("%Y-%m-%d %H:%M:%S"),
        "market_zone":       "WR",
        "price_inr_per_mwh": _price_series(ts, HOUR_MULT_WR, WR_BASE, rng),
    })
    return (
        pd.concat([df_sr, df_wr], ignore_index=True)
        .sort_values(["timestamp", "market_zone"])
        .reset_index(drop=True)
    )


def make_renewable(rng: np.random.Generator) -> pd.DataFrame:
    """1 440 rows: same timestamps as price_history, per-zone solar + wind."""
    ts = pd.date_range(PRICE_START, PRICE_END + pd.Timedelta(hours=23), freq="h")
    rows: list[dict] = []
    caps = {"SR": (300.0, 150.0), "WR": (250.0, 200.0)}  # (solar_cap_mw, wind_cap_mw)
    for zone, (solar_cap, wind_cap) in caps.items():
        for t in ts:
            h = t.hour
            if 6 <= h <= 18:
                solar_frac = math.sin(math.pi * (h - 6) / 12.0)
                solar = round(solar_cap * solar_frac * float(rng.uniform(0.55, 1.0)), 2)
            else:
                solar = 0.0
            wind = round(wind_cap * float(rng.uniform(0.15, 0.85)), 2)
            rows.append({
                "timestamp":   t.strftime("%Y-%m-%d %H:%M:%S"),
                "market_zone": zone,
                "solar_mw":    solar,
                "wind_mw":     wind,
            })
    return (
        pd.DataFrame(rows)
        .sort_values(["timestamp", "market_zone"])
        .reset_index(drop=True)
    )


def make_forecasts(price_df: pd.DataFrame) -> pd.DataFrame:
    """
    384 rows: 8 days (Sep 12–19) × 24 h × 2 zones.
    Model: seasonal_naive_7d_v0 — mean of same hour over the previous 7 days.
    """
    # Build a lookup: (zone, ts) → price
    ph = price_df.copy()
    ph["ts"] = pd.to_datetime(ph["timestamp"])

    rows: list[dict] = []
    for zone in ["SR", "WR"]:
        zone_series = (
            ph[ph["market_zone"] == zone]
            .set_index("ts")["price_inr_per_mwh"]
        )
        day = FCST_START
        while day <= FCST_END:
            fcst_id    = f"F-{zone}-{day.strftime('%Y%m%d')}"
            created_at = (day - pd.Timedelta(days=1)).strftime("%Y-%m-%d 12:00:00")
            for h in range(24):
                # Collect prices for same hour across previous 7 days
                vals: list[float] = []
                for lag in range(1, 8):
                    key = day - pd.Timedelta(days=lag) + pd.Timedelta(hours=h)
                    if key in zone_series.index:
                        vals.append(float(zone_series[key]))
                if not vals:
                    continue
                predicted = round(float(np.mean(vals)), 2)
                ts_str = (day + pd.Timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
                rows.append({
                    "forecast_id":               fcst_id,
                    "market_zone":               zone,
                    "created_at":                created_at,
                    "timestamp":                 ts_str,
                    "predicted_price_inr_per_mwh": predicted,
                    "model_version":             MODEL_VER,
                })
            day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def make_status() -> pd.DataFrame:
    """3 rows: one snapshot per site at 2026-09-18 23:00:00."""
    rows = []
    for site in SITES:
        st = SITE_STATUS_NOW[site["site_id"]]
        rows.append({"site_id": site["site_id"], "timestamp": STATUS_TS, **st})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Reference LP  (§10.1) — reproduced by energy_agent.tools.optimizer within 1 %
# ─────────────────────────────────────────────────────────────────────────────

def solve_lp(site: dict, prices_24h: list[float], soc_0_mwh: float) -> dict:
    """
    Linear program for a single battery site over a 24-hour horizon.

    Maximise:  Σ_t  p_t·(d_t − c_t)  −  deg·Σ_t d_t
    Subject to:
        SOC_t = SOC_0 + η·Σ_{k≤t} c_k − (1/η)·Σ_{k≤t} d_k
        max(soc_min, reserve)·cap  ≤  SOC_t  ≤  soc_max·cap      ∀t
        SOC_24  ≥  SOC_0                                (don't drain over the day)
        Σ_t d_t  ≤  max_daily_discharge_mwh
        0  ≤  c_t, d_t  ≤  power_mw                    ∀t

    Where η = sqrt(round_trip_efficiency).

    Variables (48): [c_0..c_23 , d_0..d_23]
    Solved with scipy.optimize.linprog(method='highs').

    Returns a dict with:
        ok, solver_status, runtime_s, c_vars, d_vars, schedule,
        revenue, charging_cost, throughput, degradation_cost, profit,
        binding_constraints
    """
    n      = len(prices_24h)        # must be 24
    eta    = math.sqrt(site["round_trip_efficiency"])
    cap    = site["capacity_mwh"]
    p_mw   = site["power_mw"]
    soc_fl = max(site["soc_min_pct"], site["reserve_soc_pct"]) / 100.0 * cap
    soc_mx = site["soc_max_pct"] / 100.0 * cap
    deg    = site["degradation_cost_inr_per_mwh"]
    max_d  = site["max_daily_discharge_mwh"]
    prices = np.asarray(prices_24h, dtype=float)

    # ── objective: minimize Σ p_t·c_t + Σ (−p_t + deg)·d_t ──────────────────
    c_obj = np.concatenate([prices, -prices + deg])

    # ── inequality constraints ─────────────────────────────────────────────────
    N2 = 2 * n
    A_rows: list[np.ndarray] = []
    b_rows: list[float]       = []

    for t in range(n):
        # Cumulative-sum row for SOC at hour t
        row = np.zeros(N2)
        row[:t + 1]      =  eta          # charge adds to SOC
        row[n : n + t + 1] = -1.0 / eta   # discharge drains SOC

        # SOC_t ≤ soc_max
        A_rows.append(row.copy())
        b_rows.append(soc_mx - soc_0_mwh)

        # SOC_t ≥ soc_floor  →  −row·x ≤ −(soc_floor − soc_0)  =  soc_0 − soc_floor
        A_rows.append(-row.copy())
        b_rows.append(soc_0_mwh - soc_fl)

    # End-of-day: SOC_24 ≥ SOC_0  →  −η·Σc + (1/η)·Σd  ≤  0
    eod = np.zeros(N2)
    eod[:n]  = -eta
    eod[n:]  =  1.0 / eta
    A_rows.append(eod)
    b_rows.append(0.0)

    # Total discharge ≤ max_daily_discharge_mwh
    td = np.zeros(N2)
    td[n:] = 1.0
    A_rows.append(td)
    b_rows.append(max_d)

    A_ub = np.array(A_rows)
    b_ub = np.array(b_rows)
    bounds = [(0.0, p_mw)] * n + [(0.0, p_mw)] * n

    t0  = time.perf_counter()
    res = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    runtime = round(time.perf_counter() - t0, 6)

    if res.status != 0:
        return {"ok": False, "solver_status": res.message, "runtime_s": runtime}

    c_vars = res.x[:n]
    d_vars = res.x[n:]

    # ── schedule: SOC is the value at END of each hour ────────────────────────
    soc      = soc_0_mwh
    schedule = []
    for t in range(n):
        soc += eta * c_vars[t] - d_vars[t] / eta
        schedule.append({
            "charge_mw":      round(float(c_vars[t]), 6),
            "discharge_mw":   round(float(d_vars[t]), 6),
            "soc_mwh":        round(float(soc), 6),
            "forecast_price": round(float(prices[t]), 2),
        })

    revenue       = float(np.dot(prices, d_vars))
    charging_cost = float(np.dot(prices, c_vars))
    throughput    = float(np.sum(d_vars))
    degradation   = deg * throughput
    profit        = revenue - charging_cost - degradation

    # ── detect binding constraints ────────────────────────────────────────────
    TOL = 1e-4
    slack   = res.slack           # slack for each A_ub row
    binding = []

    # SOC upper rows are at even indices (0, 2, 4, ...)
    if any(abs(slack[2 * t]) < TOL for t in range(n)):
        binding.append("soc_max")

    # SOC lower rows are at odd indices (1, 3, 5, ...)
    if any(abs(slack[2 * t + 1]) < TOL for t in range(n)):
        if site["reserve_soc_pct"] >= site["soc_min_pct"]:
            binding.append("reserve_soc")
        else:
            binding.append("soc_min")

    # End-of-day (index 2n)
    if abs(slack[2 * n]) < TOL:
        binding.append("soc_end")

    # Max discharge (index 2n + 1)
    if abs(slack[2 * n + 1]) < TOL:
        binding.append("max_discharge")

    # Power limits (variable upper bounds)
    if (
        any(abs(c_vars[t] - p_mw) < TOL for t in range(n))
        or any(abs(d_vars[t] - p_mw) < TOL for t in range(n))
    ):
        binding.append("power_limit")

    return {
        "ok":                 True,
        "solver_status":      "optimal",
        "runtime_s":          runtime,
        "c_vars":             c_vars.tolist(),
        "d_vars":             d_vars.tolist(),
        "schedule":           schedule,
        "revenue":            round(revenue, 2),
        "charging_cost":      round(charging_cost, 2),
        "throughput":         round(throughput, 3),
        "degradation_cost":   round(degradation, 2),
        "profit":             round(profit, 2),
        "binding_constraints": binding,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Optimization runs for OPT_DATE
# ─────────────────────────────────────────────────────────────────────────────

def make_opt_runs(fcst_df: pd.DataFrame) -> pd.DataFrame:
    """Run the reference LP for each site on the 2026-09-19 forecast."""
    rows: list[dict] = []
    for site in SITES:
        zone     = site["market_zone"]
        fcst_id  = f"F-{zone}-{OPT_DATE.strftime('%Y%m%d')}"

        day_fcst = (
            fcst_df[fcst_df["forecast_id"] == fcst_id]
            .sort_values("timestamp")["predicted_price_inr_per_mwh"]
            .tolist()
        )
        if len(day_fcst) < 24:
            print(f"  WARNING: fewer than 24 forecast rows for {fcst_id}")
            continue

        soc_pct   = SITE_STATUS_NOW[site["site_id"]]["soc_pct"]
        soc_0_mwh = soc_pct / 100.0 * site["capacity_mwh"]

        res = solve_lp(site, day_fcst, soc_0_mwh)
        if not res["ok"]:
            print(f"  WARNING: LP failed for {site['site_id']}: {res['solver_status']}")
            continue

        # Attach timestamps to schedule rows
        schedule_ts = []
        for i, row in enumerate(res["schedule"]):
            ts = (OPT_DATE + pd.Timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S")
            schedule_ts.append({"timestamp": ts, **row})

        run_id     = f"OPT-{site['site_id']}-{OPT_DATE.strftime('%Y%m%d')}-001"
        created_at = "2026-09-18 23:30:00"

        rows.append({
            "optimization_run_id":  run_id,
            "site_id":              site["site_id"],
            "created_at":           created_at,
            "forecast_id":          fcst_id,
            "solver_status":        res["solver_status"],
            "runtime_s":            res["runtime_s"],
            "initial_soc_mwh":      round(soc_0_mwh, 3),
            "expected_revenue_inr": res["revenue"],
            "charging_cost_inr":    res["charging_cost"],
            "degradation_cost_inr": res["degradation_cost"],
            "expected_profit_inr":  res["profit"],
            "throughput_mwh":       res["throughput"],
            "binding_constraints":  json.dumps(res["binding_constraints"]),
            "schedule_json":        json.dumps(schedule_ts),
        })
        print(
            f"  {site['site_id']}: profit={res['profit']:>12,.2f}  "
            f"deg={res['degradation_cost']:>10,.2f}  "
            f"throughput={res['throughput']:.3f} MWh"
        )
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Backtest (Sep 12 → Sep 18, 7 days)
# ─────────────────────────────────────────────────────────────────────────────

def make_backtest(price_df: pd.DataFrame, fcst_df: pd.DataFrame) -> pd.DataFrame:
    """
    Closed-loop backtest for 7 days (Sep 12–18) per site.

    For each day:
      - Solve LP on that day's forecast (SOC_0 = initial_soc_pct × cap)
      - Value the plan at actual prices → actual_profit
      - Solve LP on actual prices → perfect_foresight_profit
      - Compute regret, forecast MAE
    Aggregate over 7 days → one row per site.
    """
    ph = price_df.copy()
    ph["ts"] = pd.to_datetime(ph["timestamp"])

    rows: list[dict] = []
    for site in SITES:
        zone   = site["market_zone"]
        soc_0  = site["initial_soc_pct"] / 100.0 * site["capacity_mwh"]
        deg    = site["degradation_cost_inr_per_mwh"]

        total_actual    = 0.0
        total_perfect   = 0.0
        total_throughput = 0.0
        total_degradation = 0.0
        total_mae       = 0.0
        total_runtime   = 0.0
        n_days          = 0

        day = FCST_START
        while day < FCST_END:   # Sep 12, 13, ..., 18
            fcst_id   = f"F-{zone}-{day.strftime('%Y%m%d')}"
            fcst_rows = (
                fcst_df[fcst_df["forecast_id"] == fcst_id]
                .sort_values("timestamp")
            )
            if len(fcst_rows) < 24:
                day += pd.Timedelta(days=1)
                continue

            fcst_prices = fcst_rows["predicted_price_inr_per_mwh"].tolist()

            # Pull actual prices for this day
            zone_ph = ph[ph["market_zone"] == zone].set_index("ts")["price_inr_per_mwh"]
            actual_prices: list[float] = []
            for h in range(24):
                key = day + pd.Timedelta(hours=h)
                actual_prices.append(
                    float(zone_ph[key]) if key in zone_ph.index
                    else float(np.mean(fcst_prices))
                )

            # Plan with forecast, value at actual prices
            res_f = solve_lp(site, fcst_prices, soc_0)
            if not res_f["ok"]:
                day += pd.Timedelta(days=1)
                continue

            c_arr  = np.array(res_f["c_vars"])
            d_arr  = np.array(res_f["d_vars"])
            act_p  = np.array(actual_prices)

            actual_revenue    = float(np.dot(act_p, d_arr))
            actual_charge     = float(np.dot(act_p, c_arr))
            tp_day            = float(np.sum(d_arr))
            deg_day           = deg * tp_day
            actual_profit_day = actual_revenue - actual_charge - deg_day

            # Perfect foresight (LP on actual prices)
            res_pf         = solve_lp(site, actual_prices, soc_0)
            pf_profit_day  = res_pf["profit"] if res_pf["ok"] else actual_profit_day

            mae_day = float(np.mean(np.abs(np.array(fcst_prices) - act_p)))

            total_actual      += actual_profit_day
            total_perfect     += pf_profit_day
            total_throughput  += tp_day
            total_degradation += deg_day
            total_mae         += mae_day
            total_runtime     += res_f["runtime_s"]
            n_days            += 1

            day += pd.Timedelta(days=1)

        if n_days == 0:
            continue

        regret      = total_perfect - total_actual
        regret_pct  = (regret / total_perfect * 100.0) if total_perfect > 0 else 0.0
        mae_avg     = total_mae / n_days
        rt_avg      = total_runtime / n_days

        start_str = FCST_START.strftime("%Y-%m-%d")
        end_str   = (FCST_END - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        bt_id     = (
            f"BT-{site['site_id']}-"
            f"{FCST_START.strftime('%Y%m%d')}-"
            f"{(FCST_END - pd.Timedelta(days=1)).strftime('%Y%m%d')}"
        )

        rows.append({
            "backtest_run_id":              bt_id,
            "site_id":                      site["site_id"],
            "period_start":                 start_str,
            "period_end":                   end_str,
            "actual_profit_inr":            round(total_actual, 2),
            "perfect_foresight_profit_inr": round(total_perfect, 2),
            "regret_inr":                   round(regret, 2),
            "regret_percent":               round(regret_pct, 2),
            "throughput_mwh":               round(total_throughput, 3),
            "degradation_cost_inr":         round(total_degradation, 2),
            "forecast_mae_inr_per_mwh":     round(mae_avg, 2),
            "optimization_runtime_s":       round(rt_avg, 6),
        })
        print(
            f"  {site['site_id']} backtest: actual={total_actual:>12,.2f}  "
            f"perfect={total_perfect:>12,.2f}  "
            f"regret={regret:>10,.2f} ({regret_pct:.1f}%)"
        )
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic sample data (seed 42)."
    )
    parser.add_argument(
        "--out", default="data/sample",
        help="Output directory (default: data/sample)"
    )
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating sample data → {out.resolve()}\n")
    rng = np.random.default_rng(SEED)

    print("  [1/7] price_history …")
    price_df  = make_prices(rng)

    print("  [2/7] renewable_generation …")
    renew_df  = make_renewable(rng)

    print("  [3/7] forecasts (seasonal_naive_7d_v0) …")
    fcst_df   = make_forecasts(price_df)

    print("  [4/7] site_status …")
    status_df = make_status()

    print("  [5/7] optimization_runs (reference LP) …")
    opt_df    = make_opt_runs(fcst_df)

    print("  [6/7] backtest_results (7-day closed-loop) …")
    bt_df     = make_backtest(price_df, fcst_df)

    sites_df  = pd.DataFrame(SITES)
    print("  [7/7] sites …")

    # Write CSVs
    sites_df.to_csv(out / "sites.csv",                index=False)
    price_df.to_csv(out / "price_history.csv",        index=False)
    renew_df.to_csv(out / "renewable_generation.csv", index=False)
    fcst_df.to_csv( out / "forecasts.csv",            index=False)
    status_df.to_csv(out / "site_status.csv",         index=False)
    opt_df.to_csv(  out / "optimization_runs.csv",    index=False)
    bt_df.to_csv(   out / "backtest_results.csv",     index=False)

    # Summary
    print("\n── Row counts ─────────────────────────────────────────────────")
    for label, df in [
        ("sites",                 sites_df),
        ("price_history",         price_df),
        ("renewable_generation",  renew_df),
        ("forecasts",             fcst_df),
        ("site_status",           status_df),
        ("optimization_runs",     opt_df),
        ("backtest_results",      bt_df),
    ]:
        print(f"  {label:<30} {len(df):>6} rows")
    print("─" * 55)
    print("Done.\n")


if __name__ == "__main__":
    main()
