import { describe, it, expect } from "vitest";
import { evaluate } from "./evaluator";
import { Execution, RiskLabel, RiskConfig } from "./types";
import { config as defaultConfig } from "./config";

function makeExecution(overrides?: Partial<Execution>): Execution {
  return {
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    toolExecutions: [],
    retryCount: 0,
    hasFinalResponse: true,
    crashed: false,
    contextWindowExceeded: false,
    ...overrides,
  };
}

describe("Evaluator", () => {
  it("returns HEALTHY when no policies trigger", () => {
    const result = evaluate(makeExecution(), defaultConfig);
    expect(result).toEqual({
      labels: [],
      warningCount: 0,
      criticalCount: 0,
      severity: "HEALTHY",
    });
  });

  it("returns HEALTHY when warning count is below threshold", () => {
    const execution = makeExecution({
      latencyMs: 5000,
      promptTokens: 20000,
      completionTokens: 10000,
    });
    const result = evaluate(execution, defaultConfig);
    expect(result.labels).toContain(RiskLabel.HIGH_LATENCY);
    expect(result.labels).toContain(RiskLabel.TOKEN_BUDGET_EXCEEDED);
    expect(result.warningCount).toBe(2);
    expect(result.criticalCount).toBe(0);
    expect(result.severity).toBe("HEALTHY");
  });

  it("returns SUSPICIOUS when warning count meets threshold", () => {
    const execution = makeExecution({
      latencyMs: 5000,
      promptTokens: 20000,
      completionTokens: 10000,
      toolExecutions: [
        { toolName: "search", success: true },
        { toolName: "search", success: true },
        { toolName: "search", success: true },
        { toolName: "search", success: true },
      ],
      contextWindowExceeded: true,
    });
    const result = evaluate(execution, defaultConfig);
    expect(result.labels).toContain(RiskLabel.HIGH_LATENCY);
    expect(result.labels).toContain(RiskLabel.TOKEN_BUDGET_EXCEEDED);
    expect(result.labels).toContain(RiskLabel.REPEATED_TOOL_CALLS);
    expect(result.labels).toContain(RiskLabel.CONTEXT_OVERFLOW);
    expect(result.warningCount).toBe(4);
    expect(result.criticalCount).toBe(0);
    expect(result.severity).toBe("SUSPICIOUS");
  });

  it("returns CRITICAL when any critical policy triggers", () => {
    const execution = makeExecution({
      toolExecutions: [{ toolName: "search", success: false }],
      crashed: true,
    });
    const result = evaluate(execution, defaultConfig);
    expect(result.labels).toContain(RiskLabel.TOOL_FAILURE);
    expect(result.labels).toContain(RiskLabel.AGENT_CRASH);
    expect(result.criticalCount).toBe(2);
    expect(result.severity).toBe("CRITICAL");
  });

  it("returns CRITICAL even when warning count is high", () => {
    const execution = makeExecution({
      latencyMs: 5000,
      promptTokens: 20000,
      completionTokens: 10000,
      toolExecutions: [
        { toolName: "search", success: true },
        { toolName: "search", success: true },
        { toolName: "search", success: true },
        { toolName: "search", success: true },
      ],
      contextWindowExceeded: true,
      crashed: true,
    });
    const result = evaluate(execution, defaultConfig);
    expect(result.labels).toContain(RiskLabel.AGENT_CRASH);
    expect(result.criticalCount).toBe(1);
    expect(result.warningCount).toBe(4);
    expect(result.severity).toBe("CRITICAL");
  });

  it("respects custom config thresholds", () => {
    const config: RiskConfig = {
      policies: {
        latencyMs: 100,
        tokenBudget: 1000,
        toolFailureThreshold: 2,
        repeatedToolThreshold: 3,
        retryThreshold: 3,
        warningThreshold: 1,
      },
    };
    const execution = makeExecution({
      latencyMs: 200,
      promptTokens: 500,
      completionTokens: 600,
    });
    const result = evaluate(execution, config);
    expect(result.labels).toContain(RiskLabel.HIGH_LATENCY);
    expect(result.labels).toContain(RiskLabel.TOKEN_BUDGET_EXCEEDED);
    expect(result.warningCount).toBe(2);
    expect(result.criticalCount).toBe(0);
    expect(result.severity).toBe("SUSPICIOUS");
  });
});
