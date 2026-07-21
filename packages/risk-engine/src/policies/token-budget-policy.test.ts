import { describe, it, expect } from "vitest";
import { evaluateTokenBudgetPolicy } from "./token-budget-policy";
import { Execution, RiskLabel, RiskPolicies } from "../types";

const policies: RiskPolicies = {
  latencyMs: 3000,
  tokenBudget: 25000,
  toolFailureThreshold: 1,
  repeatedToolThreshold: 3,
  retryThreshold: 3,
  warningThreshold: 3,
};

function makeExecution(
  promptTokens: number,
  completionTokens: number,
): Execution {
  return {
    latencyMs: 0,
    promptTokens,
    completionTokens,
    toolExecutions: [],
    retryCount: 0,
    hasFinalResponse: true,
    crashed: false,
    contextWindowExceeded: false,
  };
}

describe("TokenBudgetPolicy", () => {
  it("returns null when under budget", () => {
    const result = evaluateTokenBudgetPolicy(makeExecution(10000, 5000), policies);
    expect(result).toBeNull();
  });

  it("returns null when exactly at budget", () => {
    const result = evaluateTokenBudgetPolicy(makeExecution(25000, 0), policies);
    expect(result).toBeNull();
  });

  it("returns TOKEN_BUDGET_EXCEEDED when over budget", () => {
    const result = evaluateTokenBudgetPolicy(makeExecution(20000, 10000), policies);
    expect(result).toEqual({
      label: RiskLabel.TOKEN_BUDGET_EXCEEDED,
      severity: "WARNING",
    });
  });
});
