# Evaluator

The Evaluator analyzes suspicious incidents and produces a structured forensic assessment. It is the first AI component in VOID.

## Pipeline

```
Incident (JSON)  ←  includes execution trace + telemetry
    ↓
Context Builder  →  EvaluationContext (with agent_steps, tool_calls, telemetry)
    ↓
Prompt Builder   →  PromptMetadata (v2 — failure mode detection)
    ↓
Gemini (gemini-3.1-flash-lite, JSON mode)
    ↓
Validator        →  JSON + Pydantic validation
    ↓
Confidence Scorer →  deterministic adjustments (label + trace heuristics)
    ↓
FullEvaluation (JSON)
```

## Package Structure

```
packages/evaluator/
    src/evaluator/
        __init__.py        — exports
        __main__.py        — CLI: stdin JSON → stdout JSON (loads .env)
        schemas.py         — Pydantic models
        context_builder.py — incident dict → EvaluationContext (parses traces)
        prompt_builder.py  — context → Gemini prompt (v2, failure mode analysis)
        gemini_client.py   — Gemini API call (JSON mode)
        validator.py       — JSON parse + field checks + Pydantic
        scorer.py          — deterministic confidence adjustments
        agent.py           — orchestrator
```

## CLI Usage

```bash
# Pipe incident JSON to the evaluator
cat incident.json | PYTHONPATH=packages/evaluator/src python3 -m evaluator

# Requires GOOGLE_API_KEY in env or repo-root .env
```

Outputs a validated `FullEvaluation` JSON document to stdout.

The Evaluator is stateless and performs no database writes.

## Components

### Context Builder (`context_builder.py`)
Pure function. Transforms a raw incident dict into an `EvaluationContext`. No AI, no I/O.

Parses optional `agent_steps` (list of step objects with `tool_calls`, `llm_response`, `state`, `retrieved_docs`) and `telemetry` summary from the incident data.

### Prompt Builder (`prompt_builder.py`)
Builds the Gemini prompt from context. Versioned (`PROMPT_VERSION = "2.0.0"`). Temperature fixed at 0.2 for consistency.

The v2 prompt instructs Gemini to analyze execution traces for 8 specific failure modes:

| Failure Mode | What it detects |
|---|---|
| `HALLUCINATION` | Confident wrong answer, no error, contradicts tool output |
| `SILENT_CONTEXT_OVERFLOW` | No error, tokens near limit, truncated mid-chain |
| `STALE_CONTEXT` | Earlier context ignored in later reasoning |
| `REASONING_DRIFT` | Reasoning quality degrades across steps |
| `TOOL_CALL_ANOMALY` | Repeated calls, wrong order, errors ignored |
| `HANDOFF_FAILURE` | Data lost between steps, state inconsistency |
| `TOKEN_BUDGET_SILENT_FAILURE` | Near-limit token budget, degraded responses |
| `LOOPING` | Same call pattern, no progress |

### Gemini Client (`gemini_client.py`)
Single responsibility: send prompt → receive JSON. Uses `gemini-3.1-flash-lite` with `response_mime_type="application/json"`. Configure via `GOOGLE_API_KEY` env var.

### Validator (`validator.py`)
Three-phase validation:
1. JSON parsing — reject malformed
2. Field checks — required fields, enum values, confidence bounds, types, failure modes
3. Pydantic — full `Evaluation` model validation

Invalid outputs are rejected (returns `None` from agent).

### Confidence Scorer (`scorer.py`)
Deterministic adjustments on top of model confidence:

**Label-based:**
- Label/classification alignment (±0.05–0.20)
- Recurring incidents (+0.05 for ≥3 occurrences)
- Missing scene data (-0.10)
- `INSUFFICIENT_EVIDENCE` capped at 0.50

**Trace-based (new):**
- Failed tool calls: +0.05 for REAL_INCIDENT, -0.10 for FALSE_POSITIVE
- High retry count (≥3): +0.05
- Silent failures (successful call, no output): +0.05 for REAL_INCIDENT

### Agent (`agent.py`)

Coordinates the evaluation pipeline by invoking each component in sequence.

Responsibilities:
- Build the evaluation context (including trace data)
- Generate the prompt
- Invoke Gemini
- Validate the response
- Apply deterministic confidence scoring
- Return a validated `FullEvaluation`

The agent performs **no persistence** and has **no external infrastructure dependencies**.

```python
agent = Agent()
evaluation = agent.evaluate(incident_data)
```

## Input Format

Incident JSON can now include execution trace data:

```json
{
  "id": "incident-123",
  "fingerprint": "abc123",
  "title": "SUSPICIOUS: HIGH_LATENCY",
  "severity": "SUSPICIOUS",
  "latest_labels": ["HIGH_LATENCY"],
  "occurrence": 1,
  "trace_id": "trace-001",
  "execution_id": "exec-001",
  "agent_steps": [
    {
      "step_number": 1,
      "llm_response": {
        "model": "gpt-4",
        "response": "Let me search...",
        "prompt_tokens": 500,
        "completion_tokens": 50
      },
      "tool_calls": [
        {
          "name": "search",
          "input": "{\"query\": \"data\"}",
          "output": "{\"results\": [...]}",
          "latency_ms": 1200,
          "success": true,
          "retry_count": 0
        }
      ],
      "retrieved_docs": ["doc content..."],
      "state": {"memory": {"key": "value"}}
    }
  ],
  "telemetry": {
    "total_latency_ms": 4200,
    "total_prompt_tokens": 1100,
    "total_completion_tokens": 150,
    "tool_call_count": 2,
    "failed_tool_calls": 0,
    "retry_count": 0
  }
}
```

