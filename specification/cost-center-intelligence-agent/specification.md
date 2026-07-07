# Specification: cost-center-intelligence-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read `product-requirements-document.md` and `intent.md` for full context
- [ ] Bootstrap agent code in `assets/cost-center-intelligence-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/cost-center-intelligence-agent/`, use copy commands — do NOT create files manually)
- [ ] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## MCP Server Integration (Path B — Existing MCP Server)

The CE_COSTCENTER_0001 MCP server is confirmed by the user. No API spec download or translation file needed.

- [ ] Wire MCP tool loading in `app/agent.py` using `get_mcp_tools()` from `mcp_tools.py` — see `../guidelines-agent.md` for canonical pattern. NEVER create direct HTTP clients (`requests`, `httpx`, OData client) for SAP APIs.
- [ ] Add the CE_COSTCENTER_0001 MCP server dependency to `assets/cost-center-intelligence-agent/asset.yaml`:
  ```yaml
  requires:
    - name: CE_COSTCENTER_0001
      kind: mcp-server
      ordId: sap.s4:apiResource:CE_COSTCENTER_0001:v1
  ```
- [ ] Generate `mcp-mock.json` using the `mcp-mock-config` skill. The mock must include at least two tools for the CE_COSTCENTER_0001 server:
  - `count_cost_centers` — returns a count of active cost centers (e.g. `{"count": 42}`)
  - `list_top_cost_centers` — returns a ranked list of the top N cost centers (e.g. `[{"CostCenter": "CC001", "CostCenterName": "IT Operations"}, ...]`)

## Agent System Prompt & Business Logic

- [ ] In `app/agent.py`, write the system prompt for the `@prompt_section` decorator. The prompt MUST:
  - Identify the agent as a Finance Cost Center Intelligence assistant
  - State the two supported queries: (1) count all active cost centers, (2) list the top 5 cost centers
  - Instruct the agent NEVER to hallucinate data — always call a tool
  - Instruct the agent to set `top` (or equivalent page-size parameter) to a maximum of 100 on every tool call that accepts it
  - Instruct the agent to inform the user if the result is capped at 100
  - Instruct the agent to politely decline out-of-scope queries (e.g. payroll, purchasing)
  - Instruct the agent to maintain session context for follow-up questions (M5)
- [ ] Implement the agent graph in `app/agent.py` using `from langchain.agents import create_agent` — NEVER use `create_react_agent`
- [ ] Load tools lazily in `_get_tools()` (not in `__init__`) via `get_mcp_tools()` from `mcp_tools.py`
- [ ] Extract all business logic from `stream()` into `_run_agent()` helper — NO `with tracer.start_as_current_span(...)` inside any `async def` that contains `yield`

## Business Step Instrumentation (Milestones)

Instrument `_run_agent()` with the following five milestones. Each must emit a structured log on achievement AND on miss. Use `with tracer.start_as_current_span(...)` inside `_run_agent()` (non-generator):

- [ ] **M1 — Query Received**
  - Log on achievement: `M1.achieved: query received from user`
  - Log on miss: `M1.missed: no query input received`
- [ ] **M2 — Intent Understood**
  - Log on achievement: `M2.achieved: intent classified, tool selected`
  - Log on miss: `M2.missed: intent classification failed or ambiguous`
- [ ] **M3 — Data Retrieved**
  - Log on achievement: `M3.achieved: cost center data retrieved from MCP server`
  - Log on miss: `M3.missed: MCP server call failed or returned empty data`
- [ ] **M4 — Answer Delivered**
  - Log on achievement: `M4.achieved: answer delivered to user`
  - Log on miss: `M4.missed: response formatting or delivery failed`
- [ ] **M5 — Follow-Up Handled**
  - Log on achievement: `M5.achieved: follow-up query resolved in session`
  - Log on miss: `M5.missed: follow-up query could not be resolved or session lost`
- [ ] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## Agent Decorator Constraints

- [ ] `app/agent.py` has exactly 3 decorated functions: `@agent_model`, `@agent_config` (temperature only), `@prompt_section`
- [ ] Run `grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/cost-center-intelligence-agent/app/agent.py` — must return `3`
- [ ] All other configuration values (e.g. top-N limit = 5) are plain Python constants, NOT decorated

## Testing

- [ ] `conftest.py` only sets `IBD_TESTING=1` and monkey-patches `mcp_tools.get_mcp_tools` — no changes to application code
- [ ] Write unit tests in `assets/cost-center-intelligence-agent/tests/`:
  - [ ] `test_count_cost_centers.py` — patches `get_mcp_tools`, mocks LLM, asserts the count tool is called and count is returned
  - [ ] `test_list_top_cost_centers.py` — patches `get_mcp_tools`, mocks LLM, asserts the list tool is called and top 5 returned
- [ ] Write `tests/test_integration.py` — end-to-end agent flow: mock LLM + mock MCP tools, submit "how many cost centers?", assert a numeric answer is returned
- [ ] Run `pytest` from `assets/cost-center-intelligence-agent/` (no args)
- [ ] If coverage < 70%, add targeted tests and re-run
- [ ] Final `pytest` run (no args) must produce `test_report.json` in `assets/cost-center-intelligence-agent/`

## Cleanup

- [ ] Delete the template runtime skill: `rm -rf assets/cost-center-intelligence-agent/app/skills/template-skill/`

## Validation

Run before marking implementation complete:

```bash
grep -r "M[0-9]\.achieved" assets/cost-center-intelligence-agent/app/
grep -r "sap_cloud_sdk.agent_decorators" assets/cost-center-intelligence-agent/app/
grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/cost-center-intelligence-agent/app/agent.py
ls assets/cost-center-intelligence-agent/test_report.json
```
