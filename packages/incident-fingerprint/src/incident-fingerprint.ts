import { createHash } from "node:crypto";
import { RiskLabel } from "./types";

export function generateFingerprint(
  labels: readonly RiskLabel[],
): string {
  return createHash("sha256")
    .update(labels.join("|"))
    .digest("hex");
}
