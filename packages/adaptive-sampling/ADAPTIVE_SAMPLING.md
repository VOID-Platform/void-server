# Adaptive Sampling

Selects representative healthy executions for offline quality evaluation.

## Pipeline Position

```
Execution → Risk Evaluation → Severity → HEALTHY? → Adaptive Sampling → BullMQ
```

Only healthy executions reach the sampler. Suspicious and critical executions are handled by `incident-formation`.

## Types

```typescript
interface AdaptiveSamplingConfig {
  windowSize: number;
}

interface SamplingInput {
  executionId: string;
  traceId?: string;
  timestamp: Date;
}

interface SamplingQueue {
  enqueue(sample: SamplingInput): Promise<void>;
  close(): Promise<void>;
}
```

## Service

```typescript
export class AdaptiveSamplingService {
  private readonly window: SamplingInput[] = [];
  private readonly windowSize: number;

  constructor(
    private readonly queue: SamplingQueue,
    config: AdaptiveSamplingConfig,
  ) {
    this.windowSize = config.windowSize;
  }

  async process(input: SamplingInput): Promise<boolean> {
    this.window.push(input);

    if (this.window.length < this.windowSize) {
      return false;
    }

    const index = Math.floor(Math.random() * this.windowSize);
    const selected = this.window[index];

    await this.queue.enqueue(selected);
    this.window.length = 0;

    return true;
  }
}
```

### Algorithm

```
Receive Healthy Execution
        │
        ▼
Append to Window (push)
        │
        ▼
  ┌─ Window Full? ─┐
  │                │
  No              Yes
  │                │
  ▼                ▼
return false      Randomly Select One
                  from window[index]
                  │
                  ▼
                  Enqueue Sample
                  │
                  ▼
                  Clear Window
                  │
                  ▼
                  return true
```

### Example (windowSize = 3)

```
Execution 1 → push → [1]         → return false
Execution 2 → push → [1, 2]      → return false
Execution 3 → push → [1, 2, 3]   → window full
                                      │
                                      ▼
                                  pick random → e.g. Execution 2
                                      │
                                      ▼
                                  enqueue(Execution 2)
                                  window.clear()
                                      │
                                      ▼
                                  return true

Execution 4 → push → [4]         → return false  (next window starts)
```

### State

- `window: SamplingInput[]` — in-memory array, bounded by `windowSize`
- `windowSize: number` — from config

No persistence, no Redis, no external storage.

## Queue

```typescript
export class BullMqSamplingQueue implements SamplingQueue {
  private readonly queue: Queue;

  constructor(config?: QueueConnectionConfig) {
    const connection = resolveConnectionConfig(config);
    this.queue = new Queue("adaptive-sampling", { connection });
  }

  async enqueue(sample: SamplingInput): Promise<void> {
    await this.queue.add("sample", sample);
  }

  async close(): Promise<void> {
    await this.queue.close();
  }
}
```

Queue name: `adaptive-sampling`

Payload:

```json
{
  "executionId": "exec-abc123",
  "traceId": "trace-xyz",
  "timestamp": "2026-01-01T00:00:00.000Z"
}
```

Connection resolution priority:

```
Explicit config → REDIS_URL env → localhost:6379
```

## Memory Model

```
Healthy Execution
        │
        ▼
window.push()     ──  20 items max  ──
                                          │
                                          ▼ (when full)
                                    random pick
                                          │
                                          ▼
                                    window.length = 0
```

For default config (`windowSize = 20`): at most 20 `SamplingInput` objects in memory.

## Tests

### Service (10 tests)

```
window accumulation  →  returns false until full
                     →  returns true when full
                     →  enqueues exactly one
selection            →  picks from the current window
                     →  equal probability (~0.25 each for n=4, 4000 trials)
window lifecycle     →  clears after selection
                     →  supports multiple consecutive windows
configuration        →  respects custom windowSize (e.g. 1 → immediate)
queue payload        →  preserves traceId when present
                     →  works without traceId
```

### Queue (9 tests)

```
connection  →  default localhost:6379
            →  REDIS_URL env parsing
            →  username from URL
            →  TLS from rediss://
            →  invalid URL throws
            →  explicit config preferred
enqueue     →  sample with all fields
            →  sample without traceId
            →  close delegates to BullMQ
```

## Out of Scope

- Evaluating execution quality
- Calling an LLM
- Generating reports
- Persisting metrics
- Storing historical samples
- Adapting the sampling rate
- Incident detection

Those belong to downstream consumers attached to the `adaptive-sampling` queue.

## NOTE 
The sampling strategy is an implementation detail. Future versions may replace the fixed-size rolling window with more advanced algorithms (e.g., reservoir sampling or adaptive sampling) without changing the public interface or queue contract.