# Roadmap

## 0.2 — Integration helpers

- FastAPI and Flask request helpers using the `Idempotency-Key` header.
- Heartbeat support for operations longer than one lease period.
- Pluggable JSON serializer interface.
- Structured hooks for logs and metrics.

## 0.3 — Shared backends

- PostgreSQL backend for multi-host deployments.
- Redis backend for short-lived, high-throughput workloads.
- Backend contract test suite for third-party adapters.

## 1.0 — Stable API

- Stable storage migration policy.
- Documented crash-consistency guarantees.
- Performance and contention benchmarks.
- Production deployment guide.
