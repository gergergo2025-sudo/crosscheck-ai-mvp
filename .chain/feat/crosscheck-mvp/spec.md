## Problem Statement

People who ask an AI about an unfamiliar subject cannot reliably tell whether an answer is correct, current, supported by evidence, or compatible with their constraints. Comparing several model responses manually still leaves them with a popularity contest: models may repeat the same error, cite weak or nonexistent sources, disagree without explaining why, or recommend an option that violates a budget or preference. Developers additionally need executable evidence for code answers, while knowledge workers and researchers need traceable sources for factual claims.

CrossCheck AI currently has only a runnable FastAPI skeleton and a health endpoint. It has no query workflow, provider integrations, structured-answer parser, independent verification, scoring, consensus analysis, persistence, cache, or user interface. API credentials must remain external to the repository, and the application must start safely even when optional services are not configured.

The MVP must turn a single question into a transparent comparison report within a target of 20 seconds. Reliability comes from evidence and explicit uncertainty rather than model voting: each important Claim is typed, independently checked where an MVP Verifier exists, linked to Evidence, and then used to explain Model Answer scores, Consensus, Disagreements, and the recommended answer. The product must never imply that agreement alone proves correctness.

## Solution

CrossCheck AI will provide a single-turn web experience backed by an asynchronous FastAPI orchestration workflow. A user submits a Question, optional Constraints, an optional question type, an optional expected output format, and optionally a permitted model selection. The Orchestrator applies one Unified Prompt to at least three independently configured providers in parallel, with OpenAI, Anthropic Claude, and DeepSeek as the default provider set. OpenAI and DeepSeek are the first mandatory adapter implementations; Claude completes the PRD-required three-provider default before the full MVP is considered complete.

Each Model Adapter returns raw text plus call metadata. The Structured Answer Parser extracts the prescribed answer, concise rationale, Claims, and model-supplied Constraint Checks. Invalid JSON receives one bounded repair attempt; a still-invalid response remains visible as a degraded plain-text Model Answer with no Claims rather than failing the entire Question.

Claims from successful answers are normalized and grouped by semantic similarity at a configurable default threshold of 0.85. Claim Clusters express which models support a materially equivalent statement. The MVP does not infer semantic opposition automatically; Disagreements are clusters lacking verified multi-model support, clusters with conflicting Evidence, and materially different model answers presented side by side.

The Orchestrator routes Claims to independent Verifiers. The Fact Verifier searches a configured search provider, preserves the supporting and conflicting result metadata, and calculates an explainable authority/confidence value. The Code Verifier runs extracted Python code and explicit or safe generated tests in a resource-limited local Docker sandbox. The Constraint Verifier compares normalized user Constraints with answer parameters and reports a result per constraint. Unsupported math, logic, opinion, and recommendation Claims remain visibly unverified; the system does not silently treat model self-confidence as proof.

The Scoring Engine applies the PRD weights to normalized, evidence-backed components and records both the total and component breakdown. Only verified Consensus earns consensus credit. The Report Builder recommends the highest-scoring usable Model Answer when its score is at least 0.60; otherwise the report explicitly says confidence is insufficient and directs the user to the Evidence and Disagreements. A partial report is returned when some providers or Verifiers fail, provided at least one Model Answer is usable.

The React report experience will show the recommendation or insufficient-confidence state, Consensus, Disagreements, expandable Model Answers, Claim verification badges, Evidence links, Constraint Checks, provider failures, and an AI fallibility notice. Users can submit helpful/not-helpful feedback, identify an erroneous Claim in a comment, or suggest a better answer. PostgreSQL stores the Question, answers, Claims, Verification Results, Report, and feedback. Redis caches exact normalized Question requests for 24 hours by default; it is an optimization, not a source of truth.

The backend remains runnable with `uv run uvicorn crosscheck.main:app --reload`; `GET /health` continues to return exactly `{"status":"ok"}`. Secret values are loaded only from runtime environment variables, never logged or persisted in answer metadata, and `.env.example` contains placeholders only.
## User Stories

