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

## 2026-10-10 — hard_delete fix (ivfflat + VACUUM) and three reviewer-requested experiments (Devyani)

An external paper reviewer flagged that the core "deletion is real" claim was weaker than the write-up implied: `hard_delete()` only rebuilt the HNSW index, never touched the ivfflat index on the same column, and never ran `VACUUM`, so a deleted embedding's bytes could still be physically present in both the ivfflat index pages and the dead heap tuple after a "successful" deletion. This directly matches the research gap `PROBLEM_STATEMENT.md` is built around (soft-delete persistence despite a reported deletion), so it's a real gap in the implementation, not just a wording issue. This touches `src/logic/hard_delete.py`, Anshika's Layer 2 file; flagged to her, fixed under the personal CLAUDE.md override for urgency, same as the `sign_deletion.py`/`deletion_certificate.py` touches earlier.

**The fix:** added `ivfflat_index` to `TENANT_CONFIG`, so `hard_delete()` now runs `REINDEX INDEX` on both the HNSW and ivfflat indexes for the affected tenant (previously only HNSW). After the delete transaction commits, it also runs `VACUUM {partition}` as a separate autocommit statement, since `VACUUM` cannot run inside a transaction block, PostgreSQL enforces this because it needs to update visibility-map bits outside of any transaction's snapshot. Verified for real (not just read through): built a one-off subject/document, called the fixed `hard_delete()`, and confirmed directly: the row is gone from a fresh `SELECT`, both indexes report `indisvalid = true` after their `REINDEX`, and `pg_stat_user_tables.last_vacuum` updates to the call's own timestamp. One honest loose end: `n_dead_tup` in `pg_stat_user_tables` didn't always drop to the expected count immediately after vacuuming a single-row delete, that stats-collector counter is an async, eventually-consistent estimate, not a ground-truth read, so I verified correctness via the actual row count and `last_vacuum` timestamp instead of trusting that one counter.

**Important correction to my own first instinct:** I initially suspected the un-rebuilt ivfflat index meant deleted documents could still show up in live search results. That's wrong: Postgres checks heap tuple visibility (MVCC) on every index scan regardless of whether the index has been rebuilt, so a stale index never returns an already-deleted row to a normal query. The real exposure the fix closes is forensic, not functional: the embedding's bytes stay physically present in ivfflat's index pages and the heap until reindexed/vacuumed, recoverable by someone with raw page/disk access, even though no ordinary SQL query would ever surface it. That's the precise claim the paper should make, not the stronger (and wrong) "deleted docs could leak into search results" version.

**Re-ran the full benchmark suite after the fix, as the reviewer explicitly asked for.** Numbers got honestly worse, which is the correct direction, since the fix makes `hard_delete()` do strictly more real work:

