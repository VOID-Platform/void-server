import { describe, it, expect } from "vitest";
import { evaluateContextOverflowPolicy } from "./context-overflow-policy";
import { Execution, RiskLabel } from "../types";

function makeExecution(contextWindowExceeded: boolean): Execution {
  return {
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions: [],
    retryCount: 0,
    hasFinalResponse: true,
    crashed: false,
    contextWindowExceeded,
  };
}

describe("ContextOverflowPolicy", () => {
  it("returns null when within context window", () => {
    const result = evaluateContextOverflowPolicy(makeExecution(false));
    expect(result).toBeNull();
  });

  it("returns CONTEXT_OVERFLOW when context window exceeded", () => {
    const result = evaluateContextOverflowPolicy(makeExecution(true));
    expect(result).toEqual({
      label: RiskLabel.CONTEXT_OVERFLOW,
      severity: "WARNING",
    });
  });
});
