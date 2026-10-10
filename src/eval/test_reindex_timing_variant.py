"""Follow-up on the index-residue finding in test_storage_erasure.py: the
current hard_delete() runs REINDEX inside the same transaction as the
DELETE, before that transaction commits. This tests a variant that commits
the DELETE first, then runs REINDEX as its own separate, later step
(structurally the same way VACUUM already is), to find out whether the
residue is a transaction-timing artifact or a fixed property of REINDEX
itself.

If this variant reliably shows 0% found: the negative becomes a fixed,
fixable design flaw, REINDEX just needs to move after commit.
If it still shows a non-zero rate: it's not about timing, REINDEX itself
does not reliably remove index-level bytes (most likely HNSW/ivfflat page
packing), an open problem, not a quick fix.

Logs per-trial results and the aggregate rate to docs/benchmark_results.csv.
"""

from src.db.db import get_connection, insert_subject, insert_document, get_document
from src.eval.generate_corpus import generate_corpus
from src.eval.run_benchmarks import log_row, append_csv, CSV_PATH
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
from src.logic.hard_delete import TENANT_CONFIG
from src.logic.sign_deletion import sign_deletion, save_audit_log

import tempfile

NUM_TRIALS = 20


def hard_delete_reindex_after_commit(document_id, tenant_id, deletion_request_id):
    """Same end state as hard_delete(), REINDEX moved to run after the
    DELETE has already committed, instead of inside the same transaction.
    """
    config = TENANT_CONFIG[tenant_id]
    partition = config["partition"]
    hnsw_index = config["hnsw_index"]
    ivfflat_index = config["ivfflat_index"]

    conn = get_connection()
    try:
        document = get_document(document_id, tenant_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found for tenant {tenant_id}")

        signing_data = sign_deletion(document[3], document_id)
        save_audit_log(conn, deletion_request_id, document_id, signing_data)

        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {partition} WHERE id = %s AND tenant_id = %s",
                (document_id, tenant_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"Expected to delete 1 document, but deleted {cur.rowcount}")

        conn.commit()  # DELETE is durable before REINDEX ever runs

        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"REINDEX INDEX {hnsw_index}")
            cur.execute(f"REINDEX INDEX {ivfflat_index}")
            cur.execute(f"VACUUM {partition}")

        return True
    except Exception:
        if not conn.autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def main():
    scratch_dir = tempfile.mkdtemp(prefix="lethe_reindex_variant_")
    print(f"Scratch dir: {scratch_dir}")

    rows = []
    subject_id = insert_subject("Reindex Timing Variant Subject", TENANT_1)
    records = generate_corpus(NUM_TRIALS)

    hnsw_found = 0
    ivfflat_found = 0

    print(f"\nRunning {NUM_TRIALS} trials of the REINDEX-after-commit variant...")
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

        hard_delete_reindex_after_commit(doc_id, TENANT_1, deletion_request_id)
        checkpoint()

        relations = search_relations(scratch_dir, f"trial_{i}", full_pat, short_pat)
        if relations[HNSW_INDEX]["full"]:
            hnsw_found += 1
        if relations[IVFFLAT_INDEX]["full"]:
            ivfflat_found += 1

        print(f"  trial {i + 1}/{NUM_TRIALS}: hnsw_found={relations[HNSW_INDEX]['full']}, ivfflat_found={relations[IVFFLAT_INDEX]['full']}")

    hnsw_rate = hnsw_found / NUM_TRIALS
    ivfflat_rate = ivfflat_found / NUM_TRIALS

    print(f"\nAfter {NUM_TRIALS} trials of REINDEX-after-commit:")
    print(f"  HNSW index, found: {hnsw_found}/{NUM_TRIALS} ({hnsw_rate:.0%})")
    print(f"  ivfflat index, found: {ivfflat_found}/{NUM_TRIALS} ({ivfflat_rate:.0%})")
    print("  (compare against the in-transaction hard_delete()'s 65% rate from the earlier run, see docs/LAB_NOTES.md)")

    log_row(
        rows,
        "reindex_after_commit_hnsw_found_rate",
        hnsw_rate,
        "fraction",
        corpus_size=NUM_TRIALS,
        notes="REINDEX run as its own step after the DELETE's transaction commits, instead of inside it; compare against storage_erasure_hnsw_full_pattern_rate (in-transaction REINDEX, 0.65 in the run this follows up on)",
    )
    log_row(
        rows,
        "reindex_after_commit_ivfflat_found_rate",
        ivfflat_rate,
        "fraction",
        corpus_size=NUM_TRIALS,
        notes="REINDEX run as its own step after the DELETE's transaction commits, instead of inside it; compare against storage_erasure_ivfflat_full_pattern_rate (in-transaction REINDEX, 0.65 in the run this follows up on)",
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
