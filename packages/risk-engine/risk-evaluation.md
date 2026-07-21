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
├── vitest.config.ts
├── risk-evaluation.md
└── src/
    ├── index.ts                        # Public API barrel
    ├── types.ts                        # All type definitions
    ├── config.ts                       # Default thresholds
    ├── evaluator.ts                    # Orchestrator
    ├── evaluator.test.ts               # Integration tests
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

The engine operates on two main shapes: what you feed in (`Execution`) and what you get back (`RiskEvaluationResult`).

```ts
export enum RiskLabel {
  HIGH_LATENCY = "HIGH_LATENCY",
  TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED",
  TOOL_FAILURE = "TOOL_FAILURE",
  REPEATED_TOOL_CALLS = "REPEATED_TOOL_CALLS",
  EXCESSIVE_RETRIES = "EXCESSIVE_RETRIES",
  NO_FINAL_RESPONSE = "NO_FINAL_RESPONSE",
  AGENT_CRASH = "AGENT_CRASH",
  CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW",
}

export type PolicySeverity = "WARNING" | "CRITICAL";

export type EvaluationSeverity = "HEALTHY" | "SUSPICIOUS" | "CRITICAL";

export interface PolicyResult {
  label: RiskLabel;
  severity: PolicySeverity;
}

export interface ToolExecution {
  toolName: string;
  success: boolean;
}

export interface Execution {
  latencyMs: number;
  promptTokens: number;
  completionTokens: number;
  toolExecutions: ToolExecution[];
  retryCount: number;
  hasFinalResponse: boolean;
  crashed: boolean;
  contextWindowExceeded: boolean;
}

export interface RiskEvaluationResult {
  labels: RiskLabel[];
  warningCount: number;
  criticalCount: number;
  severity: EvaluationSeverity;
}

export interface RiskPolicies {
  latencyMs: number;
  tokenBudget: number;
  toolFailureThreshold: number;
  repeatedToolThreshold: number;
  retryThreshold: number;
  warningThreshold: number;
}

export interface RiskConfig {
  policies: RiskPolicies;
}
```

Labels use an `enum` instead of raw strings to prevent typos like `"HIGH_LATENCYY"`. Every threshold — `repeatedToolThreshold` and `retryThreshold` included — lives in `RiskPolicies` so tuning is centralized.

### Field semantics

| Field                    | Description |
|--------------------------|-------------|
| `latencyMs`              | Wall-clock duration of the execution in milliseconds |
| `promptTokens`           | Tokens consumed by the prompt |
| `completionTokens`       | Tokens consumed by the completion |
| `toolExecutions`         | Ordered list of tool call results |
| `retryCount`             | Number of automatic retries triggered |
| `hasFinalResponse`       | Whether a final user-facing response was produced |
| `crashed`                | Whether the agent crashed or threw an unhandled error |
| `contextWindowExceeded`  | Whether the execution hit the context-length limit |

---

## Default Configuration (`src/config.ts`)

