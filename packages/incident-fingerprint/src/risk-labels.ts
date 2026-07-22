import { RiskLabel, type RiskEvaluationResult } from "./types";

const VALID_LABELS = new Set<string>(Object.values(RiskLabel));

export function normalizeRiskLabels(result: RiskEvaluationResult): RiskLabel[] {
  const seen = new Set<RiskLabel>();
  const unique: RiskLabel[] = [];

  for (const label of result.labels) {
    if (!VALID_LABELS.has(label)) continue;
    if (seen.has(label)) continue;
    seen.add(label);
    unique.push(label);
  }

  return [...unique].sort();
}
