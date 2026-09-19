"""
AgentState definition for energy-ops-agent.
"""

from __future__ import annotations
from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    user_query: str
    site_ids: list[str]
    intent: str            # STATUS, FORECAST, OPTIMIZE, SCENARIO, BACKTEST,
                           # RISK, COMPARE, FLEET_OPTIMIZE, EXPLAIN, HELP
    forecast: dict[str, Any]
    scenario: str          # enum value, e.g. HIGH_PRICE
    scenario_result: dict[str, Any]
    dispatch: dict[str, Any]
    risk_result: dict[str, Any]
    backtest_result: dict[str, Any]
    status_data: list[dict[str, Any]]
    fleet_result: dict[str, Any]
    fleet_dispatches: list[dict[str, Any]]
    fleet_risk: list[dict[str, Any]]
    compare_result: dict[str, Any]
    tool_results: dict[str, Any]     # keyed by tool name -> list of results; SOURCE OF TRUTH for the response
    error: Optional[dict[str, Any]]  # {"code": ..., "message": ...} when a node fails
    final_response: dict[str, Any]   # structured payload + rendered text
    executed_path: list[str]
    is_refusal: bool
    refusal_site: str
    run_id: str
