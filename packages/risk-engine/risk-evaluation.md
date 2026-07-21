# Risk Evaluation Engine

## Overview

The `@void-server/risk-engine` package is a pure, deterministic module that evaluates AI agent execution sessions for risk. It inspects structured execution telemetry against a set of configurable policies and produces a risk verdict: `HEALTHY`, `SUSPICIOUS`, or `CRITICAL`.

There are **no external dependencies** — no database, no HTTP calls, no LLM invocations, no OpenTelemetry. The engine is a simple function: `evaluate(execution, config) => RiskEvaluationResult`.

The `Execution` type intentionally avoids OpenTelemetry-specific fields (Span, Trace, Resource, InstrumentationScope). Those belong to the ingestion layer, not the risk engine.

---

## Package Structure

```
packages/risk-engine/
├── package.json
├── tsconfig.json
├── tsconfig.build.json
├── vitest.config.ts
├── risk-evaluation.md
└── src/
    ├── index.ts                        # Public API barrel
    ├── types.ts                        # All type definitions
    ├── config.ts                       # Default thresholds
    ├── evaluator.ts                    # Orchestrator with input validation
    ├── evaluator.test.ts               # Integration + validation tests
    └── policies/
        ├── latency-policy.ts           + latency-policy.test.ts
        ├── token-budget-policy.ts      + token-budget-policy.test.ts
        ├── tool-failure-policy.ts      + tool-failure-policy.test.ts
        ├── repeated-tool-policy.ts     + repeated-tool-policy.test.ts
        ├── retry-policy.ts             + retry-policy.test.ts
        ├── no-response-policy.ts       + no-response-policy.test.ts
        ├── agent-crash-policy.ts       + agent-crash-policy.test.ts
        └── context-overflow-policy.ts  + context-overflow-policy.test.ts
```

---

## Types (`src/types.ts`)

The `RiskLabel` enum prevents typos in label strings:

`RiskLabel.HIGH_LATENCY`, `RiskLabel.TOKEN_BUDGET_EXCEEDED`, `RiskLabel.TOOL_FAILURE`, `RiskLabel.REPEATED_TOOL_CALLS`, `RiskLabel.EXCESSIVE_RETRIES`, `RiskLabel.NO_FINAL_RESPONSE`, `RiskLabel.AGENT_CRASH`, `RiskLabel.CONTEXT_OVERFLOW`, `RiskLabel.INVALID_EXECUTION_INPUT`, `RiskLabel.INVALID_CONFIG_INPUT`.

| Interface | Purpose |
|-----------|---------|
| `Execution` | Incoming session telemetry (latencyMs, promptTokens, completionTokens, toolExecutions[], retryCount, hasFinalResponse, crashed, contextWindowExceeded) |
| `RiskConfig` | Wraps `RiskPolicies` with all thresholds |
| `RiskPolicies` | `latencyMs`, `tokenBudget`, `toolFailureThreshold`, `repeatedToolThreshold`, `retryThreshold`, `warningThreshold` |
| `PolicyResult` | `{ label: RiskLabel; severity: "WARNING" \| "CRITICAL" }` |
| `RiskEvaluationResult` | `{ labels, warningCount, criticalCount, severity }` |

See `src/types.ts` for the full source.

---

## Default Configuration (`src/config.ts`)

```ts
export const config: RiskConfig = {
  policies: {
    latencyMs: 3000,
    tokenBudget: 25000,
    toolFailureThreshold: 1,
    repeatedToolThreshold: 3,
    retryThreshold: 3,
    warningThreshold: 3,
  },
};
```

Every threshold is overridable by passing a custom `RiskConfig` to `evaluate()`.

---

## Risk Model

### Severity levels

| Severity     | Rule |
|--------------|------|
| `HEALTHY`    | No `CRITICAL` policy fired AND `warningCount < warningThreshold` |
| `SUSPICIOUS` | No `CRITICAL` policy fired BUT `warningCount >= warningThreshold` |
| `CRITICAL`   | At least one `CRITICAL` policy fired (overrides everything) |

### Policy list

| # | Policy               | Severity  | Condition |
|---|----------------------|-----------|-----------|
| 1 | **Latency**          | WARNING   | `latencyMs > policies.latencyMs` |
| 2 | **Token Budget**     | WARNING   | `promptTokens + completionTokens > policies.tokenBudget` |
| 3 | **Tool Failure**     | CRITICAL  | `failed tool count > 0 && >= policies.toolFailureThreshold` |
| 4 | **Repeated Tool**    | WARNING   | `max consecutive identical tool calls > policies.repeatedToolThreshold` |
| 5 | **Retry**            | WARNING   | `retryCount > policies.retryThreshold` |
| 6 | **No Response**      | CRITICAL  | `hasFinalResponse === false` |
| 7 | **Agent Crash**      | CRITICAL  | `crashed === true` |
| 8 | **Context Overflow** | WARNING   | `contextWindowExceeded === true` |

