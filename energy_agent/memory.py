"""
Conversation session and multi-turn state tracking.
"""

from __future__ import annotations
from typing import Any, Optional


class SessionMemory:
    """
    Maintains operational context (active site, last dispatch, last scenario) across turns.
    """
    def __init__(self):
        self.active_site_id: Optional[str] = "S001"
        self.last_intent: Optional[str] = None
        self.last_dispatch: Optional[dict[str, Any]] = None
        self.history: list[dict[str, Any]] = []

    def update(self, state: dict[str, Any]) -> None:
        site_ids = state.get("site_ids", [])
        if site_ids:
            self.active_site_id = site_ids[0]
        if state.get("intent"):
            self.last_intent = state["intent"]
        if state.get("dispatch"):
            self.last_dispatch = state["dispatch"]
        self.history.append({
            "query": state.get("user_query"),
            "intent": state.get("intent"),
            "response": state.get("final_response", {}).get("message"),
        })

    def resolve_site(self, extracted_sites: list[str]) -> list[str]:
        if extracted_sites:
            self.active_site_id = extracted_sites[0]
            return extracted_sites
        if self.active_site_id:
            return [self.active_site_id]
        return ["S001"]


# Global default session memory
default_session = SessionMemory()
