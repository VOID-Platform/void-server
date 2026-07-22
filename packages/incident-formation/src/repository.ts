import type { PrismaClient } from "@void-server/db";
import type { IncidentRecord, IncidentRepository, CreateIncidentData, UpdateIncidentData } from "./types";

export class PrismaIncidentRepository implements IncidentRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async findByFingerprint(fingerprint: string, includeReports = false): Promise<IncidentRecord | null> {
    return this.prisma.incident.findUnique({
      where: { fingerprint },
      ...(includeReports ? { include: { reports: true } } : {}),
    }) as Promise<IncidentRecord | null>;
  }

  async create(data: CreateIncidentData, includeReports = false): Promise<IncidentRecord> {
    return this.prisma.incident.create({
      data: data as any,
      ...(includeReports ? { include: { reports: true } } : {}),
    }) as Promise<IncidentRecord>;
  }

  async update(id: string, data: UpdateIncidentData, includeReports = false): Promise<IncidentRecord> {
    return this.prisma.incident.update({
      where: { id },
      data: data as any,
      ...(includeReports ? { include: { reports: true } } : {}),
    }) as Promise<IncidentRecord>;
  }
}
