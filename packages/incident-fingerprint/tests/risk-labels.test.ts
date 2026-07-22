import { describe, it, expect } from "vitest";
import { RiskLabel, type RiskEvaluationResult } from "../src/types";
import { normalizeRiskLabels } from "../src/risk-labels";

describe("normalizeRiskLabels", () => {
  it("removes duplicate labels", () => {
    const result: RiskEvaluationResult = {
      severity: "CRITICAL",
      labels: [
        RiskLabel.HIGH_LATENCY,
        RiskLabel.HIGH_LATENCY,
        RiskLabel.TOOL_FAILURE,
      ],
    };
    const normalized = normalizeRiskLabels(result);
    expect(normalized).toEqual([RiskLabel.HIGH_LATENCY, RiskLabel.TOOL_FAILURE]);
  });

  it("preserves only valid labels and filters out unknown ones", () => {
    const result: RiskEvaluationResult = {
      severity: "HIGH",
      labels: [
        RiskLabel.AGENT_CRASH,
        "UNKNOWN_LABEL" as RiskLabel,
        RiskLabel.NO_FINAL_RESPONSE,
      ],
    };
    const normalized = normalizeRiskLabels(result);
    expect(normalized).toEqual([RiskLabel.AGENT_CRASH, RiskLabel.NO_FINAL_RESPONSE]);
  });

  it("returns deterministic output for same input", () => {
    const result: RiskEvaluationResult = {
      severity: "SUSPICIOUS",
      labels: [
        RiskLabel.TOKEN_BUDGET_EXCEEDED,
        RiskLabel.HIGH_LATENCY,
      ],
    };
    const a = normalizeRiskLabels(result);
    const b = normalizeRiskLabels(result);
    expect(a).toEqual(b);
  });

  it("returns immutable output (modifying original input does not affect previous output)", () => {
    const labels = [RiskLabel.HIGH_LATENCY, RiskLabel.TOOL_FAILURE];
    const result: RiskEvaluationResult = { severity: "LOW", labels };
    const normalized = normalizeRiskLabels(result);
    labels.push(RiskLabel.AGENT_CRASH);
    expect(normalized).toHaveLength(2);
  });

  it("returns labels in sorted alphabetical order", () => {
    const result: RiskEvaluationResult = {
      severity: "CRITICAL",
      labels: [
        RiskLabel.TOOL_FAILURE,
        RiskLabel.AGENT_CRASH,
        RiskLabel.HIGH_LATENCY,
      ],
    };
    const normalized = normalizeRiskLabels(result);
    expect(normalized).toEqual([
      RiskLabel.AGENT_CRASH,
      RiskLabel.HIGH_LATENCY,
      RiskLabel.TOOL_FAILURE,
    ]);
  });

  it("handles empty labels array", () => {
    const result: RiskEvaluationResult = { severity: "LOW", labels: [] };
    expect(normalizeRiskLabels(result)).toEqual([]);
  });

  it("handles all valid labels without duplicates", () => {
    const allLabels = Object.values(RiskLabel);
    const result: RiskEvaluationResult = { severity: "CRITICAL", labels: allLabels };
    const normalized = normalizeRiskLabels(result);
    expect(normalized).toEqual([...allLabels].sort());
  });
});
