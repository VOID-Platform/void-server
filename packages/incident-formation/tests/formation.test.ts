import { describe, it, expect, vi } from "vitest";
import { IncidentFormationService, generateTitle } from "../src/service";
import type { IncidentInput, IncidentRecord, IncidentRepository, IncidentQueue } from "../src/types";

function createMockRepo(): IncidentRepository {
  return {
    findByFingerprint: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  };
}

function createMockQueue(): IncidentQueue {
  return { enqueueAnalysis: vi.fn().mockResolvedValue(undefined), close: vi.fn() };
}

function makeRecord(overrides: Partial<IncidentRecord> = {}): IncidentRecord {
  return {
    id: "inc-1",
    fingerprint: "fp-1",
    trace_id: "trace-1",
    execution_id: "exec-1",
    title: "CRITICAL: AGENT_CRASH",
    severity: "CRITICAL",
    status: "OPEN",
    confidence: 0,
    first_scene: "",
    last_scene: "",
    latest_report_id: null,
    occurrence: 1,
    last_seen: new Date("2026-01-01T00:00:00Z"),
    analysis_status: "PENDING",
    latest_labels: ["AGENT_CRASH"],
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: new Date("2026-01-01T00:00:00Z"),
    reports: [],
    ...overrides,
  };
}

function suspiciousInput(overrides: Partial<IncidentInput> = {}): IncidentInput {
  return {
    fingerprint: "fp-suspicious",
    severity: "SUSPICIOUS",
    labels: ["HIGH_LATENCY"],
    executionId: "exec-1",
    traceId: "trace-1",
    timestamp: new Date("2026-01-01T00:00:00Z"),
    ...overrides,
  };
}

function criticalInput(overrides: Partial<IncidentInput> = {}): IncidentInput {
  return {
    fingerprint: "fp-critical",
    severity: "CRITICAL",
    labels: ["AGENT_CRASH"],
    executionId: "exec-1",
    timestamp: new Date("2026-01-01T00:00:00Z"),
    ...overrides,
  };
}

describe("generateTitle", () => {
  it("generates title from severity and labels", () => {
    expect(generateTitle("CRITICAL", ["AGENT_CRASH"] as any)).toBe("CRITICAL: AGENT_CRASH");
  });

  it("uses severity only when labels are empty", () => {
    expect(generateTitle("HEALTHY", [] as any)).toBe("HEALTHY");
  });

  it("joins multiple labels with separator", () => {
    expect(generateTitle("SUSPICIOUS", ["HIGH_LATENCY", "TOOL_FAILURE"] as any)).toBe(
      "SUSPICIOUS: HIGH_LATENCY + TOOL_FAILURE",
    );
  });
});

