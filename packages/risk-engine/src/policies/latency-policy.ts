import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateLatencyPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  if (execution.latencyMs > policies.latencyMs) {
    return { label: RiskLabel.HIGH_LATENCY, severity: "WARNING" };
  }
  return null;
}
