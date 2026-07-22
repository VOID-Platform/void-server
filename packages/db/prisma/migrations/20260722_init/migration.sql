-- CreateEnum
CREATE TYPE "AnalysisStatus" AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED');

-- Add columns as nullable first so existing rows get NULL
ALTER TABLE "incidents" ADD COLUMN "last_seen" TIMESTAMPTZ;
ALTER TABLE "incidents" ADD COLUMN "analysis_status" "AnalysisStatus";
ALTER TABLE "incidents" ADD COLUMN "latest_labels" JSONB;

-- Backfill last_seen from updated_at (all existing rows are NULL)
UPDATE "incidents" SET "last_seen" = "updated_at";

-- Backfill analysis_status based on whether a report exists
UPDATE "incidents"
SET "analysis_status" = CASE
  WHEN "latest_report_id" IS NOT NULL THEN 'COMPLETED'::"AnalysisStatus"
  ELSE 'PENDING'::"AnalysisStatus"
END;

-- Now apply NOT NULL and defaults for future rows
ALTER TABLE "incidents" ALTER COLUMN "last_seen" SET NOT NULL;
ALTER TABLE "incidents" ALTER COLUMN "last_seen" SET DEFAULT now();
ALTER TABLE "incidents" ALTER COLUMN "analysis_status" SET NOT NULL;
ALTER TABLE "incidents" ALTER COLUMN "analysis_status" SET DEFAULT 'PENDING';
