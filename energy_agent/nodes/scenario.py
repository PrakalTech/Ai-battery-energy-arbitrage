"""
Scenario execution node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.scenario import run_scenario


def scenario_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    site_ids = state.get("site_ids", ["S001"])
    sid = site_ids[0] if site_ids else "S001"
    scenario = state.get("scenario", "HIGH_PRICE")

    res = run_scenario(sid, scenario=scenario)
    tool_results["run_scenario"] = res

    if res.get("status") != "ok":
        return {
            "error": {
                "code": "SCENARIO_FAILURE",
                "message": res.get("error", "Scenario evaluation could not produce a valid schedule."),
            },
            "tool_results": tool_results,
        }

    return {
        "scenario_result": res,
        "tool_results": tool_results,
    }
