import { Queue } from "bullmq";
import type { IncidentQueue, QueueConnectionConfig, JobType } from "./types";

function resolveConnectionConfig(config?: QueueConnectionConfig): QueueConnectionConfig {
  if (config) return config;
  const envUrl = process.env.REDIS_URL;
  if (envUrl) return { url: envUrl };
  return { host: "localhost", port: 6379 };
}

export class BullMqIncidentQueue implements IncidentQueue {
  private readonly queue: Queue;

  constructor(config?: QueueConnectionConfig) {
    const connection = resolveConnectionConfig(config);
    this.queue = new Queue("incident-analysis", { connection });
  }

  async enqueueAnalysis(jobName: JobType, incidentId: string, fingerprint: string): Promise<void> {
    await this.queue.add(
      jobName,
      { incidentId, fingerprint },
      { jobId: incidentId },
    );
  }

  async close(): Promise<void> {
    await this.queue.close();
  }
}
