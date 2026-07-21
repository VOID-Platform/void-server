import { describe, it, expect } from "vitest";
import { evaluateAgentCrashPolicy } from "./agent-crash-policy";
import { Execution, RiskLabel } from "../types";

function makeExecution(crashed: boolean): Execution {
  return {
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions: [],
    retryCount: 0,
    hasFinalResponse: true,
    crashed,
    contextWindowExceeded: false,
  };
}

describe("AgentCrashPolicy", () => {
  it("returns null when execution succeeded", () => {
    const result = evaluateAgentCrashPolicy(makeExecution(false));
    expect(result).toBeNull();
  });

  it("returns AGENT_CRASH when execution crashed", () => {
    const result = evaluateAgentCrashPolicy(makeExecution(true));
    expect(result).toEqual({ label: RiskLabel.AGENT_CRASH, severity: "CRITICAL" });
  });
});