1. As a knowledge worker, I want to submit one natural-language Question, so that I can compare several independent answers without visiting several products.
2. As a user, I want a clear validation error for a blank or oversized Question, so that I can correct my request without losing context.
3. As a decision maker, I want to attach structured or natural-language Constraints, so that recommendations are evaluated against my real situation.
4. As a user, I want to specify a question type when I know it, so that the appropriate verification path is selected.
5. As a user, I want CrossCheck to infer a supported question type when I omit it, so that the common flow remains simple.
6. As a user, I want to request a list, comparison table, or steps, so that each model aims for a useful presentation format.
7. As a user, I want the same substantive Unified Prompt sent to every selected model, so that the comparison is fair.
8. As a researcher, I want at least three independently configured model providers queried by default, so that the report reflects genuinely different systems.
9. As a cost-conscious operator, I want the allowed models and maximum query cost configurable, so that one Question cannot create uncontrolled spend.
10. As a user, I want model calls to run concurrently, so that the report can meet the 20-second target.
11. As a user, I want bounded timeouts, retries, and exponential backoff for transient provider failures, so that temporary errors do not unnecessarily ruin a report.
12. As a user, I want one provider failure isolated from the other providers, so that I can still receive a useful partial Report.
13. As an operator, I want an unavailable or unconfigured provider shown as a sanitized status, so that missing credentials are actionable without exposing secrets.
14. As a user, I want an explicit service error when no configured model can answer, so that I am not shown an empty or fabricated Report.
15. As a user, I want the service and health check to start without provider keys, so that configuration problems do not crash the application.
16. As a reviewer, I want each Model Answer to contain an answer, concise rationale, typed Claims, sources, confidence, assumptions, and Constraint Checks, so that it can be evaluated consistently.
17. As a safety-conscious user, I want the rationale to be a concise explanation rather than hidden chain-of-thought, so that the report is useful without claiming access to private model reasoning.
18. As a user, I want JSON wrapped in prose or a Markdown fence to be recovered when unambiguous, so that harmless provider formatting does not discard an answer.
19. As a user, I want invalid structured output to receive one repair attempt, so that recoverable schema mistakes are corrected within the time budget.
20. As a user, I want a still-unparseable response retained as plain text and marked degraded, so that I can inspect it without mistaking it for verified content.
21. As a reviewer, I want unknown fields tolerated but required field types validated, so that provider evolution is resilient without weakening the report contract.
22. As a researcher, I want materially equivalent Claims grouped across models, so that repeated wording does not clutter Consensus.
23. As a reviewer, I want every Claim Cluster to identify its representative Claim and supporting models, so that the origin of Consensus is traceable.
24. As a reviewer, I want duplicate Claims from the same model to count once in a cluster, so that one verbose answer cannot manufacture Consensus.
25. As a user, I want similarity threshold and embedding model configuration recorded, so that cluster behavior can be understood and tuned.
26. As a user, I want a deterministic lexical fallback when embedding service is unavailable, so that the report can still group obvious duplicates without overstating semantic Consensus.
27. As a user asking a factual Question, I want each Fact Claim checked against independent search results, so that agreement among models is not treated as proof.
28. As a researcher, I want supporting and conflicting Evidence links, titles, domains, snippets, and available publication dates, so that I can inspect the basis of a verdict.
29. As a reviewer, I want source authority and recency incorporated into an explainable confidence, so that weak or stale Evidence is not presented like a primary source.
30. As a user, I want a Fact Claim marked unverified when search is unavailable or Evidence is inconclusive, so that absence of evidence is never converted into a pass.
31. As a developer, I want Python code answers executed against explicit tests in an isolated local Docker sandbox, so that recommendations include behavioral evidence.
32. As an operator, I want sandbox network access disabled and CPU, memory, process, output, filesystem, and wall-time limits enforced, so that untrusted code cannot endanger the host.
33. As a developer, I want model-provided tests used when safely parseable and minimal deterministic tests generated only for recognized tasks, so that the test basis is visible rather than arbitrary.
34. As a developer, I want code execution results to include execution status, passed and total test counts, bounded output, and sanitized errors, so that failures are diagnosable.
35. As a user, I want every submitted Constraint normalized and checked separately, so that one satisfied preference cannot hide a violated budget.
36. As a user, I want quantitative Constraints compared with normalized units and currencies only when safely comparable, so that the system does not make invalid conversions.
37. As a user, I want unknown or unevaluable Constraints marked indeterminate with a reason, so that uncertainty remains visible.
38. As a user, I want Fact, Code, and Constraint results attached back to the originating Claims and Model Answers, so that evidence provenance is preserved.
39. As a user, I want unsupported math, logic, opinion, and recommendation Claims labeled unverified or not-applicable, so that unsupported Verifiers do not pretend to decide them.
40. As a user, I want every Model Answer score shown with component values and effective denominators, so that the recommendation is explainable.
41. As a user, I want only independently verified multi-model Consensus to earn score credit, so that shared hallucinations are not rewarded.
42. As a user, I want missing scoring components handled by documented neutral normalization rather than silently scored as correct, so that answer types are compared consistently.
43. As a user, I want the highest-scoring usable Model Answer recommended only above the 0.60 threshold, so that weak results are not endorsed.
44. As a user, I want deterministic tie handling disclosed, so that repeated equivalent queries produce stable recommendations.
45. As a user, I want a clear insufficient-confidence result when no answer crosses the threshold, so that I know to inspect Evidence and Disagreements.
46. As a user, I want verified Consensus summarized separately, so that I can quickly see what independent evidence supports.
47. As a user, I want uncertain, conflicting, and model-specific Claims shown as Disagreements, so that differences are not hidden by the recommendation.
48. As a user, I want each verification badge to distinguish verified, uncertain, conflict, unavailable, and not-applicable states, so that a missing check is not confused with a failed check.
49. As a user, I want Evidence links opened as external, safely rendered links, so that untrusted model content cannot inject active markup.
50. As a user, I want full Model Answers and scores in expandable comparison cards, so that I can audit the recommendation without an overwhelming default view.
51. As a user, I want provider and Verifier progress states while a Question is running, so that I understand where time is being spent.
52. As a user, I want a cached exact repeat to return the same complete Report quickly, so that repeated Questions cost less and feel responsive.
53. As a user, I want cache keys to include all inputs that affect the Report, so that different Constraints, formats, models, or scoring configuration do not collide.
54. As an operator, I want a configurable 24-hour default cache TTL and a safe bypass mechanism, so that time-sensitive Questions can be refreshed.
55. As an operator, I want Questions, Model Answers, Claims, Verification Results, Reports, and feedback persisted transactionally, so that an audit trail remains internally consistent.
56. As a user, I want to mark a Report helpful or unhelpful and add a comment, so that I can provide outcome feedback.
57. As a user, I want to identify an erroneous Claim or suggest a better answer in feedback, so that future tuning has specific evidence.
58. As an operator, I want feedback stored without automatically changing live scoring weights, so that unreviewed input cannot manipulate recommendations.
59. As an operator, I want model name, latency, token usage when supplied, retry count, parse status, verification status, cache status, and sanitized failures logged, so that reliability and cost can be monitored.
60. As a security reviewer, I want API keys read only from environment configuration and redacted from logs, database records, errors, and responses, so that credentials are not leaked.
61. As a privacy-conscious user, I want logs to avoid raw Question, Model Answer, and feedback bodies by default, so that potentially sensitive content is minimized.
62. As an operator, I want the public API to reject excessive payloads and apply configurable rate limits, so that the MVP resists accidental or abusive load.
63. As an operator, I want PostgreSQL, Redis, backend, frontend, and the sandbox prerequisites runnable through local Docker-based setup, so that development is reproducible.
64. As a developer, I want the documented uv and Uvicorn command to start the backend and preserve the exact health response, so that the existing operational contract remains valid.
65. As a user in a medical, legal, or financial context, I want evidence and uncertainty displayed without an automated decision, so that the product does not overstep its risk boundary.
66. As a user, I want a persistent notice that AI-generated content may be wrong and key information should be checked, so that the Report is not mistaken for a guarantee.
67. As a product owner, I want new Model Adapters and Verifiers to plug into stable interfaces, so that additional providers and assurance methods do not rewrite orchestration.
68. As an API consumer, I want machine-readable request, success, partial-success, and error schemas, so that clients can integrate without scraping UI text.
69. As an API consumer, I want stable identifiers for Reports, Model Answers, Claims, Clusters, and Verification Results, so that feedback and drill-down references remain valid.
70. As a user, I want only a single-turn Question flow in the MVP, so that the interface is predictable and does not imply conversational memory.
## Implementation Decisions

### Product and repository baseline

