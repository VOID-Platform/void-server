import { describe, it, expect, vi } from "vitest";
import { AdaptiveSamplingService } from "../src/service";
import type { SamplingInput, SamplingQueue } from "../src/types";

function createInput(overrides: Partial<SamplingInput> = {}): SamplingInput {
  return {
    executionId: `exec-${Math.random().toString(36).slice(2, 8)}`,
    timestamp: new Date(),
    ...overrides,
  };
}

function createMockQueue(): SamplingQueue {
  return { enqueue: vi.fn().mockResolvedValue(undefined), close: vi.fn() };
}

describe("AdaptiveSamplingService", () => {
  describe("window accumulation", () => {
    it("returns false until the window is full", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 5 });

      for (let i = 0; i < 4; i++) {
        await expect(service.process(createInput())).resolves.toBe(false);
      }
      expect(queue.enqueue).not.toHaveBeenCalled();
    });

    it("returns true when the window is full", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 5 });

      for (let i = 0; i < 4; i++) {
        await service.process(createInput());
      }
      const result = await service.process(createInput());
      expect(result).toBe(true);
    });

    it("enqueues exactly one execution when window fills", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 10 });

      for (let i = 0; i < 10; i++) {
        await service.process(createInput());
      }
      expect(queue.enqueue).toHaveBeenCalledTimes(1);
    });
  });

  describe("selection", () => {
    it("enqueues an execution from the current window", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 5 });
      const inputs = Array.from({ length: 5 }, () => createInput());

      for (const input of inputs) {
        await service.process(input);
      }

      const enqueued = (queue.enqueue as ReturnType<typeof vi.fn>).mock.calls[0][0] as SamplingInput;
      expect(inputs.some((i) => i.executionId === enqueued.executionId)).toBe(true);
    });

    it("each execution in the window has roughly equal probability (statistical)", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 4 });
      const inputs = Array.from({ length: 4 }, (_, i) => createInput({ executionId: `exec-${i}` }));
      const counts: Record<string, number> = { "exec-0": 0, "exec-1": 0, "exec-2": 0, "exec-3": 0 };
      const trials = 4000;

      for (let t = 0; t < trials; t++) {
        const q = createMockQueue();
        const svc = new AdaptiveSamplingService(q, { windowSize: 4 });
        for (const input of inputs) {
          await svc.process(input);
        }
        const selected = (q.enqueue as ReturnType<typeof vi.fn>).mock.calls[0][0].executionId;
        counts[selected]++;
      }

      for (const execId of Object.keys(counts)) {
        const ratio = counts[execId] / trials;
        expect(ratio).toBeGreaterThan(0.2);
        expect(ratio).toBeLessThan(0.3);
      }
    });
  });

  describe("window lifecycle", () => {
    it("clears the window after selection", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 3 });

      await service.process(createInput());
      await service.process(createInput());
      await service.process(createInput());
      expect(queue.enqueue).toHaveBeenCalledTimes(1);

      await expect(service.process(createInput())).resolves.toBe(false);
      expect(queue.enqueue).toHaveBeenCalledTimes(1);
    });

    it("supports multiple consecutive windows", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 3 });
      const expectedWindows = 5;

      for (let w = 0; w < expectedWindows; w++) {
        for (let i = 0; i < 2; i++) {
          await service.process(createInput());
        }
        await service.process(createInput());
      }

      expect(queue.enqueue).toHaveBeenCalledTimes(expectedWindows);
    });
  });

  describe("configuration", () => {
    it("respects custom windowSize", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 1 });

      const result = await service.process(createInput());
      expect(result).toBe(true);
      expect(queue.enqueue).toHaveBeenCalledTimes(1);
    });

    it("rejects non-positive windowSize", () => {
      const queue = createMockQueue();
      expect(() => new AdaptiveSamplingService(queue, { windowSize: 0 })).toThrow("positive integer");
      expect(() => new AdaptiveSamplingService(queue, { windowSize: -1 })).toThrow("positive integer");
    });

    it("rejects non-integer windowSize", () => {
      const queue = createMockQueue();
      expect(() => new AdaptiveSamplingService(queue, { windowSize: 1.5 })).toThrow("positive integer");
      expect(() => new AdaptiveSamplingService(queue, { windowSize: NaN })).toThrow("positive integer");
    });
  });

  describe("queue payload", () => {
    it("enqueues an execution from the current window with traceId", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 2 });
      const inputs = [createInput(), createInput({ traceId: "trace-abc-123" })];

      for (const input of inputs) {
        await service.process(input);
      }

      const enqueued = (queue.enqueue as ReturnType<typeof vi.fn>).mock.calls[0][0] as SamplingInput;
      expect(inputs.some((i) => i.executionId === enqueued.executionId)).toBe(true);
    });

    it("enqueues an execution from the current window without traceId", async () => {
      const queue = createMockQueue();
      const service = new AdaptiveSamplingService(queue, { windowSize: 2 });
      const inputs = [createInput({ traceId: undefined }), createInput({ traceId: undefined })];

      for (const input of inputs) {
        await service.process(input);
      }

      const enqueued = (queue.enqueue as ReturnType<typeof vi.fn>).mock.calls[0][0] as SamplingInput;
      expect(inputs.some((i) => i.executionId === enqueued.executionId)).toBe(true);
    });
  });
});
