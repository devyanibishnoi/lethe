# Lab Notes

Shared, running research log. Dated entries, what was tried, what happened, actual numbers, failed attempts included. This becomes the methodology and results write-up later, see the Research Paper Prep section of `docs/CHECKLIST.md` for how these entries map onto paper sections.

---

## 2026-09-26 — Layer 3 environment and synthetic corpus (Devyani)

Set up a local dev environment against the schema and hard-delete/signing code Hridya and Anshika had already committed (Docker + pgvector, `.env`, Python venv, local signing keypair). Applied `src/db/schema.sql` cleanly; the ivfflat index creation logged a "low recall" notice on the empty table, expected, resolves once real data is loaded.

Built `src/eval/generate_corpus.py`: four incident-log sentence templates (failed login, suspicious outbound traffic, flagged process, unusual cloud-storage access) filled with randomized names/IPs/hostnames/timestamps, embedded with `all-MiniLM-L6-v2` (384-dim, matches the schema's `vector(384)` column), spread round-robin across the two test tenants. Verified with a round-trip insert/fetch test against the live database.

## 2026-09-26 — Layer 3 benchmark suite (Devyani)

Built `src/eval/run_benchmarks.py`, logging to `docs/benchmark_results.csv` (append-only, long/tidy format: one row per measurement with a `metric` label, so new measurement types never require a schema change).

First full run produced misleading numbers: a crashed earlier run had already grown the tenant partition to 5000 documents, so the "corpus size" labels on the index-rebuild sweep (100/500/1000) didn't reflect the true index size at measurement time — the script needs to reset its own test corpus at the start of every run rather than assume a clean database. Added an explicit reset step and re-ran.

**Results (single run, tenant 1, `all-MiniLM-L6-v2` embeddings, HNSW index, cosine distance):**

| Metric | Corpus size | Value |
|---|---|---|
| Single hard-delete latency | 6 docs | 64.8 ms |
| Cascading subject erasure (50 docs) | 50 docs | 4765.8 ms (~95 ms/doc) |
| Index rebuild cost | 100 | 10.7 ms |
| Index rebuild cost | 500 | 92.0 ms |
| Index rebuild cost | 1000 | 108.4 ms |
| Index rebuild cost | 5000 | 870.9 ms |
| Recall@10 overlap, before vs. after deleting 20 unrelated docs | 4980 | 0.995 |

Index rebuild cost scales worse than linearly with corpus size (5x the data, from 1000 to 5000, cost ~8x), consistent with HNSW's graph-insertion cost rising as the graph grows, this is the numeric evidence behind the "HNSW is costlier to update" tradeoff noted in the checklist. Recall@10 stayed at 0.995 after deleting unrelated documents, supporting the core claim that hard-delete doesn't quietly degrade retrieval quality for the rest of the corpus. Still want to run the inverse test deliberately (delete a document known to be in a query's top-k) to confirm recall visibly drops there, as a sanity check that the metric can actually detect a real regression.

Plots saved to `docs/benchmark_plots/`.