- Preserve the existing Python 3.11, uv-managed, `src`-layout FastAPI application and exact `GET /health` response. The current hidden `GET /api/query` placeholder is removed when the real `POST /api/query` contract is introduced; no public GET query endpoint is added.
- Add a React, Vite, and Tailwind web client, PostgreSQL 15 persistence, Redis 7 caching, and a local Docker execution sandbox. Docker Compose is the reproducible local integration environment. The backend remains runnable independently when PostgreSQL or Redis is unavailable only for health and configuration diagnostics; query persistence is required for successful Reports, while cache failure degrades to an uncached query.
- Use asynchronous in-process orchestration for the MVP. No task queue, distributed workflow engine, or background polling protocol is introduced.
- Use the PRD domain terms consistently: Question is the submitted request; Model Answer is one provider result; Claim is an asserted unit from an answer; Claim Cluster groups materially equivalent Claims; Verification Result records one Verifier outcome; Evidence is a source or execution artifact; Report is the immutable query result; Consensus is verified multi-model support; Disagreement is uncertainty, conflict, or model-specific content; Constraint Check is one normalized constraint outcome.
- The full MVP acceptance surface covers fact, Python code/algorithm, and explicit-constraint Questions. Fact, Code, and Constraint Verifiers are included. Math and logic Claims may be parsed and displayed but do not receive an automated correctness verdict.

### Public API contract

- `POST /api/query` accepts JSON with `question` (required nonblank string, maximum 10,000 UTF-8 characters), `constraints` (optional JSON object or natural-language string), `question_type` (optional `auto`, `fact`, `code`, or `constraint`, default `auto`), `expected_output_format` (optional `plain`, `list`, `table`, or `steps`), `models` (optional nonempty array of configured allow-listed model identifiers), and `refresh` (optional boolean, default false). Unknown top-level request fields are rejected to surface client mistakes.
- A model identifier maps to a server-side Adapter configuration; the request cannot supply provider URLs, credentials, prompts, timeout overrides, or arbitrary model parameters. Duplicate model identifiers are normalized away while retaining configured order. The default list contains one OpenAI, one Claude, and one DeepSeek model and must be operator-configurable because provider model names change.
- A successful query returns HTTP 200 with `report_id`, `status` (`complete` or `partial`), `cached`, timestamps and duration, the normalized Question summary, `recommended_answer` (nullable), `recommendation_message`, `consensus`, `disagreements`, `model_comparison`, deduplicated `evidence`, aggregate `constraints_check`, and `warnings`. A partial status means at least one requested provider or Verifier failed or became unavailable; its failure remains visible in `model_comparison` or warnings.
- Every Model Answer entry exposes a stable ID, configured model identifier, provider, answer text, concise rationale, Claims, Constraint Checks, parse status (`parsed` or `degraded`), score and component breakdown, latency, and sanitized provider status. Raw provider response is persisted for audit but is not returned separately when it would duplicate answer text or contain provider-only metadata.
- Every Claim exposes a stable ID, type, text, optional model-provided source, bounded self-reported confidence, assumptions, Cluster ID when assigned, Verification status, Verification confidence, and Evidence references. Model confidence is always labeled as self-reported and never substitutes for verification.
- Verification status is a closed vocabulary: `pending`, `verified`, `unverified`, `conflict`, `unavailable`, and `not_applicable`. The UI must not collapse these into a binary pass/fail.
- Empty or invalid input returns HTTP 422 with field-level details. Rate limiting returns 429. No configured usable provider returns 503 with code `MODEL_CONFIGURATION_UNAVAILABLE`. Exhaustion or failure of every selected provider returns 502 with code `NO_USABLE_MODEL_ANSWER`. The standard error body contains `error.code`, a safe human-readable `error.message`, optional field `details`, and a request ID; it never contains credentials, prompts with secrets, or raw upstream bodies.
- `POST /api/feedback` accepts `report_id`, `helpful` (required boolean), optional bounded `comment`, optional `claim_id` identifying an alleged error, and optional bounded `suggested_answer`. The Claim, if supplied, must belong to the Report. It returns HTTP 201 with the feedback ID and creation time. Feedback is append-only and does not recalculate the existing Report.
- API schema is published through FastAPI OpenAPI. All identifiers are UUIDs represented as strings, times are UTC ISO 8601, confidence and score values are numbers in `[0,1]`, and absent values use JSON null rather than magic strings.

### Orchestration and question classification

- The query use case is the single coordinator for cache lookup, persistence, provider fan-out, parsing, classification, clustering, verification, scoring, Report creation, and cache write. Internal services exchange validated domain objects rather than provider-specific dictionaries.
- Question type precedence is explicit user selection, then deterministic signals for code and structured Constraints, then a bounded classifier, then `fact` as the conservative fallback. The inferred type and whether it was user-selected are recorded in the Report.
- The overall target is under 20 seconds. Provider and search calls run concurrently where dependencies permit. The coordinator carries an absolute deadline and cancels remaining optional work when the deadline is exhausted, returning a partial Report if at least one usable answer exists.
- Persistence is transactional at Report assembly: a client never receives a Report ID whose Report and answer relationships were only partly written. Provider-call diagnostic records may be written separately for observability, but cannot appear as a completed Report.

### Unified Prompt and Structured Answer Parser

- One versioned Unified Prompt contains the Question, serialized Constraints, inferred or selected type, expected output format, and the prescribed structured schema. Provider-specific transport wrappers may differ, but substantive instructions and input content remain equivalent across providers.
- The prompt requests `answer`, a concise `reasoning` summary, `claims`, and `constraints_check`. Claim types are limited to `fact`, `code`, `math`, `logic`, `opinion`, and `recommendation`. It requests source URLs or citations only when the model actually has them and forbids invented sources. It asks for strict JSON without Markdown fences.
- `reasoning` is treated as a concise answer rationale, not hidden chain-of-thought. It may be empty; answer eligibility does not depend on receiving private reasoning.
- The parser first attempts the whole response as JSON, then a single unambiguous fenced or balanced JSON object after removing harmless surrounding prose. It validates required fields, coerces only safe primitives, clamps neither out-of-range confidence nor malformed content, and records validation diagnostics.
- On parse failure, the same Adapter receives one repair request containing the invalid response and schema instructions, subject to the query deadline and cost ceiling. This repair is distinct from transport retries. If repair fails, the original raw text becomes a degraded Model Answer, Claims and Constraint Checks are empty, parse success is false, and its score is zero. A degraded answer remains visible but is never recommended.
- Unknown structured-answer fields are ignored for forward compatibility. Missing optional source or assumptions fields become null or empty; a missing or invalid answer, Claims collection, Claim type, or confidence shape fails structured parsing.

### Model Adapter boundary

