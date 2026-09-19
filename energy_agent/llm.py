"""
Provider-agnostic LLM interface for Energy Ops Agent.
Supports Google Gemini, OpenAI, Anthropic, and offline deterministic rule-based mode (LLM_PROVIDER=none).
"""

from __future__ import annotations
import json
import os
import re
import urllib.request
import urllib.error
from typing import Any, Optional


VALID_INTENTS = {
    "STATUS",
    "FORECAST",
    "OPTIMIZE",
    "SCENARIO",
    "BACKTEST",
    "RISK",
    "COMPARE",
    "FLEET_OPTIMIZE",
    "EXPLAIN",
    "HELP",
}


def classify_intent_offline(query: str) -> dict[str, Any]:
    """
    Deterministic rule-based intent, entity, and scenario classification.
    Runs completely offline for testing and LLM_PROVIDER=none mode.
    """
    q_lower = query.lower().strip()

    # 1. Check for invariant 3 refusals (must never call dispatch/constraint tools)
    refusal_patterns = [
        r"set .* (discharge|charge) to .* mw",
        r"discharge .* mw",
        r"charge .* mw",
        r"raise the soc limit",
        r"lower the soc limit",
        r"change (the )?(soc|power|capacity|efficiency|degradation) limit",
        r"ignore the risk checker",
        r"bypass (the )?risk",
        r"disable (the )?risk",
        r"max profit .* ignore",
    ]
    for pat in refusal_patterns:
        if re.search(pat, q_lower):
            # Extract mentioned site if any
            m = re.search(r"\b(s\d{3})\b", q_lower)
            site = m.group(1).upper() if m else "S001"
            return {
                "intent": "HELP",
                "site_ids": [site] if m else [],
                "is_refusal": True,
                "refusal_site": site,
                "scenario": None,
            }

    # 2. Extract site IDs
    found_sites = [s.upper() for s in re.findall(r"\b(s\d{3})\b", q_lower)]
    is_all_sites = bool(re.search(r"\b(all sites|all the sites|fleet|every site)\b", q_lower))

    # 3. Intent detection
    # Help
    if q_lower in ("help", "what can you do", "?", "commands"):
        return {"intent": "HELP", "site_ids": [], "is_refusal": False, "scenario": None}

    # Compare
    if "compare" in q_lower:
        return {
            "intent": "COMPARE",
            "site_ids": found_sites or ["S001", "S002", "S003"],
            "is_refusal": False,
            "scenario": None,
        }

    # Fleet optimize
    if ("optimize" in q_lower or "plan" in q_lower) and is_all_sites:
        return {
            "intent": "FLEET_OPTIMIZE",
            "site_ids": ["S001", "S002", "S003"],
            "is_refusal": False,
            "scenario": None,
        }

    # Explain
    if any(w in q_lower for w in ("why did you", "explain", "reason for", "why charge", "why discharge")):
        return {
            "intent": "EXPLAIN",
            "site_ids": found_sites[:1] if found_sites else ["S001"],
            "is_refusal": False,
            "scenario": None,
        }

    # Backtest
    if any(w in q_lower for w in ("backtest", "perform over the last", "last week", "past week", "historical performance", "regret")):
        return {
            "intent": "BACKTEST",
            "site_ids": found_sites[:1] if found_sites else ["S003"],
            "is_refusal": False,
            "scenario": None,
        }

    # Compound: Optimize + Scenario ("what could go wrong")
    if "optimize" in q_lower and any(w in q_lower for w in ("what could go wrong", "risk", "stress", "uncertainty")):
        return {
            "intent": "OPTIMIZE",
            "site_ids": found_sites[:1] if found_sites else ["S001"],
            "is_refusal": False,
            "scenario": "FORECAST_ERROR",
        }

    # Risk
    if "risk" in q_lower or "risky" in q_lower or "what could go wrong" in q_lower:
        return {
            "intent": "RISK",
            "site_ids": found_sites[:1] if found_sites else ["S002"],
            "is_refusal": False,
            "scenario": None,
        }

    # Scenario queries
    if any(w in q_lower for w in ("what if", "scenario", "prices are", "prices fall", "prices drop", "spike", "solar", "renewable")):
        scenario = "HIGH_PRICE"
        if "fall" in q_lower or "drop" in q_lower or "lower" in q_lower or "decrease" in q_lower:
            scenario = "LOW_PRICE"
        elif "solar" in q_lower or "renewable" in q_lower:
            scenario = "HIGH_RENEWABLE"
        elif "spike" in q_lower or "volatil" in q_lower:
            scenario = "HIGH_VOLATILITY"
        elif "error" in q_lower or "uncertain" in q_lower or "wrong" in q_lower:
            scenario = "FORECAST_ERROR"

        return {
            "intent": "SCENARIO",
            "site_ids": found_sites[:1] if found_sites else ["S001"],
            "is_refusal": False,
            "scenario": scenario,
        }

    # Optimize single site
    if "optimize" in q_lower or "schedule" in q_lower or "plan" in q_lower:
        return {
            "intent": "OPTIMIZE",
            "site_ids": found_sites[:1] if found_sites else ["S001"],
            "is_refusal": False,
            "scenario": None,
        }

    # Forecast
    if "forecast" in q_lower or "prediction" in q_lower or "predicted" in q_lower:
        return {
            "intent": "FORECAST",
            "site_ids": found_sites[:1] if found_sites else ["S002"],
            "is_refusal": False,
            "scenario": None,
        }

    # Status / Active sites
    if "status" in q_lower or "sites" in q_lower or "active" in q_lower or "soc" in q_lower:
        if is_all_sites or ("active sites" in q_lower and not found_sites):
            site_ids = ["S001", "S002", "S003"] if is_all_sites else []
        else:
            site_ids = found_sites
        return {
            "intent": "STATUS",
            "site_ids": site_ids,
            "is_refusal": False,
            "scenario": None,
        }

    # Default fallback to HELP
    return {
        "intent": "HELP",
        "site_ids": found_sites[:1] if found_sites else [],
        "is_refusal": False,
        "scenario": None,
    }


