# SDK Ingestion & Pipeline Wiring

## Architecture

Two entry points converge into the same incident pipeline:

```
SDK Application
  │  POST /api/traces  (agent steps + telemetry)
  ▼
/api/traces
  │
  ├── risk-engine.evaluate()
  │     └── severity + labels
  │
  ├── HEALTHY ──▶ adaptive-sampling (1/N queue)
  │
  └── SUSPICIOUS/CRITICAL ──▶ IncidentFormationService
                                │
                                ├── DB upsert (create/update incident)
                                └── queue "incident-analysis"
                                      │
                                      ▼
                                  worker.ts
                                    ├── evaluator (Python LLM)
                                    ├── promotion gate
                                    └── issue agent (Python LLM)
```

## Entry point — `POST /api/traces` (`apps/node-api/src/index.ts`)

### Imports + service singletons (lines 1-20)

```typescript
import express from 'express';
import cors from 'cors';
import { db } from './db';
import { evaluate } from "@void-server/risk-engine";
import { config as defaultRiskConfig } from "@void-server/risk-engine";
import { normalizeRiskLabels } from "@void-server/incident-fingerprint";
import { IncidentFormationService, PrismaIncidentRepository, BullMqIncidentQueue } from "@void-server/incident-formation";
import { AdaptiveSamplingService, BullMqSamplingQueue } from "@void-server/adaptive-sampling";

const app = express();
const PORT = process.env.NODE_API_PORT || 3001;

app.use(cors());
app.use(express.json());

const repo = new PrismaIncidentRepository(db);
const queue = new BullMqIncidentQueue();
const formationService = new IncidentFormationService(repo, queue);
const samplingQueue = new BullMqSamplingQueue();
const sampler = new AdaptiveSamplingService(samplingQueue, {});
```

### Endpoint (lines 92-167)

```typescript
app.post("/api/traces", async (req, res) => {
  try {
    const body = req.body;
    if (!body.execution_id) {
      return res.status(400).json({ error: "execution_id is required" });
    }

    // Build risk-engine Execution from incoming telemetry
    const execution = {
      latencyMs: body.total_latency_ms ?? 0,
      promptTokens: body.total_prompt_tokens ?? 0,
      completionTokens: body.total_completion_tokens ?? 0,
      toolExecutions: (body.steps ?? []).map((s: any) => ({
        toolName: s.tool_name ?? "unknown",
        success: s.success ?? true,
      })),
      retryCount: body.retry_count ?? 0,
      hasFinalResponse: body.crashed !== true,
      crashed: body.crashed ?? false,
      contextWindowExceeded: body.context_window_exceeded ?? false,
    };

    const risk = evaluate(execution, defaultRiskConfig);
    const labels = normalizeRiskLabels({
      severity: risk.severity as any,
      labels: risk.labels,
    });
    const timestamp = new Date();
    const agentSteps = body.steps ?? [];
    const telemetry = {
      total_latency_ms: body.total_latency_ms,
      total_prompt_tokens: body.total_prompt_tokens,
      total_completion_tokens: body.total_completion_tokens,
      tool_call_count: agentSteps.length,
      failed_tool_calls: agentSteps.filter((s: any) => !s.success).length,
      retry_count: body.retry_count,
    };

    // HEALTHY → adaptive sampling
    if (risk.severity === "HEALTHY") {
      const sampled = await sampler.process({
        executionId: body.execution_id,
        traceId: body.trace_id,
        timestamp,
        agentSteps,
        telemetry,
      });
      return res.status(200).json({
        status: "healthy",
        execution_id: body.execution_id,
        severity: "HEALTHY",
        labels,
        sampled,
      });
    }

    // SUSPICIOUS/CRITICAL → incident formation (creates incident + enqueues)
    const result = await formationService.process({
      severity: risk.severity,
      labels,
      executionId: body.execution_id,
      traceId: body.trace_id,
      timestamp,
      agent_steps: agentSteps,
      telemetry,
    });

    const incidentId = result.action !== "SKIPPED" ? result.incident.id : undefined;

    return res.status(result.action === "CREATED" ? 201 : 200).json({
      status: result.action === "CREATED" ? "incident_created" : "incident_updated",
      execution_id: body.execution_id,
      severity: risk.severity,
      labels,
      incident_id: incidentId,
    });

  } catch (err) {
    console.error("[traces] error:", err);
    return res.status(500).json({ error: "Internal server error" });
  }
});
```

**Key points:**
- `fingerprint` is NOT generated in the endpoint — `IncidentFormationService` owns it
- `normalizeRiskLabels` receives severity cast to avoid type mismatch between risk-engine's `"HEALTHY"` value and incident-fingerprint's `Severity` type
- Response is immediate — client does NOT wait for evaluator or issue agent

---

## IncidentFormationService — fingerprint generation (`packages/incident-formation/src/service.ts`)

`IncidentInput.fingerprint` is now optional. If absent, the service computes it from labels:

