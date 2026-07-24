import type { RiskLabel } from "@void-server/incident-fingerprint";
import { generateFingerprint, generateLegacyFingerprint } from "@void-server/incident-fingerprint";
import type { IncidentInput, IncidentRecord, IncidentRepository, IncidentQueue, ProcessResult } from "./types";
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

    const fingerprint = input.fingerprint ?? generateFingerprint(input.labels);
    let existing = await this.repo.findByFingerprint(fingerprint);

    if (!existing && !input.fingerprint && input.labels.length > 0) {
      const legacyFingerprint = generateLegacyFingerprint(input.labels);
      if (legacyFingerprint !== fingerprint) {
        existing = await this.repo.findByFingerprint(legacyFingerprint);
      }
    }

    if (existing) {
      return this.handleExisting(existing, input);
    }

    let created;
    try {
      created = await this.repo.create({
        fingerprint,
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
        agent_steps: input.agent_steps,
        telemetry: input.telemetry,
      });
    } catch (err: any) {
      if (err?.code === "P2002") {
        let raceExisting = await this.repo.findByFingerprint(fingerprint);
        if (!raceExisting && !input.fingerprint && input.labels.length > 0) {
          const legacyFingerprint = generateLegacyFingerprint(input.labels);
          if (legacyFingerprint !== fingerprint) {
            raceExisting = await this.repo.findByFingerprint(legacyFingerprint);
          }
        }
        if (raceExisting) return this.handleExisting(raceExisting, input);
      }
      throw err;
    }

    const isCritical = input.severity === "CRITICAL";
    const jobType = isCritical ? JOB_TYPES.CRITICAL : JOB_TYPES.EVALUATE;

    await this.queue.enqueueAnalysis(jobType, created.id, created.fingerprint);

    return { incident: created, action: "CREATED" };
  }

  private async handleExisting(existing: IncidentRecord, input: IncidentInput): Promise<ProcessResult> {
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
      ...(input.agent_steps !== undefined ? { agent_steps: input.agent_steps } : {}),
      ...(input.telemetry !== undefined ? { telemetry: input.telemetry } : {}),
      ...(isEscalating
        ? { severity: "CRITICAL", title: generateTitle("CRITICAL", input.labels) }
        : {}),
    });

    if (isEscalating) {
      await this.queue.enqueueAnalysis(JOB_TYPES.CRITICAL, updated.id, updated.fingerprint);
    }

    return { incident: updated, action: "UPDATED" };
  }
}
