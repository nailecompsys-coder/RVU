-- Run once against the shared Cal/RVU PostgreSQL database.
ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS service_date DATE;
ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS mrn VARCHAR(64);
ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS line_items TEXT;
