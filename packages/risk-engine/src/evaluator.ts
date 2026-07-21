import { Execution, PolicyResult, RiskConfig, RiskEvaluationResult, RiskLabel } from "./types";
import { evaluateLatencyPolicy } from "./policies/latency-policy";
import { evaluateTokenBudgetPolicy } from "./policies/token-budget-policy";
import { evaluateToolFailurePolicy } from "./policies/tool-failure-policy";
import { evaluateRepeatedToolPolicy } from "./policies/repeated-tool-policy";
import { evaluateRetryPolicy } from "./policies/retry-policy";
import { evaluateNoResponsePolicy } from "./policies/no-response-policy";
import { evaluateAgentCrashPolicy } from "./policies/agent-crash-policy";
import { evaluateContextOverflowPolicy } from "./policies/context-overflow-policy";

// TODO(v2):
// Risk Evaluation currently operates on normalized execution metadata.
// Future versions should support distributed execution graphs reconstructed
// from multiple OpenTelemetry traces.

type Policy = (execution: Execution, config: RiskConfig) => PolicyResult | null;

const policies: Policy[] = [
  (execution, config) => evaluateLatencyPolicy(execution, config.policies),
  (execution, config) => evaluateTokenBudgetPolicy(execution, config.policies),
  (execution, config) => evaluateToolFailurePolicy(execution, config.policies),
  (execution, config) => evaluateRepeatedToolPolicy(execution, config.policies),
  (execution, config) => evaluateRetryPolicy(execution, config.policies),
  (execution) => evaluateNoResponsePolicy(execution),
  (execution) => evaluateAgentCrashPolicy(execution),
  (execution) => evaluateContextOverflowPolicy(execution),
];

interface ValidationError {
  field: string;
  reason: string;
}

function validateExecution(execution: Execution): ValidationError[] {
  const errors: ValidationError[] = [];
  if (typeof execution.latencyMs !== "number" || !isFinite(execution.latencyMs) || execution.latencyMs < 0) {
    errors.push({ field: "latencyMs", reason: "must be a finite non-negative number" });
  }
  if (typeof execution.promptTokens !== "number" || !isFinite(execution.promptTokens) || execution.promptTokens < 0) {
    errors.push({ field: "promptTokens", reason: "must be a finite non-negative number" });
  }
  if (typeof execution.completionTokens !== "number" || !isFinite(execution.completionTokens) || execution.completionTokens < 0) {
    errors.push({ field: "completionTokens", reason: "must be a finite non-negative number" });
  }
  if (!Array.isArray(execution.toolExecutions)) {
    errors.push({ field: "toolExecutions", reason: "must be an array" });
  }
  if (typeof execution.retryCount !== "number" || !isFinite(execution.retryCount) || execution.retryCount < 0 || !Number.isInteger(execution.retryCount)) {
    errors.push({ field: "retryCount", reason: "must be a finite non-negative integer" });
  }
  if (typeof execution.hasFinalResponse !== "boolean") {
    errors.push({ field: "hasFinalResponse", reason: "must be a boolean" });
  }
  if (typeof execution.crashed !== "boolean") {
    errors.push({ field: "crashed", reason: "must be a boolean" });
  }
  if (typeof execution.contextWindowExceeded !== "boolean") {
    errors.push({ field: "contextWindowExceeded", reason: "must be a boolean" });
  }
  return errors;
}

function validateConfig(config: RiskConfig): ValidationError[] {
  const errors: ValidationError[] = [];
  const p = config.policies;
  if (typeof p.latencyMs !== "number" || !isFinite(p.latencyMs) || p.latencyMs <= 0) {
    errors.push({ field: "policies.latencyMs", reason: "must be a finite positive number" });
  }
  if (typeof p.tokenBudget !== "number" || !isFinite(p.tokenBudget) || p.tokenBudget <= 0) {
    errors.push({ field: "policies.tokenBudget", reason: "must be a finite positive number" });
  }
  if (typeof p.toolFailureThreshold !== "number" || !isFinite(p.toolFailureThreshold) || p.toolFailureThreshold < 0 || !Number.isInteger(p.toolFailureThreshold)) {
    errors.push({ field: "policies.toolFailureThreshold", reason: "must be a finite non-negative integer" });
  }
  if (typeof p.repeatedToolThreshold !== "number" || !isFinite(p.repeatedToolThreshold) || p.repeatedToolThreshold <= 0 || !Number.isInteger(p.repeatedToolThreshold)) {
    errors.push({ field: "policies.repeatedToolThreshold", reason: "must be a finite positive integer" });
  }
  if (typeof p.retryThreshold !== "number" || !isFinite(p.retryThreshold) || p.retryThreshold <= 0 || !Number.isInteger(p.retryThreshold)) {
    errors.push({ field: "policies.retryThreshold", reason: "must be a finite positive integer" });
  }
  if (typeof p.warningThreshold !== "number" || !isFinite(p.warningThreshold) || p.warningThreshold <= 0 || !Number.isInteger(p.warningThreshold)) {
    errors.push({ field: "policies.warningThreshold", reason: "must be a finite positive integer" });
  }
  return errors;
}

export function evaluate(execution: Execution, config: RiskConfig): RiskEvaluationResult {
  const execErrors = validateExecution(execution);
  if (execErrors.length > 0) {
    return {
      labels: [RiskLabel.INVALID_EXECUTION_INPUT],
      warningCount: 0,
      criticalCount: 1,
      severity: "CRITICAL",
    };
  }

  const configErrors = validateConfig(config);
  if (configErrors.length > 0) {
    return {
      labels: [RiskLabel.INVALID_CONFIG_INPUT],
      warningCount: 0,
      criticalCount: 1,
      severity: "CRITICAL",
    };
  }

  const results: PolicyResult[] = [];

  for (const policy of policies) {
    const result = policy(execution, config);
    if (result !== null) {
      results.push(result);
    }
  }

  const labels = results.map((r) => r.label);
  const warningCount = results.filter((r) => r.severity === "WARNING").length;
  const criticalCount = results.filter((r) => r.severity === "CRITICAL").length;

  let severity: RiskEvaluationResult["severity"] = "HEALTHY";
  if (criticalCount > 0) {
    severity = "CRITICAL";
  } else if (warningCount >= config.policies.warningThreshold) {
    severity = "SUSPICIOUS";
  }

  return { labels, warningCount, criticalCount, severity };
}
