import { describe, it, expect } from "vitest";
import { evaluateRepeatedToolPolicy } from "./repeated-tool-policy";
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

const tool = (name: string): ToolExecution => ({
  toolName: name,
  success: true,
});

describe("RepeatedToolPolicy", () => {
  it("returns null for different tools", () => {
    const result = evaluateRepeatedToolPolicy(
      makeExecution([tool("search"), tool("read"), tool("write")]),
      policies,
    );
    expect(result).toBeNull();
  });

  it("returns null for same tool twice", () => {
    const result = evaluateRepeatedToolPolicy(
      makeExecution([tool("search"), tool("search")]),
      policies,
    );
    expect(result).toBeNull();
  });

  it("returns null for same tool three times (at threshold)", () => {
    const result = evaluateRepeatedToolPolicy(
      makeExecution([tool("search"), tool("search"), tool("search")]),
      policies,
    );
    expect(result).toBeNull();
  });

  it("returns REPEATED_TOOL_CALLS for same tool four times", () => {
    const result = evaluateRepeatedToolPolicy(
      makeExecution([
        tool("search"),
        tool("search"),
        tool("search"),
        tool("search"),
      ]),
      policies,
    );
    expect(result).toEqual({
      label: RiskLabel.REPEATED_TOOL_CALLS,
      severity: "WARNING",
    });
  });

  it("returns null when repeated tool is interrupted by different tool", () => {
    const result = evaluateRepeatedToolPolicy(
      makeExecution([
        tool("search"),
        tool("search"),
        tool("read"),
        tool("search"),
        tool("search"),
        tool("search"),
      ]),
      policies,
    );
    expect(result).toBeNull();
  });

  it("returns null for empty tool list", () => {
    const result = evaluateRepeatedToolPolicy(makeExecution([]), policies);
    expect(result).toBeNull();
  });

  it("respects custom repeatedToolThreshold", () => {
    const customPolicies = { ...policies, repeatedToolThreshold: 5 };
    const calls = Array.from({ length: 6 }, () => ({ toolName: "search", success: true }));
    const result = evaluateRepeatedToolPolicy(makeExecution(calls), customPolicies);
    expect(result).toEqual({
      label: RiskLabel.REPEATED_TOOL_CALLS,
      severity: "WARNING",
    });
  });
});
