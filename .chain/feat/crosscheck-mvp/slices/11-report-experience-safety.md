---
id: 11-report-experience-safety
title: Safe, accessible full Report experience
blocked_by:
  - 01-durable-query-tracer
risk: false
---

# 11: Safe, accessible full Report experience

**What to build:** A user gets a responsive 70/30 desktop Report that stacks coherently on narrow screens, with honest staged provider/aggregation/verification progress, recommendation or insufficient-confidence card, status-specific Claim/Evidence badges, aggregate Constraint Checks, and expandable complete Model Answers. Untrusted text is escaped, only valid HTTP(S) Evidence becomes a hostname-labeled safe external link, all states are keyboard and screen-reader usable, every Report carries the AI fallibility notice, and medical/legal/financial Questions suppress automated endorsement in favor of evidence-oriented wording. This slice owns user stories 48–51, 65, and 66 and the report hierarchy, safe rendering, accessibility, progress, and high-compliance-domain decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Browser contract fixtures prove complete, partial, cached, degraded, provider-failure, insufficient-confidence, and all six verification states render with text-plus-icon semantics, expandable audit detail, truthful staged loading, duplicate-submit prevention, retry, and the required notices.
- [ ] Browser security, accessibility, keyboard, and viewport tests prove HTML/script-like text cannot execute, dangerous or malformed URLs never become links, valid external links expose hostnames and safe attributes, focus/status announcements work, and high-compliance Questions never receive decision-endorsement language.
