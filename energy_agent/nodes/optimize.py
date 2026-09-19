"""
Optimization node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.optimizer import optimize_battery


def optimize_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    intent = state.get("intent", "OPTIMIZE")
    site_ids = state.get("site_ids", ["S001"])
    forecast = state.get("forecast")

    if intent == "FLEET_OPTIMIZE":
        # optimize per site
        site_dispatches = []
        for sid in site_ids:
            res = optimize_battery(sid, db_path=None)
            if res.get("status") != "ok":
                return {
                    "error": {
                        "code": "OPTIMIZER_FAILURE",
                        "message": f"Optimization could not produce a feasible schedule for {sid}.",
                    },
                    "tool_results": tool_results,
                }
            site_dispatches.append(res)
        tool_results["optimize_battery"] = site_dispatches
        return {
            "fleet_dispatches": site_dispatches,
            "tool_results": tool_results,
        }

    # Single site optimization
    sid = site_ids[0] if site_ids else "S001"
    opt_res = optimize_battery(sid, forecast=forecast)
    tool_results["optimize_battery"] = opt_res

    if opt_res.get("status") != "ok":
        return {
            "error": {
                "code": "OPTIMIZER_FAILURE",
                "message": "Optimization could not produce a feasible schedule.",
            },
            "tool_results": tool_results,
        }

    return {
        "dispatch": opt_res,
        "tool_results": tool_results,
    }
