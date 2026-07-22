-- CreateEnum
CREATE TYPE "AnalysisStatus" AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED');

-- Add new columns
ALTER TABLE "incidents" ADD COLUMN "last_seen" TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE "incidents" ADD COLUMN "analysis_status" "AnalysisStatus" NOT NULL DEFAULT 'PENDING';
ALTER TABLE "incidents" ADD COLUMN "latest_labels" JSONB;

-- Backfill last_seen from updated_at where last_seen was default now()
UPDATE "incidents" SET "last_seen" = "updated_at" WHERE "last_seen" IS NULL;

-- Backfill analysis_status based on whether a report exists
UPDATE "incidents"
SET "analysis_status" = CASE
  WHEN "latest_report_id" IS NOT NULL THEN 'COMPLETED'::"AnalysisStatus"
  ELSE 'PENDING'::"AnalysisStatus"
END;
