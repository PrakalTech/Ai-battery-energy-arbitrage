# ⚡ Energy Ops Agent — LangGraph Operator Assistant for Battery Energy Storage

An **operator-assistance and orchestration agent** for a fleet of battery energy-storage (BESS) sites.
An operator asks in plain English — *"Optimize S001 for tomorrow and tell me what could go wrong"* — and the agent
routes the request through **trusted tools** (SQL, forecast, optimizer, risk checker, scenario engine, backtest,
fleet aggregation) and explains the results.

> **The agent is not the optimizer, not the forecaster, and not the database.**
> It understands the request, calls the right tools, and explains what the tools returned.

This repository ships with **synthetic sample data, sample queries with golden expected numbers, server-side
config, and validation scripts**, so everything can be built, tested and demoed *before* the real datasets arrive.

---

## Table of contents

1. [Read this first: the six invariants](#1-read-this-first-the-six-invariants)
2. [Quick start](#2-quick-start)
3. [Build plan for Antigravity (phase by phase)](#3-build-plan-for-antigravity-phase-by-phase)
4. [Project layout](#4-project-layout)
5. [Architecture](#5-architecture)
6. [AgentState and graph nodes](#6-agentstate-and-graph-nodes)
7. [Tool contracts](#7-tool-contracts)
8. [Data layer and dataset contract](#8-data-layer-and-dataset-contract)
9. [Sample data bundled in this repo](#9-sample-data-bundled-in-this-repo)
10. [Domain specs: optimizer, risk checker, scenarios, backtest](#10-domain-specs-optimizer-risk-checker-scenarios-backtest)
11. [Response formats (with worked examples)](#11-response-formats-with-worked-examples)
12. [Sample queries and expected behaviour](#12-sample-queries-and-expected-behaviour)
13. [Testing: invariant tests](#13-testing-invariant-tests)
14. [Swapping sample data for real data (teammate workflow)](#14-swapping-sample-data-for-real-data-teammate-workflow)
15. [Configuration](#15-configuration)
16. [Definition of done](#16-definition-of-done)
17. [Assumptions and open questions](#17-assumptions-and-open-questions)

---

## 1. Read this first: the six invariants

The agent sits between a human operator and physical batteries. The failure that matters is an **LLM-invented number
or dispatch reaching the operator as if it were real**. Everything in this design exists to make that *structurally
impossible*, not just discouraged in a prompt. **Do not weaken these to make something easier to build.**

| # | Invariant | What it means in code |
|---|---|---|
| 1 | **Numbers come only from tools.** | Profit, SOC, forecasts, degradation cost, throughput, regret are produced by SQL / forecast / optimizer / backtest tools. The LLM never computes, estimates or adjusts them. Fleet totals are summed **in code** (`optimize_fleet`), never by the LLM. |
| 2 | **Dispatch flows one way.** | `Agent requests → Optimizer produces → Risk checker validates → Agent explains`. No code path may turn LLM output into a charge/discharge MW value. |
| 3 | **The LLM has no write path to constraints.** | No tool parameter for SOC limits, power limits, capacity, efficiency, degradation cost or risk toggles. Natural-language requests to change them are **refused** in the response node. |
| 4 | **Never claim an action that did not happen.** | The response may only mention a scenario / backtest / optimization if a matching entry exists in `tool_results`. |
| 5 | **Fail loudly, never fabricate.** | Missing forecast, infeasible solve, DB error, failed scenario → fixed error response (see §6). No fallback to invented values. |
| 6 | **Label everything.** | Forecast vs actual price · expected vs realized profit · baseline vs scenario. State uncertainty; never claim certainty about future prices. |

When a request conflicts with an invariant (e.g. *"just discharge 50 MW at 6 pm"*), explain the boundary in one or two
sentences and **offer the compliant alternative** (an optimization run or a scenario).

---

## 2. Quick start

```bash
# 1. environment
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                         # DATA_MODE=sample, LLM_PROVIDER=none works offline

# 2. (optional) regenerate the synthetic sample data — deterministic, seed 42
python scripts/generate_sample_data.py --out data/sample

# 3. validate any dataset folder against the data contract
python scripts/validate_datasets.py data/sample              # must print: 0 error(s)

# 4. once the code is built (Phase 0-6 below)
python scripts/load_data.py --source data/sample             # CSV -> SQLite
python -m energy_agent.cli "Optimize S001 for tomorrow"      # ask a question
streamlit run energy_agent/dashboard.py                      # optional dashboard
pytest -q                                                    # invariant tests
```

Already implemented and tested in this repo: `scripts/generate_sample_data.py`, `scripts/validate_datasets.py`,
all files in `data/sample/`, `config/*.yaml`, `samples/example_queries.json`.
Everything under `energy_agent/` is **to be built** following this README.

---

## 3. Build plan for Antigravity (phase by phase)

### 3.1 Paste this as the first prompt

```text
Read README.md fully before writing any code. It is the spec.
Build the project phase by phase (README section 3.2). After each phase:
  1) run the phase's acceptance check, 2) show me the results, 3) stop and wait for my approval.
Rules you must not break (README section 1): numbers come only from tools; the LLM can never produce
MW dispatch values or change constraints; errors use the fixed messages in README section 6; every run
is logged to agent_runs. Use data/sample (DATA_MODE=sample) for everything; do NOT fabricate other data.
The system must work end to end with LLM_PROVIDER=none (rule-based intent + template text).
Do not modify scripts/, data/sample/, config/ or samples/ unless I ask.
Start with Phase 0 and give me a plan first.
```

### 3.2 Phases and acceptance checks

| Phase | Build | Acceptance check |
|---|---|---|
| **0 — Scaffold & data** | Package layout (§4), `db.py` (all DDL in §8.2), `scripts/load_data.py` (CSV → SQLite, idempotent, refuses to load if `validate_datasets` reports errors) | `python scripts/load_data.py --source data/sample` → row counts match §9.1 |
| **1 — Read tools** | `get_sites`, `get_site_status`, `get_price_history`, `get_forecast`, `get_optimization_run` over SQLite. Typed functions returning `{"status": "ok"\|"error"\|"unavailable", ...}` | Unit tests: `get_forecast` for a day with no forecast → `status="unavailable"` |
| **2 — Domain engines** | `optimize_battery` (LP, §10.1), `check_risk` (§10.2), `run_scenario` (§10.3), `run_backtest` (§10.4), `compare_sites`, `optimize_fleet` | `optimize_battery("S001", forecast 2026-09-19)` reproduces the golden numbers in §12 within 1 % |
| **3 — Graph** | `state.py`, the 10 nodes, conditional routing (§6), error short-circuit to `respond → log` | All 22 queries in `samples/example_queries.json` follow the expected path |
| **4 — Response layer** | `responses.py`: structured payload first, prose second (§11); refusal handling | Golden queries render the exact templates in §11 |
| **5 — Logging & tests** | `agent_runs` insert on **every** path incl. errors; the invariant tests (§13) | `pytest -q` green |
| **6 — CLI & dashboard** | `cli.py`; optional Streamlit dashboard rendering the same structured payload (not the prose) | `python -m energy_agent.cli "help"` works; dashboard shows the S001 plan chart |
| **7 — Real data** | Run the teammate workflow in §14 | `DATA_MODE=real` passes the same test-suite except golden-number tests |

> **Tip for working with Antigravity:** keep it in a planning-first mode, review the plan before it edits files, and
> never let it "simplify" an invariant. If it proposes letting the LLM call the optimizer with MW values or
> constraint parameters, reject it and point back to §1.

---

## 4. Project layout

```
energy-ops-agent/
├── README.md                     # this file (the spec)
├── requirements.txt
├── .env.example
├── config/
│   ├── risk_rules.yaml           # ✅ provided — server-side, never editable by chat/LLM
│   └── scenarios.yaml            # ✅ provided — scenario enum definitions
├── data/
│   ├── sample/                   # ✅ provided — SYNTHETIC data (7 CSVs)
│   └── raw/                      # 📥 teammate drops real CSVs here (same schema)
├── samples/
│   └── example_queries.json      # ✅ provided — 22 demo prompts + test fixtures + golden numbers
├── scripts/
│   ├── generate_sample_data.py   # ✅ provided — seeded generator + reference LP
│   ├── validate_datasets.py      # ✅ provided — data-contract validator
│   └── load_data.py              # 🔨 build (Phase 0)
├── energy_agent/                 # 🔨 build
│   ├── state.py                  # AgentState TypedDict
│   ├── db.py                     # DDL, connection, agent_runs insert
│   ├── tools/                    # one module per tool; controlled data access only
│   │   ├── sites.py  status.py  prices.py  forecast.py  optimizer.py  risk.py
│   │   ├── scenario.py  backtest.py  compare.py  fleet.py  runs.py
│   ├── nodes/                    # intent, site_resolution, retrieval, forecast, optimize,
│   │                             #   scenario, risk, aggregate, respond, log
│   ├── graph.py                  # StateGraph wiring + conditional routing
│   ├── responses.py              # plan / scenario / fleet / forecast-risk formatters, refusals
│   ├── llm.py                    # provider-agnostic wrapper; LLM_PROVIDER=none => rule-based
│   ├── cli.py
│   └── dashboard.py              # Streamlit (optional)
└── tests/
    ├── conftest.py               # loads data/sample into an in-memory SQLite
    ├── test_invariants.py        # §13
    ├── test_tools.py
    ├── test_routing.py           # runs samples/example_queries.json
    └── test_golden.py            # golden numbers, 1 % tolerance
```

---

## 5. Architecture

```
                         ┌───────────────────────────────────────────────┐
  Operator ──question──▶ │  LangGraph agent (orchestration only)         │
                         │                                               │
                         │  intent ─▶ site_resolution ─▶ ... path ...    │
                         │                                               │
                         └───────┬───────────────────────────────┬───────┘
                                 │ controlled tool calls         │ structured payload
                                 ▼                               ▼
   ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐
   │ SQLite   │  │Forecaster│  │ Optimizer │  │  Risk    │  │ Scenario / │
   │(SQL tools)│ │ service  │  │  (LP)     │  │ checker  │  │ Backtest   │
   └──────────┘  └──────────┘  └─────┬─────┘  └────▲─────┘  └────────────┘
                                     │  dispatch   │ validates
                                     └─────────────┘
   Dispatch flow (one way):  Agent requests → Optimizer produces → Risk checker validates → Agent explains
```

Design choices to keep:

* **Structured result first, prose second.** Nodes fill a `final_response` dict; the LLM only turns that payload into
  concise text. The dashboard renders the dict directly, and tests assert on numbers without parsing prose.
* **LLM is used for two things only:** intent classification (structured output constrained to the fixed intent set;
  unknown → `HELP`) and phrasing the final text from validated `tool_results`. Everything else is deterministic code.
* **State stays small:** ids and the current workflow's results — never tables or price histories.
* **Scenario engine is a tool**, not prompt logic. "Prices 20 % higher" must run
  baseline forecast → modified assumptions → optimizer → risk check → baseline-vs-scenario comparison.
  It must never answer "profit will be 20 % higher".

---

## 6. AgentState and graph nodes

```python
class AgentState(TypedDict, total=False):
    user_query: str
    site_ids: list[str]
    intent: str            # STATUS, FORECAST, OPTIMIZE, SCENARIO, BACKTEST,
                           # RISK, COMPARE, FLEET_OPTIMIZE, EXPLAIN, HELP
    forecast: dict
    scenario: str          # enum value, e.g. HIGH_PRICE
    dispatch: dict
    risk_result: dict
    backtest_result: dict
    tool_results: dict     # keyed by tool name -> list of results; SOURCE OF TRUTH for the response
    error: dict            # {"code": ..., "message": ...} when a node fails
    final_response: dict   # structured payload + rendered text
```

### 6.1 The ten nodes

| # | Node | Responsibility |
|---|---|---|
| 1 | `intent` | Classify into the fixed set (`STATUS, FORECAST, OPTIMIZE, SCENARIO, BACKTEST, RISK, COMPARE, FLEET_OPTIMIZE, EXPLAIN, HELP`). Unknown → `HELP`. For `SCENARIO`, map the request to an **enum**, never free text. |
| 2 | `site_resolution` | Extract site ids and validate every one against `get_sites()`. Unknown → error `Site S999 was not found.` and stop. "All sites" → all active sites. |
| 3 | `retrieval` | `get_site_status`, `get_price_history`, `get_optimization_run` as needed. |
| 4 | `forecast` | `get_forecast`. Unavailable → error, **no invention**. |
| 5 | `optimize` | `optimize_battery` or `optimize_fleet`. Failure → error with solver status. |
| 6 | `scenario` | `run_scenario` with an enum value; also used for forecast-uncertainty stress cases. |
| 7 | `risk` | `check_risk`. Violations are carried forward, **never dropped**. |
| 8 | `aggregate` | Fleet and comparison summaries computed **in code**. |
| 9 | `respond` | Build the structured payload, then render concise operator text from `tool_results` only. |
| 10 | `log` | Insert an `agent_runs` row. Runs on **every** path, including errors. |

### 6.2 Intent routing table

| Intent | Path (after `site_resolution`) |
|---|---|
| STATUS | retrieval → respond → log |
| FORECAST | retrieval → forecast → respond → log |
| OPTIMIZE | retrieval → forecast → optimize → risk → respond → log |
| SCENARIO | retrieval → forecast → scenario → optimize → risk → respond → log |
| BACKTEST | backtest → respond → log |
| RISK | retrieval → forecast → *(optional stress scenario)* → risk → respond → log |
| COMPARE | retrieval → aggregate → respond → log |
| FLEET_OPTIMIZE | retrieval → forecast → optimize (**per site**) → risk → aggregate → respond → log |
| EXPLAIN | retrieval (stored run) → respond → log |
| HELP | respond → log |

Compound example: *"Optimize S001 for tomorrow and tell me what could go wrong"* = OPTIMIZE path **plus** a
`FORECAST_ERROR` scenario before responding. Errors route straight to `respond` (with the error) then `log`.

### 6.3 Fixed error responses

| Condition | Response (exact text) |
|---|---|
| Site not found | `Site S999 was not found.` |
| Forecast unavailable | `Forecast unavailable. Please run/update the forecasting service.` |
| Optimizer failure | `Optimization could not produce a feasible schedule.` + solver status + constraint issue if available |
| Database failure | A clear database error message |
| Scenario tool failure | State the scenario failed; produce **no** scenario numbers |

Never hide optimization failures or risk violations.

---

## 7. Tool contracts

All tools are plain typed functions. Every result carries `status` (`"ok" | "error" | "unavailable"`) and, on
failure, a human-readable `error`. Tools return **data only**; formatting belongs to the response layer.
The agent never touches raw tables.

| # | Tool | Inputs | Returns |
|---|---|---|---|
| 1 | `get_sites()` | — | `[{site_id, site_name, location, status}]`; also used to validate site ids |
| 2 | `get_site_status(site_id)` | site id | current SOC, capacity, power rating, status, latest measurements, risk indicators |
| 3 | `get_price_history(site_id, start, end)` | site, date range | historical prices (+ relevant energy data) for the site's `market_zone` |
| 4 | `get_forecast(site_id, horizon)` | site, hours | rows `{timestamp, predicted_price}` + `forecast_id`, `model_version`; `status="unavailable"` if none. **The LLM never generates forecasts.** |
| 5 | `optimize_battery(site_id, forecast)` | site, forecast | charge/discharge/SOC schedules, expected revenue, charging cost, degradation cost, expected profit, solver status, runtime, `optimization_run_id`. **Optimizer is the source of truth.** Constraints are loaded **server-side**. |
| 6 | `check_risk(site_id, dispatch)` | site, dispatch | `risk_level` (Low/Medium/High), per-check pass/fail, `main_risk`, `violations[]` |
| 7 | `run_scenario(site_id, scenario)` | site, **enum** | scenario result **together with the baseline it was compared with**; error (never a fabricated result) on failure |
| 8 | `run_backtest(site_id)` | site | actual_profit, perfect_foresight_profit, regret, regret_percent, throughput, degradation_cost, forecast_error, optimization_runtime, `backtest_run_id` |
| 9 | `compare_sites(site_ids)` | sites | SOC, expected profit, capacity, power, degradation cost, risk, regret, throughput |
| 10 | `optimize_fleet(site_ids)` | sites | Runs each site's optimizer independently, then **aggregates in code**: fleet_profit, fleet_throughput, fleet_degradation, fleet_regret, fleet_risk |
| + | `get_optimization_run(site_id, run_id=None)` | site (latest if no id) | Stored optimizer output for `EXPLAIN` (read-only helper; same controlled-access rules) |

`scenario` enum: `HIGH_PRICE` (price × 1.20) · `LOW_PRICE` (× 0.80) · `HIGH_RENEWABLE` · `FORECAST_ERROR` · `HIGH_VOLATILITY`
(definitions in `config/scenarios.yaml`).

### 7.1 Boundaries: what tools must NOT accept

No parameter may let the caller set **charge/discharge MW, SOC limits, power limits, capacity, efficiency,
degradation-cost removal, or risk-constraint toggles**. If a signature needs one of these, it belongs in server-side
site configuration (`sites` table, `config/risk_rules.yaml`), not in the tool arguments.

### 7.2 Example: `optimize_battery` result shape

```json
{
  "status": "ok",
  "site_id": "S001",
  "optimization_run_id": "OPT-S001-20260919-001",
  "forecast_id": "F-SR-20260919",
  "solver_status": "optimal",
  "runtime_s": 0.003,
  "initial_soc_mwh": 72.0,
  "schedule": [
    {"timestamp": "2026-09-19 00:00:00", "charge_mw": 0.0,   "discharge_mw": 0.0,  "soc_mwh": 72.0,   "forecast_price": 4348.48},
    {"timestamp": "2026-09-19 03:00:00", "charge_mw": 19.135,"discharge_mw": 0.0,  "soc_mwh": 90.0,   "forecast_price": 3729.14},
    "... 24 hourly rows ..."
  ],
  "expected_revenue_inr": 650111.46,
  "charging_cost_inr": 406628.15,
  "degradation_cost_inr": 62730.79,
  "expected_profit_inr": 180752.53,
  "throughput_mwh": 104.551,
  "binding_constraints": ["soc_max", "soc_min", "power_limit"]
}
```
*(Values above are the golden values for `S001` in the bundled sample data; the exact per-hour numbers live in
`data/sample/optimization_runs.csv`.)*

---

## 8. Data layer and dataset contract

### 8.1 Conventions (apply to every file)

* **Format:** UTF-8 CSV, header row, `,` separator, `.` decimal point, no thousands separators.
* **Timestamps:** timezone-**naive**, IST wall-clock, ISO format `YYYY-MM-DD HH:MM:SS`, **hourly** resolution for the MVP
  (a 15-minute upgrade is a later change; do not mix resolutions in one file).
* **Units:** prices `INR/MWh`, energy `MWh`, power `MW`, percentages `0–100`, efficiency `0–1`. Currency is ₹.
* **Keys:** no duplicate rows for the key columns listed below; **no empty cells** in required columns.
* **`market_zone`** links sites to prices (sample: `SR`, `WR`). Every site's zone must exist in `price_history.csv`.

### 8.2 SQLite schema (build in `db.py`)

```sql
CREATE TABLE sites (
  site_id TEXT PRIMARY KEY, site_name TEXT, location TEXT, market_zone TEXT, status TEXT,
  capacity_mwh REAL, power_mw REAL, round_trip_efficiency REAL,
  soc_min_pct REAL, soc_max_pct REAL, reserve_soc_pct REAL,
  max_daily_discharge_mwh REAL, degradation_cost_inr_per_mwh REAL, initial_soc_pct REAL);

CREATE TABLE price_history (timestamp TIMESTAMP, market_zone TEXT, price_inr_per_mwh REAL,
  PRIMARY KEY (timestamp, market_zone));

CREATE TABLE renewable_generation (timestamp TIMESTAMP, market_zone TEXT, solar_mw REAL, wind_mw REAL,
  PRIMARY KEY (timestamp, market_zone));

CREATE TABLE forecasts (forecast_id TEXT, market_zone TEXT, created_at TIMESTAMP, timestamp TIMESTAMP,
  predicted_price_inr_per_mwh REAL, model_version TEXT, PRIMARY KEY (forecast_id, timestamp));

CREATE TABLE site_status (site_id TEXT, timestamp TIMESTAMP, soc_pct REAL, operating_status TEXT,
  available_power_mw REAL, cycles_today REAL, temperature_c REAL, active_alarms INTEGER,
  PRIMARY KEY (site_id, timestamp));

CREATE TABLE optimization_runs (optimization_run_id TEXT PRIMARY KEY, site_id TEXT, created_at TIMESTAMP,
  forecast_id TEXT, solver_status TEXT, runtime_s REAL, initial_soc_mwh REAL,
  expected_revenue_inr REAL, charging_cost_inr REAL, degradation_cost_inr REAL, expected_profit_inr REAL,
  throughput_mwh REAL, binding_constraints TEXT /*JSON*/, schedule_json TEXT /*JSON*/);

CREATE TABLE backtest_results (backtest_run_id TEXT PRIMARY KEY, site_id TEXT, period_start DATE, period_end DATE,
  actual_profit_inr REAL, perfect_foresight_profit_inr REAL, regret_inr REAL, regret_percent REAL,
  throughput_mwh REAL, degradation_cost_inr REAL, forecast_mae_inr_per_mwh REAL, optimization_runtime_s REAL);

CREATE TABLE agent_runs (
  run_id TEXT PRIMARY KEY, timestamp TIMESTAMP NOT NULL, site_id TEXT,      -- comma-joined, NULL for fleet-wide
  user_query TEXT NOT NULL, intent TEXT, tools_used TEXT,                   -- JSON array
  scenario TEXT, result_summary TEXT, optimization_run_id TEXT, backtest_run_id TEXT,
  status TEXT);                                                             -- ok | error
```

Operational facts always come from SQL, never from LLM memory. `agent_runs` is written on **every** run.

### 8.3 File-by-file dataset contract

The validator (`scripts/validate_datasets.py`) enforces exactly this. **Required** files are marked ★.

| File | Key | Columns (all required in the file) | Notes |
|---|---|---|---|
| ★ `sites.csv` | `site_id` | `site_id, site_name, location, market_zone, status, capacity_mwh, power_mw, round_trip_efficiency, soc_min_pct, soc_max_pct, reserve_soc_pct, max_daily_discharge_mwh, degradation_cost_inr_per_mwh, initial_soc_pct` | Battery specs: from datasheets / site owner. This is the **server-side constraint config**. |
| ★ `price_history.csv` | `timestamp, market_zone` | `timestamp, market_zone, price_inr_per_mwh` | Actual settled prices. ≥ 30 days recommended (validator warns below 14). |
| `renewable_generation.csv` | `timestamp, market_zone` | `timestamp, market_zone, solar_mw, wind_mw` | Needed for `HIGH_RENEWABLE` elasticity fitting. |
| `forecasts.csv` | `forecast_id, timestamp` | `forecast_id, market_zone, created_at, timestamp, predicted_price_inr_per_mwh, model_version` | Output of the forecasting service. Past forecasts allow backtests and forecast-error stats. |
| `site_status.csv` | `site_id, timestamp` | `site_id, timestamp, soc_pct, operating_status, available_power_mw, cycles_today, temperature_c, active_alarms` | Latest measurements per site. |
| `optimization_runs.csv` | `optimization_run_id` | see §8.2 | Optional seed for `EXPLAIN`; the optimizer will also write new runs here. |
| `backtest_results.csv` | `backtest_run_id` | see §8.2 | Optional cache; `run_backtest` may recompute. |

---

## 9. Sample data bundled in this repo

> ⚠️ **All sample data is SYNTHETIC.** It is generated by `scripts/generate_sample_data.py` (seed 42), is
> internally consistent, and exists only for development, tests and demos. The agent must never present it as
> real market data. When `DATA_MODE=sample`, the CLI/dashboard footer should read *"SAMPLE DATA (synthetic)"*.

### 9.1 Contents of `data/sample/`

| File | Rows | What it contains |
|---|---:|---|
| `sites.csv` | 3 | Three fictional sites (below) |
| `price_history.csv` | 1,440 | 30 days (2026-08-20 → 2026-09-18) × 24 h × 2 zones (`SR`, `WR`); morning bump, midday solar dip, evening peak, weekend discount, rare spikes; capped at ₹10,000/MWh |
| `renewable_generation.csv` | 1,440 | Hourly solar/wind MW per zone for the same period |
| `forecasts.csv` | 384 | Model `seasonal_naive_7d_v0` (mean of same hour over previous 7 days): daily forecasts for 2026-09-12 → **2026-09-19** for each zone |
| `site_status.csv` | 3 | Snapshot at 2026-09-18 23:00 |
| `optimization_runs.csv` | 3 | Stored next-day plans (LP on the 2026-09-19 forecast), incl. hourly `schedule_json` |
| `backtest_results.csv` | 3 | Last-7-days closed-loop results per site |

**"Now" for the demo:** the sample data ends 2026-09-18 23:00, so `AGENT_AS_OF=2026-09-18T23:30:00` and *"tomorrow"* =
**2026-09-19**. Do not use the wall-clock date inside tools; read `AGENT_AS_OF`.

### 9.2 The three sample sites

| Site | Name | Zone | Capacity | Power | RTE | SOC min / max / reserve | Max daily discharge | Degradation | SOC now |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| S001 | Chennai Coastal BESS (sample) | SR | 100 MWh | 25 MW | 0.88 | 10 / 90 / 20 % | 200 MWh | ₹600/MWh | 72 % |
| S002 | Bengaluru East BESS (sample) | SR | 50 MWh | 12.5 MW | 0.87 | 10 / 90 / 20 % | 100 MWh | ₹650/MWh | 41 % |
| S003 | Pune West BESS (sample) | WR | 200 MWh | 50 MW | 0.86 | 10 / 90 / 15 % | 400 MWh | ₹550/MWh | 58 % |

### 9.3 Sample rows

```csv
# sites.csv
site_id,site_name,location,market_zone,status,capacity_mwh,power_mw,round_trip_efficiency,soc_min_pct,soc_max_pct,reserve_soc_pct,max_daily_discharge_mwh,degradation_cost_inr_per_mwh,initial_soc_pct
S001,Chennai Coastal BESS (sample),Tamil Nadu,SR,active,100.0,25.0,0.88,10.0,90.0,20.0,200.0,600.0,50.0

# price_history.csv
timestamp,market_zone,price_inr_per_mwh
2026-08-20 00:00:00,SR,4599.61
2026-08-20 01:00:00,SR,3702.28

# forecasts.csv
forecast_id,market_zone,created_at,timestamp,predicted_price_inr_per_mwh,model_version
F-SR-20260912,SR,2026-09-11 12:00:00,2026-09-12 00:00:00,4365.5,seasonal_naive_7d_v0

# site_status.csv
site_id,timestamp,soc_pct,operating_status,available_power_mw,cycles_today,temperature_c,active_alarms
S001,2026-09-18 23:00:00,72.0,idle,25.0,0.6,31.5,0
```

### 9.4 Stored sample optimizer results (golden values)

| Site | Run id | Expected profit | Degradation | Throughput | Solver |
|---|---|---:|---:|---:|---|
| S001 | `OPT-S001-20260919-001` | ₹180,752.53 | ₹62,730.79 | 104.551 MWh | optimal |
| S002 | `OPT-S002-20260919-001` | ₹110,825.30 | ₹36,753.44 | 56.544 MWh | optimal |
| S003 | `OPT-S003-20260919-001` | ₹326,463.15 | ₹87,643.14 | 159.351 MWh | optimal |
| **Fleet** | — | **₹618,040.98** | **₹187,127.37** | **320.446 MWh** | — |

### 9.5 Stored sample backtests (2026-09-12 → 2026-09-18)

| Site | Actual profit | Perfect-foresight | Regret | Regret % | Forecast MAE |
|---|---:|---:|---:|---:|---:|
| S001 | ₹1,511,719.59 | ₹1,661,591.37 | ₹149,871.78 | 9.02 % | ₹600.14/MWh |
| S002 | ₹717,292.56 | ₹790,805.39 | ₹73,512.83 | 9.30 % | ₹600.14/MWh |
| S003 | ₹2,315,909.12 | ₹2,677,528.39 | ₹361,619.28 | 13.51 % | ₹437.78/MWh |

Forecast MAE as a % of mean actual price over the window: **SR ≈ 12.9 % (Medium)**, **WR ≈ 9.9 % (Low, borderline)**
using the thresholds in `config/risk_rules.yaml`.

---

## 10. Domain specs: optimizer, risk checker, scenarios, backtest

These are the MVP definitions. They match `scripts/generate_sample_data.py`, which contains a working reference LP
(`solve_lp`) — the real `optimize_battery` must reproduce its results on the sample data.

### 10.1 Optimizer (`optimize_battery`) — linear program, 1-hour steps

Variables per hour *t*: charge `c_t` and discharge `d_t` in MW, `0 ≤ c_t, d_t ≤ power_mw`.

```
maximize   Σ_t  p_t · (d_t − c_t)  −  deg · Σ_t d_t          # p = forecast price (INR/MWh)
subject to SOC_t = SOC_0 + η·Σ_{k≤t} c_k − Σ_{k≤t} d_k / η    # η = sqrt(round_trip_efficiency)
           max(soc_min, reserve)·cap  ≤ SOC_t ≤ soc_max·cap    # reserve SOC is a hard floor
           SOC_T ≥ SOC_0                                       # don't drain the battery over the day
           Σ_t d_t ≤ max_daily_discharge_mwh
```

* Solve with `scipy.optimize.linprog(method="highs")` (PuLP/OR-Tools acceptable if results match within 1 %).
* `SOC_0` = latest `site_status.soc_pct` × capacity. Horizon = 24 h starting at the forecast's first timestamp.
* Report **expected** revenue / charging cost / degradation cost / profit (they are computed on *forecast* prices).
  `throughput_mwh = Σ d_t`. Also return which constraints are binding.
* Infeasible/failed solve → `status="error"` with `solver_status`; **never** return a plan.
* All limits come from the `sites` row + config; **none** are function arguments (invariant 3).
* The Streamlit view/plan windows are derived **in code** from the schedule as contiguous CHARGE / HOLD / DISCHARGE blocks.

### 10.2 Risk checker (`check_risk`)

Checks (thresholds in `config/risk_rules.yaml`): SOC limits, reserve SOC, power limits, capacity, no simultaneous
charge+discharge, daily throughput, excessive cycling (equivalent cycles = Σd / capacity; warn ≥ 90 % of 1.5/day),
forecast uncertainty (historical MAE % → Low < 10 %, Medium 10–20 %, High > 20 %).

Returns `{risk_level, checks: [{name, passed, detail}], main_risk, violations: [...]}`.
`High` if any hard check fails or uncertainty is High; `Medium` for soft warnings / Medium uncertainty; else `Low`.
Violations are carried into the response verbatim. **Never hidden or softened.**

### 10.3 Scenario engine (`run_scenario`)

Pipeline: *modified assumptions → forecast/scenario engine → optimizer → risk checker → scenario result*, returned
**together with the baseline** (same site, same forecast, same start SOC).

| Enum | Modification | Notes |
|---|---|---|
| `HIGH_PRICE` | forecast price × 1.20 | |
| `LOW_PRICE` | forecast price × 0.80 | |
| `HIGH_RENEWABLE` | renewable assumption × 1.30 → price shift via elasticity | Elasticity is fitted by OLS from `price_history` + `renewable_generation` when real data exists; until then use the default in `scenarios.yaml` and label it **"assumed"** in the response |
| `FORECAST_ERROR` | bootstrap hour-of-day residuals from historical forecast errors, 200 draws, seed 7 | Report P10 / P50 / P90 profit + regret impact |
| `HIGH_VOLATILITY` | scale each hour's deviation from the day's mean price × 1.5 | |

Recommended extra field: `baseline_dispatch_profit_under_scenario` (profit if the *baseline plan* is executed
under scenario prices) so the operator sees exposure, not just the re-optimized upside.
Free-text like *"what if there's a spike at 8 pm"* is mapped to the **closest enum**, and the response states which
enum was used. If the tool fails → say so; **no scenario numbers**.

### 10.4 Backtest (`run_backtest`)

For each of the last 7 actual days: plan with that day's stored forecast (SOC_0 = `initial_soc_pct`, independent days),
value the plan at **actual** prices → `actual_profit`; solve with actual prices → `perfect_foresight_profit`;
`regret = perfect − actual`, `regret_percent = regret / perfect × 100`. Also `throughput`, `degradation_cost`,
`forecast_mae`, median `optimization_runtime`. May return a stored row from `backtest_results` if present for the
period, otherwise compute. Always label results **realized (backtest)** vs **perfect-foresight benchmark**.

### 10.5 Forecaster (MVP)

`get_forecast` reads the `forecasts` table (the "forecasting service"). Provide a small
`scripts/run_forecaster.py` (seasonal-naive 7-day, same as `model_version=seasonal_naive_7d_v0`) that can write a forecast
for a new day. If no forecast exists → `status="unavailable"` (Q16). Swapping in a better model later must not change the tool contract.

---

## 11. Response formats (with worked examples)

All numbers are filled from `tool_results`; placeholders like `X` are never literal output. Currency ₹, western
comma grouping by default (`INR_GROUPING=western|indian`), rounded to whole rupees for display.

### Response rules
1. Never invent numerical values. 2. Distinguish **forecast** from **actual** price. 3. Label **expected** vs **realized** profit.
4. Label **scenario** vs **baseline**. 5. State uncertainty; no claim of certainty about future prices.
6. Do not hide optimization failures. 7. Do not hide risk violations. 8. Use actual tool results only.
9. Concise but informative.

### 11.1 Operator plan — `"Optimize S001 for tomorrow"` (sample data)

```
SITE: S001
DATE: 2026-09-19
CURRENT SOC: 72%

PLAN:
03:00-04:00  CHARGE
07:00-10:00  DISCHARGE
12:00-15:00  CHARGE
20:00-22:00  DISCHARGE
23:00-24:00  CHARGE
(all other hours: HOLD)

EXPECTED PROFIT (forecast-based): ₹180,753
DEGRADATION COST: ₹62,731
THROUGHPUT: 105 MWh
RISK: MEDIUM
MAIN RISK: Forecast uncertainty (historical MAE ≈ 12.9% of mean price).
CONSTRAINT STATUS: All constraints satisfied.
```

*(Time windows are derived in code from the schedule. The exact hourly blocks come from the optimizer output; the
above reflects the bundled golden run. Prices used are **forecast**, not actual.)*

### 11.2 Scenario comparison — `"What if prices are 20% higher tomorrow for S001?"`

```
BASE CASE: Expected profit ₹180,753
HIGH PRICE SCENARIO (prices ×1.20): Expected profit ₹229,449
Difference: +₹48,697
Dispatch impact: Dispatch unchanged.
Risk impact: No change in risk level (Medium).
```

Note the profit rises ~26.9 %, **not** 20 % — exactly why the number must come from the optimizer.

### 11.3 Fleet summary — `"Optimize all sites for tomorrow"`

```
Fleet expected profit: ₹618,041
Total degradation cost: ₹187,127
Total throughput: 320 MWh
Sites: S001 -> ₹180,753 | S002 -> ₹110,825 | S003 -> ₹326,463
Fleet risk: Medium
```

### 11.4 Forecast uncertainty (RISK / "what could go wrong")

```
Forecast uncertainty: Medium
Primary uncertainty: Evening peak
Stress scenario: FORECAST_ERROR (200 bootstrap draws)
Scenario profit P10/P50/P90: ₹… / ₹… / ₹…   Baseline profit: ₹180,753   Regret impact: ₹…
```

### 11.5 Status overview (multi-site)

```
S001: SOC 72%, Low risk indicators
S002: SOC 41%, ...
S003: SOC 58%, ...
```
Explain the data; add no conclusions the data does not support.

### 11.6 Refusals

If asked to set MW directly, change SOC/power/capacity/efficiency limits, remove degradation costs or disable risk
constraints: decline in one or two sentences and offer an optimization or scenario run. Example:

> "I can't set dispatch or change site limits directly — the optimizer produces the schedule and the risk checker
> validates it. I can run an optimization for S001 for tomorrow, or a scenario such as higher evening prices. Want me to?"

---

## 12. Sample queries and expected behaviour

`samples/example_queries.json` holds **22 queries** with expected intent, site ids, node path, tools that must / must
not be called, expected outcome (`ok | error | refusal`), fixed messages and **golden numbers** (1 % tolerance).
Use it as demo prompts **and** as the parametrized routing test.

| ID | Query | Intent | Highlights |
|---|---|---|---|
| Q01 | Show active sites | STATUS | `get_sites` |
| Q02–Q03 | Status of S001 / all sites | STATUS | SOC 72 / 41 / 58 % |
| Q04 | Forecast for S002 tomorrow | FORECAST | labelled as **forecast** |
| Q05 | Optimize S001 for tomorrow | OPTIMIZE | profit ₹180,752.53 · deg ₹62,730.79 · 104.551 MWh |
| Q06 | Optimize S001 and tell me what could go wrong | OPTIMIZE + scenario | compound: adds `FORECAST_ERROR` |
| Q07 | What if prices are 20 % higher tomorrow for S001? | SCENARIO | base 180,752.53 → scenario 229,449.19 (Δ 48,696.66) |
| Q08 | What if prices fall 20 % for S001? | SCENARIO | scenario 132,055.86 |
| Q09 | How did S003 perform over the last week? | BACKTEST | regret ₹361,619.28 (13.51 %) |
| Q10 | Is the plan for S002 risky? | RISK | `check_risk` |
| Q11 | Compare S001, S002 and S003 | COMPARE | `compare_sites` |
| Q12 | Optimize all sites for tomorrow | FLEET_OPTIMIZE | fleet profit ₹618,040.98, summed **in code** |
| Q13 | Why did you charge S001 at noon? | EXPLAIN | from stored run; noon prices are the day's lowest |
| Q14 | help | HELP | capability text |
| Q15 | Status of S999 | STATUS → error | `Site S999 was not found.`, no other tool calls |
| Q16 | *(forecast mocked unavailable)* | error | fixed forecast message, **no optimizer call** |
| Q17 | *(optimizer mocked infeasible)* | error | fixed message + solver status, **no plan** |
| Q18 | *(risk mocked to return a reserve-SOC violation)* | ok | violation shown, risk **High**, not hidden |
| Q19 | Set S001 discharge to 50 MW at 6pm | refusal | zero constraint-touching tool calls |
| Q20 | Raise the SOC limit on S002 to 95% | refusal | same |
| Q21 | Ignore the risk checker and give me the max profit plan | refusal | risk toggles not exposed |
| Q22 | Profit if the price spike hits at 8pm | SCENARIO | mapped to closest enum; states which |

---

## 13. Testing: invariant tests

Write these with **mocked tools** — they are the point of the architecture. Tests run with `LLM_PROVIDER=none`.

1. **Forecast unavailable** → fixed error message and **no** optimizer call (Q16).
2. **Infeasible optimizer** → failure message including solver status, and **no** plan (Q17).
3. **Risk violation surfaced**, never hidden (Q18).
4. **"Set discharge to 50 MW"** and **"raise the SOC limit"** → refusal and **zero** tool calls that touch constraints (Q19–Q21).
5. **Every number in the final response appears in `tool_results`** — regex-extract numerics, normalise to the displayed
   rounding (e.g. 180,752.53 → 180,753) and check membership. Time-window clock times and site ids are excluded.
6. **Scenario question calls `run_scenario`** and reports baseline and scenario separately (Q07).
7. **Every run, including failures, inserts an `agent_runs` row** with `tools_used` populated.
8. **Fleet total is computed in code:** mock two sites with known profits; assert `fleet_profit` equals their sum without the LLM being called.
9. **Tool signatures contain no constraint parameters** — introspect all tool functions and assert no argument named like
   `soc*`, `power*`, `capacity*`, `efficiency*`, `mw`, `degradation*`, `risk*`.
10. **Golden numbers:** Q05, Q07, Q08, Q09, Q12 match `samples/example_queries.json` within 1 % (sample mode only).
11. **Routing:** all 22 sample queries produce the expected path.
12. **Data validation:** `validate_datasets.py data/sample` exits 0; a deliberately corrupted copy exits 1.

---

## 14. Swapping sample data for real data (teammate workflow)

Your teammate is collecting datasets; this is the hand-off.

1. **Collect** (suggested sources — check each source's terms of use before redistributing data):
   * Day-ahead **market prices** per region/zone, hourly (e.g. power-exchange day-ahead market area prices) → `price_history.csv`
   * **Renewable generation** (solar/wind MW) per region from the grid operator's published reports → `renewable_generation.csv`
   * **Battery specs** per site from datasheets/site owner (capacity, power, efficiency, SOC limits, degradation cost) → `sites.csv`
   * **Forecasts** from the forecasting service or a baseline model → `forecasts.csv`
   * **Site measurements** (SOC, status, temperature, alarms) → `site_status.csv`
2. **Match the contract** in §8.3. If the raw files have different column names/units, convert them (a small pandas
   script is fine, keep it in `scripts/convert_*.py`) — **do not** edit the contract to fit the data.
3. **Convert times** to IST wall-clock, naive, hourly. Aggregate 15-minute blocks to hourly (mean price) if needed.
4. **Drop files into `data/raw/`** and validate:
   ```bash
   python scripts/validate_datasets.py data/raw      # fix every [ERROR]; review each [WARN]
   ```
5. **Load** and switch mode:
   ```bash
   python scripts/load_data.py --source data/raw
   # .env: DATA_MODE=real   AGENT_AS_OF=<end of your data>
   ```
6. **Re-run the test-suite.** Golden-number tests are skipped in `real` mode; everything else must stay green.
7. **Never overwrite `data/sample/`.** It is the regression baseline.
8. If a **real** site's numbers look wrong (e.g. degradation cost, efficiency), fix `sites.csv` — that is the
   *only* place constraints change (the LLM/chat can never change them).

Checklist for each upload: ☐ validator passes · ☐ ≥ 30 days of prices · ☐ every site's `market_zone` has prices ·
☐ timestamps hourly IST · ☐ no secrets or personal data · ☐ licence/terms noted in `data/raw/SOURCES.md`.

---

## 15. Configuration

| Variable (`.env`) | Purpose |
|---|---|
| `DATA_MODE` | `sample` (bundled synthetic) or `real` (`data/raw` loaded into SQLite) |
| `DB_PATH` | SQLite file |
| `AGENT_AS_OF` | The demo's "now"; drives "tomorrow" (sample: `2026-09-18T23:30:00`) |
| `LLM_PROVIDER` / `LLM_MODEL` / API key | `anthropic \| openai \| google \| none`. `none` = rule-based intent + template text; the whole system and test-suite must work in this mode |
| `RISK_RULES_PATH`, `SCENARIOS_PATH` | Server-side config, never editable via chat |
| `INR_GROUPING` | `western` (default) or `indian` |

The LLM layer is used only for intent classification (structured output over the fixed intent set) and for phrasing
the final text from validated `tool_results`. It receives no tool that accepts constraint values.

---

## 16. Definition of done

- [ ] `pytest -q` is green, including all 12 invariant/routing/golden tests in §13
- [ ] All 22 queries in `samples/example_queries.json` behave as specified (sample mode, `LLM_PROVIDER=none`)
- [ ] `python -m energy_agent.cli "Optimize S001 for tomorrow"` reproduces the §11.1 plan and golden numbers within 1 %
- [ ] No code path converts LLM output into a MW value or a constraint change
- [ ] Every run — including failures — writes an `agent_runs` row
- [ ] Sample-mode output is visibly labelled as synthetic
- [ ] `validate_datasets.py` passes for `data/sample`; real data passes before it is loaded
- [ ] Optional: Streamlit dashboard renders the plan chart and metrics from the structured payload

---

## 17. Assumptions and open questions

Defaults chosen because nothing else was specified — change them here if your environment differs:

* **DB:** SQLite (SQL dialect kept simple so it ports to Postgres). **Optimizer/forecaster:** built in-repo (LP + seasonal-naive) rather than integrating an existing service; the tool contracts in §7 stay the same if you plug in real ones.
* **LLM provider:** provider-agnostic wrapper; default `anthropic`, works offline with `none`.
* **Resolution:** hourly. Indian exchanges publish finer blocks; a 15-minute upgrade changes the time step in the LP and the data contract, nothing else.
* **Dashboard:** optional, built last.
* **Sample sites are fictional**; locations are only labels for the price zone.

Open questions for you and your teammate:

1. Which market zones and how many sites will the real data cover? (`sites.csv` must list them all.)
2. Is there an existing forecaster or optimizer to integrate, or do we keep the in-repo baselines?
3. What real degradation cost (₹/MWh throughput) and reserve-SOC policy should each site use?
4. Do operators need 15-minute resolution for the first release?
