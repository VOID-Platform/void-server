import { describe, it, expect } from "vitest";
import { evaluateNoResponsePolicy } from "./no-response-policy";
import { Execution, RiskLabel } from "../types";

function makeExecution(hasFinalResponse: boolean): Execution {
  return {
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions: [],
    retryCount: 0,
    hasFinalResponse,
    crashed: false,
    contextWindowExceeded: false,
  };
}

describe("NoResponsePolicy", () => {
  it("returns null when response exists", () => {
    const result = evaluateNoResponsePolicy(makeExecution(true));
    expect(result).toBeNull();
  });

  it("returns NO_FINAL_RESPONSE when response is missing", () => {
    const result = evaluateNoResponsePolicy(makeExecution(false));
    expect(result).toEqual({
      label: RiskLabel.NO_FINAL_RESPONSE,
      severity: "CRITICAL",
    });
  });
});
