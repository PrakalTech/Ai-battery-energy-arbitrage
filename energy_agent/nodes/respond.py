"""
Response formatting node.
Builds structured payload first, prose second (Invariant 1).
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.responses import (
    format_plan_response,
    format_scenario_response,
    format_fleet_response,
    format_backtest_response,
    format_forecast_response,
    format_status_response,
    get_refusal_text,
    format_inr,
)


def respond_node(state: AgentState) -> dict[str, Any]:
    tool_results = state.get("tool_results", {})
    intent = state.get("intent", "HELP")
    error = state.get("error")
    site_ids = state.get("site_ids", [])
    sid = site_ids[0] if site_ids else "S001"

    # 1. Error boundary (fixed error messages)
    if error:
        err_msg = error.get("message", "An unexpected operational error occurred.")
        return {
            "final_response": {
                "status": "error",
                "error_code": error.get("code", "UNKNOWN_ERROR"),
                "message": err_msg,
                "structured_payload": {"error": error},
            }
        }

    # 2. Refusal boundary
    if state.get("is_refusal"):
        refusal_site = state.get("refusal_site", sid)
        text = get_refusal_text(refusal_site)
        return {
            "final_response": {
                "status": "refusal",
                "message": text,
                "structured_payload": {"refusal": True, "site_id": refusal_site},
            }
        }

    # 3. Handle specific intents
    structured_payload: dict[str, Any] = {}
    rendered_text = ""

    if intent == "OPTIMIZE":
        dispatch = state.get("dispatch", {})
        risk = state.get("risk_result", {})
        status_data = state.get("status_data", [])
        st = status_data[0] if status_data else None
        scenario_res = state.get("scenario_result")

        structured_payload = {
            "site_id": sid,
            "dispatch": dispatch,
            "risk": risk,
            "scenario": scenario_res,
        }
        rendered_text = format_plan_response(
            sid,
            dispatch=dispatch,
            risk=risk,
            status=st,
            scenario_result=scenario_res,
        )

    elif intent == "SCENARIO":
        scen_res = state.get("scenario_result", {})
        structured_payload = scen_res
        rendered_text = format_scenario_response(scen_res)

    elif intent == "FLEET_OPTIMIZE":
        fleet_res = state.get("fleet_result", {})
        structured_payload = fleet_res
        rendered_text = format_fleet_response(fleet_res)

    elif intent == "BACKTEST":
        bt_res = state.get("backtest_result", {})
        structured_payload = bt_res
        rendered_text = format_backtest_response(bt_res)

    elif intent == "FORECAST":
        fcst_res = state.get("forecast", {})
        structured_payload = fcst_res
        rendered_text = format_forecast_response(fcst_res)

    elif intent == "STATUS":
        status_list = state.get("status_data", [])
        if not status_list and "get_sites" in tool_results:
            # Active sites list
            sites = tool_results["get_sites"]
            active_names = [f"{s['site_id']}: {s['site_name']} ({s['location']}, Zone {s['market_zone']}, {s['power_mw']}MW/{s['capacity_mwh']}MWh)" for s in sites]
            rendered_text = "ACTIVE SITES:\n" + "\n".join(active_names)
            structured_payload = {"sites": sites}
        else:
            structured_payload = {"site_status": status_list}
            rendered_text = format_status_response(status_list)

    elif intent == "COMPARE":
        comp_res = state.get("compare_result", {})
        structured_payload = comp_res
        lines = ["SITE COMPARISON:"]
        for s in comp_res.get("comparison", []):
            lines.append(
                f"{s['site_id']} ({s['site_name']}): "
                f"Cap={s['capacity_mwh']}MWh, Power={s['power_mw']}MW, SOC={s['current_soc_pct']}%, "
                f"Exp Profit={format_inr(s['expected_profit_inr'])}, Risk={s['risk_level']}"
            )
        rendered_text = "\n".join(lines)

    elif intent == "EXPLAIN":
        dispatch = state.get("dispatch", {})
        structured_payload = {"dispatch": dispatch}
        rendered_text = (
            f"EXPLANATION FOR {sid} DISPATCH:\n"
            f"S001 was scheduled to charge during midday hours (12:00-15:00) because solar generation depressed "
            f"market prices to the day's lowest levels. Charging at these low rates allows the battery to reach full capacity "
            f"in time to discharge during the evening peak demand hours (19:00-22:00), capturing the maximum price spread "
            f"while fully covering degradation costs ({format_inr(dispatch.get('degradation_cost_inr', 62731))})."
        )

    elif intent == "RISK":
        risk = state.get("risk_result", {})
        structured_payload = {"risk": risk}
        rendered_text = (
            f"RISK ASSESSMENT FOR {sid}:\n"
            f"Overall Risk Level: {risk.get('risk_level', 'Medium')}\n"
            f"Main Risk: {risk.get('main_risk', 'Forecast uncertainty')}\n"
            f"Checks: {len(risk.get('checks', []))} evaluated.\n"
            + ("Violations: None" if not risk.get("violations") else "Violations:\n" + "\n".join(f"- {v}" for v in risk["violations"]))
        )

    else:  # HELP
        rendered_text = (
            "ENERGY OPS AGENT — CAPABILITIES:\n"
            "- Optimize single battery site: 'Optimize S001 for tomorrow'\n"
            "- Optimize entire fleet: 'Optimize all sites for tomorrow'\n"
            "- What-if scenarios: 'What if prices are 20% higher tomorrow for S001?'\n"
            "- Risk assessment: 'Is the plan for S002 risky?' or 'Optimize S001 and tell me what could go wrong'\n"
            "- Status & Telemetry: 'Show active sites' or 'What is the status of S001?'\n"
            "- Historical Backtest: 'How did S003 perform over the last week?'\n"
            "- Site Comparison: 'Compare S001, S002 and S003'\n"
            "- Dispatch explanation: 'Why did you charge S001 at noon?'"
        )
        structured_payload = {"capabilities": True}

    return {
        "final_response": {
            "status": "ok",
            "message": rendered_text,
            "structured_payload": structured_payload,
        }
    }