```ts
import { RiskConfig } from "./types";

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

| # | Policy               | Label                       | Severity  | Condition |
|---|----------------------|-----------------------------|-----------|-----------|
| 1 | **Latency**          | `RiskLabel.HIGH_LATENCY`    | WARNING   | `latencyMs > policies.latencyMs` |
| 2 | **Token Budget**     | `RiskLabel.TOKEN_BUDGET_EXCEEDED` | WARNING | `promptTokens + completionTokens > policies.tokenBudget` |
| 3 | **Tool Failure**     | `RiskLabel.TOOL_FAILURE`    | CRITICAL  | `failed tool count >= policies.toolFailureThreshold` |
| 4 | **Repeated Tool**    | `RiskLabel.REPEATED_TOOL_CALLS` | WARNING | `max consecutive identical tool calls > policies.repeatedToolThreshold` |
| 5 | **Retry**            | `RiskLabel.EXCESSIVE_RETRIES` | WARNING | `retryCount > policies.retryThreshold` |
| 6 | **No Response**      | `RiskLabel.NO_FINAL_RESPONSE` | CRITICAL | `hasFinalResponse === false` |
| 7 | **Agent Crash**      | `RiskLabel.AGENT_CRASH`     | CRITICAL  | `crashed === true` |
| 8 | **Context Overflow** | `RiskLabel.CONTEXT_OVERFLOW` | WARNING  | `contextWindowExceeded === true` |

---

## Policy Implementations

### 1. Latency Policy (`src/policies/latency-policy.ts`)

Flags when execution duration exceeds the threshold.

```ts
import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateLatencyPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  if (execution.latencyMs > policies.latencyMs) {
    return { label: RiskLabel.HIGH_LATENCY, severity: "WARNING" };
  }
  return null;
}
```

### 2. Token Budget Policy (`src/policies/token-budget-policy.ts`)

Flags when total token consumption (prompt + completion) exceeds the budget.

```ts
import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateTokenBudgetPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  const totalTokens = execution.promptTokens + execution.completionTokens;
  if (totalTokens > policies.tokenBudget) {
    return { label: RiskLabel.TOKEN_BUDGET_EXCEEDED, severity: "WARNING" };
  }
  return null;
}
```

### 3. Tool Failure Policy (`src/policies/tool-failure-policy.ts`)

Flags when the number of failed tool calls meets or exceeds the failure threshold.

```ts
import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateToolFailurePolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  const failedTools = execution.toolExecutions.filter((t) => !t.success).length;
  if (failedTools >= policies.toolFailureThreshold) {
    return { label: RiskLabel.TOOL_FAILURE, severity: "CRITICAL" };
  }
  return null;
}
```

### 4. Repeated Tool Policy (`src/policies/repeated-tool-policy.ts`)

Detects when the same tool is called consecutively more than the configured threshold. The consecutive run resets when a different tool appears. The threshold is read from `policies.repeatedToolThreshold` instead of being hardcoded.

```ts
import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateRepeatedToolPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  const tools = execution.toolExecutions;
  if (tools.length === 0) return null;

  let maxConsecutive = 1;
  let currentRun = 1;

  for (let i = 1; i < tools.length; i++) {
    if (tools[i].toolName === tools[i - 1].toolName) {
      currentRun++;
      if (currentRun > maxConsecutive) {
        maxConsecutive = currentRun;
      }
    } else {
      currentRun = 1;
    }
  }

  if (maxConsecutive > policies.repeatedToolThreshold) {
    return { label: RiskLabel.REPEATED_TOOL_CALLS, severity: "WARNING" };
  }
  return null;
}
```

### 5. Retry Policy (`src/policies/retry-policy.ts`)

Flags when the execution required excessive automatic retries. The threshold is read from `policies.retryThreshold` instead of being hardcoded.

```ts
import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateRetryPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  if (execution.retryCount > policies.retryThreshold) {
    return { label: RiskLabel.EXCESSIVE_RETRIES, severity: "WARNING" };
  }
  return null;
}
```

### 6. No Response Policy (`src/policies/no-response-policy.ts`)

Flags when the agent finished without producing a final user-facing response.

```ts
import { Execution, PolicyResult, RiskLabel } from "../types";

export function evaluateNoResponsePolicy(
  execution: Execution,
): PolicyResult | null {
  if (!execution.hasFinalResponse) {
    return { label: RiskLabel.NO_FINAL_RESPONSE, severity: "CRITICAL" };
  }
  return null;
}
```

### 7. Agent Crash Policy (`src/policies/agent-crash-policy.ts`)

Flags when the agent execution ended in a crash.

```ts
import { Execution, PolicyResult, RiskLabel } from "../types";

export function evaluateAgentCrashPolicy(
  execution: Execution,
): PolicyResult | null {
  if (execution.crashed) {
    return { label: RiskLabel.AGENT_CRASH, severity: "CRITICAL" };
  }
  return null;
}
```

### 8. Context Overflow Policy (`src/policies/context-overflow-policy.ts`)

Flags when the execution exceeded the context window limit.

```ts
import { Execution, PolicyResult, RiskLabel } from "../types";

export function evaluateContextOverflowPolicy(
  execution: Execution,
): PolicyResult | null {
  if (execution.contextWindowExceeded) {
    return { label: RiskLabel.CONTEXT_OVERFLOW, severity: "WARNING" };
  }
  return null;
}
```

---

## Evaluator (`src/evaluator.ts`)

The evaluator runs all 8 policies in sequence, collects non-null results, and derives the final severity. It includes a `TODO(v2)` marker for future distributed trace support.

```ts
import { Execution, PolicyResult, RiskConfig, RiskEvaluationResult } from "./types";
import { evaluateLatencyPolicy } from "./policies/latency-policy";
import { evaluateTokenBudgetPolicy } from "./policies/token-budget-policy";
import { evaluateToolFailurePolicy } from "./policies/tool-failure-policy";
import { evaluateRepeatedToolPolicy } from "./policies/repeated-tool-policy";
import { evaluateRetryPolicy } from "./policies/retry-policy";
import { evaluateNoResponsePolicy } from "./policies/no-response-policy";
import { evaluateAgentCrashPolicy } from "./policies/agent-crash-policy";
import { evaluateContextOverflowPolicy } from "./policies/context-overflow-policy";