All trace fields are optional — incidents without traces still evaluate normally (with INSUFFICIENT_EVIDENCE as fallback).

## Output Format

```json
{
  "evaluation": {
    "summary": "forensic assessment of the incident",
    "classification": "REAL_INCIDENT",
    "recoverability": "RECOVERABLE",
    "confidence": 0.87,
    "failure_modes": ["TOOL_CALL_ANOMALY"],
    "suspected_root_cause": "search tool returned incomplete results silently",
    "suspected_components": ["search", "llm"],
    "reasoning": ["tool call anomaly detected in step 1"],
    "recommendations": ["add input validation to search tool"]
  },
  "metadata": {
    "prompt_version": "2.0.0",
    "model_version": "gemini-3.1-flash-lite",
    "model_temperature": 0.2,
    "evaluated_at": "2026-07-23T..."
  }
}
```

## Worker

The BullMQ worker at `apps/node-api/src/worker.ts` consumes the `incident-analysis` queue.

Pipeline:

1. Pop `evaluate-incident` job
2. Fetch Incident + execution trace using Prisma
3. Execute Python Evaluator
4. Receive `FullEvaluation`
5. Persist Evaluation using Prisma
6. Update Incident status

```bash
# Run the worker
cd apps/node-api && PYTHONPATH=../../packages/evaluator/src npx tsx src/worker.ts
```

## Queue Integration

The existing `IncidentFormationService` already enqueues SUSPICIOUS incidents with job name `evaluate-incident`. The worker picks these up automatically.

| Severity | Persisted? | Queued? | Job Name |
|---|---|---|---|
| HEALTHY | No | No | — |
| SUSPICIOUS | Yes | Yes (on creation) | `evaluate-incident` |
| CRITICAL | Yes | Yes (on creation / escalation) | `critical-incident` |

## Confidence Routing

| Confidence | Route |
|---|---|
| >= 0.90 | Automated action |
| 0.70 – 0.89 | Human approval |
| < 0.70 | Store only |

## Running Tests

### Setup Environment

**From package directory (`packages/evaluator`):**
```bash
cd packages/evaluator
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Or from repository root (`void-server`):**
```bash
python3 -m venv packages/evaluator/.venv
packages/evaluator/.venv/bin/pip install -e packages/evaluator
```

### Unit & End-to-End Test Suite (48 tests)

**From package directory:**
```bash
PYTHONPATH=src .venv/bin/python3 -m unittest tests/test_evaluator_e2e.py -v
```

**Or from repo root:**
```bash
PYTHONPATH=packages/evaluator/src packages/evaluator/.venv/bin/python3 -m unittest packages/evaluator/tests/test_evaluator_e2e.py -v
```

### Live Gemini API Integration Test

```bash
cd packages/evaluator
PYTHONPATH=src .venv/bin/python3 -m unittest tests/test_live_gemini.py -v
```

Skips automatically if `GOOGLE_API_KEY` is not set.

### Golden Dataset

Located at `evaluation_dataset/incidents/`:

| Incident | Labels | Severity | Scenario |
|---|---|---|---|
| `example/` | HIGH_LATENCY, TOKEN_OVERFLOW | SUSPICIOUS | Real performance problem |
| `false-positive/` | TRANSIENT_ERROR | SUSPICIOUS | Transient blip, likely not real |
| `transient-error/` | TRANSIENT_ERROR, RATE_LIMIT | SUSPICIOUS | External service hiccup |
| `crash-loop/` | CRASH_LOOP | CRITICAL | Agent crashing repeatedly |
| `critical-escalation/` | ESCALATION, HIGH_LATENCY | CRITICAL | Escalated severity with latency |
| `recurring/` | HIGH_LATENCY | SUSPICIOUS | Happened 12 times |
| `insufficient-evidence/` | (none) | SUSPICIOUS | No trace data available |
| `rate-limit/` | RATE_LIMIT | SUSPICIOUS | API rate limiting |
| `mixed-labels/` | TRANSIENT_ERROR, TOKEN_OVERFLOW | SUSPICIOUS | Conflicting signal |
| `silent-hallucination/` | (none) | SUSPICIOUS | Agent ignored KB result, output $3.8B vs actual $2.1B |
| `context-overflow/` | TOKEN_OVERFLOW | SUSPICIOUS | 27K tokens, agent confused specs (128GB→256GB, 4G→5G) |
| `looping/` | REPEATED_TOOL_CALLS | CRITICAL | Same search_api called 7× with identical input, all failed |
| `handoff-failure/` | (none) | SUSPICIOUS | Planner chose 2025, researcher used 2024, wrong answer |
| `tool-anomaly/` | TOOL_FAILURE | SUSPICIOUS | Validation failed, ignored, send_email attempted anyway |

Evaluate all incidents against live Gemini:

```bash
./evaluation_dataset/run_all.sh
```

Or evaluate a single incident:

```bash
PYTHONPATH=packages/evaluator/src \
    packages/evaluator/.venv/bin/python3 -m evaluator \
    < evaluation_dataset/incidents/crash-loop/incident.json
```

## Configuration

| Env Var | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key (required, can be configured in `.env`) |

## Dependencies

- `google-genai` — Gemini API SDK
- `pydantic` — schema validation
