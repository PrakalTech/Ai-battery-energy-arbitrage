"""
Site resolution and validation node.
"""

from __future__ import annotations
import re
from typing import Any
from energy_agent.state import AgentState
from energy_agent.tools.sites import get_sites


def site_resolution_node(state: AgentState) -> dict[str, Any]:
    tool_results = dict(state.get("tool_results", {}))

    # Invariant check: call get_sites to validate
    all_sites = get_sites()
    tool_results["get_sites"] = all_sites
    known_site_ids = {s["site_id"] for s in all_sites}

    query = state.get("user_query", "")
    intent = state.get("intent", "HELP")

    # If already marked refusal or help with no sites needed
    if state.get("is_refusal") or (intent == "HELP" and not state.get("site_ids")):
        return {"tool_results": tool_results}

    # Extract all S### tokens from query
    all_mentioned = [s.upper() for s in re.findall(r"\b(s\d{3})\b", query, re.IGNORECASE)]

    # Check for invalid sites
    for sid in all_mentioned:
        if sid not in known_site_ids:
            return {
                "error": {
                    "code": "SITE_NOT_FOUND",
                    "message": f"Site {sid} was not found.",
                },
                "tool_results": tool_results,
            }

    site_ids = state.get("site_ids", [])
    # If all sites requested
    if re.search(r"\b(all sites|all the sites|fleet|every site)\b", query, re.IGNORECASE):
        site_ids = [s["site_id"] for s in all_sites if s.get("status") == "active"]

    # Verify existing site_ids
    for sid in site_ids:
        if sid not in known_site_ids:
            return {
                "error": {
                    "code": "SITE_NOT_FOUND",
                    "message": f"Site {sid} was not found.",
                },
                "tool_results": tool_results,
            }

    # Default to S001 if single-site intent had no site specified
    if not site_ids and intent in ("OPTIMIZE", "FORECAST", "RISK", "SCENARIO", "EXPLAIN", "BACKTEST"):
        site_ids = ["S001"]

    return {
        "site_ids": site_ids,
        "tool_results": tool_results,
    }
