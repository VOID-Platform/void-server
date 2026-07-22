-- CreateEnum
CREATE TYPE "AnalysisStatus" AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED');

-- Backfill last_seen from updated_at where last_seen was default now()
UPDATE "incidents" SET "last_seen" = "updated_at" WHERE "last_seen" IS NULL;

-- Backfill analysis_status from latest_report_id
UPDATE "incidents"
SET "analysis_status" = CASE
  WHEN "latest_report_id" IS NOT NULL THEN 'COMPLETED'::"AnalysisStatus"
  ELSE 'PENDING'::"AnalysisStatus"
END;
