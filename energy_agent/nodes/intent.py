"""
Intent classification node.
"""

from __future__ import annotations
from typing import Any
from energy_agent.state import AgentState
from energy_agent.llm import classify_intent


def intent_node(state: AgentState) -> dict[str, Any]:
    query = state.get("user_query", "")
    res = classify_intent(query)

    updates: dict[str, Any] = {
        "intent": res["intent"],
        "site_ids": res.get("site_ids", []),
    }
    if res.get("scenario"):
        updates["scenario"] = res["scenario"]

    if res.get("is_refusal"):
        updates["is_refusal"] = True
        updates["refusal_site"] = res.get("refusal_site", "S001")

    return updates
