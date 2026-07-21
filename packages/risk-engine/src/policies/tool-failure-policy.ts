import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateToolFailurePolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  const failedTools = execution.toolExecutions.filter((t) => !t.success).length;
  if (failedTools > 0 && failedTools >= policies.toolFailureThreshold) {
    return { label: RiskLabel.TOOL_FAILURE, severity: "CRITICAL" };
  }
  return null;
}
