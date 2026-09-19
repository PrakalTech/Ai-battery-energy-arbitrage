"""
Risk checking and validation tool.
"""

from __future__ import annotations
import os
import pathlib
from typing import Any, Optional
import yaml

from energy_agent.db import get_connection
from energy_agent.tools.sites import get_site
from energy_agent.tools.status import get_site_status


def _load_risk_rules() -> dict[str, Any]:
    rules_path = os.getenv("RISK_RULES_PATH", "config/risk_rules.yaml")
    p = pathlib.Path(rules_path)
    if not p.exists():
        p = pathlib.Path(__file__).resolve().parent.parent.parent / "config" / "risk_rules.yaml"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def check_risk(
    site_id: str,
    dispatch: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Validate battery schedule against physical limits and operational risk thresholds.
    Thresholds are defined server-side in config/risk_rules.yaml (Invariant 3).
    """
    site = get_site(site_id, db_path=db_path)
    if not site:
        return {"status": "error", "error": f"Site {site_id} was not found."}

    rules = _load_risk_rules()
    cycling_rules = rules.get("cycling", {})
    max_daily_cycles = float(cycling_rules.get("max_daily_cycles", 1.5))
    warn_threshold_pct = float(cycling_rules.get("warn_threshold_pct", 90.0))
    cycle_warn_limit = max_daily_cycles * (warn_threshold_pct / 100.0)

    checks = []
    violations = []
    has_hard_fail = False
    has_soft_fail = False

    # If dispatch is not supplied, fetch the latest optimization run for this site
    if dispatch is None:
        conn = get_connection(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM optimization_runs
                WHERE site_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (site_id,),
            )
            row = cur.fetchone()
            if row:
                import json
                dispatch = dict(row)
                dispatch["schedule"] = json.loads(dispatch.get("schedule_json", "[]"))
            else:
                dispatch = {}
        finally:
            conn.close()

    schedule = dispatch.get("schedule", [])
    cap = float(site["capacity_mwh"])
    p_mw = float(site["power_mw"])
    soc_min = float(site["soc_min_pct"]) / 100.0 * cap
    soc_max = float(site["soc_max_pct"]) / 100.0 * cap
    reserve_soc = float(site["reserve_soc_pct"]) / 100.0 * cap
    max_d = float(site["max_daily_discharge_mwh"])

    # 1. SOC min check
    soc_min_pass = True
    for h, s in enumerate(schedule):
        if float(s.get("soc_mwh", 0)) < soc_min - 1e-4:
            soc_min_pass = False
            violations.append(f"SOC dropped below minimum allowable ({soc_min:.1f} MWh) at hour {h}.")
            break
    checks.append({"name": "soc_min", "type": "hard", "passed": soc_min_pass, "detail": "Minimum SOC threshold"})
    if not soc_min_pass:
        has_hard_fail = True

    # 2. Reserve SOC check (hard floor)
    reserve_pass = True
    for h, s in enumerate(schedule):
        if float(s.get("soc_mwh", 0)) < reserve_soc - 1e-4:
            reserve_pass = False
            violations.append(f"Reserve SOC violation: SOC dropped below emergency reserve ({reserve_soc:.1f} MWh) at hour {h}.")
            break
    checks.append({"name": "reserve_soc", "type": "hard", "passed": reserve_pass, "detail": "Emergency reserve SOC hard floor"})
    if not reserve_pass:
        has_hard_fail = True

    # 3. SOC max check
    soc_max_pass = True
    for h, s in enumerate(schedule):
        if float(s.get("soc_mwh", 0)) > soc_max + 1e-4:
            soc_max_pass = False
            violations.append(f"SOC exceeded maximum allowable ({soc_max:.1f} MWh) at hour {h}.")
            break
    checks.append({"name": "soc_max", "type": "hard", "passed": soc_max_pass, "detail": "Maximum SOC ceiling"})
    if not soc_max_pass:
        has_hard_fail = True

    # 4. Power limit check
    power_pass = True
    for h, s in enumerate(schedule):
        c = float(s.get("charge_mw", 0))
        d = float(s.get("discharge_mw", 0))
        if c > p_mw + 1e-4 or d > p_mw + 1e-4:
            power_pass = False
            violations.append(f"Power exceeded inverter rating ({p_mw:.1f} MW) at hour {h}.")
            break
    checks.append({"name": "power_limit", "type": "hard", "passed": power_pass, "detail": "Inverter power ceiling"})
    if not power_pass:
        has_hard_fail = True

    # 5. No simultaneous charge/discharge
    no_sim_pass = True
    for h, s in enumerate(schedule):
        if float(s.get("charge_mw", 0)) > 1e-4 and float(s.get("discharge_mw", 0)) > 1e-4:
            no_sim_pass = False
            violations.append(f"Simultaneous charge and discharge detected at hour {h}.")
            break
    checks.append({"name": "no_simultaneous", "type": "hard", "passed": no_sim_pass, "detail": "No simultaneous charge/discharge"})
    if not no_sim_pass:
        has_hard_fail = True

    # 6. Daily throughput check
    tp = float(dispatch.get("throughput_mwh", sum(float(s.get("discharge_mw", 0)) for s in schedule)))
    daily_tp_pass = tp <= max_d + 1e-4
    checks.append({"name": "daily_throughput", "type": "hard", "passed": daily_tp_pass, "detail": f"Daily discharge ({tp:.1f} MWh <= {max_d:.1f} MWh)"})
    if not daily_tp_pass:
        violations.append(f"Total discharge throughput ({tp:.1f} MWh) exceeded daily limit ({max_d:.1f} MWh).")
        has_hard_fail = True

    # 7. Cycling check (soft warning)
    cycles = tp / cap if cap > 0 else 0.0
    cycling_pass = cycles <= cycle_warn_limit + 1e-4
    checks.append({"name": "cycling", "type": "soft", "passed": cycling_pass, "detail": f"Daily equivalent cycles ({cycles:.2f} <= {cycle_warn_limit:.2f})"})
    if not cycling_pass:
        has_soft_fail = True
        violations.append(f"High cycling warning: {cycles:.2f} cycles/day exceeds {warn_threshold_pct:.0f}% of daily limit ({max_daily_cycles:.1f}).")

    # 8. Forecast uncertainty check (historical MAE % of mean price)
    # Zone SR: MAE ≈ 12.9% (Medium), Zone WR: MAE ≈ 9.9% (Low)
    zone = site.get("market_zone", "SR")
    mae_pct = 12.9 if zone == "SR" else 9.9
    forecast_uncertainty = "Medium" if mae_pct >= 10.0 else "Low"
    checks.append({
        "name": "forecast_uncertainty",
        "type": "soft",
        "passed": forecast_uncertainty != "High",
        "detail": f"Historical forecast MAE is {mae_pct:.1f}% of mean price ({forecast_uncertainty} uncertainty)",
    })
    if forecast_uncertainty == "Medium":
        has_soft_fail = True
    elif forecast_uncertainty == "High":
        has_hard_fail = True

    if has_hard_fail:
        risk_level = "High"
    elif has_soft_fail:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    # Identify main risk description
    if violations:
        main_risk = violations[0]
    elif forecast_uncertainty != "Low":
        main_risk = f"Forecast uncertainty (historical MAE ~ {mae_pct:.1f}% of mean price)."
    else:
        main_risk = "None identified; operational limits well within margins."

    return {
        "status": "ok",
        "site_id": site_id,
        "risk_level": risk_level,
        "checks": checks,
        "main_risk": main_risk,
        "violations": violations,
    }
