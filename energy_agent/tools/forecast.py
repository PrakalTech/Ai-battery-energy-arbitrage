"""
Forecast retrieval tool.
"""

from __future__ import annotations
import os
import datetime
from typing import Any, Optional
from energy_agent.db import get_connection
from energy_agent.tools.sites import get_site


def get_forecast(
    site_id: str,
    horizon: int = 24,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Get price forecast for site's market_zone for the next operating horizon.
    Returns:
      {
        "status": "ok",
        "site_id": site_id,
        "market_zone": market_zone,
        "forecast_id": forecast_id,
        "model_version": model_version,
        "created_at": created_at,
        "forecast": [{"timestamp": ..., "predicted_price_inr_per_mwh": ...}, ...]
      }
    or status="unavailable" if no forecast exists.
    """
    site = get_site(site_id, db_path=db_path)
    if not site:
        return {"status": "error", "error": f"Site {site_id} was not found."}

    market_zone = site["market_zone"]
    # Determine target forecast date based on AGENT_AS_OF (default: 2026-09-18T23:30:00 -> tomorrow: 2026-09-19)
    as_of_str = os.getenv("AGENT_AS_OF", "2026-09-18T23:30:00")
    try:
        as_of_dt = datetime.datetime.fromisoformat(as_of_str)
    except Exception:
        as_of_dt = datetime.datetime(2026, 9, 18, 23, 30, 0)

    target_date = (as_of_dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    target_fcst_id = f"F-{market_zone}-{(as_of_dt + datetime.timedelta(days=1)).strftime('%Y%m%d')}"

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        # Look for target forecast ID first
        cur.execute(
            """
            SELECT forecast_id, market_zone, created_at, timestamp, predicted_price_inr_per_mwh, model_version
            FROM forecasts
            WHERE market_zone = ? AND (forecast_id = ? OR date(timestamp) = ?)
            ORDER BY timestamp ASC
            """,
            (market_zone, target_fcst_id, target_date),
        )
        rows = cur.fetchall()

        # Fallback to latest forecast for the zone if target date not found
        if not rows:
            cur.execute(
                """
                SELECT forecast_id, market_zone, created_at, timestamp, predicted_price_inr_per_mwh, model_version
                FROM forecasts
                WHERE market_zone = ?
                ORDER BY created_at DESC, timestamp ASC
                LIMIT ?
                """,
                (market_zone, horizon),
            )
            rows = cur.fetchall()

        if not rows:
            return {
                "status": "unavailable",
                "site_id": site_id,
                "market_zone": market_zone,
                "error": "Forecast unavailable. Please run/update the forecasting service.",
            }

        first_row = dict(rows[0])
        forecast_id = first_row["forecast_id"]
        model_version = first_row["model_version"]
        created_at = first_row["created_at"]

        forecast_list = [
            {
                "timestamp": str(r["timestamp"]),
                "predicted_price_inr_per_mwh": float(r["predicted_price_inr_per_mwh"]),
            }
            for r in rows[:horizon]
        ]

        if len(forecast_list) < horizon:
            # If fewer than requested horizon
            pass

        return {
            "status": "ok",
            "site_id": site_id,
            "market_zone": market_zone,
            "forecast_id": forecast_id,
            "model_version": model_version,
            "created_at": created_at,
            "forecast": forecast_list,
        }
    finally:
        conn.close()
