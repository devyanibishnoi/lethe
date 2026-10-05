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

## 2026-09-27 — Layer 4 compliance dashboard (Devyani)

Built the dashboard as a thin FastAPI layer (`src/api/main.py`) over Layers 1–3's existing functions, plus a static HTML/CSS/JS frontend (`frontend/`): an Overview page (subjects, tenants, consent, document counts), a semantic search demo, an erasure-request flow (submit → cascading erasure → completion), an audit trail (per-entry signature verification, whole-chain verification, and a demo-only endpoint to deliberately corrupt one entry so tamper detection can be shown live), a benchmarks page charting the CSV above, and a deletion-certificate view.

**Methodological finding worth keeping for the paper's Methodology section:** a deletion certificate meant to let a third party independently re-run signature verification must serialize `signed_at` as the exact string embedded in the original signed message, not any semantically-equivalent reformatting. The signing code (`build_message()`) embeds a timestamp via Python's default `str(datetime)` (space-separated: `2026-09-27 05:37:19.527313+00:00`); a JSON API response serializing the same value defaults to ISO-8601 (`T`-separated), a one-character difference that is enough to make an otherwise-valid signature fail re-verification, since ECDSA verifies an exact byte string. Fixed by having the certificate endpoint emit `str(signed_at)` explicitly rather than relying on default JSON datetime encoding. General point for the write-up: any value embedded in a signed message must be treated as an exact byte string everywhere it is later re-displayed or re-transmitted, not merely as "the same timestamp."

**Open item, recorded rather than hidden:** during a 71-signature benchmark run, one single signature failed self-consistent verification (its own stored signature did not verify against its own stored fields), while the hash-chain linkage on that same row was intact. Ruled out: stale/rotated signing keys, duplicate timestamps, duplicate document IDs. Root cause not identified; it did not recur across two subsequent full benchmark runs (142 further signatures, all valid). Mitigation added to `sign_deletion()`: the signing function now verifies its own signature immediately after producing it and raises rather than returning if that self-check fails, so a future occurrence would be caught at the moment of signing, loudly, instead of discovered later by an independent audit. Worth a paragraph in the Discussion section regardless of whether it recurs, and worth Anshika's attention since it touches the signing path in `src/logic/sign_deletion.py`.
