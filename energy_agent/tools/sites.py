"""
Site discovery and information tool.
"""

from __future__ import annotations
import sqlite3
from typing import Any, Optional
from energy_agent.db import get_connection


def get_sites(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Return all registered sites from the database.
    Used for site discovery, validation, and metadata.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sites ORDER BY site_id ASC")
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_site(site_id: str, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Return single site row or None if not found.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sites WHERE site_id = ?", (site_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
