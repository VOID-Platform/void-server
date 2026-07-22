export { RiskLabel } from "@void-server/risk-engine";

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | "SUSPICIOUS";

export interface RiskEvaluationResult {
  severity: Severity;
  labels: RiskLabel[];
}
