import { Queue } from "bullmq";
import type { SamplingQueue, SamplingInput, QueueConnectionConfig } from "./types";

function parseRedisUrl(urlStr: string): QueueConnectionConfig {
  const parsed = new URL(urlStr);
  if (!parsed.hostname) throw new Error(`Invalid REDIS_URL: no hostname in "${urlStr}"`);

  const config: QueueConnectionConfig = {
    host: parsed.hostname,
    port: parsed.port ? parseInt(parsed.port, 10) : 6379,
  };

  if (parsed.username) config.username = decodeURIComponent(parsed.username);
  const password = parsed.password ? decodeURIComponent(parsed.password) : undefined;
  if (password) config.password = password;

  const db = parsed.pathname ? parseInt(parsed.pathname.replace("/", ""), 10) : NaN;
  if (!isNaN(db)) config.db = db;

  if (parsed.protocol === "rediss:") config.tls = {};

  return config;
}

function resolveConnectionConfig(config?: QueueConnectionConfig): QueueConnectionConfig {
  if (config) return config;
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
    await this.queue.add("sample", sample);
  }

  async close(): Promise<void> {
    await this.queue.close();
  }
}
