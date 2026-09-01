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