- A shared asynchronous Adapter interface accepts the versioned prompt, model configuration, deadline, and generation options and returns a provider-neutral result containing raw text, provider/model identity, latency, token usage and cost when reported, retry count, and a sanitized outcome. Provider SDK types do not cross this boundary.
- Implement distinct OpenAI, Anthropic Claude, and DeepSeek adapters. OpenAI and DeepSeek are the initial mandatory pair; the default full-MVP configuration is not valid as “three-model mode” until Claude is present. Adding another provider requires only a new Adapter plus configuration registration and contract tests.
- Each attempt has a maximum 10-second timeout but is additionally capped by the remaining overall deadline. Retry at most two times after the initial attempt for network failures, timeouts, HTTP 408/429, and retryable 5xx responses. Use exponential backoff with jitter and honor a bounded `Retry-After`. Authentication, permission, malformed-request, and other permanent 4xx failures are not retried.
- Calls are isolated: one failed Adapter cannot cancel successful siblings. The cost guard checks configured per-model estimates before dispatch and reported usage afterward; models that would exceed the configured maximum are skipped with an explicit status. The MVP makes no claim of precise billing where providers omit usage.
- Secret configuration is resolved at startup into server-side settings but validated lazily per integration. Missing keys do not prevent application startup or health checks. An unavailable optional Adapter is reported; if none of the requested/default Adapters are usable, query returns the explicit 503 contract.

### Claim normalization, clustering, Consensus, and Disagreement

- Preserve original Claim text for display and audit. A separate normalization removes surrounding whitespace, normalizes Unicode and case where language-safe, and collapses punctuation/spacing solely for matching.
- Generate sentence embeddings for nonempty Claims through a configurable embedding service/model, cache embeddings by normalized text and embedding version, and perform deterministic greedy clustering in Model Answer order. A Claim joins the cluster with the highest similarity to its representative when cosine similarity is at least 0.85; otherwise it starts a new cluster. The representative is the highest self-reported-confidence Claim, breaking ties by longer text and then stable input order.
- The threshold is configuration with 0.85 as the default and is recorded with the embedding version in Report metadata. Only one Claim per model contributes support to a Cluster even if that answer repeats itself.
- If embedding generation is unavailable, use a deterministic normalized-token similarity fallback only for obvious near-duplicates at a stricter configured threshold. Mark clustering as degraded in Report warnings; degraded grouping alone cannot earn semantic Consensus credit unless the representative Claim is independently verified.
- A Consensus item requires at least two distinct successful model providers in a Cluster and a `verified` Verification Result for the representative. It includes supporting models, verification confidence, and Evidence references. Model count alone is insufficient.
- Automatic semantic contradiction/opposition inference is deferred. Therefore `oppose_models` remains empty unless a model explicitly negates an identical normalized proposition in a deterministically recognized form; this limited behavior must not be marketed as general contradiction detection. Disagreements include singleton Claims, multi-model clusters without verified support, clusters marked conflict/unverified/unavailable, and answer-level alternatives. The report describes why each item is included.

### Verifier boundary and Evidence

- A shared asynchronous Verifier interface receives a typed Claim, relevant Question context, normalized Constraints, and deadline, and returns a provider-neutral Verification Result. Verifiers are registered by Claim type and question context; multiple applicable results may attach to a Claim. Unsupported types return `not_applicable`, not success.
- Verification errors are data, not orchestration exceptions. Each result records verifier type/version, status, confidence, bounded details, Evidence references, duration, and sanitized failure reason. Evidence provenance is immutable after Report creation.
- Fact Verification searches the configured search provider for the representative Fact Claim, requesting five results by default within the permitted 5–10 range. It retains URL, title, domain, bounded snippet, available publication date, search rank, calculated domain authority, recency, and whether the item supports, conflicts with, or is merely related to the Claim.
- Fact authority uses the PRD weighting: 0.4 domain whitelist class, 0.3 configured source reputation, and 0.3 recency. Government and educational domains and configured primary or high-reputation publishers receive higher scores; Wikipedia may corroborate but cannot be the sole Evidence for `verified`. Domain matching uses parsed hostnames, never substring checks.
- A Fact Claim is `verified` only when at least one high-authority primary source or two independent credible domains provide materially supporting Evidence and no equal-or-stronger conflict is found. It is `conflict` when credible Evidence directly contradicts it, `unverified` when results are related but insufficient, and `unavailable` when search cannot run. Search absence never verifies a Claim. Semantic support/conflict classification may use a separately configured lightweight adjudicator, but its output is advisory and must be anchored to returned Evidence rather than used as a source itself.
- Code Verification is limited to Python in the MVP. It extracts a clearly delimited code candidate and explicit tests where present. For a small allow-list of recognized algorithm contracts, deterministic locally maintained tests may be selected from the Question; otherwise the result states that no safe test contract was available rather than inventing expected behavior with another answer model.
- Code executes only in an ephemeral local Docker container built from a pinned, minimal image. It has no network, no host mounts, a read-only base filesystem plus bounded temporary workspace, non-root user, dropped Linux capabilities, process/CPU/memory/output limits, and a hard wall timeout. The result records `executed`, passed and total tests, exit class, bounded stdout/stderr, and sanitized error. A zero-test run cannot be `verified`.
- Constraint Verification creates one normalized check per user Constraint. Structured Constraints are preferred; natural-language Constraints use deterministic extraction for recognized budget, duration, weight, dimensions, inclusion, exclusion, usage, and preference forms, with an optional lightweight extractor clearly recorded. The answer side is derived from Claim and Constraint Check content and may be corroborated by Fact Evidence.
- Numeric comparisons preserve unit and currency. No live currency conversion or unstated unit conversion is performed; incomparable values are `unverified`. Enumerated exclusion is strict, usage and preference are explicitly satisfied only with supporting answer content, and missing answer parameters are `unverified`. Each result reports normalized expected value, observed value, comparator, status, and reason.

### Scoring and recommendation

