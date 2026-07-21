import { Execution, PolicyResult, RiskLabel } from "../types";

export function evaluateContextOverflowPolicy(
  execution: Execution,
): PolicyResult | null {
  if (execution.contextWindowExceeded) {
    return { label: RiskLabel.CONTEXT_OVERFLOW, severity: "WARNING" };
  }
  return null;
}
