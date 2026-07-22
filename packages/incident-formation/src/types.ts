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
  findByFingerprint(fingerprint: string): Promise<IncidentRecord | null>;
  create(data: CreateIncidentData): Promise<IncidentRecord>;
  update(id: string, data: UpdateIncidentData): Promise<IncidentRecord>;
}

export interface CreateIncidentData {
  fingerprint: string;
  trace_id: string;
  execution_id: string;
  title: string;
  severity: string;
  status: string;
  confidence: number;
  first_scene: string;
  last_scene: string;
  occurrence: number;
  last_seen: Date;
  analysis_status: string;
  latest_labels: RiskLabel[];
}

export interface UpdateIncidentData {
  occurrence: number;
  execution_id: string;
  last_seen: Date;
  latest_labels: RiskLabel[];
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

export const JOB_TYPES = {
  EVALUATE: "evaluate-incident" as JobType,
  CRITICAL: "critical-incident" as JobType,
} as const;
