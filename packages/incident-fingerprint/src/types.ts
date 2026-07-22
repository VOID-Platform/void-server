import { RiskLabel } from "@void-server/risk-engine";
export { RiskLabel };

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | "SUSPICIOUS";

export interface RiskEvaluationResult {
  severity: Severity;
  labels: RiskLabel[];
}