- Calculate the five PRD components on `[0,1]`: factual verification pass rate (`w1=0.30`), mean authority of supporting Fact Evidence (`w2=0.15`), executable test pass rate (`w3=0.20`), Constraint satisfaction rate (`w4=0.20`), and verified Consensus coverage (`w5=0.15`). Persist raw numerator, denominator, component score, configured weight, and whether the component was applicable.
- A component is applicable only when its evidence category exists: factual components require Fact Claims, execution requires an executed Code test suite, constraint satisfaction requires submitted Constraints, and Consensus requires at least two usable Model Answers and parsed Claims. Unsupported or unavailable checks do not count as passes. Applicable checks with attempted but failed/unverified evidence score zero.
- To avoid structurally penalizing a fact-only or code-only Question for absent categories, exclude genuinely non-applicable components and renormalize the remaining configured weights to total 1. This preserves the PRD weight ratios and is disclosed in the component breakdown. If no component is applicable, the answer score is zero.
- Consensus coverage is the fraction of that answer's unique Cluster memberships that are both supported by at least two providers and independently verified. It never rewards an unverified majority.
- Apply assurance caps after the weighted score: a degraded answer scores zero; a query with only one usable provider, or an answer with no successful independent Verification Result, cannot exceed 0.59. A credible conflicting result on a central Claim is reflected as zero for that Claim and keeps the recommendation below the 0.60 threshold until the conflict is resolved.
- Recommend the highest final score at or above 0.60. Scores are rounded only for display. Exact ties use configured model order for stability and disclose the tie; provider order is not itself a score. If no eligible answer crosses the threshold, `recommended_answer` is null and the prescribed insufficient-confidence message is returned.
### Persistence and data model

- Use PostgreSQL UUID primary keys, UTC timezone-aware creation timestamps, foreign keys, explicit enums or constrained strings for closed statuses, and JSONB only for genuinely variable structured payloads. Apply schema migrations rather than creating tables implicitly at application startup.
- `questions` stores ID, original text, canonicalized Constraints JSON, selected/inferred type and origin, expected output format, selected model identifiers, nullable user ID, request ID, and creation time. The MVP is anonymous and does not create accounts; user ID remains nullable for future compatibility.
- `answers` stores ID, Question foreign key, provider and model identifiers, bounded raw response, validated Structured Answer JSON, parse status and diagnostics, score and component breakdown, latency, token/cost metadata when reported, sanitized call status, and creation time. A unique constraint prevents duplicate answer rows for the same Question execution and model identifier.
- `claim_clusters` stores ID, Question foreign key, representative text, clustering method/version/threshold, verification summary, supporting model identifiers, limited opposing identifiers, and creation time. It exists explicitly rather than encoding all cluster identity only inside Report JSON.
- `claims` stores ID, Answer and optional Cluster foreign keys, original and normalized text, Claim type, model-provided source, self-reported confidence, assumptions, aggregate Verification status/confidence, and creation time. Index Answer, Cluster, and type/status fields used by Report assembly.
- `verification_results` stores ID, Claim foreign key, Verifier type/version, closed status, boolean `verified` compatibility value where required by the PRD, confidence, Evidence JSONB, bounded details JSONB, duration, sanitized failure class, and creation time. The boolean is true only for status `verified`; consumers use the richer status for display.
- `reports` stores ID, Question foreign key, nullable recommended Answer foreign key, overall status, recommendation message, Consensus and Disagreements JSONB, model score summary, Constraint summary, warnings, versions of prompt/clustering/scoring configuration, total duration, and creation time. A Report is immutable after creation; feedback is separate.
- `feedback` stores ID, Report foreign key, helpful boolean, optional Claim foreign key, bounded comment and suggested answer, nullable anonymous user ID, and creation time. Validate relational ownership before insert and index Report and creation time.
- Delete behavior preserves audit consistency: deleting a Question through future administrative tooling cascades its Reports, Answers, Claims, Verification Results, and feedback as one controlled operation. No delete API is part of this MVP.
- Do not store API keys, authorization headers, full provider request headers, sandbox host details, or search-provider credentials anywhere in these records. Bound raw response, Evidence snippet, execution output, feedback, and diagnostic sizes to prevent unbounded storage.

### Cache behavior

- Redis caches only completed or partial HTTP 200 Reports. Never cache validation, authentication/configuration, rate-limit, or all-provider-failure responses.
- The cache key is a versioned SHA-256 digest of normalized Question text, canonical Constraints, question type, expected format, ordered effective model set, Unified Prompt version, Adapter/model configuration version, clustering version, Verifier version set, and scoring configuration. No secret is part of the key or value.
- Default TTL is 86,400 seconds and is configurable. `refresh=true` bypasses lookup and replaces the key only after a new Report commits successfully. Concurrent identical misses use a short Redis lock or single-flight mechanism; lock expiry must be below the query deadline plus a small cleanup margin.
- Redis failure is logged and returned as a warning while the uncached query continues. PostgreSQL remains the durable source for a cached Report ID. If a cache value references a missing or incompatible Report, treat it as a miss.
- **Assumption:** although the PRD mentions identical or similar Questions, the MVP performs exact canonical request caching only. Semantic cache reuse risks returning stale or constraint-mismatched evidence and is deferred.

### Report web experience

- Provide one responsive single-page flow with Question input, optional collapsible Constraints, question type, expected format, and model selection. Default controls remain simple; advanced choices expose only server allow-listed values.
- During submission show one status per selected model plus aggregation/verification progress that can be truthfully derived from the request lifecycle. The API remains synchronous in the MVP, so progress may use staged client states rather than claiming unavailable server events. Prevent duplicate submissions while one request is active and allow retry after failure.
- Render the recommendation card first, including Model Answer text, source model, final confidence/score, component explanation, and a conspicuous insufficient-confidence alternative when recommendation is null.
- Render verified Consensus with supporting models and Evidence; Disagreements with inclusion reasons and links to relevant Model Answers; a Claim/Evidence panel with status badges; an aggregate per-Constraint result; and expandable Model Answer cards with complete answer, concise rationale, Claims, score breakdown, parse/provider status, and failures.
- Badge semantics are explicit: verified uses a positive check, unverified or unavailable uses a warning, conflict uses an error mark, pending appears only during processing, and not-applicable uses a neutral mark. Do not rely on color alone.
- Treat all model, search, and feedback content as untrusted text. Do not render arbitrary HTML or Markdown with active elements. Evidence URLs must be valid HTTP(S), receive safe external-link attributes, and display their hostname. No provider response may inject script, style, or navigation.
- The feedback area supports helpful/not helpful, optional erroneous Claim selection, comment, and suggested answer. It confirms successful storage and handles invalid Report/Claim references without discarding typed feedback.
- Meet baseline accessibility expectations: keyboard-operable controls and disclosures, associated labels, visible focus, semantic tables or lists, status text in addition to icons, polite loading announcements, and reasonable narrow-screen stacking of the 70/30 desktop layout.
- Display “AI-generated content may be wrong; verify important information” on every Report. When the Question appears medical, legal, or financial, replace recommendation language with evidence-oriented wording and suppress automated decision endorsement even if an answer scores above threshold.

