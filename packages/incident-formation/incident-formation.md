# Incident Formation Service

## Pipeline

```
Risk Evaluation Result
        ↓
normalizeRiskLabels()
        ↓
generateFingerprint()
        ↓
Incident Formation Service   ← this package
        ↓
PostgreSQL (source of truth)
        ↓
BullMQ (analysis queue)
```

## Responsibilities

- Ignore healthy executions — no persistence, no queue.
- Persist suspicious and critical incidents.
- Queue suspicious incidents for AI evaluation (`evaluate-incident`).
- Queue critical incidents for immediate processing (`critical-incident`).
- Guarantee idempotent behavior.

## Flow

```
IncidentInput
     ↓
  severity?
     │
  ┌──┼──┐
  │  │  │
HEALTHY SUSPICIOUS CRITICAL
  │     │          │
  │  find/create  find/create
  │     │          │
  │  update/      update/
  │  create       create
  │     │          │
  │  queue        queue
  │  "evaluate"   "critical"
  │     │          │
 return  return     return
{SKIPPED} {incident, action}
```

## Types

```ts
import type { Incident } from "@void-server/db";
import type { RiskLabel } from "@void-server/incident-fingerprint";

type RiskSeverity = "HEALTHY" | "SUSPICIOUS" | "CRITICAL";
type AnalysisStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
type JobType = "evaluate-incident" | "critical-incident";

interface IncidentInput {
  fingerprint: string;
  severity: RiskSeverity;
  labels: RiskLabel[];
  executionId: string;
  traceId?: string;
  timestamp: Date;
}

type ProcessResult =
  | { incident: IncidentRecord; action: "CREATED" | "UPDATED" }
  | { action: "SKIPPED" };

interface IncidentRepository {
  findByFingerprint(fingerprint: string): Promise<IncidentRecord | null>;
  create(data: CreateIncidentData): Promise<IncidentRecord>;
  update(id: string, data: UpdateIncidentData): Promise<IncidentRecord>;
}

interface IncidentQueue {
  enqueueAnalysis(jobName: JobType, incidentId: string, fingerprint: string): Promise<void>;
  close(): Promise<void>;
}
```

## Repository

```ts
import type { PrismaClient } from "@void-server/db";

export class PrismaIncidentRepository implements IncidentRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async findByFingerprint(fingerprint: string): Promise<IncidentRecord | null> {
    return this.prisma.incident.findUnique({
      where: { fingerprint },
      include: { reports: true },
    });
  }

  async create(data: CreateIncidentData): Promise<IncidentRecord> {
    return this.prisma.incident.create({ data, include: { reports: true } });
  }

  async update(id: string, data: UpdateIncidentData): Promise<IncidentRecord> {
    return this.prisma.incident.update({
      where: { id },
      data,
      include: { reports: true },
    });
  }
}
```

## Queue

```ts
import { Queue } from "bullmq";

function resolveConnectionConfig(config?: QueueConnectionConfig): QueueConnectionConfig {
  if (config) return config;
  const envUrl = process.env.REDIS_URL;
  if (envUrl) return { url: envUrl };
  return { host: "localhost", port: 6379 };
}

export class BullMqIncidentQueue implements IncidentQueue {
  private readonly queue: Queue;

  constructor(config?: QueueConnectionConfig) {
    const connection = resolveConnectionConfig(config);
    this.queue = new Queue("incident-analysis", { connection });
  }

  async enqueueAnalysis(jobName: JobType, incidentId: string, fingerprint: string): Promise<void> {
    await this.queue.add(
      jobName,
      { incidentId, fingerprint },
      { jobId: incidentId },
    );
  }

  async close(): Promise<void> {
    await this.queue.close();
  }
}
```

### Queue Routing

| Severity    | Job Name               | Destined For |
|-------------|------------------------|--------------|
| HEALTHY     | — (skipped)            | —            |
| SUSPICIOUS  | `evaluate-incident`    | Evaluator    |
| CRITICAL    | `critical-incident`    | Issue Agent  |

