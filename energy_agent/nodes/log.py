"""
Logging node.
Writes a record to agent_runs on EVERY path including errors and refusals (Invariant 6).
"""

from __future__ import annotations
import datetime
import uuid
from typing import Any
from energy_agent.state import AgentState
from energy_agent.db import get_connection, insert_agent_run


def log_node(state: AgentState) -> dict[str, Any]:
    run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    query = state.get("user_query", "")
    intent = state.get("intent", "UNKNOWN")
    tool_results = state.get("tool_results", {})
    tools_used = list(tool_results.keys())

    site_ids = state.get("site_ids", [])
    site_id_str = ",".join(site_ids) if site_ids else None

    final_resp = state.get("final_response", {})
    status = final_resp.get("status", "ok")
    if state.get("error"):
        status = "error"

    summary = final_resp.get("message", "")[:250] if final_resp else None
    opt_run_id = state.get("dispatch", {}).get("optimization_run_id")
    bt_run_id = state.get("backtest_result", {}).get("backtest_run_id")
    scenario = state.get("scenario")

    try:
        conn = get_connection()
        insert_agent_run(
            conn,
            run_id=run_id,
            timestamp=ts,
            site_id=site_id_str,
            user_query=query,
            intent=intent,
            tools_used=tools_used,
            scenario=scenario,
            result_summary=summary,
            optimization_run_id=opt_run_id,
            backtest_run_id=bt_run_id,
            status=status,
        )
        conn.close()
    except Exception:
        pass

    return {"run_id": run_id}
