import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateRepeatedToolPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  const tools = execution.toolExecutions;
  if (tools.length === 0) return null;

  let maxConsecutive = 1;
  let currentRun = 1;

  for (let i = 1; i < tools.length; i++) {
    if (tools[i].toolName === tools[i - 1].toolName) {
      currentRun++;
      if (currentRun > maxConsecutive) {
        maxConsecutive = currentRun;
      }
    } else {
      currentRun = 1;
    }
  }

  if (maxConsecutive > policies.repeatedToolThreshold) {
    return { label: RiskLabel.REPEATED_TOOL_CALLS, severity: "WARNING" };
  }
  return null;
}
