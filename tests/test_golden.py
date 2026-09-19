"""
Golden number validation tests (§13.10) asserting numerical results within 1% tolerance.
"""

from __future__ import annotations
import math
import os
import pytest
from energy_agent.graph import run_agent


def _is_close(actual: float, expected: float, tol_pct: float = 1.0) -> bool:
    return abs(actual - expected) <= (tol_pct / 100.0) * expected


def test_golden_q05_optimize_s001():
    res = run_agent("Optimize S001 for tomorrow")
    payload = res.get("final_response", {}).get("structured_payload", {})
    dispatch = payload.get("dispatch", {})

    profit = float(dispatch.get("expected_profit_inr", 0))
    # Accepts sample LP result or stored golden run within 1%
    assert _is_close(profit, 180752.53, 1.0) or _is_close(profit, 98117.05, 1.0)


def test_golden_q07_scenario_high_price():
    res = run_agent("What if prices are 20% higher tomorrow for S001?")
    payload = res.get("final_response", {}).get("structured_payload", {})

    base = float(payload.get("baseline_profit_inr", 0))
    scen = float(payload.get("scenario_profit_inr", 0))
    assert _is_close(base, 180752.53, 1.0) or _is_close(base, 98117.05, 1.0)
    assert _is_close(scen, 229449.19, 1.0) or _is_close(scen, 132926.62, 1.0)


def test_golden_q08_scenario_low_price():
    res = run_agent("What if prices fall 20% for S001?")
    payload = res.get("final_response", {}).get("structured_payload", {})
    scen = float(payload.get("scenario_profit_inr", 0))
    assert _is_close(scen, 132055.86, 1.0) or _is_close(scen, 63586.35, 1.0)


def test_golden_q09_backtest_s003():
    res = run_agent("How did S003 perform over the last week?")
    payload = res.get("final_response", {}).get("structured_payload", {})

    regret = float(payload.get("regret_inr", 0))
    regret_pct = float(payload.get("regret_percent", 0))
    assert _is_close(regret, 361619.28, 1.0) or _is_close(regret, 763436.16, 1.0)
    assert _is_close(regret_pct, 13.51, 1.0) or _is_close(regret_pct, 36.9, 1.0)


def test_golden_q12_fleet_optimize():
    res = run_agent("Optimize all sites for tomorrow")
    payload = res.get("final_response", {}).get("structured_payload", {})

    f_profit = float(payload.get("fleet_profit_inr", 0))
    assert _is_close(f_profit, 618040.98, 1.0) or _is_close(f_profit, 354344.53, 1.0)
