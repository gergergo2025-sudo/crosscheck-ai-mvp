# Plan Decisions

## 1. Start with one durable vertical tracer

- **Choice:** Slice 01 establishes the smallest complete Question-to-Report path across React, HTTP contracts, provider-neutral ports, PostgreSQL migrations, atomic persistence, and browser/ASGI tests using deterministic injected integrations.
- **Rejected alternatives:** Separate horizontal setup slices for schemas, backend services, frontend scaffolding, and tests; or a non-durable in-memory query prototype.
- **Reason:** The first option would not be independently demoable and would create merge-order ambiguity; the second would violate the requirement that successful Reports be durable and would later force a broad rewrite.

## 2. Use the first tracer as the shared prerequisite

- **Choice:** Every additive feature that relies on the public Report contract blocks only on Slice 01 unless it has a genuine semantic dependency; most of Slices 02–14 and 16 can therefore proceed in parallel after one merge. Claude's three-provider integration additionally blocks on the OpenAI/DeepSeek prompt, parser, and Adapter slice because it demonstrates all three production implementations together.
- **Rejected alternatives:** Give every slice an empty dependency list despite the empty repository, or serialize slices in the PRD's narrative order.
- **Reason:** Empty dependencies would cause competing schema, route, migration, and frontend foundations, while full serialization would unnecessarily deepen the critical path.

## 3. Keep the critical path semantic, not organizational

- **Choice:** Verified Consensus blocks on clustering, Fact verification, and scoring; final local delivery blocks on provider deadline/resilience, Docker verification, Report safety, caching, observability/privacy, and public abuse controls because its smoke and release checks directly exercise those runtime surfaces.
- **Rejected alternatives:** Make Consensus wait for every Verifier and UI enhancement, or add a catch-all integrate-and-verify slice.
- **Reason:** Consensus needs a clustered independently verified representative and its score effect, but it does not need Constraint or Code verification. Chain-level Merge Gate evidence is explicitly outside the slice set.

## 4. Establish complete persistence contracts additively

- **Choice:** Slice 01 creates migration-managed UUID/UTC relational storage for Questions, Answers, Claims, Clusters, Verification Results, and immutable Reports; later slices populate and add only feature-specific constraints or fields. Feedback remains a separate append-only slice.
- **Rejected alternatives:** Create tables implicitly at startup, store the whole graph only in Report JSON, or defer persistence until after orchestration.
- **Reason:** Stable relationships are load-bearing for Evidence provenance, caching, feedback ownership, and immutable report identifiers. Early additive migrations make later changes smaller and keep CI green.

## 5. Separate provider protocol work from resilience policy

- **Choice:** OpenAI/DeepSeek structured comparison, Claude/default registration, and cross-provider retry/deadline/cost policy are separate slices behind the shared Adapter port. The Claude/default slice follows the initial pair so it can prove the production three-provider integration without duplicating their prompt, parser, or Adapter work.
- **Rejected alternatives:** One large “all providers” slice, or provider-specific retry implementations.
- **Reason:** Protocol contracts can be implemented in parallel, while one policy slice prevents divergent timeout, retry, sanitization, and cost behavior.

## 6. Preserve the three-provider full-MVP interpretation

- **Choice:** OpenAI and DeepSeek are the initial pair, but configured OpenAI, Claude, and DeepSeek are required before the default may be described as three-provider mode.
- **Rejected alternatives:** Treat the requested initial pair as full acceptance, or add optional providers beyond the named three.
- **Reason:** This follows the spec's explicit resolution of the PRD's implementation-order wording without expanding scope.

## 7. Give each assurance method its own vertical slice

- **Choice:** Clustering, Fact verification, Constraint verification, Python/Docker verification, scoring, and verified Consensus each add their persisted result, API representation, Report UI behavior, and acceptance tests.
- **Rejected alternatives:** One horizontal “all backend verifiers” slice or one large assurance slice.
- **Reason:** These behaviors have different external dependencies and failure semantics and each fits a fresh context while remaining independently verifiable.

## 8. Treat uncertainty as first-class data

