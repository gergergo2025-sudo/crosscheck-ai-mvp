ALTER TABLE reports ADD COLUMN IF NOT EXISTS cache_key VARCHAR(64);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS cache_key_version VARCHAR(32);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS report_payload JSONB;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS behavior_versions JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS verification_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_reports_cache_key ON reports(cache_key);
INSERT INTO schema_migrations(version) VALUES ('002_report_cache_and_versions') ON CONFLICT (version) DO NOTHING;