### Configuration, security, and privacy

- Central validated settings cover provider model identifiers and keys, search and embedding provider, PostgreSQL and Redis URLs, prompt/version identifiers, timeouts/retries, total query deadline, model count and cost ceiling, cache TTL, cluster threshold, score weights/threshold, rate limits, sandbox image/limits, payload/output bounds, and allowed frontend origin.
- Runtime secrets come from environment variables or deployment secret injection. `.env` is local-only and ignored; `.env.example` includes empty placeholders and safe nonsecret defaults. Configuration and exception representations redact fields whose names or values could be credentials. Never hardcode, print, commit, return, or persist real keys.
- `GET /health` is a liveness check and remains independent of external integrations. A separate readiness check may report only coarse PostgreSQL/Redis configuration and connectivity status without provider secrets; readiness does not call paid model APIs.
- The anonymous MVP collects no required identity fields. Store content needed to generate and audit Reports, but avoid raw bodies in ordinary logs. Use request/report IDs, hashes, lengths, categories, timings, and status codes for diagnostics. Sanitize upstream errors and sandbox output before logging or returning them.
- Apply configurable request-body limits, Question/feedback field bounds, allow-listed models, timeout and concurrency limits, and per-client rate limiting. Trust proxy headers only from configured proxies. The API does not expose arbitrary outbound URLs.
- Search uses provider-returned result metadata in the MVP and does not crawl Evidence URLs. If later retrieval is added, it requires SSRF controls, DNS/IP revalidation, content limits, and private-network denial and is not implied by this specification.
- Sandbox execution is opt-in only for Code Verification and must fail closed when Docker or the pinned image is unavailable. The backend process never executes submitted code directly.
- High-compliance domains receive evidence display and uncertainty notices only. No legal, financial, or medical automated decision is produced. Feedback is never interpreted as verified truth without offline review.
- **Assumption:** authentication, user accounts, tenant separation, billing, and user-facing retention/deletion controls are not required for the anonymous MVP. Deployments must still configure transport security, database access control, backups, and an operational retention policy.

### Observability, availability, and cost

- Emit structured events for request start/end, cache hit/miss/error, Adapter outcome/retry/latency/tokens/reported cost, parse/repair outcome, clustering mode, Verifier outcome/latency, scoring summary, Report persistence, and feedback creation. Correlate with request and Report IDs and exclude raw user/provider content by default.
- Provide metrics for query latency and status, provider availability and latency, parse degradation, Verifier availability and verdicts, cache hit rate, sandbox failures, estimated/reported cost, score distribution, insufficient-confidence rate, and feedback helpfulness. The 20-second target is measured at the API boundary for uncached requests and reported separately from cached latency.
- The >99% core-flow availability objective is an SLI/SLO to measure after deployment, not a claim that external providers are always available. Partial Reports, multiple providers, bounded retries, and cache improve availability; the status must still honestly identify degraded assurance.
- Enforce a configurable query cost ceiling before dispatch where estimates exist. Record estimated versus provider-reported cost without exposing rates as guarantees. A skipped provider yields a partial Report warning; cost control cannot silently reduce the model set and still claim three-model Consensus.
- Use connection pooling for PostgreSQL and Redis, bounded HTTP clients with reused connections, and bounded fan-out. No retry loop may outlive the absolute query deadline.

### Deployment and compatibility

- Docker Compose defines PostgreSQL 15, Redis 7, backend, and frontend services plus the local sandbox prerequisite. Service health checks and dependency ordering assist startup but do not conceal failed migrations or missing required infrastructure.
- The backend uses migrations as an explicit startup/deployment step. The frontend receives only the public API base URL and other nonsecret build-time settings. Provider keys never enter frontend bundles or browser storage.
- Preserve the documented local backend command and exact health payload. Document setup, environment placeholders, migration, test, frontend, Docker/Compose, and sandbox-image preparation commands as part of delivery.
- Prefer compatible additive API and persistence changes during MVP iteration. Version prompt, scoring, clustering, and Verifier behavior in each Report so cached and historical results remain interpretable.
## Testing Decisions

### Test philosophy and selected seams

- A good test asserts externally observable behavior: HTTP schemas/statuses, persisted Report relationships, rendered user states, provider protocol compatibility, or sandbox isolation and results. It must not assert private helper calls, coroutine scheduling order, internal class names, SQL text, CSS utility classes, or incidental log wording.
- Prefer deterministic inputs, fixed clocks/IDs where needed, recorded configuration versions, and controlled fake external responses. Paid model/search services are not required for the default suite. Tests must prove uncertainty and degraded states as carefully as happy paths; a test that only checks “200” is insufficient.
- **Primary seam — HTTP Report seam:** exercise `GET /health`, `POST /api/query`, and `POST /api/feedback` through the ASGI HTTP boundary, with real parsing, clustering, verification routing, scoring, Report building, validation, and serialization. Inject deterministic provider, search, embedding, clock, and sandbox ports. Use real PostgreSQL and Redis in integration coverage where persistence/cache behavior is the subject. This is the highest and broadest seam and should carry most backend acceptance coverage.
- **Browser Report seam:** exercise the built web application from Question entry through Report rendering and feedback, using a controlled API server. This seam covers semantics, accessibility-visible states, safe rendering, responsive content hierarchy, and interaction rather than component implementation.
- **External Adapter contract seam:** execute each Model Adapter and search/embedding integration against a mock HTTP server that reproduces success, malformed payload, timeout, rate-limit, retryable server error, permanent client error, and usage metadata. This narrower seam is justified because upstream protocols cannot be faithfully diagnosed at the public HTTP seam alone.
- **Docker Sandbox seam:** execute harmless and adversarial fixture programs in the real pinned local container to prove test reporting and isolation limits. Mocking Docker cannot establish the security property, so these tests are marked integration and may be skipped only when the environment explicitly lacks Docker.
- Database migrations, transactions, Redis cache, and rate-limit behavior are tested through the HTTP Report seam against containerized services rather than through repository or ORM-unit seams. Pure deterministic scoring and normalization examples may have focused table tests for exhaustive boundary coverage, but endpoint tests remain the acceptance authority.

### Backend behavior coverage

