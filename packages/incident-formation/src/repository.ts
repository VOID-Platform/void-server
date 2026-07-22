import type { PrismaClient } from "@void-server/db";
import type { IncidentRecord, IncidentRepository, CreateIncidentData, UpdateIncidentData } from "./types";

export class PrismaIncidentRepository implements IncidentRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async findByFingerprint(fingerprint: string): Promise<IncidentRecord | null> {
    return this.prisma.incident.findUnique({
      where: { fingerprint },
      include: { reports: true },
    });
  }

  async create(data: CreateIncidentData): Promise<IncidentRecord> {
    return this.prisma.incident.create({ data, include: { reports: true } });
  }

  async update(id: string, data: UpdateIncidentData): Promise<IncidentRecord> {
    return this.prisma.incident.update({
      where: { id },
      data,
      include: { reports: true },
    });
  }
}