### Connection Resolution

1. Explicit `QueueConnectionConfig` → used as-is.
2. `REDIS_URL` env var → `{ url: REDIS_URL }`.
3. Default → `{ host: "localhost", port: 6379 }`.

## Service

```ts
import { JOB_TYPES } from "./types";

export function generateTitle(severity: string, labels: RiskLabel[]): string {
  if (labels.length === 0) return severity;
  return `${severity}: ${labels.join(" + ")}`;
}

export class IncidentFormationService {
  constructor(
    private readonly repo: IncidentRepository,
    private readonly queue: IncidentQueue,
  ) {}

  async process(input: IncidentInput): Promise<ProcessResult> {
    if (input.severity === "HEALTHY") {
      return { action: "SKIPPED" };
    }

    const existing = await this.repo.findByFingerprint(input.fingerprint);

    if (existing) {
      const updated = await this.repo.update(existing.id, {
        occurrence: existing.occurrence + 1,
        execution_id: input.executionId,
        last_seen: input.timestamp,
        latest_labels: input.labels,
      });
      return { incident: updated, action: "UPDATED" };
    }

    const isCritical = input.severity === "CRITICAL";

    const created = await this.repo.create({
      fingerprint: input.fingerprint,
      trace_id: input.traceId ?? "",
      execution_id: input.executionId,
      title: generateTitle(input.severity, input.labels),
      severity: input.severity,
      status: "OPEN",
      confidence: 0,
      first_scene: "",
      last_scene: "",
      occurrence: 1,
      last_seen: input.timestamp,
      analysis_status: "PENDING",
      latest_labels: input.labels,
    });

    const jobType = isCritical ? JOB_TYPES.CRITICAL : JOB_TYPES.EVALUATE;

    await this.queue.enqueueAnalysis(jobType, created.id, created.fingerprint);

    return { incident: created, action: "CREATED" };
  }
}
```

## Idempotency

- **Database**: fingerprint is the unique key. Same fingerprint → update (`UPDATED`). Different → create (`CREATED`). Never creates duplicate incidents.
- **Queue**: `jobId = incidentId` in BullMQ prevents duplicate jobs. Only newly created incidents are enqueued. Updates never re-enqueue.
- **Convergence**: Processing the same execution multiple times always converges to the same state.

## Known Limitation (Hackathon Scope)

Create + queue is not atomic:

```
Create Incident ✅
Redis crashes ❌
```

If queueing fails after creation, the incident persists with `analysis_status = "PENDING"` and no job in the queue. A future recovery worker can pick up incidents in this state and re-enqueue them.

This is an accepted tradeoff. Distributed transactions are out of scope.

## Usage

```ts
import { PrismaClient } from "@void-server/db";
import {
  PrismaIncidentRepository,
  BullMqIncidentQueue,
  IncidentFormationService,
} from "@void-server/incident-formation";

const repo = new PrismaIncidentRepository(new PrismaClient());
const queue = new BullMqIncidentQueue(); // reads REDIS_URL from env
const service = new IncidentFormationService(repo, queue);

const result = await service.process({
  fingerprint: "7e3a9c...",
  severity: "CRITICAL",
  labels: [RiskLabel.AGENT_CRASH, RiskLabel.NO_FINAL_RESPONSE],
  executionId: "exec-123",
  timestamp: new Date(),
});

if (result.action === "SKIPPED") {
  // healthy execution, no-op
} else {
  console.log(result.action, result.incident.id);
}
```

## Key Properties

- **Idempotent** — same input always converges to same state.
- **Severity-routed** — healthy skipped; suspicious/critical persisted and queued with different job names.
- **PostgreSQL is source of truth** — Redis is only a queue backend.
- **Minimal queue payloads** — only `incidentId` + `fingerprint`, no traces or telemetry.
- **Dependency injection** — repository and queue are injected through interfaces.
- **Deterministic** — no LLM or evaluator in this component.