// TODO(v2):
// Risk Evaluation currently operates on normalized execution metadata.
// Future versions should support distributed execution graphs reconstructed
// from multiple OpenTelemetry traces.

type Policy = (execution: Execution, config: RiskConfig) => PolicyResult | null;

const policies: Policy[] = [
  (execution, config) => evaluateLatencyPolicy(execution, config.policies),
  (execution, config) => evaluateTokenBudgetPolicy(execution, config.policies),
  (execution, config) => evaluateToolFailurePolicy(execution, config.policies),
  (execution, config) => evaluateRepeatedToolPolicy(execution, config.policies),
  (execution, config) => evaluateRetryPolicy(execution, config.policies),
  (execution) => evaluateNoResponsePolicy(execution),
  (execution) => evaluateAgentCrashPolicy(execution),
  (execution) => evaluateContextOverflowPolicy(execution),
];

export function evaluate(execution: Execution, config: RiskConfig): RiskEvaluationResult {
  const results: PolicyResult[] = [];

  for (const policy of policies) {
    const result = policy(execution, config);
    if (result !== null) {
      results.push(result);
    }
  }

  const labels = results.map((r) => r.label);
  const warningCount = results.filter((r) => r.severity === "WARNING").length;
  const criticalCount = results.filter((r) => r.severity === "CRITICAL").length;

  let severity: RiskEvaluationResult["severity"] = "HEALTHY";
  if (criticalCount > 0) {
    severity = "CRITICAL";
  } else if (warningCount >= config.policies.warningThreshold) {
    severity = "SUSPICIOUS";
  }

  return { labels, warningCount, criticalCount, severity };
}
```

### Orchestration logic

```
for each policy → call → return PolicyResult | null
                  ↓
          collect non-null results
                  ↓
          labels    ← map to RiskLabel values
          warnings  ← count severity === "WARNING"
          criticals ← count severity === "CRITICAL"
                  ↓
          severity ← CRITICAL (criticalCount > 0)
                   | SUSPICIOUS (warnings ≥ warningThreshold)
                   | HEALTHY    (otherwise)
```

---

## Public API (`src/index.ts`)

```ts
export { evaluate } from "./evaluator";
export { config } from "./config";
export { RiskLabel } from "./types";
export type {
  PolicySeverity,
  EvaluationSeverity,
  PolicyResult,
  ToolExecution,
  Execution,
  RiskEvaluationResult,
  RiskPolicies,
  RiskConfig,
} from "./types";
```

Consumers import the evaluate function, the default config, and the enum:

```ts
import { evaluate, config, RiskLabel } from "@void-server/risk-engine";

const result = evaluate(execution, config);
// { labels: [RiskLabel.HIGH_LATENCY], warningCount: 1, criticalCount: 0, severity: "HEALTHY" }
```

---

## Usage Examples

### Basic usage with defaults

```ts
import { evaluate, config } from "@void-server/risk-engine";

const execution = {
  latencyMs: 1200,
  promptTokens: 8000,
  completionTokens: 4000,
  toolExecutions: [
    { toolName: "search", success: true },
    { toolName: "read", success: true },
  ],
  retryCount: 0,
  hasFinalResponse: true,
  crashed: false,
  contextWindowExceeded: false,
};

const result = evaluate(execution, config);
// { labels: [], warningCount: 0, criticalCount: 0, severity: "HEALTHY" }
```

### Critical execution

```ts
const execution = {
  latencyMs: 500,
  promptTokens: 1000,
  completionTokens: 2000,
  toolExecutions: [
    { toolName: "search", success: false },
    { toolName: "read", success: false },
  ],
  retryCount: 0,
  hasFinalResponse: false,
  crashed: true,
  contextWindowExceeded: false,
};

const result = evaluate(execution, config);
// {
//   labels: ["TOOL_FAILURE", "NO_FINAL_RESPONSE", "AGENT_CRASH"],
//   warningCount: 0,
//   criticalCount: 3,
//   severity: "CRITICAL",
// }
```

### Custom thresholds

```ts
import { evaluate } from "@void-server/risk-engine";

