"""
Risk check node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.risk import check_risk


def risk_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    intent = state.get("intent", "RISK")
    site_ids = state.get("site_ids", ["S001"])

    if intent == "FLEET_OPTIMIZE":
        # Check risk per site
        dispatches = state.get("fleet_dispatches", [])
        risk_results = []
        for d in dispatches:
            sid = d.get("site_id", "S001")
            r = check_risk(sid, dispatch=d)
            risk_results.append(r)
        tool_results["check_risk"] = risk_results
        return {
            "fleet_risk": risk_results,
            "tool_results": tool_results,
        }

    sid = site_ids[0] if site_ids else "S001"
    dispatch = state.get("dispatch")
    risk_res = check_risk(sid, dispatch=dispatch)
    tool_results["check_risk"] = risk_res

    return {
        "risk_result": risk_res,
        "tool_results": tool_results,
    }
