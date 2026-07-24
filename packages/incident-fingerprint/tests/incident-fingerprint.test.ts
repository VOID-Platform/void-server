import { describe, it, expect } from "vitest";
import { RiskLabel } from "../src/types";
import { generateFingerprint, generateLegacyFingerprint, hashJoin } from "../src/incident-fingerprint";

describe("generateFingerprint", () => {
  it("identical labels produce identical fingerprint", () => {
    const labels = [
      RiskLabel.HIGH_LATENCY,
      RiskLabel.REPEATED_TOOL_CALLS,
      RiskLabel.TOKEN_BUDGET_EXCEEDED,
    ];
    const fp1 = generateFingerprint(labels);
    const fp2 = generateFingerprint(labels);
    expect(fp1).toBe(fp2);
  });

  it("different labels produce different fingerprint", () => {
    const labelsA = [RiskLabel.HIGH_LATENCY];
    const labelsB = [RiskLabel.TOOL_FAILURE];
    expect(generateFingerprint(labelsA)).not.toBe(generateFingerprint(labelsB));
  });

  it("handles empty labels array", () => {
    const fp = generateFingerprint([]);
    expect(typeof fp).toBe("string");
    expect(fp.length).toBe(64);
  });

  it("produces a 64-character hexadecimal string", () => {
    const fp = generateFingerprint([RiskLabel.CONTEXT_OVERFLOW]);
    expect(fp).toMatch(/^[0-9a-f]{64}$/);
  });

  it("sorts labels deterministically", () => {
    const sorted = [RiskLabel.HIGH_LATENCY, RiskLabel.TOOL_FAILURE];
    const unsorted = [RiskLabel.TOOL_FAILURE, RiskLabel.HIGH_LATENCY];
    expect(generateFingerprint(sorted)).toBe(generateFingerprint(unsorted));
  });

  it("prevents delimiter collision issues in hashJoin", () => {
    const hashA = hashJoin(["a|b", "c"]);
    const hashB = hashJoin(["a", "b|c"]);
    expect(hashA).not.toBe(hashB);
  });

  it("generates legacy order-sensitive fingerprint for backward compatibility", () => {
    const labels = [RiskLabel.TOOL_FAILURE, RiskLabel.HIGH_LATENCY];
    const legacyFp = generateLegacyFingerprint(labels);
    expect(legacyFp).toMatch(/^[0-9a-f]{64}$/);
    expect(legacyFp).not.toBe(generateFingerprint(labels));
  });
});
