# Incident Fingerprint

## Pipeline

```
Risk Evaluation Result
        ↓
   Risk Labels
        ↓
Incident Fingerprint
```

## Risk Labels

Normalize a `RiskEvaluationResult` into a sorted, deduplicated, validated collection of `RiskLabel` values.

```ts
import { createHash } from "node:crypto";
import { RiskLabel } from "./types";

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
```

## Incident Fingerprint

Generate a deterministic SHA-256 hex fingerprint from **already-normalized** `RiskLabel` values. The input must be sorted and deduplicated — this is the caller's responsibility (use `normalizeRiskLabels` first).

```ts
import { createHash } from "node:crypto";
import { RiskLabel } from "./types";

export function generateFingerprint(
  labels: readonly RiskLabel[],
): string {
  return createHash("sha256")
    .update(labels.join("|"))
    .digest("hex");
}
```

## Contract

```
RiskEvaluationResult
        ↓
normalizeRiskLabels()   ← validates, deduplicates, sorts
        ↓
Normalized Labels
        ↓
generateFingerprint()   ← joins, hashes, returns hex
```

Each function has exactly one responsibility.

## Key Properties

- **Deterministic** — same labels always produce same fingerprint.
- **Severity-independent** — severity is excluded from the hash; only labels matter.
- **Pure** — no database, HTTP, queues, LLMs, or side effects.
- **Immutable** — input arrays are never mutated.
