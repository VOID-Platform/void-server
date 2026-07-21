import { describe, it, expect } from "vitest";
import { evaluateRetryPolicy } from "./retry-policy";
import { Execution, RiskLabel, RiskPolicies } from "../types";

const policies: RiskPolicies = {
  latencyMs: 3000,
  tokenBudget: 25000,
  toolFailureThreshold: 1,
  repeatedToolThreshold: 3,
  retryThreshold: 3,
  warningThreshold: 3,
};

function makeExecution(retryCount: number): Execution {
  return {
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions: [],
    retryCount,
    hasFinalResponse: true,
    crashed: false,
    contextWindowExceeded: false,
  };
}

describe("RetryPolicy", () => {
  it("returns null when no retries", () => {
    const result = evaluateRetryPolicy(makeExecution(0), policies);
    expect(result).toBeNull();
  });

  it("returns null when retries at threshold", () => {
    const result = evaluateRetryPolicy(makeExecution(3), policies);
    expect(result).toBeNull();
  });

  it("returns EXCESSIVE_RETRIES when retries exceed threshold", () => {
    const result = evaluateRetryPolicy(makeExecution(4), policies);
    expect(result).toEqual({ label: RiskLabel.EXCESSIVE_RETRIES, severity: "WARNING" });
  });

  it("respects custom retryThreshold", () => {
    const customPolicies = { ...policies, retryThreshold: 5 };
    const result = evaluateRetryPolicy(makeExecution(5), customPolicies);
    expect(result).toBeNull();
  });
});
