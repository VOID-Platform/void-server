import { describe, it, expect, vi, beforeEach } from "vitest";
import { BullMqSamplingQueue } from "../src/queue";

const mockAdd = vi.fn();
const mockClose = vi.fn();

vi.mock("bullmq", () => ({
  Queue: vi.fn().mockImplementation(() => ({
    add: mockAdd,
    close: mockClose,
  })),
}));

describe("BullMqSamplingQueue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.REDIS_URL;
  });

  describe("connection", () => {
    it("uses default connection when no config provided", async () => {
      const { Queue } = await import("bullmq");
      new BullMqSamplingQueue();
      expect(Queue).toHaveBeenCalledWith("adaptive-sampling", {
        connection: { host: "localhost", port: 6379 },
      });
    });

    it("uses REDIS_URL from environment when no config provided", async () => {
      process.env.REDIS_URL = "redis://myredis:6379";
      const { Queue } = await import("bullmq");
      new BullMqSamplingQueue();
      expect(Queue).toHaveBeenCalledWith("adaptive-sampling", {
        connection: expect.objectContaining({ host: "myredis", port: 6379 }),
      });
    });

    it("parses username from REDIS_URL", async () => {
      process.env.REDIS_URL = "redis://alice@myredis:6379";
      const { Queue } = await import("bullmq");
      new BullMqSamplingQueue();
      expect(Queue).toHaveBeenCalledWith("adaptive-sampling", {
        connection: expect.objectContaining({ username: "alice" }),
      });
    });

    it("parses TLS from rediss:// URL", async () => {
      process.env.REDIS_URL = "rediss://myredis:6380";
      const { Queue } = await import("bullmq");
      new BullMqSamplingQueue();
      expect(Queue).toHaveBeenCalledWith("adaptive-sampling", {
        connection: expect.objectContaining({ tls: {} }),
      });
    });

    it("throws on invalid REDIS_URL", () => {
      process.env.REDIS_URL = "not-a-valid-url";
      expect(() => new BullMqSamplingQueue()).toThrow();
    });

    it("prefers explicit config over REDIS_URL env var", async () => {
      process.env.REDIS_URL = "redis://should-not-be-used:6379";
      const { Queue } = await import("bullmq");
      new BullMqSamplingQueue({ host: "explicit", port: 9999 });
      expect(Queue).toHaveBeenCalledWith("adaptive-sampling", {
        connection: { host: "explicit", port: 9999 },
      });
    });
  });

  describe("enqueue", () => {
    it("enqueues sample with all fields", async () => {
      const queue = new BullMqSamplingQueue();
      const sample = {
        executionId: "exec-1",
        traceId: "trace-1",
        timestamp: new Date("2026-01-01T00:00:00Z"),
      };

      await queue.enqueue(sample);

      expect(mockAdd).toHaveBeenCalledWith("sample", sample);
    });

    it("enqueues sample without optional traceId", async () => {
      const queue = new BullMqSamplingQueue();
      const sample = {
        executionId: "exec-2",
        timestamp: new Date("2026-01-01T00:00:00Z"),
      };

      await queue.enqueue(sample);

      expect(mockAdd).toHaveBeenCalledWith("sample", sample);
    });

    it("closes the underlying BullMQ queue", async () => {
      const queue = new BullMqSamplingQueue();
      await queue.close();
      expect(mockClose).toHaveBeenCalledOnce();
    });
  });
});
