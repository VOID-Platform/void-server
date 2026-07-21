import { Execution, PolicyResult, RiskLabel } from "../types";

export function evaluateNoResponsePolicy(
  execution: Execution,
): PolicyResult | null {
  if (!execution.hasFinalResponse) {
    return { label: RiskLabel.NO_FINAL_RESPONSE, severity: "CRITICAL" };
  }
  return null;
}