- Verify the documented Uvicorn import starts and `GET /health` returns status 200 with exactly `{"status":"ok"}` regardless of missing provider, search, Redis, or sandbox credentials/configuration.
- Verify query request acceptance for minimal input and every optional field, plus rejection of blank/whitespace, excessive lengths, malformed Constraints, unknown type/format/model, duplicate-normalized empty model set, unknown fields, and oversized body.
- Verify a factual Question with three valid structured Model Answers produces a durable Report containing all requested model entries, Claims, Clusters, Evidence, score breakdowns, verified Consensus, and a threshold-qualified recommendation.
- Verify a Python code Question reports real passed/total test evidence and uses execution in scoring. Verify syntax errors, failed tests, timeout, output truncation, prohibited network, fork/process pressure, memory pressure, filesystem attempts, missing Docker, and no safe test contract yield distinct safe statuses without host execution.
- Verify a constrained Question reports each structured and supported natural-language Constraint separately, including satisfied, violated, missing, incompatible currency/unit, exclusion, usage, and preference cases. Unevaluable values must be unverified, never implicitly satisfied.
- Verify selected question type overrides inference; otherwise verify representative fact, code, and constraint inference and conservative fallback, with the classification origin exposed.
- Verify all model calls receive equivalent versioned substantive prompt content and selected formatting/Constraints, while credentials and provider-only transport fields remain outside the prompt and response.
- Verify initial success, transient success after retry, maximum two retries after initial attempt, non-retry permanent error, exponential backoff under a fake clock, bounded `Retry-After`, per-attempt timeout, absolute deadline cancellation, and cost-ceiling skip. Concurrency coverage must demonstrate elapsed wall time tracks the slowest parallel dependency rather than the sum, within non-flaky tolerance.
- Verify one or two provider failures produce a partial HTTP 200 when another parsed answer is usable, including sanitized warnings and failed model entries. Verify all unconfigured providers produce the defined 503 and all dispatched providers failing produce the defined 502.
- Verify strict JSON, fenced JSON, unambiguous embedded JSON, harmless optional omissions, unknown fields, invalid required fields, out-of-range confidence, repair success, and repair failure. Repair failure must retain bounded plain text, empty Claims, degraded status, zero score, and recommendation ineligibility.
- Verify Unicode/spacing normalization, duplicate Claims from one model, similarity just below/at/above 0.85, representative tie-breaking, deterministic cluster order, embedding-version recording, and lexical fallback warnings. Fixtures must include paraphrases that should group and superficially overlapping Claims that must not group.
- Verify Consensus requires two distinct providers plus independent verification. Shared unsupported Claims, repeated Claims from one model, lexical grouping without verification, and majority Claims contradicted by stronger Evidence must not earn consensus credit.
- Verify Disagreements include singleton, unverified, unavailable, conflicting, and answer-level alternatives and that general semantic opposition is not asserted by the MVP.
- Verify Fact Verification with a high-authority primary source, two independent credible sources, Wikipedia-only corroboration, stale sources, duplicate domains, deceptive hostname substrings, credible conflict, unrelated results, search timeout, and missing key. Assert Evidence provenance and explainable authority/recency components, not a private matching algorithm.
- Verify each score component's numerator, denominator, applicability, weight, normalization, and final cap using table-driven boundary examples. Cover no Claims, no Constraints, fact-only, code-only, mixed answers, one usable provider, no independent verification, central conflict, scores immediately below/at 0.60, floating ties, and configured weight changes.
- Verify recommendation selects the highest eligible unrounded score, stable configured order breaks exact ties with disclosure, degraded answers are excluded, and insufficient confidence produces a null recommendation with the prescribed message.
- Verify Report persistence is atomic under an injected write failure, foreign keys and relational ownership hold, Report content is immutable after return, raw/error/output sizes are bounded, and no secret-like fixture value is stored in answer, verification, Report, feedback, or diagnostic fields.
- Verify exact canonical cache hit returns the durable existing Report with `cached=true`; differing Constraints, format, model order/effective set, prompt version, or scoring/Verifier version misses. Cover TTL expiry, refresh bypass, stale/missing Report reference, concurrent single-flight behavior, Redis outage degradation, and the rule that errors are not cached.
- Verify feedback creation, Report-not-found, Claim-not-in-Report, field bounds, multiple append-only submissions, and no score/Report mutation. Feedback response and logs must not echo more content than the contract permits.
- Verify the standard 422/429/502/503 error envelope and request correlation. Inject credentials and sensitive markers into upstream errors to prove response, structured logs, traces, and persisted diagnostics redact them.
- Verify allow-listed models, request rate and concurrency limits, trusted-proxy handling, HTTP(S)-only Evidence links, payload bounds, and that the backend makes no direct request to model-supplied source URLs.
- Run migrations against an empty PostgreSQL database and upgrade from every supported migration checkpoint. Verify schema constraints, indexes needed by the Report lookup path, and rollback guidance separately from application behavior.

### Frontend behavior coverage

- Through the Browser Report seam, submit a minimal Question and an advanced request with Constraints, type, format, and models; verify disabled duplicate submission, honest staged loading, retryable error, complete result, partial result, cache indicator, and insufficient-confidence result.
- Verify recommendation, Consensus, Disagreements, Evidence, per-Constraint Checks, expandable Model Answers, score breakdowns, degraded/provider failures, and all six verification statuses render from contract fixtures without assuming fields that the API does not guarantee.
- Verify Evidence is rendered as escaped text with a visible hostname and safe external-link behavior. Inject HTML, script-like model text, dangerous schemes, overlong snippets, and malformed URLs to ensure none execute or become unsafe links.
- Verify feedback success, validation failure, server failure preserving typed input, Claim selection, and suggested answer. Assert the original Report does not change after feedback.
- Run automated accessibility checks plus keyboard-only navigation for form controls, collapsible sections, Model Answer cards, status announcements, feedback, and Evidence links. Verify badges have text equivalents and tables/lists retain meaningful semantics.
- Verify the desktop 70/30 information hierarchy and narrow-screen stacked reading order at representative viewports without snapshotting incidental Tailwind class output.

### Nonfunctional and operational coverage

- Measure uncached end-to-end API latency with controlled provider/search delays to confirm parallel execution and deadline behavior; treat the under-20-second requirement as a release performance test, not a brittle per-commit unit assertion. Measure cached responses separately.
- Load-test configured request and provider concurrency, connection pools, Redis single-flight, and rate limits. Confirm overload returns bounded 429/partial behavior rather than exhausting workers or opening unbounded outbound calls.
- Run dependency and secret scanning, ensure `.env` is excluded and `.env.example` contains placeholders only, inspect the frontend bundle for secrets, and validate the sandbox image is pinned and runs non-root with the specified restrictions.
- Smoke-test Docker Compose startup, migrations, readiness, backend health, frontend-to-backend request, PostgreSQL persistence, Redis cache, and a safe Docker sandbox execution using only fake provider/search services.

