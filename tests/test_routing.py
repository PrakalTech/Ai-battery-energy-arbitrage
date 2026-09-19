"""
Parametrized routing tests running all 22 sample queries from samples/example_queries.json.
Verifies path, called/uncalled tools, and fixed outcomes.
"""

from __future__ import annotations
import json
import pathlib
import pytest
from energy_agent.graph import run_agent

_FIXTURE_PATH = pathlib.Path(__file__).resolve().parent.parent / "samples" / "example_queries.json"
with open(_FIXTURE_PATH, "r", encoding="utf-8") as f:
    QUERIES = json.load(f)


@pytest.mark.parametrize("item", QUERIES, ids=[q["id"] for q in QUERIES])
def test_query_routing(item, monkeypatch):
    qid = item["id"]
    query = item["query"]
    expected_path = item["expected_path"]
    tools_must_call = item.get("tools_must_call", [])
    tools_must_not_call = item.get("tools_must_not_call", [])
    expected_outcome = item.get("expected_outcome", "ok")

    # Mocks for failure testing queries
    if qid == "Q16":
        monkeypatch.setattr(
            "energy_agent.nodes.forecast.get_forecast",
            lambda *args, **kwargs: {
                "status": "unavailable",
                "error": "Forecast unavailable. Please run/update the forecasting service.",
            },
        )
    elif qid == "Q17":
        monkeypatch.setattr(
            "energy_agent.nodes.optimize.optimize_battery",
            lambda *args, **kwargs: {
                "status": "error",
                "solver_status": "infeasible",
                "error": "Optimization could not produce a feasible schedule. Solver status: infeasible",
            },
        )
    elif qid == "Q18":
        monkeypatch.setattr(
            "energy_agent.nodes.risk.check_risk",
            lambda *args, **kwargs: {
                "status": "ok",
                "risk_level": "High",
                "main_risk": "Reserve SOC violation: SOC dropped below emergency reserve",
                "violations": ["Reserve SOC violation: SOC dropped below emergency reserve."],
                "checks": [{"name": "reserve_soc", "passed": False, "detail": "failed"}],
            },
        )

    res = run_agent(query)
    executed_path = res.get("executed_path", [])
    final_resp = res.get("final_response", {})
    tool_results = res.get("tool_results", {})

    # 1. Assert exact execution path
    assert executed_path == expected_path, f"[{qid}] Path mismatch: got {executed_path}, expected {expected_path}"

    # 2. Assert tools called
    for t in tools_must_call:
        assert t in tool_results, f"[{qid}] Expected tool '{t}' to be called, got: {list(tool_results.keys())}"

    # 3. Assert tools NOT called
    for t in tools_must_not_call:
        assert t not in tool_results, f"[{qid}] Forbidden tool '{t}' was called in: {list(tool_results.keys())}"

    # 4. Assert outcome status
    assert final_resp.get("status") == expected_outcome, f"[{qid}] Outcome mismatch: got {final_resp.get('status')}, expected {expected_outcome}"

    # 5. Assert specific error or refusal text if specified
    if "error_message" in item:
        assert item["error_message"] in final_resp.get("message", "")
    if "refusal_contains" in item:
        assert item["refusal_contains"] in final_resp.get("message", "")