describe("IncidentFormationService", () => {
  describe("HEALTHY severity", () => {
    it("skips incident creation and queueing", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();
      const service = new IncidentFormationService(repo, queue);

      const result = await service.process({
        fingerprint: "fp-healthy",
        severity: "HEALTHY",
        labels: [],
        executionId: "exec-1",
        timestamp: new Date(),
      });

      expect(result).toEqual({ action: "SKIPPED" });
      expect(repo.findByFingerprint).not.toHaveBeenCalled();
      expect(repo.create).not.toHaveBeenCalled();
      expect(repo.update).not.toHaveBeenCalled();
      expect(queue.enqueueAnalysis).not.toHaveBeenCalled();
    });
  });

  describe("SUSPICIOUS severity", () => {
    it("creates new incident and enqueues for evaluation", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      repo.findByFingerprint = vi.fn().mockResolvedValue(null);
      repo.create = vi.fn().mockImplementation((data) =>
        Promise.resolve(makeRecord({ ...data, id: "inc-1" })),
      );
      queue.enqueueAnalysis = vi.fn().mockResolvedValue(undefined);

      const service = new IncidentFormationService(repo, queue);
      const result = await service.process(suspiciousInput());

      expect(repo.create).toHaveBeenCalledWith(
        expect.objectContaining({
          severity: "SUSPICIOUS",
          status: "OPEN",
          occurrence: 1,
          analysis_status: "PENDING",
        }),
      );
      expect(queue.enqueueAnalysis).toHaveBeenCalledWith(
        "evaluate-incident",
        "inc-1",
        "fp-suspicious",
      );
      expect(result.action).toBe("CREATED");
      expect(result).toHaveProperty("incident");
    });

    it("updates existing incident and does not enqueue", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      const existing = makeRecord({ severity: "SUSPICIOUS", occurrence: 1 });
      repo.findByFingerprint = vi.fn().mockResolvedValue(existing);
      repo.update = vi.fn().mockResolvedValue(makeRecord({ severity: "SUSPICIOUS", occurrence: 2 }));

      const service = new IncidentFormationService(repo, queue);
      const result = await service.process(suspiciousInput({ executionId: "exec-2" }));

      expect(repo.update).toHaveBeenCalledWith("inc-1", {
        occurrence: 2,
        execution_id: "exec-2",
        last_seen: new Date("2026-01-01T00:00:00Z"),
        latest_labels: ["HIGH_LATENCY"],
      });
      expect(queue.enqueueAnalysis).not.toHaveBeenCalled();
      expect(result.action).toBe("UPDATED");
    });
  });

  describe("CRITICAL severity", () => {
    it("creates new incident and enqueues for critical processing", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      repo.findByFingerprint = vi.fn().mockResolvedValue(null);
      repo.create = vi.fn().mockImplementation((data) =>
        Promise.resolve(makeRecord({ ...data, id: "inc-1" })),
      );
      queue.enqueueAnalysis = vi.fn().mockResolvedValue(undefined);

      const service = new IncidentFormationService(repo, queue);
      const result = await service.process(criticalInput());

      expect(repo.create).toHaveBeenCalledWith(
        expect.objectContaining({ severity: "CRITICAL" }),
      );
      expect(queue.enqueueAnalysis).toHaveBeenCalledWith(
        "critical-incident",
        "inc-1",
        "fp-critical",
      );
      expect(result.action).toBe("CREATED");
    });

    it("updates existing critical incident and does not enqueue", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      const existing = makeRecord({ severity: "CRITICAL", occurrence: 1 });
      repo.findByFingerprint = vi.fn().mockResolvedValue(existing);
      repo.update = vi.fn().mockResolvedValue(makeRecord({ severity: "CRITICAL", occurrence: 2 }));

      const service = new IncidentFormationService(repo, queue);
      const result = await service.process(criticalInput({ executionId: "exec-2" }));

      expect(repo.update).toHaveBeenCalled();
      expect(queue.enqueueAnalysis).not.toHaveBeenCalled();
      expect(result.action).toBe("UPDATED");
    });
  });

  describe("idempotency", () => {
    it("repeated processing converges to same state", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      const existing = makeRecord({ occurrence: 3 });
      repo.findByFingerprint = vi.fn().mockResolvedValue(existing);
      repo.update = vi.fn().mockResolvedValue(makeRecord({ occurrence: 4 }));

      const service = new IncidentFormationService(repo, queue);

      const first = await service.process(criticalInput());
      const second = await service.process(criticalInput());

      expect(first.action).toBe("UPDATED");
      expect(second.action).toBe("UPDATED");
      expect(first).toHaveProperty("incident");
      expect(second).toHaveProperty("incident");
    });
  });

  describe("error handling", () => {
    it("propagates repository errors", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      repo.findByFingerprint = vi.fn().mockRejectedValue(new Error("DB connection failed"));

      const service = new IncidentFormationService(repo, queue);
      await expect(service.process(suspiciousInput())).rejects.toThrow("DB connection failed");
    });

    it("propagates queue errors without losing the created incident", async () => {
      const repo = createMockRepo();
      const queue = createMockQueue();

      repo.findByFingerprint = vi.fn().mockResolvedValue(null);
      repo.create = vi.fn().mockResolvedValue(makeRecord());
      queue.enqueueAnalysis = vi.fn().mockRejectedValue(new Error("Redis unavailable"));

      const service = new IncidentFormationService(repo, queue);
      await expect(service.process(suspiciousInput())).rejects.toThrow("Redis unavailable");

      expect(repo.create).toHaveBeenCalledTimes(1);
    });
  });
});
