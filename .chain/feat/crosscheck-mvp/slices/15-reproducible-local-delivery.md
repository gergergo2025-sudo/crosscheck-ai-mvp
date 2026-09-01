---
id: 15-reproducible-local-delivery
title: Reproducible local full-stack delivery
blocked_by:
  - 01-durable-query-tracer
  - 04-provider-resilience-deadline-cost
  - 08-python-docker-verification
  - 11-report-experience-safety
  - 12-exact-report-cache
  - 14-observability-privacy-abuse-controls
  - 16-public-api-abuse-controls
risk: true
---

# 15: Reproducible local full-stack delivery

**What to build:** An operator can follow documented uv, migration, frontend, Docker Compose, sandbox-image, and test commands to run PostgreSQL 15, Redis 7, FastAPI, React/Vite/Tailwind, and the pinned non-root sandbox prerequisite as one reproducible local system. Health checks and dependency ordering expose failed migrations instead of concealing them, frontend configuration contains only a public API base URL, and release evidence covers performance, load behavior, dependency/secret scanning, migration upgrades, and the full fake-provider smoke path. This slice owns user stories 63 and 64 and the deployment, health compatibility, operational documentation, and nonfunctional release-validation decisions.

**Blocked by:** 01-durable-query-tracer, 04-provider-resilience-deadline-cost, 08-python-docker-verification, 11-report-experience-safety, 12-exact-report-cache, 14-observability-privacy-abuse-controls, 16-public-api-abuse-controls.

- [ ] A clean-environment smoke test follows the documentation to build services, run every migration checkpoint, start Compose, return the exact backend health payload, serve the frontend, persist a fake-provider Report, hit Redis on repeat, and execute one safe sandbox fixture without real paid credentials.
- [ ] Release checks prove controlled uncached work stays within the 20-second target through parallelism/deadline behavior, cached latency is measured separately, configured overload returns bounded 429 or truthful partial results, dependencies and secrets scan cleanly, the frontend bundle contains no keys, and the pinned sandbox image runs non-root with its declared restrictions.
