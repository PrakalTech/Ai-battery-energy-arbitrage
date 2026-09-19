"""
Aggregation node for multi-site and fleet metrics.
Computes totals strictly in code (Invariant 1).
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.fleet import optimize_fleet
from energy_agent.tools.compare import compare_sites


def aggregate_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    intent = state.get("intent", "FLEET_OPTIMIZE")
    site_ids = state.get("site_ids", ["S001", "S002", "S003"])

    if intent == "FLEET_OPTIMIZE":
        fleet_res = optimize_fleet(site_ids)
        tool_results["optimize_fleet"] = fleet_res
        return {
            "fleet_result": fleet_res,
            "tool_results": tool_results,
        }

    elif intent == "COMPARE":
        comp_res = compare_sites(site_ids)
        tool_results["compare_sites"] = comp_res
        return {
            "compare_result": comp_res,
            "tool_results": tool_results,
        }

    return {"tool_results": tool_results}
