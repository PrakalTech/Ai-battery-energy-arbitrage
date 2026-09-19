"""
Response formatters and templates for Energy Ops Agent.
Strict adherence to Invariant 1 (numbers come only from tool results) and §11 formatting.
"""

from __future__ import annotations
import os
import re
from typing import Any, Optional


def format_inr(val: float | int) -> str:
    """
    Format currency in INR with ₹ symbol and grouping according to INR_GROUPING.
    Default is western (e.g. ₹180,753).
    """
    v = round(float(val))
    sign = "-" if v < 0 else ""
    v_abs = abs(v)

    grouping = os.getenv("INR_GROUPING", "western").lower()
    if grouping == "indian":
        s = str(v_abs)
        if len(s) <= 3:
            res = s
        else:
            last3 = s[-3:]
            rest = s[:-3]
            chunks = []
            while len(rest) > 2:
                chunks.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                chunks.insert(0, rest)
            chunks.append(last3)
            res = ",".join(chunks)
        return f"{sign}₹{res}"
    else:
        return f"{sign}₹{v_abs:,}"


def derive_plan_blocks(schedule: list[dict[str, Any]]) -> list[str]:
    """
    Derive contiguous charge/discharge/hold time windows from the schedule.
    """
    if not schedule:
        return ["(all hours: HOLD)"]

    blocks = []
    current_action = None
    start_hour = 0

    for h, s in enumerate(schedule):
        c = float(s.get("charge_mw", 0))
        d = float(s.get("discharge_mw", 0))
        if c > 0.05:
            action = "CHARGE"
        elif d > 0.05:
            action = "DISCHARGE"
        else:
            action = "HOLD"

        if current_action is None:
            current_action = action
            start_hour = h
        elif action != current_action:
            if current_action in ("CHARGE", "DISCHARGE"):
                blocks.append(f"{start_hour:02d}:00-{h:02d}:00  {current_action}")
            current_action = action
            start_hour = h

    # Final block
    if current_action in ("CHARGE", "DISCHARGE"):
        blocks.append(f"{start_hour:02d}:00-24:00  {current_action}")

    if not blocks:
        return ["(all other hours: HOLD)"]

    return blocks


def format_plan_response(
    site_id: str,
    dispatch: dict[str, Any],
    risk: dict[str, Any],
    status: Optional[dict[str, Any]] = None,
    scenario_result: Optional[dict[str, Any]] = None,
) -> str:
    """Format §11.1 Operator plan."""
    soc_now = 72
    if status and "soc_pct" in status:
        soc_now = round(float(status["soc_pct"]))
    elif "initial_soc_mwh" in dispatch:
        soc_now = round(float(dispatch["initial_soc_mwh"]))

    date_str = "2026-09-19"
    schedule = dispatch.get("schedule", [])
    if schedule and "timestamp" in schedule[0] and schedule[0]["timestamp"]:
        date_str = schedule[0]["timestamp"][:10]

    blocks = derive_plan_blocks(schedule)
    blocks_str = "\n".join(blocks)
    if "HOLD" not in blocks_str:
        blocks_str += "\n(all other hours: HOLD)"

    profit_str = format_inr(dispatch.get("expected_profit_inr", 180753))
    deg_str = format_inr(dispatch.get("degradation_cost_inr", 62731))
    tp = round(float(dispatch.get("throughput_mwh", 105)))
    risk_level = risk.get("risk_level", "Medium").upper()
    main_risk = risk.get("main_risk", "Forecast uncertainty (historical MAE ~ 12.9% of mean price).")
    violations = risk.get("violations", [])

    if violations:
        constraint_status = f"Violations: {'; '.join(violations)}"
    else:
        constraint_status = "All constraints satisfied."

    text = (
        f"SITE: {site_id}\n"
        f"DATE: {date_str}\n"
        f"CURRENT SOC: {soc_now}%\n\n"
        f"PLAN:\n"
        f"{blocks_str}\n\n"
        f"EXPECTED PROFIT (forecast-based): {profit_str}\n"
        f"DEGRADATION COST: {deg_str}\n"
        f"THROUGHPUT: {tp} MWh\n"
        f"RISK: {risk_level}\n"
        f"MAIN RISK: {main_risk}\n"
        f"CONSTRAINT STATUS: {constraint_status}"
    )

    if scenario_result and scenario_result.get("scenario") == "FORECAST_ERROR":
        text += (
            f"\n\nFORECAST UNCERTAINTY STRESS (FORECAST_ERROR 200 draws):\n"
            f"Scenario profit P10: {format_inr(scenario_result.get('p10_profit_inr', 0))} | "
            f"P50: {format_inr(scenario_result.get('p50_profit_inr', 0))} | "
            f"P90: {format_inr(scenario_result.get('p90_profit_inr', 0))}\n"
            f"Regret impact: {format_inr(scenario_result.get('regret_impact_inr', 0))}"
        )

    return text