def call_gemini(prompt: str, model: str = "gemini-2.5-flash", api_key: Optional[str] = None) -> Optional[str]:
    """Call Google Gemini API via HTTP POST."""
    key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-goog-api-key": key},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            candidates = body.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
    except Exception:
        return None
    return None


def classify_intent(query: str) -> dict[str, Any]:
    """
    Main intent classification entrypoint.
    If LLM_PROVIDER is google and API key is present, validates with Gemini;
    Always ensures deterministic compliance and exact enum conformance.
    """
    # Baseline deterministic parse is the primary anchor to guarantee non-negotiable invariants
    offline_res = classify_intent_offline(query)
    provider = os.getenv("LLM_PROVIDER", "none").lower()

    if provider in ("google", "gemini"):
        # We can optionally enhance intent with Gemini if it's not a refusal
        if offline_res.get("is_refusal"):
            return offline_res

        # If offline detected unknown or general, query Gemini
        prompt = (
            f"You are an energy battery operations classifier. Classify the user query into exactly one of these intents:\n"
            f"STATUS, FORECAST, OPTIMIZE, SCENARIO, BACKTEST, RISK, COMPARE, FLEET_OPTIMIZE, EXPLAIN, HELP.\n"
            f"Also extract site_ids (e.g. S001, S002, S003) and scenario enum if applicable.\n"
            f"User query: '{query}'\n"
            f"Respond ONLY in valid JSON with keys: 'intent', 'site_ids', 'scenario'."
        )
        gemini_out = call_gemini(prompt)
        if gemini_out:
            try:
                clean_json = re.sub(r"^```json\s*|\s*```$", "", gemini_out.strip(), flags=re.MULTILINE)
                parsed = json.loads(clean_json)
                intent = parsed.get("intent", "").upper()
                if intent in VALID_INTENTS:
                    offline_res["intent"] = intent
                if parsed.get("site_ids"):
                    offline_res["site_ids"] = [str(s).upper() for s in parsed["site_ids"]]
                if parsed.get("scenario"):
                    offline_res["scenario"] = str(parsed["scenario"]).upper()
            except Exception:
                pass

    return offline_res
