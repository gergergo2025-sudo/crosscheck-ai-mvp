---
id: 08-python-docker-verification
title: Isolated Python code verification
blocked_by:
  - 01-durable-query-tracer
risk: true
---

# 08: Isolated Python code verification

**What to build:** A developer can inspect behavioral evidence for a clearly delimited Python answer executed with safely parseable model-provided tests or deterministic tests for a small recognized-task allow-list in an ephemeral, pinned local Docker sandbox. The Verification Result records the bounded test basis and whether tests came from the model or a named deterministic contract; malformed or unsafe tests are rejected, and unrecognized tasks receive no invented tests. The sandbox fails closed without Docker or a safe test contract, disables network and host access, enforces resource and output limits, and reports bounded execution status, passed/total tests, output, and sanitized errors; unsupported Claim types are explicitly not applicable. This slice owns user stories 31–34 and 39 and the Code Verifier, sandbox, safe-test-selection, and unsupported-Verifier decisions.

**Blocked by:** 01-durable-query-tracer.

- [ ] Real Docker integration tests prove the actual execution path runs as a non-root UID with dropped capabilities, no host mounts or host visibility, a read-only root filesystem, and writes permitted only inside a bounded temporary workspace; safe workspace writes succeed, while network access, writes outside that workspace, process/fork pressure, memory pressure, output floods, and wall-time excess are denied or bounded, and submitted code never executes in the backend process.
- [ ] HTTP and real-Docker fixtures distinguish safely parseable model-provided tests, rejected malformed or unsafe model tests, deterministic suites for every recognized contract in the allow-list, and an unrecognized contract that runs zero tests and returns a safe refusal; syntax errors, failed tests, missing Docker, and no-safe-contract cases produce distinct bounded statuses, and the persisted and returned Evidence exposes bounded test-source and test-basis metadata with passed/total counts only when tests ran.
- [ ] A browser acceptance test proves execution Evidence is attached to the originating Claim and Model Answer, makes its test basis inspectable, and renders unavailable and not-applicable states without implying correctness.
