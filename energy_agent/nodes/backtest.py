"""
Backtest node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.backtest import run_backtest


def backtest_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    site_ids = state.get("site_ids", ["S003"])
    sid = site_ids[0] if site_ids else "S003"

    res = run_backtest(sid)
    tool_results["run_backtest"] = res

    return {
        "backtest_result": res,
        "tool_results": tool_results,
    }
