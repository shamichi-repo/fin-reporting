# Agent Guidelines

Technical constraints and patterns for building Pro-Code AI Agents. Follow these throughout specification execution.

## Tech Stack

- Python 3.13
- Agent framework defined in the `sap-agent-bootstrap` skill
- Agent2Agent (A2A) protocol
- Local execution only (in-memory storage, no deployment)

## Project Structure

- Asset root: `assets/<asset-name>/`
- Required structure: `asset.yaml`, `app/`
- Full layout from project root: `solution.yaml`, `assets/<asset-name>/asset.yaml`, `assets/<asset-name>/app/`
- `asset.yaml` must use `buildPath: .` and `/.well-known/agent.json` for all health probes
- Follow the `sap-agent-bootstrap` skill for project scaffolding — invoke directly from `assets/<asset-name>/`, use copy commands

## Key Constraints

- When working with LangChain or LangGraph, you MUST NEVER use the `create_react_agent` function (`from langgraph.prebuilt import create_react_agent`) as it has been deprecated in LangChain 1.0. Instead, you should use the `from langchain.agents import create_agent` function.
- **NEVER call SAP APIs directly** (no `requests`, `httpx`, or hand-rolled OData clients). All SAP API consumption MUST go through MCP servers. The agent consumes them as tools, never as raw HTTP calls (regardless of whether it's an existing MCP Server or a new MCP Server created by the `mcp-translation-file` skill).
- Only use public APIs; mock any private systems (like S/4HANA) with minimal mock data
- AI Core is available at **runtime** via LiteLLM (environment variables provided at deployment) but is **NOT available during tests** — all LLM calls must be mocked
- No Git operations, no authentication, no documentation/READMEs
- Update `requirements.txt` for any new dependencies
- Never modify `sys.path`
- Map SAP Joule Studio/Skills concepts to standard agent tools
- No `.env` files (environment variables supplied at runtime)

## Code Quality

- All Python code must compile with valid imports
- No `src.` import patterns
- All function parameters must be used in function body

## Agent Decorators

- The bootstrap template already includes decorator scaffolding — no separate skill invocation needed
- **NEVER add new decorated functions to `app/agent.py`** — the three from the bootstrap template (`@agent_model`, `@agent_config` for temperature, `@prompt_section`) are the complete and final set. `@agent_config` is not a general-purpose decorator; it exposes parameters to the SAP platform UI and is intentionally limited to temperature. All other values (thresholds, limits, counts, etc.) must be plain Python constants.
- Never mark decorator tasks complete until `sap_cloud_sdk.agent_decorators` imports exist in `app/agent.py`

## Agent Instrumentation

- ALL business logic steps MUST be instrumented with proper logging and OpenTelemetry spans
- Use milestones from the PRD's "Milestones" section (if available) or derive from the project input for business step instrumentation
- Each milestone must emit structured log statements on achievement and miss
- Log pattern: `[MILESTONE_ID].[achieved|missed]: [description]`
- Add OpenTelemetry custom spans for each business step using `tracer.start_as_current_span` — use the **decorator form** (`@tracer.start_as_current_span("name")`) on regular async methods, or the **context manager form** (`with tracer.start_as_current_span("name"):`) inside non-generator async functions
- **NEVER use `with tracer.start_as_current_span(...)` as a context manager inside an async generator** (i.e. any method containing `yield`). Doing so causes `ValueError: Token was created in a different Context` when the generator is closed via `GeneratorExit`. For `stream()`, extract all business logic into a plain async helper method (e.g. `_run_agent()`) and instrument that helper instead, then call it from `stream()` and yield the result outside any span context.
- Ensure `auto_instrument()` is called at top of `main.py` before any AI framework imports

## MCP Tool Integration

All SAP API integrations MUST use this pattern. If the PRD or specification references any SAP API (OData, REST, events), MCP wiring is mandatory, not optional.

MCP tool names are prefixed with an MCP server identifier at runtime (e.g. `mcp_myserver__get_items`). **Never hard-code tool names in code.** Retrieve tools dynamically via `get_mcp_tools()` and let the agent resolve them by capability, not by name.

When writing system instructions for the agent, explicitly instruct the agent not to hallucinate data. The system prompt MUST always instruct the agent to set `top` (or equivalent page-size parameter) to a maximum of 100 on every tool call that accepts it — regardless of whether the user requested a limit — to prevent context overflow. The agent must inform the user when this limit is applied.

## Runtime Skills

If the agent requires more complex task specific instructions or resources (multi-step workflows, domain-specific instruction, reference material) that don't belong in the system prompt, create them as runtime skills under `app/skills/<skill-name>/SKILL.md` (frontmatter `name` + `description`, body is the instructions). Skills can also ship companion asset files alongside the `SKILL.md` (e.g. `app/skills/<skill-name>/references/foo.md`, templates, JSON examples). The agent loads all runtime skills and their asset files on demand via the `load(path)` tool — no extra wiring needed.

### Canonical Pattern

```python
from mcp_tools import get_mcp_tools

async def _load_tools() -> list:
    return await get_mcp_tools()
```

`mcp_tools.py` is the owned indirection layer produced by the bootstrap — import from there, never directly from `sap_cloud_sdk.agentgateway`. This is the target the test fixture patches.

Call `_load_tools()` lazily (not in `__init__`) — it makes network calls. Wire the result into the agent graph:

```python
class MyAgent:
    def __init__(self):
        self._tools = None

    async def _get_tools(self) -> list:
        if self._tools is None:
            self._tools = await _load_tools()
        return self._tools

    async def stream(self, query, context_id, ext_impl=None):
        tools = await self._get_tools()
        graph = self._build_graph(tools, system_prompt=get_system_prompt())
        ...
```

### Local Testing (IBD_TESTING)

**Do NOT branch on `IBD_TESTING` in application code.** The `conftest.py` monkey-patches `mcp_tools.get_mcp_tools` before any agent code runs. Agent code stays identical in production and tests.

The patch returns `StructuredTool` instances built from `mcp-mock.json`. Generate `mcp-mock.json` with the `mcp-mock-config` skill before running tests.

## Testing

Working directory for all test operations: `assets/<asset-name>/` (asset root).

### Setup

1. Install test dependencies: `pip install -r requirements-test.txt`

### Boilerplate Files

- `conftest.py` — shared fixtures, custom markers, writes `test_report.json` on full runs
- `pytest.ini` — configures test discovery (`prebuilt_tests/`, `tests/`), default flags, markers
- `requirements-test.txt` — test dependencies
- `prebuilt_tests/` — pre-built structure and server tests; NEVER modify these

### Writing Tests

- All generated tests go in `assets/<asset-name>/tests/` (NOT inside `app/`)
- Unit tests: exactly one per tool; run each immediately after writing
- Integration test: one end-to-end test exercising the full agent graph
- **AI Core / LLM calls MUST be mocked in all tests.** AI Core credentials are NOT available in the test environment. Patch the LLM (e.g. `ChatLiteLLM`) to return canned responses. Never make real network calls to AI Core during tests.
- Mock all external systems (S/4HANA, MCP servers, AI Core) — tests must run offline

### Running Tests

- ALWAYS invoke as just `pytest` from asset root — no paths, no `--cov`, no `--json-report`, no extra flags
- `pytest.ini` configures everything; extra CLI flags conflict with ini settings
- Only exception: targeting a single test: `pytest path/to/test_file.py::test_name`
- Coverage must be ≥ 70%; if below, add targeted tests until threshold met
- Final `pytest` run (no args) MUST produce `test_report.json` — this only happens on full runs without arguments

## Validation Checklist

Run these verifications before marking implementation complete:

```bash
# Instrumentation
grep -r "M[0-9]\.achieved" assets/<asset-name>/app/     # must return results

# Decorators
grep -r "sap_cloud_sdk.agent_decorators" assets/<asset-name>/app/  # must return results
grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/<asset-name>/app/agent.py  # must return 3

# Test report
ls assets/<asset-name>/test_report.json                  # must exist
```

## MCP Translation Files, MCP Servers & Mock Tools (Post-Implementation)

After all asset spec TODO items are complete, run the applicable path(s):

### Path A — API spec files (OData/REST, no existing MCP server)

Run when `specification/<asset-name>/api-specs/` contains API spec files.

1. **MCP Translation Files:** Invoke the `mcp-translation-file` skill.
2. **MCP Server Assets:** Invoke the `setup-solution` skill to create MCP server assets.

### Path B — MCP spec files (existing MCP server with known ORD ID)

Run when `specification/<asset-name>/mcp-specs/` contains `mcp-spec-*.json` files.

No translation or MCP server asset creation needed — the MCP server already exists externally.

### MCP Server Dependencies in asset.yaml

For **every** MCP server the agent uses, add a corresponding entry to the agent's `asset.yaml` under `requires`:

```yaml
requires:
  - name: <mcp-server-name>
    kind: mcp-server
    ordId: <ord-id>
    version: <version>  # optional — omit if not available
```

### Mock MCP Configuration

After confirming MCP servers, invoke the `mcp-mock-config` skill to generate `mcp-mock.json`.

## Agent Evaluation (Post-Implementation)

Run after all tests pass and the agent is working locally.

1. Invoke `sap-aeval-generate-tool-schema` skill from asset root to produce `tools.json`.
2. Invoke `sap-aeval-generate-testcase` skill passing PRD file path and `tools.json`.
