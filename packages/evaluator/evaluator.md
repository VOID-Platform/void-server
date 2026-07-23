# Evaluator

The Evaluator analyzes suspicious incidents and produces a structured forensic assessment. It is the first AI component in VOID.

## Pipeline

```
Incident (JSON)  ←  includes execution trace + telemetry
    ↓
Context Builder  →  EvaluationContext (with agent_steps, tool_calls, telemetry)
    ↓
Prompt Builder   →  PromptMetadata (v3 — failure mode + urgency)
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
Builds the Gemini prompt from context. Versioned (`PROMPT_VERSION = "3.0.0"`). Temperature fixed at 0.2 for consistency.

The v3 prompt instructs Gemini to analyze execution traces for 8 specific failure modes and assign a graded urgency tier:

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
2. Field checks — required fields, enum values, confidence bounds, types, failure modes, urgency sub-fields
3. Pydantic — full `Evaluation` model validation

Invalid outputs are rejected (returns `None` from agent). Urgency tiers are enforced: FALSE_POSITIVE and INSUFFICIENT_EVIDENCE must have tier DEFER and page_now false.

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
    "recommendations": ["add input validation to search tool"],
    "urgency": {
      "tier": "P1",
      "page_now": false,
      "status": "TERMINATED",
      "reasoning": "Failure terminated but hallucinated number may have reached downstream."
    }
  },
  "metadata": {
    "prompt_version": "3.0.0",
    "model_version": "gemini-3.1-flash-lite",
    "model_temperature": 0.2,
    "evaluated_at": "2026-07-23T..."
  }
}
```

## Urgency Tiers

| Tier | Description | page_now |
|------|-------------|----------|
| **P0** | Actively ongoing failure with real-time impact — still consuming resources, still making calls, or actively producing bad output that could reach a user/downstream system right now. | `true` |
| **P1** | Failure has terminated but caused or risks meaningful damage (e.g. a hallucinated number may have already reached a customer, a destructive action may have already executed, a workflow is now stuck in a bad state that blocks other work). Needs human attention same-day. | `false` |
| **P2** | Failure terminated, impact is contained or low-stakes (e.g. an internal-only report needs a re-run, a single non-critical task failed with no downstream consequence). Review during business hours. | `false` |
| **DEFER** | Classified as REAL_INCIDENT but genuinely low-risk and non-urgent (e.g. a one-off latency blip that self-resolved). Also used for FALSE_POSITIVE and INSUFFICIENT_EVIDENCE. | `false` |

## Urgency Routing

| Urgency Tier | Action |
|---|---|
| P0 | Page immediately, auto-escalate |
| P1 | Same-day human review |
| P2 | Business-hours review |
| DEFER | Log for pattern-tracking |

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

### Unit & End-to-End Test Suite (49 tests)

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

| Incident | Labels | Severity | Trace | Scenario |
|---|---|---|---|---|---|
| `example/` | HIGH_LATENCY, TOKEN_OVERFLOW | SUSPICIOUS | Yes | Timeout + partial weather data from 10-city request |
| `false-positive/` | TRANSIENT_ERROR | SUSPICIOUS | Yes | Search API unavailable once, recovers on retry |
| `transient-error/` | TRANSIENT_ERROR, RATE_LIMIT | SUSPICIOUS | Yes | Exchange rate API rate-limited, recovers with backoff |
| `crash-loop/` | CRASH_LOOP | CRITICAL | Yes | Code interpreter OOM on 4 attempts, different strategies all fail |
| `critical-escalation/` | ESCALATION, HIGH_LATENCY | CRITICAL | Yes | Payment processor 75s total, banking timeout → escalation |
| `recurring/` | HIGH_LATENCY | SUSPICIOUS | Yes | 7-8s data_fetch calls across 12 occurrences |
| `insufficient-evidence/` | (none) | SUSPICIOUS | No | Empty trace ID — tests graceful empty-trace handling |
| `rate-limit/` | RATE_LIMIT | SUSPICIOUS | Yes | Supplier API 429, retries with backoff, succeeds |
| `mixed-labels/` | TRANSIENT_ERROR, TOKEN_OVERFLOW | SUSPICIOUS | Yes | LLM generate hit 16K token limit, split prompt succeeded on retry |
| `silent-hallucination/` | (none) | SUSPICIOUS | Yes | KB returned $2.1B, agent output $3.8B — must infer from trace |
| `context-overflow/` | TOKEN_OVERFLOW | SUSPICIOUS | Yes | 27K tokens, agent confused specs (128GB→256GB, 4G→5G) |
| `looping/` | REPEATED_TOOL_CALLS | CRITICAL | Yes | Same search_api called 7× with identical input, all failed |
| `handoff-failure/` | (none) | SUSPICIOUS | Yes | Planner chose 2025, researcher used 2024 — must infer from trace |
| `tool-anomaly/` | TOOL_FAILURE | SUSPICIOUS | Yes | Email validation failed, agent ignored and sent anyway |
| `ambiguous-edge-case/` | (none) | SUSPICIOUS | Yes | 3 KB sources disagree on Tokyo population; agent picked one confidently |
| `near-perfect/` | TOKEN_OVERFLOW | SUSPICIOUS | Yes | Near-token-limit (~22K), outputs intact — subtle degradation test |

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
