"""
Pytest configuration and fixtures.
Loads sample data into SQLite and sets up test environment.
"""

from __future__ import annotations
import os
import pathlib
import pytest
from dotenv import load_dotenv

_ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

os.environ["LLM_PROVIDER"] = "none"
os.environ["DATA_MODE"] = "sample"
os.environ["AGENT_AS_OF"] = "2026-09-18T23:30:00"
os.environ["DB_PATH"] = str(_ROOT / "energy_agent.db")
