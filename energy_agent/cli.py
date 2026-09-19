"""
Command-line interface for Energy Ops Agent.
Usage:
    python -m energy_agent.cli "Optimize S001 for tomorrow"
    python -m energy_agent.cli "help"
"""

from __future__ import annotations
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from energy_agent.graph import run_agent


def main():
    if len(sys.argv) < 2:
        query = "help"
    else:
        query = " ".join(sys.argv[1:])

    res = run_agent(query)
    msg = res.get("final_response", {}).get("message", "No response generated.")

    print("\n" + "=" * 60)
    print(f"QUERY: {query}")
    print("=" * 60)
    print(msg)
    print("=" * 60)

    data_mode = os.getenv("DATA_MODE", "sample").lower()
    if data_mode == "sample":
        print("SAMPLE DATA (synthetic)\n")
    else:
        print("PRODUCTION DATA (real)\n")


if __name__ == "__main__":
    main()
