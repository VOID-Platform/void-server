import { createHash } from "node:crypto";
import { RiskLabel } from "./types";

export function hashJoin(strings: readonly string[]): string {
  return createHash("sha256")
    .update(JSON.stringify([...strings].sort()))
    .digest("hex");
}

export function generateLegacyFingerprint(
  labels: readonly RiskLabel[],
): string {
  return createHash("sha256")
    .update(labels.join("|"))
    .digest("hex");
}

export function generateFingerprint(
  labels: readonly RiskLabel[],
): string {
  return hashJoin(labels);
}
