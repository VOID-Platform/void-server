# Running Incidents Against the Real LLM

## Prerequisites

```bash
# 1. Set your Gemini API key
export GOOGLE_API_KEY="your-key-here"

# 2. Activate the venv (one-time setup)
cd packages/evaluator
python3 -m venv .venv
.venv/bin/pip install -e .
cd ../..
```

## Run All Incidents

```bash
./evaluation_dataset/run_all.sh
```

This evaluates every incident in `evaluation_dataset/incidents/*/` against the live Gemini API and prints the `FullEvaluation` JSON for each.

## Run a Single Incident

```bash
PYTHONPATH=packages/evaluator/src \
    packages/evaluator/.venv/bin/python3 -m evaluator \
    < evaluation_dataset/incidents/crash-loop/incident.json
```

## Run the Live Integration Test

```bash
cd packages/evaluator
PYTHONPATH=src .venv/bin/python3 -m unittest tests/test_live_gemini.py -v
```

Skips automatically if `GOOGLE_API_KEY` is not set.

## What to Look For

| Field | What to check |
|---|---|
| `classification` | Does the LLM correctly identify REAL_INCIDENT vs FALSE_POSITIVE? |
| `recoverability` | Does RECOVERABLE make sense for the scenario? |
| `confidence` | Is the model's confidence reasonable given the evidence? |
| `reasoning` | Are the reasoning steps coherent and grounded in the incident data? |
| `recommendations` | Are the suggestions actionable and relevant? |

The final `confidence` in the output includes deterministic adjustments from `scorer.py` — model confidence alone may be higher or lower before adjustment.

## Scenarios

| Incident | Labels | What to expect |
|---|---|---|
| `example/` | HIGH_LATENCY + TOKEN_OVERFLOW | REAL_INCIDENT, RECOVERABLE, high confidence |
| `false-positive/` | TRANSIENT_ERROR | FALSE_POSITIVE, RECOVERABLE |
| `transient-error/` | TRANSIENT_ERROR + RATE_LIMIT | FALSE_POSITIVE, RECOVERABLE |
| `crash-loop/` | CRASH_LOOP | REAL_INCIDENT, NON_RECOVERABLE, high confidence |
| `critical-escalation/` | ESCALATION + HIGH_LATENCY | REAL_INCIDENT, NON_RECOVERABLE, high confidence |
| `recurring/` | HIGH_LATENCY (x12) | REAL_INCIDENT, RECOVERABLE, high confidence |
| `insufficient-evidence/` | (none) | INSUFFICIENT_EVIDENCE, UNKNOWN, low confidence |
| `rate-limit/` | RATE_LIMIT | FALSE_POSITIVE, RECOVERABLE |
| `mixed-labels/` | TRANSIENT_ERROR + TOKEN_OVERFLOW | Conflicting — see what the LLM decides |
