import { Execution, PolicyResult, RiskLabel } from "../types";

export function evaluateAgentCrashPolicy(
  execution: Execution,
): PolicyResult | null {
  if (execution.crashed) {
    return { label: RiskLabel.AGENT_CRASH, severity: "CRITICAL" };
  }
  return null;
}
