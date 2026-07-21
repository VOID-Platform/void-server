import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateRetryPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  if (execution.retryCount > policies.retryThreshold) {
    return { label: RiskLabel.EXCESSIVE_RETRIES, severity: "WARNING" };
  }
  return null;
}
