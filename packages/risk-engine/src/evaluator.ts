import { Execution, PolicyResult, RiskConfig, RiskEvaluationResult } from "./types";
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

export function evaluate(execution: Execution, config: RiskConfig): RiskEvaluationResult {
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
