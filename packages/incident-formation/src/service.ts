import type { RiskLabel } from "@void-server/incident-fingerprint";
import type { IncidentInput, IncidentRepository, IncidentQueue, ProcessResult } from "./types";
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
