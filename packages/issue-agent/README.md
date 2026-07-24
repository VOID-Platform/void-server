# VOID Issue Agent

Converts an evaluated AI incident into an engineering-ready GitHub Issue.

The Evaluator answers *"What happened?"* — the Issue Agent answers *"Where is the likely bug and what should engineering investigate first?"*

---

## Logic Flow (End to End)

```
Incident Snapshot (JSON)
        │
        ▼
  Evidence Extractor    ── extracts failed tool calls per failure mode
        │
        ▼
  PydanticAI Agent      ── 4 tools: search_repo, read_file, build_code_graph, create_issue
        │
        ├── Repository Investigator  (search → graph → read → analyze)
        └── Report Writer           (structured EngineeringReport)
        │
        ▼
  Engineering Report (JSON)
        │
        ▼
  GitHub Issue          (skipped in dev mode)
```

### Step 1: Load & Parse Incident Snapshot

The entry point (`__main__.py`) reads JSON from stdin, validates it into an `IncidentSnapshot`:

```python
raw = json.loads(sys.stdin.read())
snapshot = IncidentSnapshot.model_validate(raw)
```

The snapshot contains the execution trace (agent steps + tool calls), evaluation result (failure modes, severity, confidence), and telemetry.

### Step 2: Extract Evidence (`evidence.py`)

Walks every failure mode and collects failed tool calls from the trace:

```python
def extract_evidence(snapshot: IncidentSnapshot) -> list[Evidence]:
    for fm in snapshot.evaluation.failure_modes:
        trace_lines = []
        for step in snapshot.execution_trace.agent_steps:
            for tc in step.tool_calls:
                if not tc.success:
                    trace_lines.append(f"Tool '{tc.name}' failed: {tc.error or 'unknown error'}")
```

Output: one `Evidence` per failure mode — failure mode name, summary, supporting trace lines, confidence score.

### Step 3: Build Agent Input

The `run_issue_agent()` function in `agent.py` serializes the snapshot + evidence into a single JSON blob the LLM receives as the user prompt:

```python
input_data = {
    "incident_id": snapshot.incident_id,
    "failure_modes": snapshot.evaluation.failure_modes,
    "confidence": snapshot.evaluation.confidence,
    "reasoning": snapshot.evaluation.reasoning,
    "severity": snapshot.evaluation.severity,
    "evidence": [e.model_dump() for e in evidence],
    "timeline": [t.model_dump() for t in timeline],
    "agent_steps": [{"step_type": s.step_type, "tool_calls": ..., "planner_output": s.planner_output, "context": s.context, "latency_ms": s.latency_ms}],
    "model": snapshot.execution_trace.model,
    "tokens_used": snapshot.execution_trace.tokens_used,
    "total_latency_ms": snapshot.execution_trace.total_latency_ms,
    "telemetry": snapshot.telemetry,
    "metadata": snapshot.metadata,
}
```

### Step 4: LLM Agent Loop (`agent.py`)

A single `Agent` with typed `EngineeringReport` output and 4 tools:

```python
agent = Agent(
    model="google:gemini-3.1-flash-lite",
    output_type=EngineeringReport,
    system_prompt="You are a senior engineer investigating an AI system incident...",
)
```

The system prompt instructs the LLM to:
1. Review the incident snapshot
2. Use repository tools to find relevant code
3. Search for symbols/filenames from the trace
4. Build code graphs around suspected files
5. Read only the functions needed to understand the bug
6. Write an **EngineeringReport** with all fields populated

**Tools registered on the agent:**

| Tool | Purpose |
|---|---|
| `search_repo(query)` | Find files matching a symbol/name |
| `read_file(path)` | Read file contents from the repo (truncated at 50KB) |
| `build_code_graph(file_paths)` | Parse imports → dependency graph |

**Dev Mode:** Set `VOID_DEV_MODE=1` — `create_github_issue` tool is not registered, agent returns the report as JSON only. The repo also switches from `GitHubRepo` (GitHub API) to `LocalRepo` (local filesystem):

```python
repo = LocalRepo() if os.environ.get("VOID_DEV_MODE") else GitHubRepo()
```

**Retry logic:** Catches `ModelHTTPError(status_code=429)` from Gemini's rate limiter. Parses `retryDelay` from the error body (nested in `error.details[*].retryDelay`), sleeps, retries up to 5 times. Uses the server's requested delay (or 20s fallback) — not exponential backoff.

**Structured logging:** Every phase of the agent run is logged as structured events:
- `system_prompt` / `user_prompt` — what the LLM received
- `model_response` — free-text LLM output (truncated to 500 chars in logs)
- `tool_call` / `tool_return` — tool name, arg count, status only (no args/body to avoid sensitive data leakage)
- `run_complete` — tokens, latency, retries, files_read, confidence

### Step 5: Repository Access (`repository.py`)

Two implementations:

**`GitHubRepo`** — uses GitHub PAT from `GITHUB_TOKEN` env var, calls GitHub REST API:
- `search_symbol(symbol)` — recursive tree search for files matching the symbol, with content-aware matching
- `read_file(path)` — GET `/contents/{path}` returns base64-decoded file content
- `build_code_graph(file_paths)` — AST-based import parsing into `CodeGraph`
- `create_issue(title, body)` — POST `/issues` to create a real GitHub issue

**`LocalRepo`** — reads from local filesystem, `create_issue()` returns `None`:
```python
class LocalRepo:
    def search_symbol(self, symbol):
        # rglob for files matching symbol, with content-aware matching
    def read_file(self, path):
        # read local file with path traversal protection, returns None if not found
    def build_code_graph(self, file_paths):
        # AST-based import parsing → CodeGraph
    def create_issue(self, title, body):
        return None
```

