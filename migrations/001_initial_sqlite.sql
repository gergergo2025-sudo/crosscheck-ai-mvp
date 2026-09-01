-- SQLite test/development equivalent of 001_initial.sql.  Production uses
-- PostgreSQL UUID and JSONB types from the sibling migration.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    constraints JSON,
    question_type TEXT NOT NULL CHECK (question_type IN ('fact', 'code', 'constraint')),
    question_type_origin TEXT NOT NULL CHECK (question_type_origin IN ('explicit', 'deterministic_code', 'deterministic_constraints', 'classifier', 'fallback')),
    expected_output_format TEXT,
    selected_models JSON NOT NULL,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_request_id ON questions(request_id);

CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    raw_response TEXT NOT NULL,
    structured_answer JSON NOT NULL,
    parse_status TEXT NOT NULL CHECK (parse_status IN ('parsed', 'degraded')),
    parse_diagnostics JSON NOT NULL,
    score REAL NOT NULL DEFAULT 0 CHECK (score >= 0 AND score <= 1),
    score_components JSON NOT NULL,
    latency_ms REAL,
    token_usage JSON,
    reported_cost REAL,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    provider_status TEXT NOT NULL,
    failure_class TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(question_id, model_name)
);
CREATE INDEX IF NOT EXISTS idx_answers_question_id ON answers(question_id);

CREATE TABLE IF NOT EXISTS claim_clusters (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    representative_text TEXT NOT NULL,
    clustering_method TEXT NOT NULL,
    clustering_version TEXT NOT NULL,
    threshold REAL,
    verification_status TEXT,
    supporting_models JSON NOT NULL,
    oppose_models JSON NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    answer_id TEXT NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK (claim_type IN ('fact', 'code', 'math', 'logic', 'opinion', 'recommendation')),
    source TEXT,
    self_confidence REAL NOT NULL CHECK (self_confidence >= 0 AND self_confidence <= 1),
    assumptions TEXT,
    cluster_id TEXT REFERENCES claim_clusters(id) ON DELETE SET NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('pending', 'verified', 'unverified', 'conflict', 'unavailable', 'not_applicable')),
    verification_confidence REAL CHECK (verification_confidence >= 0 AND verification_confidence <= 1),
    evidence_ids JSON NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_answer_id ON claims(answer_id);
CREATE INDEX IF NOT EXISTS idx_claims_cluster_id ON claims(cluster_id);

CREATE TABLE IF NOT EXISTS verification_results (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    verifier_type TEXT NOT NULL,
    verifier_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'unverified', 'conflict', 'unavailable', 'not_applicable')),
    verified INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSON NOT NULL,
    details JSON NOT NULL,
    duration_ms REAL,
    failure_class TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_results_claim_id ON verification_results(claim_id);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    recommended_answer_id TEXT REFERENCES answers(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('complete', 'partial')),
    recommendation_message TEXT NOT NULL,
    consensus JSON NOT NULL,
    disagreements JSON NOT NULL,
    model_scores JSON NOT NULL,
    constraints_check JSON NOT NULL,
    evidence JSON NOT NULL,
    warnings JSON NOT NULL,
    prompt_version TEXT NOT NULL,
    total_duration_ms REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(question_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    helpful INTEGER NOT NULL,
    claim_id TEXT REFERENCES claims(id) ON DELETE SET NULL,
    comment TEXT,
    suggested_answer TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_report_created ON feedback(report_id, created_at);

INSERT INTO schema_migrations(version) VALUES ('001_initial') ON CONFLICT(version) DO NOTHING;