const result = evaluate(execution, {
  policies: {
    latencyMs: 5000,
    tokenBudget: 50000,
    toolFailureThreshold: 3,
    repeatedToolThreshold: 5,
    retryThreshold: 5,
    warningThreshold: 2,
  },
});
```

---

## Testing

**Framework:** Vitest v1.6+  
**Config** (`vitest.config.ts`):

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
```

### Commands

| Command | Purpose |
|---------|---------|
| `npm test` | Run all tests once |
| `npm run test:watch` | Watch mode |
| `npm run test:coverage` | Run with coverage report |

### Test results

```
 ✓ src/policies/token-budget-policy.test.ts     (3 tests)
 ✓ src/policies/retry-policy.test.ts            (4 tests)
 ✓ src/policies/context-overflow-policy.test.ts (2 tests)
 ✓ src/policies/agent-crash-policy.test.ts      (2 tests)
 ✓ src/policies/latency-policy.test.ts          (3 tests)
 ✓ src/policies/no-response-policy.test.ts      (2 tests)
 ✓ src/policies/repeated-tool-policy.test.ts    (7 tests)
 ✓ src/policies/tool-failure-policy.test.ts     (4 tests)
 ✓ src/evaluator.test.ts                        (6 tests)

 Test Files  9 passed (9)
      Tests  33 passed (33)
```

### Test coverage

| Policy                | Tests | Scenarios covered |
|------------------------|-------|-------------------|
| Latency               | 3     | below, at, above threshold |
| Token Budget          | 3     | under, at, over budget |
| Tool Failure          | 4     | no failures, empty, at threshold, exceeds threshold |
| Repeated Tool         | 7     | different tools, 2x same, 3x same (at threshold), 4x same, interrupted run, empty, custom threshold |
| Retry                 | 4     | none, at threshold, above threshold, custom threshold |
| No Response           | 2     | response present, response missing |
| Agent Crash           | 2     | no crash, crashed |
| Context Overflow      | 2     | within window, exceeded |
| Evaluator (integration) | 6   | HEALTHY, SUSPICIOUS, CRITICAL, CRITICAL overrides warnings, custom config, mixed policies |

---

## Architecture Diagram

```
                  ┌──────────────────────────────────────────────┐
                  │                Execution                     │
                  │  { latencyMs, promptTokens, completionTokens, │
                  │    toolExecutions[], retryCount,              │
                  │    hasFinalResponse, crashed,                 │
                  │    contextWindowExceeded }                    │
                  └──────────────┬───────────────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────────────┐
                  │         evaluate(config)                     │
                  │   ┌─────────────────────────────────────┐   │
                  │   │  latency-policy      ─── WARNING     │   │
                  │   │  token-budget-policy  ─── WARNING     │   │
                  │   │  tool-failure-policy  ─── CRITICAL    │   │
                  │   │  repeated-tool-policy ─── WARNING     │   │
                  │   │  retry-policy        ─── WARNING     │   │
                  │   │  no-response-policy  ─── CRITICAL    │   │
                  │   │  agent-crash-policy  ─── CRITICAL    │   │
                  │   │  context-overflow-policy ─ WARNING   │   │
                  │   └─────────────────────────────────────┘   │
                  └──────────────┬───────────────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────────────┐
                  │     RiskEvaluationResult                     │
                  │  { labels: RiskLabel[],                      │
                  │    warningCount: number,                     │
                  │    criticalCount: number,                    │
                  │    severity: EvaluationSeverity }            │
                  └──────────────────────────────────────────────┘
```

---

## Design Decisions

1. **Pure functions only** — every policy is a function `(Execution, partial config) => PolicyResult | null`. Easy to test, easy to compose.
2. **Null means PASS** — policies return `null` instead of a no-op result, keeping the result array clean.
3. **CRITICAL overrides SUSPICIOUS** — any single critical policy bumps the entire evaluation to `CRITICAL`, regardless of warning count.
4. **Config is injected, not imported** — the evaluator receives config as a parameter so callers can override thresholds without module mutation.
5. **All thresholds in one place** — `latencyMs`, `tokenBudget`, `toolFailureThreshold`, `repeatedToolThreshold`, `retryThreshold`, and `warningThreshold` all live in `RiskPolicies`.
6. **`RiskLabel` enum** — prevents typos in label strings; every valid label is a named member.
7. **Execution is generic** — intentionally avoids OpenTelemetry-specific fields (Span, Trace, Resource, InstrumentationScope). Those belong to the ingestion layer.
8. **TODO(v2) markers** — future goals like distributed trace reconstruction are documented inline.