---

## Policy Signatures

Policies follow two signatures:

- **Config-dependent** (5 policies): `(execution: Execution, policies: RiskPolicies) => PolicyResult | null`
  - Latency, Token Budget, Tool Failure, Repeated Tool, Retry
- **Stateless** (3 policies): `(execution: Execution) => PolicyResult | null`
  - No Response, Agent Crash, Context Overflow

All source files live in `src/policies/`. See the individual `.ts` files for exact implementation.

---

## Evaluator (`src/evaluator.ts`)

The `evaluate()` function:

1. **Validates** input — checks `Execution` and `RiskConfig` container objects, array element shapes, non-finite, negative, or type-invalid values. Returns `CRITICAL` with `INVALID_EXECUTION_INPUT` or `INVALID_CONFIG_INPUT` on failure, along with detailed validation error fields in `errors`.
2. **Runs** all 8 policies in sequence.
3. **Aggregates** labels, warning count, critical count.
4. **Derives** severity — any CRITICAL → `CRITICAL`; warnings ≥ `warningThreshold` → `SUSPICIOUS`; otherwise `HEALTHY`.

Includes `TODO(v2)` marker for future distributed trace reconstruction.

---

## Public API (`src/index.ts`)

```ts
export { evaluate } from "./evaluator";
export { config } from "./config";
export { RiskLabel } from "./types";
export type { PolicySeverity, EvaluationSeverity, PolicyResult, ToolExecution, Execution, ValidationError, RiskEvaluationResult, RiskPolicies, RiskConfig } from "./types";
```

### Usage

```ts
import { evaluate, config, RiskLabel } from "@void-server/risk-engine";

const result = evaluate(execution, config);
// { labels: [RiskLabel.HIGH_LATENCY], warningCount: 1, criticalCount: 0, severity: "HEALTHY" }
```

Custom thresholds:

```ts
const result = evaluate(execution, {
  policies: { latencyMs: 5000, tokenBudget: 50000, toolFailureThreshold: 3, repeatedToolThreshold: 5, retryThreshold: 5, warningThreshold: 2 },
});
```

---

## Testing

**Framework:** Vitest v1.6+

### Commands (from monorepo root)

```bash
npm test -w @void-server/risk-engine
npm run test:watch -w @void-server/risk-engine
npm run test:coverage -w @void-server/risk-engine
```

Or directly from `packages/risk-engine/`:

```bash
cd packages/risk-engine && npm test
```

### Test count

```
 Test Files  9 passed (9)
      Tests  46 passed (46)
```

Tests cover all policies (including edge cases like zero/negative/custom thresholds), input validation (NaN, Infinity, negative values, non-integer fields), and integration scenarios.

---

## Architecture Diagram

```
                  Execution { latencyMs, promptTokens, ... }
                              │
                              ▼
                   evaluate(execution, config)
                    ├── validate inputs → CRITICAL on failure
                    ├── latency-policy          ─── WARNING
                    ├── token-budget-policy      ─── WARNING
                    ├── tool-failure-policy      ─── CRITICAL
                    ├── repeated-tool-policy     ─── WARNING
                    ├── retry-policy             ─── WARNING
                    ├── no-response-policy       ─── CRITICAL
                    ├── agent-crash-policy       ─── CRITICAL
                    └── context-overflow-policy  ─── WARNING
                              │
                              ▼
                  RiskEvaluationResult { labels, warningCount, criticalCount, severity }
```

---

## Design Decisions

1. **Pure functions only** — every policy is a simple function. Easy to test, easy to compose.
2. **Null means PASS** — policies return `null` instead of a no-op result.
3. **CRITICAL overrides SUSPICIOUS** — any single critical policy bumps the entire evaluation to `CRITICAL`, regardless of warning count.
4. **All thresholds in one place** — every configurable number lives in `RiskPolicies`.
5. **`RiskLabel` enum** — prevents typos in label strings.
6. **Input validation boundary** — `evaluate()` rejects non-finite, negative, or type-invalid values before running policies, returning a CRITICAL result.
7. **Execution is generic** — no OTel-specific fields. Those belong in the ingestion layer.
8. **`TODO(v2)` markers** — future goals documented inline.