**Code graph** is built by AST-parsing imports and function/class definitions, resolving against known repo files to avoid stdlib/phantom dependencies:

```python
# AST parses "from foo import bar" + "import baz"
# Creates edges: tool_timeout.py ─imports─► agent.py
# Also indexes function defs as graph nodes: tool_timeout.py::search_code()
```

### Step 6: Engineering Report (`schemas.py`)

The agent's typed output (18 fields):

```python
class EngineeringReport(BaseModel):
    summary: str                         # one-line summary of the bug
    root_cause: str                      # root cause analysis
    evidence: list[str]                  # supporting evidence strings
    suspected_components: list[str]      # e.g. ["Planner", "ToolExecutor"]
    relevant_files: list[str]            # file paths
    relevant_functions: list[str]        # function names
    suggested_investigation: list[str]   # next steps for engineering
    suggested_fix: str                   # proposed fix description
    suggested_tests: list[str]           # test scenarios to add
    confidence: float                    # 0.0 - 1.0

    executive_summary: str = ""          # high-level incident description
    impact: str = ""                     # what broke and for whom
    timeline: list[TimelineEvent] = []   # ordered reconstruction of incident
    repository_findings: RepositoryFindings = Field(default_factory=RepositoryFindings)
    missing_context: MissingContext | None = None
    evidence_analysis: str = ""          # how each conclusion is grounded
    secondary_effects: list[str] = []    # cascading failures
    issue_title: str = ""                # ready-to-use GitHub issue title
```

### Step 7: GitHub Issue Creation (Host Code)

After the agent returns the report, host code (`__main__.py` or pipeline) calls `create_github_issue_from_report()` to create exactly one GitHub issue with the full report — avoiding the model skipping/repeating the tool or 429 replays creating duplicates.

---

## Architecture

```
packages/issue-agent/src/issue_agent/
├── __init__.py
├── __main__.py        # CLI entry: read stdin → run → print report
├── agent.py           # PydanticAI Agent, tools, retry, logging
├── evidence.py        # Failed tool call extraction
├── repository.py      # GitHubRepo (prod) / LocalRepo (dev)
└── schemas.py         # Pydantic models: IncidentSnapshot → EngineeringReport
```

---

## Production vs Dev Mode

| Aspect | Production | Dev Mode |
|---|---|---|
| Env var | (unset) | `VOID_DEV_MODE=1` |
| Repo backend | `GitHubRepo` (GitHub API) | `LocalRepo` (local filesystem) |
| Issue creation | Host code calls `create_github_issue_from_report()` after validation | No issue created |
| Report output | Printed to stdout + posted to GitHub | Printed to stdout only |

---

## Usage

```bash
# Install
pip install -e packages/issue-agent

# Configure (production)
export GITHUB_TOKEN=ghp_...
export DEMO_REPOSITORY=owner/repo

# Run (reads incident JSON from stdin)
cat evaluation_dataset/incidents/example/incident.json | PYTHONPATH=packages/issue-agent/src python -m issue_agent

# Dev mode (no GitHub API calls)
VOID_DEV_MODE=1 cat evaluation_dataset/incidents/example/incident.json | PYTHONPATH=packages/issue-agent/src python -m issue_agent
```

Note: `VOID_DEV_MODE=1` must be passed to Python, not just `cat`.

---

## E2E Monitoring

A standalone script runs all 14 incident scenarios against the agent and prints a detailed report for each:

```bash
# From repository root (requires GOOGLE_API_KEY in .env)
packages/evaluator/.venv/bin/python3 packages/issue-agent/tests/e2e_monitor.py

# Or run specific scenarios
packages/evaluator/.venv/bin/python3 packages/issue-agent/tests/e2e_monitor.py example tool-anomaly
```

Output per scenario:
1. **Evaluator output** — classification, failure modes, severity, reasoning, recommendations
2. **LLM conversation** — system prompt, user prompt, every model response text, every tool call with args, tool return statuses
3. **Run metrics** — tokens (input/output/total), requests, tool calls, latency, retries, files read
4. **Engineering report** — all 18 fields from the structured output
5. **Summary table** — pass/fail per scenario with confidence scores

Caveat: Gemini's free tier has 15 RPM quota — running all 14 scenarios in sequence will hit rate limits. Retry logic handles this, but some scenarios may still fail. Run individual scenarios or use a paid API key for batch runs.

### Test Suite

```bash
# Unit tests only (no LLM calls, fast)
PYTHONPATH=packages/issue-agent/src:packages/evaluator/src:packages/issue-agent/tests python -m unittest \
    tests/test_schemas.py tests/test_agent.py tests/test_repository.py tests/test_mapper.py -v
```

---

---

## Test Scenarios

Each scenario under `tests/issue-agent/` (evaluation fixtures) and `evaluation_dataset/incidents/` (input incidents) contains:
- `incident.json` — full incident with traces + evaluator output
- `evaluation.json` — just the evaluation result
- `expected.json` — expected investigation targets for validation

```text
evaluation_dataset/incidents/
├── tool_timeout/        # tool timed out twice, no retry logic
├── planner_bug/         # sequential calls instead of batching
├── handoff_failure/     # state lost during agent handoff
├── context_overflow/    # document exceeded context window
└── tool_call_anomaly/   # null field propagated silently
```

Full scenario list: `context-overflow`, `handoff-failure`, `looping`, `silent-hallucination`, `tool-anomaly`, `crash-loop`, `critical-escalation`, `example`, `false-positive`, `insufficient-evidence`, `mixed-labels`, `rate-limit`, `recurring`, `transient-error`.

---

## Monitor Limitations

The monitor does not print every model response in full; structured logging truncates model text to 500 characters and prompts to 300. For complete conversation debugging, inspect the structured log output directly.