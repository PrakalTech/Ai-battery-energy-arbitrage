"""
Data retrieval node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.status import get_site_status
from energy_agent.tools.runs import get_optimization_run


def retrieval_node(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        return {}

    tool_results = dict(state.get("tool_results", {}))
    intent = state.get("intent", "STATUS")
    site_ids = state.get("site_ids", ["S001"])

    if intent == "EXPLAIN":
        sid = site_ids[0] if site_ids else "S001"
        run_res = get_optimization_run(sid)
        tool_results["get_optimization_run"] = run_res
        return {
            "dispatch": run_res,
            "tool_results": tool_results,
        }

    # For status or optimization/risk retrieval
    status_list = []
    for sid in site_ids:
        st = get_site_status(sid)
        if st.get("status") == "ok":
            status_list.append(st)

    tool_results["get_site_status"] = status_list
    return {
        "status_data": status_list,
        "tool_results": tool_results,
    }
