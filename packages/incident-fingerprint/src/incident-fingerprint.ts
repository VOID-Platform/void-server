import { createHash } from "node:crypto";
import { RiskLabel } from "./types";

export function hashJoin(strings: readonly string[]): string {
  return createHash("sha256")
    .update([...strings].sort().join("|"))
    .digest("hex");
}

export function generateFingerprint(
  labels: readonly RiskLabel[],
): string {
  return hashJoin(labels);
}
