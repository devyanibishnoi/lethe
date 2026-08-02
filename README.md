# Lethe

**Certified Forgetting: Hard-Delete and Cryptographically-Audited Vector Indexing for GDPR-Compliant RAG Knowledge Bases**


## What this is

Lethe is a database-native deletion layer for RAG (Retrieval-Augmented Generation) knowledge bases. Most vector databases only soft-delete on request, the embedding stays physically recoverable on disk even after a "delete" call. Lethe fixes that with a partitioned index, so a deletion only rebuilds the affected shard, and a cryptographically signed audit table that proves a deletion actually happened.

Full problem statement and research gap: see [`PROBLEM_STATEMENT.md`](./PROBLEM_STATEMENT.md).

This is one half of a broader direction: Lethe is the trust layer (proves data can be truly deleted), Claire is the intelligence layer (detects and explains threats), part of a private, enterprise-hosted AI security platform.

## Team

Work is split by layer, not by feature, each person owns one type of work across the whole system:

| Layer | Owner | Covers |
|---|---|---|
| 1 — Foundations | Hridya | Schema, partitioning, indexes |
| 2 — Core Logic | Anshika | Hard-delete, cryptographic signing, verification |
| 3 — Evaluation | Devyani | Synthetic corpus, benchmarking, results |

Because it's a layered split, work is sequential: Layer 2 needs Layer 1's schema before it can build, Layer 3 needs Layer 2's functions before it can benchmark. Full detail in [`docs/CHECKLIST.md`](./docs/CHECKLIST.md).

## Tech stack

- PostgreSQL + `pgvector`
- Python for indexing, benchmarking, and synthetic corpus generation
- HNSW / IVF / IVF-PQ index comparisons

## Project structure

```
lethe/
├── src/
│   ├── db/      # Layer 1 — schema, partitions, indexes, CRUD helpers
│   ├── logic/   # Layer 2 — hard-delete, signing, verification
│   └── eval/    # Layer 3 — synthetic corpus, benchmarks
├── docs/
│   ├── CHECKLIST.md      # start here — full step-by-step build guide
│   ├── LAB_NOTES.md       # shared running log (create this as you go, see CHECKLIST.md)
│   └── benchmark_results.csv / benchmark_plots/   # created as you run benchmarks
├── PROBLEM_STATEMENT.md
└── README.md
```

## Milestones

- Review-1 (31-Jul-2026): team identification, problem definition, research gap — done
- Review-2 (14-Aug-2026): 30% coding
- Review-3 (09-Oct-2026): full project demo

## Getting started

Full instructions, with every command and code snippet, are in [`docs/CHECKLIST.md`](./docs/CHECKLIST.md). Short version:

1. Install Docker, spin up Postgres + pgvector with the provided `docker-compose.yml`.
2. Set up a Python virtual environment and install the requirements listed in the checklist.
3. Run the schema, then each person builds their track (schema, indexing, or audit/benchmarking).


