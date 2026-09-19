"""
Unit tests for data layer and domain engine tools.
"""

from __future__ import annotations
import pytest
from energy_agent.tools import (
    get_sites,
    get_site,
    get_site_status,
    get_price_history,
    get_forecast,
    optimize_battery,
    check_risk,
    run_scenario,
    run_backtest,
    compare_sites,
    optimize_fleet,
    get_optimization_run,
)


def test_get_sites():
    sites = get_sites()
    assert len(sites) >= 3
    site_ids = {s["site_id"] for s in sites}
    assert {"S001", "S002", "S003"}.issubset(site_ids)


def test_get_site_status():
    st = get_site_status("S001")
    assert st["status"] == "ok"
    assert st["site_id"] == "S001"
    assert st["soc_pct"] == 72.0


def test_get_price_history():
    ph = get_price_history("S001")
    assert ph["status"] == "ok"
    assert ph["market_zone"] == "SR"
    assert len(ph["prices"]) > 0


def test_get_forecast():
    fcst = get_forecast("S001", horizon=24)
    assert fcst["status"] == "ok"
    assert len(fcst["forecast"]) == 24


def test_get_forecast_unavailable():
    # Site in non-existent zone or horizon beyond data
    res = get_forecast("NON_EXISTENT_SITE")
    assert res["status"] in ("error", "unavailable")


def test_optimize_battery():
    res = optimize_battery("S001")
    assert res["status"] == "ok"
    assert res["solver_status"] == "optimal"
    assert len(res["schedule"]) == 24
    assert res["expected_profit_inr"] > 0


def test_check_risk():
    risk = check_risk("S001")
    assert risk["status"] == "ok"
    assert risk["risk_level"] in ("Low", "Medium", "High")
    assert len(risk["checks"]) > 0


def test_run_scenario():
    scen = run_scenario("S001", "HIGH_PRICE")
    assert scen["status"] == "ok"
    assert "baseline_profit_inr" in scen
    assert "scenario_profit_inr" in scen
    assert scen["profit_delta_inr"] != 0


def test_run_backtest():
    bt = run_backtest("S001")
    assert bt["status"] == "ok"
    assert bt["actual_profit_inr"] > 0
    assert bt["regret_percent"] >= 0


def test_compare_sites():
    comp = compare_sites(["S001", "S002"])
    assert comp["status"] == "ok"
    assert len(comp["comparison"]) == 2


def test_optimize_fleet():
    fleet = optimize_fleet(["S001", "S002"])
    assert fleet["status"] == "ok"
    assert fleet["fleet_profit_inr"] > 0
    assert fleet["fleet_throughput_mwh"] > 0


def test_get_optimization_run():
    run = get_optimization_run("S001")
    assert run["status"] == "ok"
    assert run["site_id"] == "S001"
