-- CrossCheck MVP durable graph.  Application migrations are explicit and
-- idempotent; no table is created implicitly by the FastAPI startup hook.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY,
    text TEXT NOT NULL,
    constraints JSONB,
    question_type VARCHAR(20) NOT NULL CHECK (question_type IN ('fact', 'code', 'constraint')),
    question_type_origin VARCHAR(32) NOT NULL CHECK (question_type_origin IN ('explicit', 'deterministic_code', 'deterministic_constraints', 'classifier', 'fallback')),
    expected_output_format VARCHAR(20),
    selected_models JSONB NOT NULL,
    request_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_request_id ON questions(request_id);

CREATE TABLE IF NOT EXISTS answers (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    provider VARCHAR(100) NOT NULL,
    model_name VARCHAR(200) NOT NULL,
    raw_response TEXT NOT NULL,
    structured_answer JSONB NOT NULL,
    parse_status VARCHAR(16) NOT NULL CHECK (parse_status IN ('parsed', 'degraded')),
    parse_diagnostics JSONB NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (score >= 0 AND score <= 1),
    score_components JSONB NOT NULL,
    latency_ms DOUBLE PRECISION,
    token_usage JSONB,
    reported_cost DOUBLE PRECISION,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    provider_status VARCHAR(64) NOT NULL,
    failure_class VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(question_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_answers_question_id ON answers(question_id);

CREATE TABLE IF NOT EXISTS claim_clusters (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    representative_text TEXT NOT NULL,
    clustering_method VARCHAR(64) NOT NULL,
    clustering_version VARCHAR(64) NOT NULL,
    threshold DOUBLE PRECISION,
    verification_status VARCHAR(32),
    supporting_models JSONB NOT NULL,
    oppose_models JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY,
    answer_id UUID NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    claim_type VARCHAR(32) NOT NULL CHECK (claim_type IN ('fact', 'code', 'math', 'logic', 'opinion', 'recommendation')),
    source TEXT,
    self_confidence DOUBLE PRECISION NOT NULL CHECK (self_confidence >= 0 AND self_confidence <= 1),
    assumptions TEXT,
    cluster_id UUID REFERENCES claim_clusters(id) ON DELETE SET NULL,
    verification_status VARCHAR(32) NOT NULL CHECK (verification_status IN ('pending', 'verified', 'unverified', 'conflict', 'unavailable', 'not_applicable')),
    verification_confidence DOUBLE PRECISION CHECK (verification_confidence >= 0 AND verification_confidence <= 1),
    evidence_ids JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_answer_id ON claims(answer_id);
CREATE INDEX IF NOT EXISTS idx_claims_cluster_id ON claims(cluster_id);

CREATE TABLE IF NOT EXISTS verification_results (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    verifier_type VARCHAR(64) NOT NULL,
    verifier_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('pending', 'verified', 'unverified', 'conflict', 'unavailable', 'not_applicable')),
    verified BOOLEAN NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSONB NOT NULL,
    details JSONB NOT NULL,
    duration_ms DOUBLE PRECISION,
    failure_class VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verification_results_claim_id ON verification_results(claim_id);

CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    recommended_answer_id UUID REFERENCES answers(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('complete', 'partial')),
    recommendation_message TEXT NOT NULL,
    consensus JSONB NOT NULL,
    disagreements JSONB NOT NULL,
    model_scores JSONB NOT NULL,
    constraints_check JSONB NOT NULL,
    evidence JSONB NOT NULL,
    warnings JSONB NOT NULL,
    prompt_version VARCHAR(64) NOT NULL,
    total_duration_ms DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(question_id)
);

CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    helpful BOOLEAN NOT NULL,
    claim_id UUID REFERENCES claims(id) ON DELETE SET NULL,
    comment TEXT,
    suggested_answer TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_report_created ON feedback(report_id, created_at);

INSERT INTO schema_migrations(version) VALUES ('001_initial') ON CONFLICT (version) DO NOTHING;