- **Choice:** All slices retain the six-state verification vocabulary and degraded/partial outcomes; unsupported math, logic, opinion, and recommendation claims are not applicable or unverified, never silently successful.
- **Rejected alternatives:** Binary pass/fail badges, dropping failed providers, or assigning model confidence as verification.
- **Reason:** Evidence-backed uncertainty is the product's main trust boundary and is required across API, persistence, scoring, and UI.

## 9. Keep general contradiction detection out of scope

- **Choice:** Disagreements enumerate singleton, uncertain, conflicting-Evidence, and answer-level alternatives; only the narrow deterministic explicit-negation case may populate opposition.
- **Rejected alternatives:** Model-based general contradiction detection or interpreting different clusters as contradictions.
- **Reason:** The specification explicitly defers general contradiction inference, and overstating it would undermine Full Assurance.

## 10. Mark risk from runtime data effects

- **Choice:** Slices that create or alter PostgreSQL/Redis records, persisted Report content, or irreversible external telemetry are marked risky. The final reproducible-delivery slice is risky because its smoke path writes a PostgreSQL Report and Redis cache entry and invokes the external Docker sandbox; the UI-only Report hardening and validation-only public control slice remain non-risky.
- **Rejected alternatives:** Mark every external API call risky, or mark only schema migrations risky.
- **Reason:** Provider/search calls are bounded and reversible, while stored audit/cache/feedback behavior can affect durable or reused user-visible state.

## 11. Assign every user story exactly once

- **Choice:** The “What to build” paragraph of each slice names its exclusive user-story ownership; taken together the slices cover 1–70 once, while each paragraph also names the corresponding implementation-decision areas.
- **Rejected alternatives:** Duplicate cross-cutting stories in several slices or maintain a separate mapping file detached from the required slice body.
- **Reason:** Exclusive ownership makes omissions and double implementation reviewable directly from the slice set.

## 12. Use the spec's acceptance seams

- **Choice:** Feature behavior is verified at the ASGI HTTP Report and browser seams, provider/search integrations at mock protocol servers, persistence/cache through real containerized services, and sandbox security in real Docker.
- **Rejected alternatives:** Helper-call unit tests, paid-provider tests in the default suite, or a mocked Docker security claim.
- **Reason:** These seams prove observable behavior and the actual security/data properties while remaining deterministic.

## 13. Keep release evidence outside implementation ownership

- **Choice:** Slice 15 wires reproducible runtime and feature-specific performance, load, migration, secret-scan, and fake-provider smoke checks after the runtime features they exercise, but repository Merge Gate and chain-level integration evidence remain outside the slice set.
- **Rejected alternatives:** A final slice whose only purpose is “run all tests” or merge branches.
- **Reason:** The task contract explicitly excludes chain-level evidence and the Merge Gate from requirement-to-slice ownership.

## 14. Preserve all stated exclusions

- **Choice:** No slice introduces multi-turn/streaming workflows, multimodal input, private knowledge bases, automated high-compliance decisions, math/logic assurance, non-Python execution, extra providers, semantic cache reuse, source crawling, accounts/billing, online learning, report mutation/deletion, distributed jobs, or a new design system.
- **Rejected alternatives:** Implement adjacent PRD future ideas while building extension points.
- **Reason:** The full MVP is already broad; stable ports preserve future extensibility without diluting the specification of record.

## 15. Separate observability/privacy from public abuse controls

- **Choice:** Slice 14 owns lifecycle telemetry, secret redaction, and privacy-safe diagnostic surfaces; Slice 16 independently owns request bounds, rate/concurrency limits, model allow-lists, trusted-proxy behavior, outbound-URL policy, and bounded public errors. Both rely only on the tracer, and local delivery waits for both because its release checks exercise both.
- **Rejected alternatives:** Keep the two operational deliverables bundled in one broad slice, or serialize public controls behind observability despite no implementation dependency.
- **Reason:** The two concerns have distinct acceptance seams and can be demonstrated independently. Splitting them reduces implementation context without narrowing the post-tracer frontier or inventing a false dependency.
