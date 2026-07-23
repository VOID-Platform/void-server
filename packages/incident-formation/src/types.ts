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
  agent_steps?: unknown;
  telemetry?: unknown;
}

export type ProcessResult =
  | { incident: IncidentRecord; action: "CREATED" | "UPDATED" }
  | { action: "SKIPPED" };

export type IncidentRecord = Incident;

export interface IncidentRepository {
  findByFingerprint(fingerprint: string): Promise<IncidentRecord | null>;
  create(data: CreateIncidentData): Promise<IncidentRecord>;
  update(id: string, data: UpdateIncidentData): Promise<IncidentRecord>;
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
  agent_steps?: unknown;
  telemetry?: unknown;
}

export interface UpdateIncidentData {
  occurrence?: number | { increment: number };
  execution_id?: string;
  trace_id?: string;
  severity?: RiskSeverity;
  title?: string;
  last_seen?: Date;
  latest_labels?: RiskLabel[];
  agent_steps?: unknown;
  telemetry?: unknown;
}

export interface IncidentQueue {
  enqueueAnalysis(jobName: JobType, incidentId: string, fingerprint: string): Promise<void>;
  close(): Promise<void>;
}

export interface QueueConnectionConfig {
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  db?: number;
  tls?: Record<string, unknown>;
  url?: string;
}

export const JOB_TYPES = {
  EVALUATE: "evaluate-incident" as JobType,
  CRITICAL: "critical-incident" as JobType,
} as const;
