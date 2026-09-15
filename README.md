# Lethe

**Certified Forgetting: Hard-Delete and Cryptographically-Audited Vector Indexing for GDPR-Compliant RAG Knowledge Bases**


## What this is

Lethe is a database-native deletion layer for RAG (Retrieval-Augmented Generation) knowledge bases. Most vector databases only soft-delete on request, the embedding stays physically recoverable on disk even after a "delete" call. Lethe fixes that with a partitioned index, so a deletion only rebuilds the affected shard, and a cryptographically signed, hash-chained audit table that proves a deletion actually happened and that the audit trail itself hasn't been quietly edited afterward.

**Why this is the hard part:** semantic search over a vector database is now commodity infrastructure, most RAG projects touch it in some form. Proving that a specific piece of data is unrecoverably gone, cheaply enough to do at scale, and in a way a regulator would actually accept as evidence, is the part almost nobody has solved. That's where this project puts its effort: the index-type comparisons (HNSW vs. IVF) exist to confirm deletion doesn't quietly degrade retrieval for everyone else's data, they're supporting evidence, not the headline.

Full problem statement and research gap: see [`PROBLEM_STATEMENT.md`](./PROBLEM_STATEMENT.md).

This is one half of a broader direction: Lethe is the trust layer (proves data can be truly deleted), Claire is the intelligence layer (detects and explains threats), part of a private, enterprise-hosted AI security platform.

## Team

Work is split by layer, not by feature, each person owns one type of work across the whole system:

| Layer | Owner | Covers |
|---|---|---|
| 1 — Foundations | Hridya | Schema, partitioning, indexes |
| 2 — Core Logic | Anshika | Hard-delete, cascading erasure, chained cryptographic signing, verification |
| 3 — Evaluation | Devyani | Synthetic corpus, benchmarking, results |
| 4 — Frontend | Devyani | Compliance dashboard: search, erasure requests, audit trail, benchmarks, certificates |

Because it's a layered split, work is sequential: Layer 2 needs Layer 1's schema before it can build, Layer 3 needs Layer 2's functions before it can benchmark, Layer 4 needs a working slice of all three before it can wire up live. Full detail in [`docs/CHECKLIST.md`](./docs/CHECKLIST.md).

## Tech stack

**Core:**
- PostgreSQL + `pgvector`
- Python for the schema layer, hard-delete/signing logic, and synthetic corpus generation
- `cryptography` (ECDSA over SECP256R1) for signing and chaining the deletion audit log

**Supporting evaluation:**
- HNSW / IVF index comparisons, benchmarked to confirm hard-delete doesn't degrade retrieval quality, not a standalone contribution
- `matplotlib` for benchmark plots

**Frontend / demo:**
- FastAPI backend exposing the core logic as HTTP endpoints
- Plain HTML/CSS/JS compliance dashboard (search, erasure requests, audit trail with live signature verification, benchmarks, downloadable deletion certificates)
- Chart.js for rendering benchmark results

## Project structure

```
lethe/
├── src/
│   ├── db/      # Layer 1 — schema, partitions, indexes, CRUD helpers
│   ├── logic/   # Layer 2 — hard-delete, cascading erasure, chained signing, verification
│   ├── eval/    # Layer 3 — synthetic corpus, benchmarks
│   └── api/     # Layer 4 — FastAPI backend for the dashboard
├── frontend/    # Layer 4 — dashboard pages (search, erasure, audit trail, benchmarks, certificates)
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
- Review-3 (09-Oct-2026): full project demo, driven live from the compliance dashboard

## Getting started

Full instructions, with every command and code snippet, are in [`docs/CHECKLIST.md`](./docs/CHECKLIST.md). Short version:

1. Install Docker, spin up Postgres + pgvector with the provided `docker-compose.yml`.
2. Set up a Python virtual environment and install the requirements listed in the checklist.
3. Run the schema, then each person builds their track: schema, core logic, evaluation, or the dashboard.