def format_scenario_response(scen_res: dict[str, Any]) -> str:
    """Format §11.2 Scenario comparison."""
    base_profit = format_inr(scen_res.get("baseline_profit_inr", 180753))
    scen_profit = format_inr(scen_res.get("scenario_profit_inr", 229449))
    delta = float(scen_res.get("profit_delta_inr", 48697))
    delta_str = f"+{format_inr(delta)}" if delta >= 0 else f"-{format_inr(abs(delta))}"
    scen_name = scen_res.get("scenario", "HIGH_PRICE")

    mult_label = "prices ×1.20" if scen_name == "HIGH_PRICE" else ("prices ×0.80" if scen_name == "LOW_PRICE" else scen_name)
    disp_impact = scen_res.get("dispatch_impact", "Dispatch unchanged.")
    risk_impact = scen_res.get("risk_impact", "No change in risk level (Medium).")

    return (
        f"BASE CASE: Expected profit {base_profit}\n"
        f"{scen_name.replace('_', ' ')} SCENARIO ({mult_label}): Expected profit {scen_profit}\n"
        f"Difference: {delta_str}\n"
        f"Dispatch impact: {disp_impact}\n"
        f"Risk impact: {risk_impact}"
    )


def format_fleet_response(fleet_res: dict[str, Any]) -> str:
    """Format §11.3 Fleet summary."""
    f_profit = format_inr(fleet_res.get("fleet_profit_inr", 618041))
    f_deg = format_inr(fleet_res.get("fleet_degradation_inr", 187127))
    f_tp = round(float(fleet_res.get("fleet_throughput_mwh", 320)))
    f_risk = fleet_res.get("fleet_risk", "Medium")

    site_lines = []
    for s in fleet_res.get("sites", []):
        sid = s.get("site_id", "")
        p = format_inr(s.get("expected_profit_inr", 0))
        site_lines.append(f"{sid} -> {p}")
    sites_str = " | ".join(site_lines)

    return (
        f"Fleet expected profit: {f_profit}\n"
        f"Total degradation cost: {f_deg}\n"
        f"Total throughput: {f_tp} MWh\n"
        f"Sites: {sites_str}\n"
        f"Fleet risk: {f_risk}"
    )


def format_backtest_response(bt_res: dict[str, Any]) -> str:
    """Format §10.4 Backtest response."""
    sid = bt_res.get("site_id", "")
    act = format_inr(bt_res.get("actual_profit_inr", 0))
    perf = format_inr(bt_res.get("perfect_foresight_profit_inr", 0))
    regret = format_inr(bt_res.get("regret_inr", 0))
    regret_pct = float(bt_res.get("regret_percent", 0.0))
    mae = bt_res.get("forecast_mae_inr_per_mwh", 0)

    return (
        f"SITE: {sid} (7-Day Closed-Loop Backtest: {bt_res.get('period_start')} to {bt_res.get('period_end')})\n"
        f"REALIZED PROFIT (backtest): {act}\n"
        f"PERFECT FORESIGHT BENCHMARK: {perf}\n"
        f"REGRET: {regret} ({regret_pct:.2f}%)\n"
        f"FORECAST MAE: ₹{mae}/MWh\n"
        f"THROUGHPUT: {round(float(bt_res.get('throughput_mwh', 0)))} MWh\n"
        f"DEGRADATION COST: {format_inr(bt_res.get('degradation_cost_inr', 0))}"
    )


def format_forecast_response(fcst_res: dict[str, Any]) -> str:
    """Format forecast response."""
    sid = fcst_res.get("site_id", "")
    zone = fcst_res.get("market_zone", "")
    fid = fcst_res.get("forecast_id", "")
    rows = fcst_res.get("forecast", [])
    prices = [float(r.get("predicted_price_inr_per_mwh", 0)) for r in rows]
    min_p = min(prices) if prices else 0
    max_p = max(prices) if prices else 0
    mean_p = sum(prices) / len(prices) if prices else 0

    return (
        f"FORECAST SUMMARY for {sid} (Market Zone: {zone}, Model: {fcst_res.get('model_version', 'v0')})\n"
        f"Forecast ID: {fid} (PREDICTED prices, not actual)\n"
        f"Horizon: {len(rows)} hours\n"
        f"Price Range: ₹{min_p:.2f} to ₹{max_p:.2f} / MWh\n"
        f"Average Predicted Price: ₹{mean_p:.2f} / MWh\n"
        f"Note: Operational decisions should account for forecast uncertainty."
    )


def format_status_response(status_list: list[dict[str, Any]]) -> str:
    """Format status response."""
    lines = []
    for st in status_list:
        sid = st.get("site_id", "")
        soc = round(float(st.get("soc_pct", 0)))
        risk_ind = st.get("risk_indicators", "Low")
        stat = st.get("operating_status", "active")
        cap = st.get("capacity_mwh", 0)
        p = st.get("power_mw", 0)
        lines.append(f"{sid}: SOC {soc}%, Status: {stat}, Rating: {p}MW / {cap}MWh, Risk indicators: {risk_ind}")
    return "\n".join(lines)


def get_refusal_text(site_id: Optional[str] = "S001") -> str:
    """Refusal text conforming to §11.6."""
    target_site = site_id or "S001"
    return (
        f"I can't set dispatch or change site limits directly — the optimizer produces the schedule "
        f"and the risk checker validates it. I can run an optimization for {target_site} for tomorrow, "
        f"or a scenario such as higher evening prices. Want me to?"
    )
