import { describe, it, expect, vi, beforeEach } from "vitest";
import { BullMqIncidentQueue } from "../src/queue";

const mockAdd = vi.fn();
const mockClose = vi.fn();

vi.mock("bullmq", () => ({
  Queue: vi.fn().mockImplementation(() => ({
    add: mockAdd,
    close: mockClose,
  })),
}));

describe("BullMqIncidentQueue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.REDIS_URL;
  });

  describe("connection", () => {
    it("uses default connection when no config provided", async () => {
      const { Queue } = await import("bullmq");
      new BullMqIncidentQueue();
      expect(Queue).toHaveBeenCalledWith("incident-analysis", {
        connection: { host: "localhost", port: 6379 },
      });
    });

    it("uses REDIS_URL from environment when no config provided", async () => {
      process.env.REDIS_URL = "redis://myredis:6379";
      const { Queue } = await import("bullmq");
      new BullMqIncidentQueue();
      expect(Queue).toHaveBeenCalledWith("incident-analysis", {
        connection: expect.objectContaining({ host: "myredis", port: 6379 }),
      });
    });

    it("parses username from REDIS_URL", async () => {
      process.env.REDIS_URL = "redis://alice@myredis:6379";
      const { Queue } = await import("bullmq");
      new BullMqIncidentQueue();
      expect(Queue).toHaveBeenCalledWith("incident-analysis", {
        connection: expect.objectContaining({ username: "alice" }),
      });
    });

    it("parses TLS from rediss:// URL", async () => {
      process.env.REDIS_URL = "rediss://myredis:6380";
      const { Queue } = await import("bullmq");
      new BullMqIncidentQueue();
      expect(Queue).toHaveBeenCalledWith("incident-analysis", {
        connection: expect.objectContaining({ tls: {} }),
      });
    });

    it("throws on invalid REDIS_URL", () => {
      process.env.REDIS_URL = "not-a-valid-url";
      expect(() => new BullMqIncidentQueue()).toThrow();
    });

    it("prefers explicit config over REDIS_URL env var", async () => {
      process.env.REDIS_URL = "redis://should-not-be-used:6379";
      const { Queue } = await import("bullmq");
      new BullMqIncidentQueue({ host: "explicit", port: 9999 });
      expect(Queue).toHaveBeenCalledWith("incident-analysis", {
        connection: { host: "explicit", port: 9999 },
      });
    });
  });

  describe("enqueue", () => {
    it("enqueues evaluation job with type-prefixed jobId", async () => {
      const queue = new BullMqIncidentQueue();
      await queue.enqueueAnalysis("evaluate-incident", "inc-1", "abc123");

      expect(mockAdd).toHaveBeenCalledWith(
        "evaluate-incident",
        { incidentId: "inc-1", fingerprint: "abc123" },
        { jobId: "evaluate-incident-inc-1" },
      );
    });

    it("enqueues critical job with type-prefixed jobId", async () => {
      const queue = new BullMqIncidentQueue();
      await queue.enqueueAnalysis("critical-incident", "inc-2", "def456");

      expect(mockAdd).toHaveBeenCalledWith(
        "critical-incident",
        { incidentId: "inc-2", fingerprint: "def456" },
        { jobId: "critical-incident-inc-2" },
      );
    });

    it("different job types for same incident get different jobIds", async () => {
      const queue = new BullMqIncidentQueue();
      await queue.enqueueAnalysis("evaluate-incident", "inc-1", "abc");
      await queue.enqueueAnalysis("critical-incident", "inc-1", "abc");

      expect(mockAdd.mock.calls[0][2].jobId).toBe("evaluate-incident-inc-1");
      expect(mockAdd.mock.calls[1][2].jobId).toBe("critical-incident-inc-1");
    });

    it("closes the underlying BullMQ queue", async () => {
      const queue = new BullMqIncidentQueue();
      await queue.close();
      expect(mockClose).toHaveBeenCalledOnce();
    });
  });
});
