import { describe, it, expect } from "vitest";
import { evaluateLatencyPolicy } from "./latency-policy";
import { Execution, RiskLabel, RiskPolicies } from "../types";

const policies: RiskPolicies = {
  latencyMs: 3000,
  tokenBudget: 25000,
  toolFailureThreshold: 1,
  repeatedToolThreshold: 3,
  retryThreshold: 3,
  warningThreshold: 3,
};

function makeExecution(latencyMs: number): Execution {
  return {
    latencyMs,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions: [],
    retryCount: 0,
    hasFinalResponse: true,
    crashed: false,
    contextWindowExceeded: false,
  };
}

describe("LatencyPolicy", () => {
  it("returns null when latency is below threshold", () => {
    const result = evaluateLatencyPolicy(makeExecution(2000), policies);
    expect(result).toBeNull();
  });

  it("returns null when latency equals threshold", () => {
    const result = evaluateLatencyPolicy(makeExecution(3000), policies);
    expect(result).toBeNull();
  });

  it("returns HIGH_LATENCY when latency exceeds threshold", () => {
    const result = evaluateLatencyPolicy(makeExecution(3500), policies);
    expect(result).toEqual({ label: RiskLabel.HIGH_LATENCY, severity: "WARNING" });
  });
});
