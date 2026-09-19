"""
Forecast node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.forecast import get_forecast


def forecast_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    site_ids = state.get("site_ids", ["S001"])
    sid = site_ids[0] if site_ids else "S001"

    fcst = get_forecast(sid, horizon=24)
    tool_results["get_forecast"] = fcst

    if fcst.get("status") != "ok":
        return {
            "error": {
                "code": "FORECAST_UNAVAILABLE",
                "message": fcst.get("error", "Forecast unavailable. Please run/update the forecasting service."),
            },
            "tool_results": tool_results,
        }

    return {
        "forecast": fcst,
        "tool_results": tool_results,
    }
