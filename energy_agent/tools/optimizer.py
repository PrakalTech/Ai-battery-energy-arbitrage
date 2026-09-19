"""
LP Optimizer tool for battery dispatch.
"""

from __future__ import annotations
import datetime
import json
import math
import time
from typing import Any, Optional

import numpy as np
from scipy.optimize import linprog

from energy_agent.db import get_connection
from energy_agent.tools.sites import get_site
from energy_agent.tools.status import get_site_status
from energy_agent.tools.forecast import get_forecast


def optimize_battery(
    site_id: str,
    forecast: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Produce optimal 24h charge/discharge schedule using linear programming (Highs).
    Constraints are loaded server-side from site configuration (Invariant 3).
    """
    site = get_site(site_id, db_path=db_path)
    if not site:
        return {"status": "error", "error": f"Site {site_id} was not found."}

    # Fetch forecast if not provided
    if forecast is None or "forecast" not in forecast:
        fcst_res = get_forecast(site_id, horizon=24, db_path=db_path)
        if fcst_res.get("status") != "ok":
            return {
                "status": "unavailable",
                "site_id": site_id,
                "error": fcst_res.get("error", "Forecast unavailable. Please run/update the forecasting service."),
            }
        forecast = fcst_res

    forecast_rows = forecast.get("forecast", [])
    if len(forecast_rows) < 24:
        return {
            "status": "unavailable",
            "site_id": site_id,
            "error": "Forecast unavailable. Please run/update the forecasting service.",
        }

    prices_24h = [float(r["predicted_price_inr_per_mwh"]) for r in forecast_rows[:24]]
    timestamps = [str(r.get("timestamp", "")) for r in forecast_rows[:24]]

    # Get initial SOC from site status
    status_res = get_site_status(site_id, db_path=db_path)
    if status_res.get("status") == "ok":
        soc_pct = float(status_res["soc_pct"])
    else:
        soc_pct = float(site.get("initial_soc_pct", 50.0))

    cap = float(site["capacity_mwh"])
    soc_0_mwh = (soc_pct / 100.0) * cap

    n = len(prices_24h)  # 24
    eta = math.sqrt(float(site["round_trip_efficiency"]))
    p_mw = float(site["power_mw"])
    soc_fl = max(float(site["soc_min_pct"]), float(site["reserve_soc_pct"])) / 100.0 * cap
    soc_mx = float(site["soc_max_pct"]) / 100.0 * cap
    deg = float(site["degradation_cost_inr_per_mwh"])
    max_d = float(site["max_daily_discharge_mwh"])
    prices = np.asarray(prices_24h, dtype=float)

    # Objective: minimize Σ p_t·c_t + Σ (−p_t + deg)·d_t
    c_obj = np.concatenate([prices, -prices + deg])

    N2 = 2 * n
    A_rows: list[np.ndarray] = []
    b_rows: list[float] = []

    for t in range(n):
        row = np.zeros(N2)
        row[:t + 1] = eta
        row[n : n + t + 1] = -1.0 / eta

        # SOC_t ≤ soc_max
        A_rows.append(row.copy())
        b_rows.append(soc_mx - soc_0_mwh)

        # SOC_t ≥ soc_floor
        A_rows.append(-row.copy())
        b_rows.append(soc_0_mwh - soc_fl)

    # End-of-day: SOC_24 ≥ SOC_0
    eod = np.zeros(N2)
    eod[:n] = -eta
    eod[n:] = 1.0 / eta
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

    t0 = time.perf_counter()
    res = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    runtime = round(time.perf_counter() - t0, 6)

    if res.status != 0:
        return {
            "status": "error",
            "site_id": site_id,
            "solver_status": res.message,
            "error": f"Optimization could not produce a feasible schedule. Solver status: {res.message}",
        }

    c_vars = res.x[:n]
    d_vars = res.x[n:]

    soc = soc_0_mwh
    schedule = []
    for t in range(n):
        soc += eta * c_vars[t] - d_vars[t] / eta
        ts = timestamps[t] if timestamps[t] else f"Hour {t:02d}:00:00"
        schedule.append({
            "timestamp": ts,
            "charge_mw": round(float(c_vars[t]), 6),
            "discharge_mw": round(float(d_vars[t]), 6),
            "soc_mwh": round(float(soc), 6),
            "forecast_price": round(float(prices[t]), 2),
        })

    revenue = float(np.dot(prices, d_vars))
    charging_cost = float(np.dot(prices, c_vars))
    throughput = float(np.sum(d_vars))
    degradation = deg * throughput
    profit = revenue - charging_cost - degradation

    # Binding constraints detection
    TOL = 1e-4
    slack = res.slack
    binding = []
    if any(abs(slack[2 * t]) < TOL for t in range(n)):
        binding.append("soc_max")
    if any(abs(slack[2 * t + 1]) < TOL for t in range(n)):
        if float(site["reserve_soc_pct"]) >= float(site["soc_min_pct"]):
            binding.append("reserve_soc")
        else:
            binding.append("soc_min")
    if abs(slack[2 * n]) < TOL:
        binding.append("soc_end")
    if abs(slack[2 * n + 1]) < TOL:
        binding.append("max_discharge")
    if (
        any(abs(c_vars[t] - p_mw) < TOL for t in range(n))
        or any(abs(d_vars[t] - p_mw) < TOL for t in range(n))
    ):
        binding.append("power_limit")

    forecast_id = forecast.get("forecast_id", f"F-{site['market_zone']}-forecast")
    opt_date_str = timestamps[0][:10].replace("-", "") if timestamps[0] else datetime.date.today().strftime("%Y%m%d")
    run_id = f"OPT-{site_id}-{opt_date_str}-001"

    result = {
        "status": "ok",
        "site_id": site_id,
        "optimization_run_id": run_id,
        "forecast_id": forecast_id,
        "solver_status": "optimal",
        "runtime_s": runtime,
        "initial_soc_mwh": round(soc_0_mwh, 3),
        "schedule": schedule,
        "expected_revenue_inr": round(revenue, 2),
        "charging_cost_inr": round(charging_cost, 2),
        "degradation_cost_inr": round(degradation, 2),
        "expected_profit_inr": round(profit, 2),
        "throughput_mwh": round(throughput, 3),
        "binding_constraints": binding,
    }

    # Record run in database
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO optimization_runs (
                optimization_run_id, site_id, created_at, forecast_id, solver_status,
                runtime_s, initial_soc_mwh, expected_revenue_inr, charging_cost_inr,
                degradation_cost_inr, expected_profit_inr, throughput_mwh,
                binding_constraints, schedule_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                site_id,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                forecast_id,
                "optimal",
                runtime,
                round(soc_0_mwh, 3),
                round(revenue, 2),
                round(charging_cost, 2),
                round(degradation, 2),
                round(profit, 2),
                round(throughput, 3),
                json.dumps(binding),
                json.dumps(schedule),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

    return result
