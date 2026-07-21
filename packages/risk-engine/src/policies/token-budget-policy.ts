import { Execution, PolicyResult, RiskLabel, RiskPolicies } from "../types";

export function evaluateTokenBudgetPolicy(
  execution: Execution,
  policies: RiskPolicies,
): PolicyResult | null {
  const totalTokens = execution.promptTokens + execution.completionTokens;
  if (totalTokens > policies.tokenBudget) {
    return { label: RiskLabel.TOKEN_BUDGET_EXCEEDED, severity: "WARNING" };
  }
  return null;
}