| Metric | Before fix | After fix |
|---|---|---|
| Single hard-delete latency | ~68 ms | ~97–141 ms (two runs; noisier now, more steps to time) |
| Cascading erasure, 50 docs | ~4150–4400 ms | ~5000–6290 ms |
| Index rebuild cost (HNSW only, 5000 docs) | ~309–333 ms | ~309–373 ms (unchanged, expected: this benchmark only ever measured HNSW in isolation, so it's a clean control showing the slowdown really is from the new ivfflat+VACUUM work, not noise) |
| Recall@10 overlap, before/after unrelated deletions | 0.995 | 0.98 (ranged 0.91–0.995 across repeated runs, this metric has real sample-noise at only 20 query vectors, don't over-read a single run) |

**Experiment 1 (reviewer's ask): rebuild cost, partitioned vs. a single combined index over all tenants.** Built a disposable `documents_unpartitioned_benchmark` table (dropped/recreated per run, never touches real data) with one HNSW index spanning both tenants, and measured `REINDEX` cost there at total size 2N against the existing per-tenant partitioned cost at size N:

| Per-tenant size (N) | Partitioned rebuild (1 tenant, size N) | Unpartitioned rebuild (both tenants combined, size 2N) | Ratio |
|---|---|---|---|
| 100 | 8.7 ms | 21.2 ms | 2.4x |
| 500 | 69.3 ms | 130.8 ms | 1.9x |
| 1000 | 108.2 ms | 236.4 ms | 2.2x |
| 5000 | 309.3 ms | 691.7 ms | 2.2x |

Consistently ~2–2.4x, slightly above the 2x raw-volume ratio, consistent with HNSW's graph-construction cost scaling worse than linearly with N (same effect the 2026-09-26 entry noted). This is the actual quantitative evidence for the partitioning claim: deleting one tenant's document only ever pays the cost of that tenant's own partition size, never the whole system's, and the gap would widen further with more tenants or more skewed sizes.

**Experiment 2 (reviewer's ask): ANN recall against exact nearest-neighbour search.** The existing `recall_at_k` metric above measures something narrower, overlap of the ANN top-k before vs. after an unrelated deletion, not recall against ground truth. Added `measure_recall_vs_exact()`: for 20 random query vectors, computes the true top-10 via a forced sequential scan (`SET enable_indexscan = off; SET enable_bitmapscan = off`, confirmed via `EXPLAIN` that this actually produces a `Seq Scan`, not just trusting the setting), and separately the ANN top-10 via the planner's normal default path, then compares the two sets. Also logs which index the planner actually picked (via `EXPLAIN`), since pgvector gives no way to pin ANN search to one index type over the other when both exist on the same column. Result at corpus size 4980: **1.0 recall** (ANN, using `ivfflat` in this run, returned exactly the same top-10 as exhaustive search for all 20 queries). Caveat for the paper: this is a small, synthetic, template-generated corpus, perfect recall here isn't a claim that HNSW/ivfflat are exact in general, it says this corpus's embeddings are well-separated enough that approximate search had no work to approximate at this scale.

**Experiment 3 (reviewer's ask): delete an audit entry from the middle of the log, confirm the chain check catches it.** This is distinct from the existing `corrupt-for-demo` feature, which mutates a stored hash in place; this test removes an entire row. Wrote `src/eval/test_chain_gap_detection.py`. First run surfaced something worth recording on its own: `verify_chain()` was already returning `False` on the real audit history before I touched anything, because of exactly the `corrupt-for-demo` fixture exercised during this session's earlier live browser testing (entry `cf397f3c...` / `72fb3f82...`, timestamped 2026-10-06 11:13:05, its stored hash is literally the mutated 65-hex-char value from that demo action). `verify_chain()` short-circuits on the first break it finds, so once any row anywhere is broken, the whole-table boolean is `False` forever after, by design, there's no way to tell from that one boolean whether a *new* break just happened. For the real test, I built my own disposable 4-entry segment, verified its links and signatures directly (not through the global `verify_chain()`), deleted the middle entry outright, and re-checked: the entry that used to come right after it now has a `previous_hash` that matches no existing row, exactly the failure mode `verify_chain()` is built to catch. **Confirmed.** Practical note for the real system, not just this test: `verify_chain()`'s single boolean return is enough to prove "something is wrong somewhere" but not "where", a real incident-response path would need it to report the first bad entry's id/position rather than just `True`/`False`, worth raising with Anshika as a possible follow-up to `verify_deletion.py`.

## 2026-10-10 — second round of reviewer feedback: storage-level verification, real tenant scaling, corpus-difficulty check (Devyani)

A second pass of feedback on the same draft, more pointed than the first round. Five points; four led to new experiments, one is a framing note for whoever writes the paper.

**1. "The core claim is never verified at the storage level."** The biggest one, and correct: everything up to this point proved deletion by querying through SQL (`SELECT`, `pg_stat_user_tables`, `pg_index.indisvalid`), never by opening the actual data files and checking the embedding's bytes are gone. Wrote `src/eval/test_storage_erasure.py`: resolves each relation's on-disk file via `pg_relation_filepath()`, pulls the file out of the Docker container with `docker cp`, and searches the raw bytes for the deleted embedding's exact float4 byte pattern (`struct.pack("<384f", *embedding)`, the literal sequence pgvector stores a vector's components as). Ran a `CHECKPOINT` before every file copy, since a raw file read can otherwise miss a page still sitting only in `shared_buffers`.

Result, and it's a genuinely important correction to what I wrote in the first round's entry above:

| Relation | Before delete | After `hard_delete()` (REINDEX + VACUUM) | After plain `DELETE` only (no reindex/vacuum) |
|---|---|---|---|
| Heap (`documents_tenant_1`) | present | **still present** | present |
| HNSW index | present | gone | present |
| ivfflat index | present | gone | present |

The index result is clean and unconditional: `REINDEX` builds a brand-new physical file from scratch and atomically swaps it in (confirmed the relfilenode literally changes, e.g. `25153` → a new OID), so there is no code path by which old bytes could survive it. The heap result is the real finding: plain `VACUUM` does **not** overwrite a dead tuple's bytes, it only marks that space reusable for a future write. The embedding is still sitting there, byte-for-byte, until some later `INSERT`/`UPDATE` happens to reuse that exact page. Followed up by testing `VACUUM FULL` on the same table: relfilenode changed (full table rewrite into a new file, same mechanism as `REINDEX`), and the pattern was confirmed gone.

This means my framing in the first-round entry above overstated the heap-level guarantee, it should read as "immediate at the index level, bounded/eventual at the heap level" rather than implying both are immediate. Brought this to Devyani (asked, not assumed, since it's a real cost/correctness tradeoff): `VACUUM FULL` would close the gap completely, but takes an ACCESS EXCLUSIVE lock on the *entire* tenant partition, not just the affected row, blocking every other read/write to that tenant for the duration, and that duration grows with partition size the same way the HNSW rebuild already does. Decision: keep `hard_delete()` on plain `VACUUM` (fast, non-blocking), and state the heap-level gap honestly as a bounded, documented limitation with a known, verified upgrade path (`VACUUM FULL` or `pg_repack` as a periodic maintenance sweep) rather than claiming a guarantee the system doesn't actually provide every time. This is a stronger, more honest paper section than either overclaiming or not testing it at all, exactly what the reviewer predicted.

**Soft-delete baseline, folded into the same test (reviewer's point 4):** the plain-`DELETE`-only column above *is* the soft-delete baseline, same methodology, same files, run in the same script for a direct side-by-side. It shows the pattern surviving everywhere, in contrast to `hard_delete()`'s index-level removal, which is exactly "what the extra work buys": two index rebuilds and a vacuum, in exchange for immediate index-level forensic erasure instead of none.

**2. "The partitioning result is thin, just two equal tenants."** Correct, the first round's ~2x number was really just "double the rows." Extended `measure_unpartitioned_rebuild_cost` into `measure_tenant_scaling()`: holds one "tenant under test" fixed at 500 docs throughout, and varies the number (2, 4, 8, 16) and sizes (deliberately uneven, e.g. the 16-tenant config ranges from 100 to 1300 docs per other tenant) of the *other* tenants sharing the system, comparing (a) cost to rebuild just the tested tenant's own partitioned index against (b) cost to rebuild one combined index spanning everyone, at the same total system size:

| Tenants | Total system size | Partitioned (tested tenant only) | Unpartitioned (combined) | Ratio |
|---|---|---|---|---|
| 2 | 2000 | 51.9 ms | 223.0 ms | 4.3x |
| 4 | 3500 | 56.3 ms | 438.9 ms | 7.8x |
| 8 | 6100 | 56.0 ms | 474.5 ms | 8.5x |
| 16 | 10000 | 65.8 ms | 931.9 ms | 14.2x |

This is a much stronger result than the first round's flat 2x: the partitioned cost for the *same* 500-doc tenant stays essentially flat (52-66ms, within normal run-to-run noise) no matter how many other tenants exist or how much data they hold, exactly the architectural property partitioning is supposed to buy, now actually measured rather than assumed. The unpartitioned cost keeps climbing, and the *gap* widens from 4.3x to 14.2x as the system grows, meaning partitioning's advantage compounds with scale rather than being a fixed constant. Plotted as `docs/benchmark_plots/tenant_scaling_*.png`.

**3. "Small scale, templated corpus, recall of 1.0 mostly shows the corpus is easy."** Took this as a hypothesis to actually test rather than just concede. Computed pairwise cosine similarity across 200 freshly generated corpus documents (19,900 pairs): mean similarity 0.435, but 5.7% of all pairs exceed 0.9 similarity and the single highest pair hits 0.998. That long tail of near-duplicate pairs, same sentence template with just a name/IP/hostname swapped, is a direct, measured explanation for why recall came out at 1.0: for most queries there's a cluster of near-identical same-template neighbors sitting far from any plausible approximation-error decision boundary, so an ANN index has very little room to get the top-10 "wrong" even approximately. This is a real limitation of the four-template synthetic corpus generator, not something a larger N alone would fix, since more rows at the same four templates just means more copies of the same easy clusters. Recording this honestly as a stated limitation: both corpus *size* (5,000-ish real-scale runs) and corpus *difficulty* (templated, low lexical diversity within a category) bound how far the recall numbers generalize, and a genuinely harder, more diverse corpus is future work, not something attempted in this pass given the time available.

**5. Novelty framing**, a note for whoever writes this section of the paper, not code: `PROBLEM_STATEMENT.md` already cites the prior work this sits next to, Chakraborttii et al. (2026), who demonstrated that deleted embeddings remain physically reconstructible from storage and proposed a basic signed proof-of-deletion. Partitioned vector indexes and hash-chained audit logs are each independently known ideas; neither is the contribution on its own. What's actually new here, and what this round of experiments exists to back up, is the specific combination applied to this problem, *measured*: a partition-aware hard-delete whose cost is empirically shown to be independent of total system size, paired with a tamper-evident audit log, verified not just architecturally but at the literal byte level on disk, against an explicit soft-delete baseline, across a range of tenant configurations. The honest byte-level result above (index erasure is immediate, heap erasure is bounded) is itself evidence of exactly this kind of rigor, prior work asserted the vulnerability existed; this work tested whether the fix actually closes it, and reported precisely how far it does and doesn't.
