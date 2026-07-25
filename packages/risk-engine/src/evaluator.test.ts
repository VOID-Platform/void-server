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
    const customConfig = { ...defaultConfig, policies: { ...defaultConfig.policies, warningThreshold: 3 } };
    const result = evaluate(execution, customConfig);
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

  describe("input validation", () => {
    it("rejects null or non-object execution input without throwing", () => {
      const result = evaluate(null as any, defaultConfig);
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_EXECUTION_INPUT);
      expect(result.errors).toEqual([{ field: "execution", reason: "must be a non-null object" }]);
    });

    it("rejects execution with negative latencyMs", () => {
      const result = evaluate(makeExecution({ latencyMs: -1 }), defaultConfig);
      expect(result).toEqual({
        labels: [RiskLabel.INVALID_EXECUTION_INPUT],
        warningCount: 0,
        criticalCount: 1,
        severity: "CRITICAL",
        errors: [{ field: "latencyMs", reason: "must be a finite non-negative number" }],
      });
    });

    it("rejects execution with NaN latencyMs", () => {
      const result = evaluate(makeExecution({ latencyMs: NaN }), defaultConfig);
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_EXECUTION_INPUT);
    });

    it("rejects execution with Infinity promptTokens", () => {
      const result = evaluate(makeExecution({ promptTokens: Infinity }), defaultConfig);
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_EXECUTION_INPUT);
    });

    it("rejects execution with malformed toolExecutions elements", () => {
      const result = evaluate(
        makeExecution({ toolExecutions: [null as any, { toolName: "tool", success: "true" as any }] }),
        defaultConfig
      );
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_EXECUTION_INPUT);
      expect(result.errors).toEqual([
        { field: "toolExecutions[0]", reason: "must be an object with string toolName and boolean success" },
        { field: "toolExecutions[1]", reason: "must be an object with string toolName and boolean success" },
      ]);
    });

    it("rejects execution with negative retryCount", () => {
      const result = evaluate(makeExecution({ retryCount: -5 }), defaultConfig);
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_EXECUTION_INPUT);
    });

    it("rejects execution with non-integer retryCount", () => {
      const result = evaluate(makeExecution({ retryCount: 1.5 }), defaultConfig);
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_EXECUTION_INPUT);
    });

    it("rejects null or non-object config input without throwing", () => {
      const result = evaluate(makeExecution(), null as any);
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_CONFIG_INPUT);
      expect(result.errors).toEqual([{ field: "policies", reason: "must be a non-null object" }]);
    });

    it("rejects config with negative latencyMs threshold", () => {
      const result = evaluate(makeExecution(), {
        policies: { ...defaultConfig.policies, latencyMs: -100 },
      });
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_CONFIG_INPUT);
    });

    it("rejects config with zero warningThreshold", () => {
      const result = evaluate(makeExecution(), {
        policies: { ...defaultConfig.policies, warningThreshold: 0 },
      });
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_CONFIG_INPUT);
    });

    it("rejects config with non-integer retryThreshold", () => {
      const result = evaluate(makeExecution(), {
        policies: { ...defaultConfig.policies, retryThreshold: 2.5 },
      });
      expect(result.severity).toBe("CRITICAL");
      expect(result.labels).toContain(RiskLabel.INVALID_CONFIG_INPUT);
    });
  });
});
