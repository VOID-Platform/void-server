import { Queue } from "bullmq";
import type { SamplingQueue, SamplingInput, QueueConnectionConfig } from "./types";

const ALLOWED_PROTOCOLS = ["redis:", "rediss:"];

function parseRedisUrl(urlStr: string): QueueConnectionConfig {
  let parsed: URL;
  try {
    parsed = new URL(urlStr);
  } catch {
    throw new Error(`Invalid REDIS_URL: "${urlStr}" is not a valid URL`);
  }

  if (!ALLOWED_PROTOCOLS.includes(parsed.protocol)) {
    throw new Error(
      `Invalid REDIS_URL protocol "${parsed.protocol}" in "${urlStr}": expected redis: or rediss:`,
    );
  }

  if (!parsed.hostname) throw new Error(`Invalid REDIS_URL: no hostname in "${urlStr}"`);

  const config: QueueConnectionConfig = {
    host: parsed.hostname,
    port: parsed.port ? parseInt(parsed.port, 10) : 6379,
  };

  if (parsed.username) config.username = decodeURIComponent(parsed.username);
  const password = parsed.password ? decodeURIComponent(parsed.password) : undefined;
  if (password) config.password = password;

  const dbPath = parsed.pathname?.replace("/", "") ?? "";
  if (dbPath.length > 0) {
    const dbNum = Number(dbPath);
    if (!Number.isInteger(dbNum) || dbNum < 0 || !Number.isSafeInteger(dbNum)) {
      throw new Error(`Invalid REDIS_URL: path "${parsed.pathname}" is not a valid database number`);
    }
    config.db = dbNum;
  }

  if (parsed.protocol === "rediss:") config.tls = {};

  return config;
}

function parseUrlField(url: string): QueueConnectionConfig {
  return parseRedisUrl(url);
}

function resolveConnectionConfig(config?: QueueConnectionConfig): QueueConnectionConfig {
  if (config) {
    if (config.url) {
      const base = parseUrlField(config.url);
      return { ...base, ...config, url: undefined };
    }
    return config;
  }
  const envUrl = process.env.REDIS_URL;
  if (envUrl) return parseRedisUrl(envUrl);
  return { host: "localhost", port: 6379 };
}

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
