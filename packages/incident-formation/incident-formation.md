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
- Escalate non-critical incidents to critical when a critical event arrives (`critical-incident`).
- Guarantee idempotent behavior across execution retries.

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
  │  create       create/escalate
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

export type RiskSeverity = "HEALTHY" | "SUSPICIOUS" | "CRITICAL";
export type AnalysisStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
export type JobType = "evaluate-incident" | "critical-incident";

export interface IncidentInput {
  fingerprint: string;
  severity: RiskSeverity;
  labels: RiskLabel[];
  executionId: string;
  traceId?: string;
  timestamp: Date;
}

export type ProcessResult =
  | { incident: IncidentRecord; action: "CREATED" | "UPDATED" }
  | { action: "SKIPPED" };

export type IncidentRecord = Incident;

export interface IncidentRepository {
  findByFingerprint(fingerprint: string, includeReports?: boolean): Promise<IncidentRecord | null>;
  create(data: CreateIncidentData, includeReports?: boolean): Promise<IncidentRecord>;
  update(id: string, data: UpdateIncidentData, includeReports?: boolean): Promise<IncidentRecord>;
}

export interface CreateIncidentData {
  fingerprint: string;
  trace_id: string;
  execution_id: string;
  title: string;
  severity: RiskSeverity;
  status: string;
  confidence: number;
  first_scene: string;
  last_scene: string;
  occurrence: number;
  last_seen: Date;
  analysis_status: AnalysisStatus;
  latest_labels: RiskLabel[];
}

export interface UpdateIncidentData {
  occurrence?: number | { increment: number };
  execution_id?: string;
  trace_id?: string;
  severity?: RiskSeverity;
  title?: string;
  last_seen?: Date;
  latest_labels?: RiskLabel[];
}

export interface IncidentQueue {
  enqueueAnalysis(jobName: JobType, incidentId: string, fingerprint: string): Promise<void>;
  close(): Promise<void>;
}

export interface QueueConnectionConfig {
  host?: string;
  port?: number;
  password?: string;
  db?: number;
  url?: string;
}
```

## Repository

```ts
import type { PrismaClient } from "@void-server/db";
import type { IncidentRecord, IncidentRepository, CreateIncidentData, UpdateIncidentData } from "./types";

export class PrismaIncidentRepository implements IncidentRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async findByFingerprint(fingerprint: string, includeReports = false): Promise<IncidentRecord | null> {
    return this.prisma.incident.findUnique({
      where: { fingerprint },
      ...(includeReports ? { include: { reports: true } } : {}),
    }) as Promise<IncidentRecord | null>;
  }

  async create(data: CreateIncidentData, includeReports = false): Promise<IncidentRecord> {
    return this.prisma.incident.create({
      data: data as any,
      ...(includeReports ? { include: { reports: true } } : {}),
    }) as Promise<IncidentRecord>;
  }

  async update(id: string, data: UpdateIncidentData, includeReports = false): Promise<IncidentRecord> {
    return this.prisma.incident.update({
      where: { id },
      data: data as any,
      ...(includeReports ? { include: { reports: true } } : {}),
    }) as Promise<IncidentRecord>;
  }
}
```

## Queue

```ts
import { Queue } from "bullmq";
import type { IncidentQueue, QueueConnectionConfig, JobType } from "./types";

function parseRedisUrl(urlStr: string): QueueConnectionConfig {
  try {
    const parsed = new URL(urlStr);
    return {
      host: parsed.hostname || "localhost",
      port: parsed.port ? parseInt(parsed.port, 10) : 6379,
      password: parsed.password ? decodeURIComponent(parsed.password) : undefined,
      db: parsed.pathname ? parseInt(parsed.pathname.replace("/", ""), 10) || 0 : 0,
    };
  } catch {
    return { host: "localhost", port: 6379 };
  }
}

function resolveConnectionConfig(config?: QueueConnectionConfig): QueueConnectionConfig {
  if (config) return config;
  const envUrl = process.env.REDIS_URL;
  if (envUrl) return parseRedisUrl(envUrl);
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
2. `REDIS_URL` env var → parsed host/port/password/db connection object.
3. Default → `{ host: "localhost", port: 6379 }`.

## Service

```ts
import type { RiskLabel } from "@void-server/incident-fingerprint";
import type { IncidentInput, IncidentRepository, IncidentQueue, ProcessResult, UpdateIncidentData } from "./types";
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
      if (existing.execution_id === input.executionId) {
        return { incident: existing, action: "UPDATED" };
      }

      const lastSeen =
        existing.last_seen && existing.last_seen > input.timestamp
          ? existing.last_seen
          : input.timestamp;

      const isEscalating = input.severity === "CRITICAL" && existing.severity !== "CRITICAL";

      const updated = await this.repo.update(existing.id, {
        occurrence: { increment: 1 } as any,
        execution_id: input.executionId,
        ...(input.traceId ? { trace_id: input.traceId } : {}),
        last_seen: lastSeen,
        latest_labels: input.labels,
        ...(isEscalating
          ? { severity: "CRITICAL", title: generateTitle("CRITICAL", input.labels) }
          : {}),
      });

      if (isEscalating) {
        await this.queue.enqueueAnalysis(JOB_TYPES.CRITICAL, updated.id, updated.fingerprint);
      }

      return { incident: updated, action: "UPDATED" };
    }

    try {
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
    } catch (err) {
      const raceExisting = await this.repo.findByFingerprint(input.fingerprint);
      if (raceExisting) {
        return this.process(input);
      }
      throw err;
    }
  }
}
```

## Idempotency & Concurrency

- **Deduplication**: Retrying the same `executionId` returns `{ incident: existing, action: "UPDATED" }` without inflating `occurrence` or updating timestamps.
- **Database**: Fingerprint is the unique key. Atomic database `{ increment: 1 }` increments the occurrence count safely under concurrency.
- **Timestamp Protection**: `last_seen` retains the maximum timestamp to ensure out-of-order events do not move recency backwards.
- **Queue**: `jobId = incidentId` in BullMQ prevents duplicate jobs. Newly created incidents (and critical escalations) are enqueued safely.
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
import { RiskLabel } from "@void-server/incident-fingerprint";
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

- **Idempotent & Concurrency-Safe** — execution-level deduplication and atomic counter updates.
- **Severity-routed & Escalating** — healthy skipped; suspicious queued for evaluator; critical (and escalations) queued for immediate issue agent response.
- **PostgreSQL is source of truth** — Redis is only a queue backend.
- **Minimal queue payloads** — only `incidentId` + `fingerprint`, no traces or telemetry.
- **Dependency injection** — repository and queue are injected through interfaces.
- **Deterministic** — no LLM or evaluator in this component.
 queue are injected through interfaces.
- **Deterministic** — no LLM or evaluator in this component.
