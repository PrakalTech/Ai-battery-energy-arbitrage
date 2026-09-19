"""
Site operating status tool.
"""

from __future__ import annotations
import sqlite3
from typing import Any, Optional
from energy_agent.db import get_connection
from energy_agent.tools.sites import get_site


def get_site_status(site_id: str, db_path: Optional[str] = None) -> dict[str, Any]:
    """
    Get current telemetry and operating status for a given site.
    Returns {status: 'ok', site_id, soc_pct, capacity_mwh, available_power_mw, ...}
    or {status: 'error', error: ...}
    """
    site = get_site(site_id, db_path=db_path)
    if not site:
        return {
            "status": "error",
            "error": f"Site {site_id} was not found.",
        }

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM site_status
            WHERE site_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (site_id,),
        )
        row = cur.fetchone()
        if not row:
            return {
                "status": "unavailable",
                "site_id": site_id,
                "error": f"No status telemetry available for site {site_id}.",
            }

        status_dict = dict(row)
        return {
            "status": "ok",
            "site_id": site_id,
            "site_name": site["site_name"],
            "location": site["location"],
            "market_zone": site["market_zone"],
            "timestamp": status_dict["timestamp"],
            "soc_pct": float(status_dict["soc_pct"]),
            "capacity_mwh": float(site["capacity_mwh"]),
            "power_mw": float(site["power_mw"]),
            "available_power_mw": float(status_dict["available_power_mw"]),
            "operating_status": status_dict["operating_status"],
            "cycles_today": float(status_dict["cycles_today"]),
            "temperature_c": float(status_dict["temperature_c"]),
            "active_alarms": int(status_dict["active_alarms"]),
            "risk_indicators": "Low" if int(status_dict["active_alarms"]) == 0 and float(status_dict["temperature_c"]) < 40 else "Medium",
        }
    finally:
        conn.close()
