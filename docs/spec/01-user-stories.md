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
