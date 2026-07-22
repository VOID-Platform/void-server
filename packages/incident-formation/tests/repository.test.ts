import { describe, it, expect, vi } from "vitest";
import { PrismaIncidentRepository } from "../src/repository";
import type { CreateIncidentData, UpdateIncidentData } from "../src/types";

function createMockPrisma() {
  return {
    incident: {
      findUnique: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
    },
  };
}

const baseCreate: CreateIncidentData = {
  fingerprint: "abc123",
  trace_id: "trace-1",
  execution_id: "exec-1",
  title: "CRITICAL: AGENT_CRASH",
  severity: "CRITICAL",
  status: "OPEN",
  confidence: 0,
  first_scene: "",
  last_scene: "",
  occurrence: 1,
  last_seen: new Date("2026-01-01T00:00:00Z"),
  analysis_status: "PENDING",
  latest_labels: ["AGENT_CRASH"] as any,
};

const baseRecord = {
  id: "inc-1",
  ...baseCreate,
  trace_id: "trace-1",
  latest_report_id: null,
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: new Date("2026-01-01T00:00:00Z"),
  reports: [],
};

describe("PrismaIncidentRepository", () => {
  it("creates an incident", async () => {
    const prisma = createMockPrisma();
    prisma.incident.create.mockResolvedValue(baseRecord);

    const repo = new PrismaIncidentRepository(prisma as any);
    const result = await repo.create(baseCreate);

    expect(prisma.incident.create).toHaveBeenCalledWith({
      data: baseCreate,
      include: { reports: true },
    });
    expect(result.id).toBe("inc-1");
  });

  it("updates an incident", async () => {
    const prisma = createMockPrisma();
    const updateData: UpdateIncidentData = {
      occurrence: 2,
      execution_id: "exec-2",
      last_seen: new Date("2026-01-02T00:00:00Z"),
      latest_labels: ["AGENT_CRASH"] as any,
    };
    prisma.incident.update.mockResolvedValue({ ...baseRecord, ...updateData });

    const repo = new PrismaIncidentRepository(prisma as any);
    const result = await repo.update("inc-1", updateData);

    expect(prisma.incident.update).toHaveBeenCalledWith({
      where: { id: "inc-1" },
      data: updateData,
      include: { reports: true },
    });
    expect(result.occurrence).toBe(2);
  });

  it("finds by fingerprint", async () => {
    const prisma = createMockPrisma();
    prisma.incident.findUnique.mockResolvedValue(baseRecord);

    const repo = new PrismaIncidentRepository(prisma as any);
    const result = await repo.findByFingerprint("abc123");

    expect(prisma.incident.findUnique).toHaveBeenCalledWith({
      where: { fingerprint: "abc123" },
      include: { reports: true },
    });
    expect(result).not.toBeNull();
    expect(result!.id).toBe("inc-1");
  });

  it("returns null when fingerprint not found", async () => {
    const prisma = createMockPrisma();
    prisma.incident.findUnique.mockResolvedValue(null);

    const repo = new PrismaIncidentRepository(prisma as any);
    const result = await repo.findByFingerprint("nonexistent");

    expect(result).toBeNull();
  });

  it("handles duplicate fingerprint on create", async () => {
    const prisma = createMockPrisma();
    prisma.incident.create.mockRejectedValue(new Error("Unique constraint failed"));

    const repo = new PrismaIncidentRepository(prisma as any);
    await expect(repo.create(baseCreate)).rejects.toThrow("Unique constraint failed");
  });

  it("increments occurrence on update", async () => {
    const prisma = createMockPrisma();
    prisma.incident.update.mockResolvedValue({ ...baseRecord, occurrence: 3 });

    const repo = new PrismaIncidentRepository(prisma as any);
    const result = await repo.update("inc-1", { ...baseRecord, occurrence: 3 });

    expect(result.occurrence).toBe(3);
  });
});
