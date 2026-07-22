# Adaptive Sampling

Selects representative healthy executions for offline quality evaluation.

## Pipeline Position

```
Execution → Risk Evaluation → Severity → HEALTHY? → Adaptive Sampling → BullMQ
```

Only healthy executions reach the sampler. The service does not enforce this — it is a caller precondition.

## Types

```typescript
interface AdaptiveSamplingConfig {
  windowSize?: number;  // default: 20
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

interface QueueConnectionConfig {
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  db?: number;
  tls?: Record<string, unknown>;
  url?: string;
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
    const windowSize = config.windowSize ?? 20;
    if (!Number.isInteger(windowSize) || windowSize < 1) {
      throw new Error(`windowSize must be a positive integer, got ${windowSize}`);
    }
    this.windowSize = windowSize;
  }

  async process(input: SamplingInput): Promise<boolean> {
    this.window.push(input);

    if (this.window.length < this.windowSize) {
      return false;
    }

    const batch = this.window.splice(0, this.windowSize);
    const index = Math.floor(Math.random() * this.windowSize);
    const selected = batch[index];

    await this.queue.enqueue(selected);

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
return false      Extract and Clear Window (splice)
                  synchronously — before any await
                  │
                  ▼
                  Randomly Select One from batch[index]
                  │
                  ▼
                  Enqueue Sample (async)
                  │
                  ▼
                  return true
```

Key design decisions:

- **Clear before await**: The window is extracted and cleared synchronously via `splice()` before `enqueue` is awaited. This prevents race conditions when multiple executions arrive concurrently.
- **No retry on failure**: If `enqueue` throws, the extracted batch is lost. This is acceptable — Adaptive Sampling is best-effort. Retaining the batch would reintroduce the race and unbounded memory growth that the synchronous clearing prevents.
- **Best-effort**: Duplicate samples are acceptable. Missing a sample from a failed enqueue is acceptable.

### Example (windowSize = 3)

```
Execution 1 → push → [1]         → return false
Execution 2 → push → [1, 2]      → return false
Execution 3 → push → [1, 2, 3]   → window full
                                      │
                                      ▼
                                  splice: batch = [1,2,3], window = []
                                      │
                                      ▼
                                  pick random from batch → e.g. Execution 2
                                      │
                                      ▼
                                  enqueue(Execution 2)
                                      │
                                      ▼
                                  return true

Execution 4 → push → [4]         → return false  (next window starts)
```

### State

- `window: SamplingInput[]` — in-memory array, bounded by `windowSize`
- `windowSize: number` — from config (default: 20, validated as positive integer)

No database. No external storage for the window. Queued samples use Redis through BullMQ.

## Queue

```typescript
export class BullMqSamplingQueue implements SamplingQueue {
  private readonly queue: Queue;

  constructor(config?: QueueConnectionConfig) {
    const connection = resolveConnectionConfig(config);
    this.queue = new Queue("adaptive-sampling", { connection });
  }

  async enqueue(sample: SamplingInput): Promise<void> {
    const payload = {
      executionId: sample.executionId,
      traceId: sample.traceId,
      timestamp: sample.timestamp.toISOString(),
    };
    await this.queue.add("sample", payload, {
      removeOnComplete: { count: 1000 },
      removeOnFail: { count: 1000 },
    });
  }

  async close(): Promise<void> {
    await this.queue.close();
  }
}
```

Queue name: `adaptive-sampling`

Serialized payload:

```json
{
  "executionId": "exec-abc123",
  "traceId": "trace-xyz",
  "timestamp": "2026-01-01T00:00:00.000Z"
}
```

`timestamp` is serialized as an ISO-8601 string. Workers should parse it back to a `Date` at the consumer boundary.

Job retention is bounded — completed and failed jobs are removed automatically (1000 most recent retained each).

Connection resolution priority:

```
Explicit config (host/port) → config.url (parsed) → REDIS_URL env → localhost:6379
```

Only `redis:` and `rediss:` protocols are accepted.

## Memory Model

```
Healthy Execution
        │
        ▼
window.push()     ──  20 items max  ──
                                          │
                                          ▼ (when full)
                                    window.splice(0, windowSize)
                                          │
                                          ▼
                                    random pick from detached batch
                                          │
                                          ▼
                                    enqueue (async, window already clear)
```

For default config (`windowSize = 20`): at most 20 `SamplingInput` objects in memory. The window is always bounded.

## Tests

### Service (13 tests)

```
window accumulation  →  returns false until full
                     →  returns true when full
                     →  enqueues exactly one
selection            →  picks from the current window
                     →  equal probability (~0.25 each for n=4, 4000 trials)
window lifecycle     →  clears before await (synchronous extraction)
                     →  supports multiple consecutive windows
configuration        →  respects custom windowSize (e.g. 1 → immediate)
                     →  rejects non-positive windowSize
                     →  rejects non-integer windowSize
queue payload        →  enqueues a member of the window with traceId
                     →  enqueues a member of the window without traceId
```

### Queue (10 tests)

```
connection  →  default localhost:6379
            →  REDIS_URL env parsing
            →  username from URL
            →  TLS from rediss://
            →  rejects non-redis protocols (http://)
            →  rejects unparseable URL
            →  explicit config preferred
enqueue     →  timestamp serialized as ISO string
            →  works without traceId
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
