import { Queue } from "bullmq";
import type { SamplingQueue, SamplingInput, QueueConnectionConfig } from "./types";

const ALLOWED_PROTOCOLS = ["redis:", "rediss:"];
const DB_PATH_RE = /^\d+$/;

function redactUrl(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.username = "";
    parsed.password = "";
    return parsed.toString();
  } catch {
    return "<unparseable>";
  }
}

function parseRedisUrl(urlStr: string, source: string): QueueConnectionConfig {
  let parsed: URL;
  try {
    parsed = new URL(urlStr);
  } catch {
    throw new Error(`Invalid ${source}: "${redactUrl(urlStr)}" is not a valid URL`);
  }

  if (!ALLOWED_PROTOCOLS.includes(parsed.protocol)) {
    throw new Error(
      `Invalid ${source} protocol "${parsed.protocol}" in "${redactUrl(urlStr)}": expected redis: or rediss:`,
    );
  }

  if (!parsed.hostname) {
    throw new Error(`Invalid ${source}: no hostname in "${redactUrl(urlStr)}"`);
  }

  const config: QueueConnectionConfig = {
    host: parsed.hostname,
    port: parsed.port ? parseInt(parsed.port, 10) : 6379,
  };

  if (parsed.username) config.username = decodeURIComponent(parsed.username);
  const password = parsed.password ? decodeURIComponent(parsed.password) : undefined;
  if (password) config.password = password;

  const dbPath = parsed.pathname?.replace("/", "") ?? "";
  if (dbPath.length > 0) {
    if (!DB_PATH_RE.test(dbPath)) {
      throw new Error(
        `Invalid ${source}: path "${parsed.pathname}" is not a valid decimal database number`,
      );
    }
    const dbNum = parseInt(dbPath, 10);
    if (dbNum < 0 || !Number.isSafeInteger(dbNum)) {
      throw new Error(
        `Invalid ${source}: path "${parsed.pathname}" is not a valid database number`,
      );
    }
    config.db = dbNum;
  }

  if (parsed.protocol === "rediss:") config.tls = {};

  return config;
}

function stripUndefined(obj: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value !== undefined) {
      result[key] = value;
    }
  }
  return result;
}

function resolveConnectionConfig(config?: QueueConnectionConfig): QueueConnectionConfig {
  if (config) {
    if (config.url) {
      const base = parseRedisUrl(config.url, "config.url");
      return { ...base, ...stripUndefined(config as Record<string, unknown>), url: undefined };
    }
    return config;
  }
  const envUrl = process.env.REDIS_URL;
  if (envUrl) return parseRedisUrl(envUrl, "REDIS_URL");
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
