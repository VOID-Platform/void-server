export interface AdaptiveSamplingConfig {
  windowSize?: number;
}

export interface SamplingInput {
  executionId: string;
  traceId?: string;
  timestamp: Date;
  agentSteps?: unknown[];
  telemetry?: Record<string, unknown>;
}

export interface SamplingQueue {
  enqueue(sample: SamplingInput): Promise<void>;
  close(): Promise<void>;
}

export interface QueueConnectionConfig {
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  db?: number;
  tls?: Record<string, unknown>;
  url?: string;
}
