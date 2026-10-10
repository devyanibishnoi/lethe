"""Follow-up to test_reindex_timing_variant.py: that test confirmed
hard_delete() (DELETE + REINDEX x2 + VACUUM, now post-commit) clears index
files 20/20. This checks the OTHER candidate design, DELETE + VACUUM FULL,
the same way: 20 trials, raw byte search of the actual HNSW/ivfflat/heap
files on disk, not a query through the database. Needed before picking a
final design, since the equal-size latency comparison alone doesn't tell
you whether VACUUM FULL's index files are actually clean.

Logs per-trial results and the aggregate rate to docs/benchmark_results.csv.
"""

import tempfile

from src.db.db import insert_subject, insert_document
from src.eval.generate_corpus import generate_corpus
from src.eval.run_benchmarks import log_row, append_csv, CSV_PATH, _delete_vacuum_full_path
from src.eval.test_storage_erasure import (
    checkpoint,
    search_relations,
    full_pattern,
    short_pattern,
    fetch_embedding,
    HEAP_RELATION,
    HNSW_INDEX,
    IVFFLAT_INDEX,
    TENANT_1,
)
from src.db.db import get_connection

NUM_TRIALS = 20


def main():
    scratch_dir = tempfile.mkdtemp(prefix="lethe_vacfull_storage_")
    print(f"Scratch dir: {scratch_dir}")

    rows = []
    subject_id = insert_subject("Vacuum Full Storage Variant Subject", TENANT_1)
    records = generate_corpus(NUM_TRIALS)

    heap_found = 0
    hnsw_found = 0
    ivfflat_found = 0

    print(f"\nRunning {NUM_TRIALS} trials of DELETE + VACUUM FULL...")
    for i in range(NUM_TRIALS):
        doc_id = insert_document(subject_id, TENANT_1, records[i]["content"], records[i]["embedding"])
        embedding = fetch_embedding(doc_id)
        full_pat = full_pattern(embedding)
        short_pat = short_pattern(embedding)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO deletion_requests (subject_id, status) VALUES (%s, 'completed') RETURNING id",
                    (subject_id,),
                )
                deletion_request_id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        _delete_vacuum_full_path(doc_id, TENANT_1, deletion_request_id)
        checkpoint()

        relations = search_relations(scratch_dir, f"trial_{i}", full_pat, short_pat)
        if relations[HEAP_RELATION]["full"]:
            heap_found += 1
        if relations[HNSW_INDEX]["full"]:
            hnsw_found += 1
        if relations[IVFFLAT_INDEX]["full"]:
            ivfflat_found += 1

        print(f"  trial {i + 1}/{NUM_TRIALS}: heap_found={relations[HEAP_RELATION]['full']}, hnsw_found={relations[HNSW_INDEX]['full']}, ivfflat_found={relations[IVFFLAT_INDEX]['full']}")

    heap_rate = heap_found / NUM_TRIALS
    hnsw_rate = hnsw_found / NUM_TRIALS
    ivfflat_rate = ivfflat_found / NUM_TRIALS

    print(f"\nAfter {NUM_TRIALS} trials of DELETE + VACUUM FULL:")
    print(f"  heap, found: {heap_found}/{NUM_TRIALS} ({heap_rate:.0%})")
    print(f"  HNSW index, found: {hnsw_found}/{NUM_TRIALS} ({hnsw_rate:.0%})")
    print(f"  ivfflat index, found: {ivfflat_found}/{NUM_TRIALS} ({ivfflat_rate:.0%})")

    log_row(
        rows, "vacuum_full_path_heap_found_rate", heap_rate, "fraction", corpus_size=NUM_TRIALS,
        notes="DELETE + VACUUM FULL as the deletion mechanism; expected 0.0, VACUUM FULL rewrites the heap into a new file",
    )
    log_row(
        rows, "vacuum_full_path_hnsw_found_rate", hnsw_rate, "fraction", corpus_size=NUM_TRIALS,
        notes="DELETE + VACUUM FULL as the deletion mechanism; compare against reindex_after_commit_hnsw_found_rate (0.0) and storage_erasure_hnsw_full_pattern_rate pre-fix (0.65)",
    )
    log_row(
        rows, "vacuum_full_path_ivfflat_found_rate", ivfflat_rate, "fraction", corpus_size=NUM_TRIALS,
        notes="DELETE + VACUUM FULL as the deletion mechanism; compare against reindex_after_commit_ivfflat_found_rate (0.0) and storage_erasure_ivfflat_full_pattern_rate pre-fix (0.65)",
    )

    append_csv(rows)
    print(f"\nAppended {len(rows)} rows to {CSV_PATH}")

    print("\nCleaning up...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM data_subjects WHERE id = %s", (subject_id,))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
