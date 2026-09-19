"""
Historical price retrieval tool.
"""

from __future__ import annotations
import sqlite3
from typing import Any, Optional
from energy_agent.db import get_connection
from energy_agent.tools.sites import get_site


def get_price_history(
    site_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Get historical prices for the site's market_zone.
    """
    site = get_site(site_id, db_path=db_path)
    if not site:
        return {"status": "error", "error": f"Site {site_id} was not found."}

    market_zone = site["market_zone"]
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = "SELECT timestamp, price_inr_per_mwh FROM price_history WHERE market_zone = ?"
        params: list[Any] = [market_zone]

        if start:
            query += " AND timestamp >= ?"
            params.append(start)
        if end:
            query += " AND timestamp <= ?"
            params.append(end)

        query += " ORDER BY timestamp ASC"
        cur.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            return {
                "status": "unavailable",
                "site_id": site_id,
                "market_zone": market_zone,
                "error": f"No price history found for market zone {market_zone}.",
                "prices": [],
            }

        prices = [{"timestamp": r[0], "price_inr_per_mwh": float(r[1])} for r in rows]
        return {
            "status": "ok",
            "site_id": site_id,
            "market_zone": market_zone,
            "count": len(prices),
            "prices": prices,
        }
    finally:
        conn.close()
