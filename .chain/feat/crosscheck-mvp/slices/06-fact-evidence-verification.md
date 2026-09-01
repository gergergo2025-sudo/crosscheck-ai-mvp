---
id: 06-fact-evidence-verification
title: Evidence-backed Fact verification
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 06: Evidence-backed Fact verification

**What to build:** A user can inspect each representative Fact Claim's independent Tavily search verdict, including supporting, conflicting, or related Evidence with safe metadata and an explainable authority/recency confidence. Verification requires a high-authority primary source or two independent credible domains without equal-or-stronger conflict; weak, stale, Wikipedia-only, inconclusive, missing-key, and timed-out searches remain visibly unverified, conflicting, or unavailable. This slice owns user stories 27–30 and the Fact Verifier, search Adapter, Evidence provenance, authority formula, and no-source-crawling decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Search contract and HTTP acceptance tests cover five ranked results, primary authority, two independent domains, Wikipedia-only corroboration, stale and duplicate domains, deceptive hostname substrings, stronger conflict, unrelated results, timeout, and missing configuration, asserting the persisted status, confidence components, immutable Evidence provenance, and absence of direct fetches to model-supplied URLs.
- [ ] A browser acceptance test proves bounded titles, hostnames, snippets, dates, support/conflict relation, and confidence reasons are inspectable while search absence is never rendered or scored as verified.
