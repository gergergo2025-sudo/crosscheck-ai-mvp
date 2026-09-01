---
id: 02-openai-deepseek-structured-comparison
title: OpenAI and DeepSeek structured comparison
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 02: OpenAI and DeepSeek structured comparison

**What to build:** A user can compare OpenAI and DeepSeek answers generated from the same versioned substantive prompt, including Constraints and requested format, with provider-neutral call metadata. Strict, fenced, or unambiguously embedded JSON is validated into the shared answer shape; a malformed response receives one bounded repair request and, if still invalid, remains visible as a zero-score degraded plain-text answer with no Claims. This slice owns user stories 7, 18, 19, and 20 and the Unified Prompt, Structured Answer Parser, and initial mandatory Adapter decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Adapter contract tests against mock OpenAI-compatible endpoints prove both providers receive equivalent versioned substantive prompt content, return normalized identity/latency/usage metadata, and never receive or expose credentials as prompt or response content.
- [ ] HTTP and browser acceptance tests cover strict, fenced, embedded, repair-success, and repair-failure responses and prove two answers remain auditable side by side, unknown fields are tolerated, invalid required shapes are rejected, and degraded output is bounded, persisted, visibly labeled, scored zero, and never recommended.