```typescript
import { generateFingerprint } from "@void-server/incident-fingerprint";

async process(input: IncidentInput): Promise<ProcessResult> {
  if (input.severity === "HEALTHY") {
    return { action: "SKIPPED" };
  }

  const fingerprint = input.fingerprint ?? generateFingerprint(input.labels);
  const existing = await this.repo.findByFingerprint(fingerprint);
  // ...
  created = await this.repo.create({
    fingerprint,  // ← uses local var, not input.fingerprint
    // ...
  });
}
```

---

## Adaptive sampling — queue payload (`packages/adaptive-sampling/src/queue.ts`)

The enqueue method now includes `agentSteps` and `telemetry` so the sampling consumer has the trace data:

```typescript
async enqueue(sample: SamplingInput): Promise<void> {
  const payload = {
    executionId: sample.executionId,
    traceId: sample.traceId,
    timestamp: sample.timestamp.toISOString(),
    agentSteps: sample.agentSteps,
    telemetry: sample.telemetry,
  };
  await this.queue.add("sample", payload, {
    removeOnComplete: { count: 1000 },
    removeOnFail: { count: 1000 },
  });
}
```

---

## Sampling consumer — promotion via IncidentFormationService (`apps/node-api/src/sampling-consumer.ts`)

After the evaluator finds a REAL_INCIDENT, fingerprint is computed from evaluator failure_modes (not `sampled:{executionId}`), then piped through `IncidentFormationService`:

```typescript
import { IncidentFormationService, PrismaIncidentRepository, BullMqIncidentQueue } from "@void-server/incident-formation";
import { createHash } from "node:crypto";

const formationService = new IncidentFormationService(
  new PrismaIncidentRepository(db),
  new BullMqIncidentQueue()
);

// ... evaluator runs, gets classification + failureModes ...

if (!promoted) {
  console.log(`[sampling] skipped ${sample.executionId}: ${classification} (confidence: ${confidence})`);
  return;
}

// Fingerprint from evaluator failure modes → same failure pattern = same fingerprint
const fingerprint = createHash("sha256")
  .update(failureModes.sort().join("|"))
  .digest("hex");

await formationService.process({
  fingerprint,
  severity: "SUSPICIOUS",
  labels: [],
  executionId: sample.executionId,
  traceId: sample.traceId,
  timestamp: new Date(sample.timestamp),
  agent_steps: sample.agentSteps,
  telemetry: sample.telemetry,
});
```

**This unifies both paths:**
- Deterministic SUSPICIOUS/CRITICAL → `IncidentFormationService` generates fingerprint from risk labels
- Promoted samples → explicit fingerprint from evaluator failure_modes, same service

Both converge through `incident-analysis` queue into the same worker.

---

## Request body (SDK-facing contract)

```json
{
  "execution_id": "string (required)",
  "trace_id": "string (optional)",
  "agent": { "name": "string", "role": "string" },
  "model": "string",
  "steps": [
    {
      "tool_name": "string",
      "input": {},
      "output": "string",
      "success": true,
      "latency_ms": 123,
      "error": null
    }
  ],
  "total_latency_ms": 5000,
  "total_prompt_tokens": 1000,
  "total_completion_tokens": 2000,
  "retry_count": 0,
  "crashed": false,
  "context_window_exceeded": false
}
```

Only `execution_id` is required. Everything else defaults safely to 0 / false / [].

---

## Response shapes

```json
// HEALTHY (not sampled)
{ "status": "healthy", "execution_id": "...", "severity": "HEALTHY", "labels": [], "sampled": false }

// HEALTHY (sampled — 1/N hit)
{ "status": "healthy", "execution_id": "...", "severity": "HEALTHY", "labels": [], "sampled": true }

// SUSPICIOUS (new incident)
{ "status": "incident_created", "execution_id": "...", "severity": "SUSPICIOUS", "labels": ["HIGH_LATENCY"], "incident_id": "uuid" }

// CRITICAL (duplicate — updated occurrence)
{ "status": "incident_updated", "execution_id": "...", "severity": "CRITICAL", "labels": ["TOOL_FAILURE"], "incident_id": "uuid" }

// Missing execution_id
400 { "error": "execution_id is required" }
```

---

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Both workers + endpoint |
| `PROMOTION_CONFIDENCE_THRESHOLD` | `0.7` | Sampling consumer |

---

## Running

```sh
# API server (includes /api/traces endpoint)
npm run dev --workspace=@void-server/node-api

# Incident analysis worker (evaluator + issue agent)
npm run dev:worker --workspace=@void-server/node-api

# Adaptive sampling consumer
npm run dev:sampling --workspace=@void-server/node-api
```

---

## Files changed

| File | Change |
|---|---|
| `apps/node-api/package.json` | Added 4 workspace dependencies |
| `apps/node-api/src/index.ts` | Added `POST /api/traces` endpoint |
| `packages/incident-formation/src/types.ts` | `fingerprint` optional in `IncidentInput` |
| `packages/incident-formation/src/service.ts` | Generate fingerprint from labels if absent |
| `packages/adaptive-sampling/src/queue.ts` | Include `agentSteps` + `telemetry` in payload |
| `apps/node-api/src/sampling-consumer.ts` | Replace `db.incident.upsert` with `formationService.process()` |