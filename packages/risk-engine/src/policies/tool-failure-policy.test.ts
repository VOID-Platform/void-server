import { describe, it, expect } from "vitest";
import { evaluateToolFailurePolicy } from "./tool-failure-policy";
import { Execution, RiskLabel, RiskPolicies, ToolExecution } from "../types";

const policies: RiskPolicies = {
  latencyMs: 3000,
  tokenBudget: 25000,
  toolFailureThreshold: 1,
  repeatedToolThreshold: 3,
  retryThreshold: 3,
  warningThreshold: 3,
};

function makeExecution(toolExecutions: ToolExecution[]): Execution {
  return {
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions,
    retryCount: 0,
    hasFinalResponse: true,
    crashed: false,
    contextWindowExceeded: false,
  };
}

const success = (name: string): ToolExecution => ({
  toolName: name,
  success: true,
});

const failure = (name: string): ToolExecution => ({
  toolName: name,
  success: false,
});

describe("ToolFailurePolicy", () => {
  it("returns null when no failures", () => {
    const result = evaluateToolFailurePolicy(
      makeExecution([success("search"), success("read")]),
      policies,
    );
    expect(result).toBeNull();
  });

  it("returns null when below threshold", () => {
    const result = evaluateToolFailurePolicy(makeExecution([]), policies);
    expect(result).toBeNull();
  });

  it("returns TOOL_FAILURE when failures equals threshold", () => {
    const result = evaluateToolFailurePolicy(
      makeExecution([failure("search")]),
      policies,
    );
    expect(result).toEqual({ label: RiskLabel.TOOL_FAILURE, severity: "CRITICAL" });
  });

  it("returns TOOL_FAILURE when failures exceed threshold", () => {
    const result = evaluateToolFailurePolicy(
      makeExecution([failure("search"), failure("read")]),
      policies,
    );
    expect(result).toEqual({ label: RiskLabel.TOOL_FAILURE, severity: "CRITICAL" });
  });
});
