export enum RiskLabel {
  HIGH_LATENCY = "HIGH_LATENCY",
  TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED",
  TOOL_FAILURE = "TOOL_FAILURE",
  REPEATED_TOOL_CALLS = "REPEATED_TOOL_CALLS",
  EXCESSIVE_RETRIES = "EXCESSIVE_RETRIES",
  NO_FINAL_RESPONSE = "NO_FINAL_RESPONSE",
  AGENT_CRASH = "AGENT_CRASH",
  CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW",
}

export type PolicySeverity = "WARNING" | "CRITICAL";

export type EvaluationSeverity = "HEALTHY" | "SUSPICIOUS" | "CRITICAL";

export interface PolicyResult {
  label: RiskLabel;
  severity: PolicySeverity;
}

export interface ToolExecution {
  toolName: string;
  success: boolean;
}

export interface Execution {
  latencyMs: number;
  promptTokens: number;
  completionTokens: number;
  toolExecutions: ToolExecution[];
  retryCount: number;
  hasFinalResponse: boolean;
  crashed: boolean;
  contextWindowExceeded: boolean;
}

export interface RiskEvaluationResult {
  labels: RiskLabel[];
  warningCount: number;
  criticalCount: number;
  severity: EvaluationSeverity;
}

export interface RiskPolicies {
  latencyMs: number;
  tokenBudget: number;
  toolFailureThreshold: number;
  repeatedToolThreshold: number;
  retryThreshold: number;
  warningThreshold: number;
}

export interface RiskConfig {
  policies: RiskPolicies;
}
