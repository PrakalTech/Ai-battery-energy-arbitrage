"""
Optimization run retrieval tool for explanation and analysis.
"""

from __future__ import annotations
import json
from typing import Any, Optional
from energy_agent.db import get_connection
from energy_agent.tools.sites import get_site


def get_optimization_run(
    site_id: str,
    run_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Retrieve stored optimization run and schedule details for EXPLAIN intents.
    """
    site = get_site(site_id, db_path=db_path)
    if not site:
        return {"status": "error", "error": f"Site {site_id} was not found."}

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        if run_id:
            cur.execute(
                """
                SELECT * FROM optimization_runs
                WHERE site_id = ? AND optimization_run_id = ?
                LIMIT 1
                """,
                (site_id, run_id),
            )
        else:
            cur.execute(
                """
                SELECT * FROM optimization_runs
                WHERE site_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (site_id,),
            )
        row = cur.fetchone()
        if not row:
            return {
                "status": "unavailable",
                "site_id": site_id,
                "error": f"No optimization run found for site {site_id}.",
            }

        res = dict(row)
        schedule = json.loads(res.get("schedule_json", "[]"))
        binding = json.loads(res.get("binding_constraints", "[]"))

        return {
            "status": "ok",
            "site_id": site_id,
            "optimization_run_id": res.get("optimization_run_id"),
            "forecast_id": res.get("forecast_id"),
            "solver_status": res.get("solver_status"),
            "runtime_s": float(res.get("runtime_s", 0.0)),
            "initial_soc_mwh": float(res.get("initial_soc_mwh", 0.0)),
            "expected_revenue_inr": float(res.get("expected_revenue_inr", 0.0)),
            "charging_cost_inr": float(res.get("charging_cost_inr", 0.0)),
            "degradation_cost_inr": float(res.get("degradation_cost_inr", 0.0)),
            "expected_profit_inr": float(res.get("expected_profit_inr", 0.0)),
            "throughput_mwh": float(res.get("throughput_mwh", 0.0)),
            "binding_constraints": binding,
            "schedule": schedule,
        }
    finally:
        conn.close()
