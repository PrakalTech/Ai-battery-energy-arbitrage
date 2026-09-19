"""
LangGraph wiring and conditional routing for Energy Ops Agent.
Strict adherence to §6.2 Intent routing table.
"""

from __future__ import annotations
from typing import Any, Literal
from langgraph.graph import StateGraph, END

from energy_agent.state import AgentState
from energy_agent.nodes import (
    intent_node,
    site_resolution_node,
    retrieval_node,
    forecast_node,
    optimize_node,
    scenario_node,
    risk_node,
    aggregate_node,
    backtest_node,
    respond_node,
    log_node,
)


def _wrap_node(name: str, fn):
    """Wraps a node to record executed path in state for verification."""
    def wrapped(state: AgentState) -> dict[str, Any]:
        res = fn(state) or {}
        executed = list(state.get("executed_path", []))
        executed.append(name)
        res["executed_path"] = executed
        return res
    return wrapped


def route_after_intent(state: AgentState) -> Literal["site_resolution", "respond"]:
    if state.get("is_refusal") or state.get("intent") == "HELP":
        return "respond"
    return "site_resolution"


def route_after_site_resolution(state: AgentState) -> Literal["retrieval", "backtest", "respond"]:
    if state.get("error"):
        return "respond"
    intent = state.get("intent", "STATUS")
    if intent == "BACKTEST":
        return "backtest"
    return "retrieval"


def route_after_retrieval(state: AgentState) -> Literal["forecast", "aggregate", "respond"]:
    if state.get("error"):
        return "respond"
    intent = state.get("intent", "STATUS")
    if intent in ("STATUS", "EXPLAIN"):
        return "respond"
    if intent == "COMPARE":
        return "aggregate"
    # FORECAST, OPTIMIZE, SCENARIO, RISK, FLEET_OPTIMIZE
    return "forecast"


def route_after_forecast(state: AgentState) -> Literal["optimize", "scenario", "risk", "respond"]:
    if state.get("error"):
        return "respond"
    intent = state.get("intent", "FORECAST")
    if intent == "FORECAST":
        return "respond"
    if intent == "SCENARIO":
        return "scenario"
    if intent == "RISK":
        return "risk"
    # OPTIMIZE, FLEET_OPTIMIZE
    return "optimize"


def route_after_optimize(state: AgentState) -> Literal["scenario", "risk", "respond"]:
    if state.get("error"):
        return "respond"
    intent = state.get("intent", "OPTIMIZE")
    # Compound query: OPTIMIZE + FORECAST_ERROR scenario
    if intent == "OPTIMIZE" and state.get("scenario") == "FORECAST_ERROR":
        return "scenario"
    return "risk"


def route_after_scenario(state: AgentState) -> Literal["optimize", "risk", "respond"]:
    if state.get("error"):
        return "respond"
    intent = state.get("intent", "SCENARIO")
    # Compound query goes to risk next
    if intent == "OPTIMIZE":
        return "risk"
    # Standard SCENARIO goes to optimize next
    return "optimize"


def route_after_risk(state: AgentState) -> Literal["aggregate", "respond"]:
    if state.get("error"):
        return "respond"
    intent = state.get("intent", "OPTIMIZE")
    if intent == "FLEET_OPTIMIZE":
        return "aggregate"
    return "respond"


def build_graph() -> StateGraph:
    """Constructs and compiles the Energy Ops Agent StateGraph."""
    graph = StateGraph(AgentState)

    # Add wrapped nodes
    graph.add_node("intent", _wrap_node("intent", intent_node))
    graph.add_node("site_resolution", _wrap_node("site_resolution", site_resolution_node))
    graph.add_node("retrieval", _wrap_node("retrieval", retrieval_node))
    graph.add_node("forecast", _wrap_node("forecast", forecast_node))
    graph.add_node("optimize", _wrap_node("optimize", optimize_node))
    graph.add_node("scenario", _wrap_node("scenario", scenario_node))
    graph.add_node("risk", _wrap_node("risk", risk_node))
    graph.add_node("aggregate", _wrap_node("aggregate", aggregate_node))
    graph.add_node("backtest", _wrap_node("backtest", backtest_node))
    graph.add_node("respond", _wrap_node("respond", respond_node))
    graph.add_node("log", _wrap_node("log", log_node))

    # Entry point
    graph.set_entry_point("intent")

    # Routing edges
    graph.add_conditional_edges("intent", route_after_intent)
    graph.add_conditional_edges("site_resolution", route_after_site_resolution)
    graph.add_conditional_edges("retrieval", route_after_retrieval)
    graph.add_conditional_edges("forecast", route_after_forecast)
    graph.add_conditional_edges("optimize", route_after_optimize)
    graph.add_conditional_edges("scenario", route_after_scenario)
    graph.add_conditional_edges("risk", route_after_risk)

    graph.add_edge("aggregate", "respond")
    graph.add_edge("backtest", "respond")
    graph.add_edge("respond", "log")
    graph.add_edge("log", END)

    return graph.compile()


# Singleton compiled graph instance
app_graph = build_graph()


def run_agent(query: str, db_path: str | None = None) -> dict[str, Any]:
    """Top-level agent runner."""
    state: AgentState = {
        "user_query": query,
        "tool_results": {},
        "executed_path": [],
    }
    return app_graph.invoke(state)
