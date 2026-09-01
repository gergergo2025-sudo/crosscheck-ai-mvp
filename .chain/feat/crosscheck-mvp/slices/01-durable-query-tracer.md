---
id: 01-durable-query-tracer
title: Durable single-model Question-to-Report tracer
blocked_by: []
risk: true
---

# 01: Durable single-model Question-to-Report tracer

**What to build:** A user can open the React single-turn form, submit a valid Question with optional type and output format, and receive a synchronous, durable Report produced through provider-neutral Adapter and Verifier ports using a deterministic test Adapter. The tracer establishes the validated request/success/error contracts, strict structured Model Answer shape, deterministic type selection, stable UUID relationships, PostgreSQL migrations and atomic Report assembly while preserving configuration-safe startup and the exact health contract. This slice owns user stories 1, 2, 4, 5, 6, 15, 16, 17, 21, 55, 64, 67, 68, 69, and 70, plus the base public API, classification, persistence, and extension-boundary decisions.

**Blocked by:** None (can start immediately).

- [ ] An ASGI acceptance test with a deterministic Adapter and real PostgreSQL proves that minimal and advanced valid requests create one transactionally consistent Question, Model Answer, Claim, and immutable Report graph with stable IDs and the published 200 schema, while blank, oversized, unknown-field, invalid type/format/model, and injected atomic-write failures produce the specified machine-readable errors without partial Report rows.
- [ ] A browser acceptance test proves the single-turn form submits once, shows the returned answer and classification origin, and preserves entered values on field errors; startup and migration checks additionally prove the documented Uvicorn import and exact health payload remain usable with every optional integration key absent.
