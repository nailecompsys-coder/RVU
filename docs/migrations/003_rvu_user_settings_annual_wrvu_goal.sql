ALTER TABLE rvu_user_settings
  ADD COLUMN IF NOT EXISTS annual_wrvu_goal DOUBLE PRECISION DEFAULT 9000.0;

UPDATE rvu_user_settings
SET annual_wrvu_goal = 9000.0
WHERE annual_wrvu_goal IS NULL;
