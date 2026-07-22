export enum RiskLabel {
  HIGH_LATENCY = "HIGH_LATENCY",
  TOOL_FAILURE = "TOOL_FAILURE",
  NO_FINAL_RESPONSE = "NO_FINAL_RESPONSE",
  AGENT_CRASH = "AGENT_CRASH",
  CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW",
  REPEATED_TOOL_CALLS = "REPEATED_TOOL_CALLS",
  TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED",
}

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | "SUSPICIOUS";

export interface RiskEvaluationResult {
  severity: Severity;
  labels: RiskLabel[];
}
