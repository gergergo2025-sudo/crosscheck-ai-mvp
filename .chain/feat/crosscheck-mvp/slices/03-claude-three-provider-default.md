---
id: 03-claude-three-provider-default
title: Claude and the three-provider default
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 03: Claude and the three-provider default

**What to build:** A user who leaves model selection at its default receives independently configured OpenAI, Claude, and DeepSeek Model Answer entries, while an allowed explicit selection uses only the normalized configured identifiers. Claude obeys the same provider-neutral contract, and three-model mode is never claimed when any required Adapter is absent from configuration. This slice owns user story 8 and the full-MVP three-provider/default-registration decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] A Claude mock-server contract suite proves successful and malformed upstream payloads, usage metadata, sanitized permanent failures, and equivalence of the versioned substantive prompt without leaking provider SDK types across the Adapter boundary.
- [ ] HTTP and browser acceptance tests prove the configured three-provider default, ordered duplicate normalization, allow-listed explicit selections, three durable comparison entries, and truthful labeling when the configured default cannot constitute three-model mode.