### Prior art

- The repository currently contains no tests, test configuration, frontend, migrations, or similar integration examples. The only established behavioral prior art is the exact asynchronous FastAPI `GET /health` endpoint and documented uv/Uvicorn startup command.
- Establish backend prior art with pytest, an async ASGI HTTP client, deterministic dependency overrides, and containerized PostgreSQL/Redis integration fixtures. Establish frontend prior art with Vitest and Testing Library for contract fixtures plus Playwright for the Browser Report seam. Later tests should copy these high-level fixtures and contract builders rather than introduce service-specific mocking styles.
## Out of Scope

- Multi-turn conversation, conversational memory, streaming follow-up questions, and real-time deep dialogue.
- Image, audio, document, or other multimodal input and output.
- Private knowledge bases, retrieval over user documents, enterprise connectors, or custom source corpora.
- Automated legal, financial, or medical decisions. These topics receive Evidence, Disagreements, uncertainty, and disclaimers only.
- General mathematical proof or calculation verification, WolframAlpha integration, and SymPy-based assurance. Math Claims are displayed as not applicable to an MVP Verifier.
- General logical-coherence scoring or model-based contradiction detection. Limited deterministic explicit-negation recognition does not constitute a contradiction engine.
- Code execution for languages other than Python, arbitrary package installation, networked code, interactive processes, GPU workloads, and model-generated tests for unrecognized specifications.
- Providers beyond OpenAI, Anthropic Claude, and DeepSeek as required implementations. Gemini, Grok, GLM, and other Adapters are extension points.
- Semantic/similar-Question cache reuse; only exact canonical request caching is allowed.
- Source-page crawling, full-text extraction, paywall bypass, browser automation, or treating a search snippet as a full source document.
- User registration, login, profiles, organizations, tenancy, role-based access, subscription plans, billing, payment, daily free-tier enforcement, and public API-key issuance.
- Automatic online learning, accepting feedback as truth, or changing scoring weights and Verifier parameters directly from feedback.
- User-facing Report editing/deletion, retention management, export, sharing, collaboration, localization, and notification features.
- A distributed task queue, asynchronous job API, WebSocket/SSE progress protocol, multi-region failover, autoscaling, or a formal production 99% availability guarantee. The MVP records and measures the availability objective.
- Building a new component design system. A small established React component library may be used, but behavior and accessibility take precedence over bespoke styling.

## Further Notes

### Assumptions

- **Three-provider interpretation:** “first implement OpenAI + DeepSeek” is an implementation-order instruction, while the PRD requirement for at least three default models defines full-MVP acceptance. Therefore OpenAI, Claude, and DeepSeek are required for the complete default flow; a two-provider stage is useful but incomplete.
- **Verifier interpretation:** “first implement fact + constraint” is also ordering, not removal of the PRD's code/algorithm MVP class. The complete MVP includes the local Docker Python Code Verifier; Fact and Constraint Verification may land earlier without changing final acceptance.
- **Search provider:** Tavily is the initial required Fact Search Adapter because it is named first and already represented in environment configuration. Serper and Brave remain alternative future Adapters; one search provider is sufficient for MVP execution, while Evidence independence is based on result domains rather than search API count.
- **Embedding provider:** use the configured OpenAI embedding model by default, with `text-embedding-3-small` as the initial setting. Lack of embedding capability triggers the explicitly degraded lexical path rather than making the application fail.
- **Anonymous product:** no authentication behavior is specified in the PRD's API contract, so the MVP is anonymous and leaves nullable user IDs for later work. Configurable rate and concurrency limits still apply.
- **Exact caching:** the concrete PRD key is a hash of Question plus Constraints and the risk section warns about inaccurate similar caching. The MVP therefore uses a versioned exact canonical key that also includes every result-affecting input/configuration; semantic cache reuse is deferred.
- **Synchronous response:** the PRD defines one `POST /api/query` response and explicitly omits a task queue. The API therefore waits up to its deadline and returns a full or partial Report; frontend progress is honest staged UI, not server-pushed per-provider events.
- **Reasoning field:** the requested `reasoning` value is a concise rationale suitable for display and audit, not hidden chain-of-thought. It is not scored as evidence.
- **Report confidence:** recommendation confidence is the explainable final score after assurance caps. It is not a statistical probability or guarantee of correctness.
- **Credential storage:** the hard constraint to read keys from `.env`/environment takes precedence over the generic PRD phrase “encrypted storage.” CrossCheck does not persist keys at all; encryption and access control of deployment secret storage are operational responsibilities.
- **Infrastructure degradation:** Redis and individual external providers may degrade gracefully. PostgreSQL is required to issue a successful durable Report; if it is unavailable, the API returns a sanitized service-unavailable error rather than returning an unpersisted ID.
- **No semantic opposition:** the implementation-order note explicitly defers contradiction identification. `oppose_models` therefore cannot imply general natural-language contradiction detection in the MVP.
- **Current model names:** provider model names in the PRD are examples and can become obsolete. Defaults are server configuration, while provider families and output behavior—not a dated model string—form the contract.
- **No existing ADR conflict:** repository inspection found no ADRs or project glossary. This specification establishes the domain vocabulary and respects the only existing runtime contracts: Python 3.11/uv, the FastAPI application import, environment placeholders, and exact health response.

### Product interpretation and risk notes

- “Full Assurance” names the workflow depth, not certainty. Every Report must expose limitations, unavailable checks, and Evidence; no UI or API text may promise that a recommended answer is true.
- Agreement and provider self-confidence are signals only. The principal trust boundary is the independent Verifier result anchored to inspectable Evidence or sandbox execution.
- A partial Report is useful only when degradation is explicit. It must not label one-provider output as Consensus, silently renormalize a reduced model set, or hide missing Verifiers.
- Provider responses, search snippets, source URLs, code, execution output, and feedback are all untrusted input. Validation, output bounding, escaping, redaction, and sandbox isolation apply at their respective boundaries.
- Delivery may be staged in the requested dependency order, but staging does not redefine the complete acceptance surface in this specification. If implementation capacity forces an interim release after the model-comparison core, deferred items must be recorded as incomplete rather than represented as a complete CrossCheck MVP.
- All normative numeric defaults—20-second target, 10-second attempt timeout, two retries after the initial attempt, 0.85 semantic threshold, five search results, 24-hour cache TTL, PRD score weights, and 0.60 recommendation threshold—are configuration values whose effective versions are stored with Reports.
