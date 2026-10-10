"""Reviewer-requested experiment: don't just trust that hard_delete() removed
the row, open the actual data files on disk before and after and check the
embedding's raw bytes are gone.

Two parts:
  1. hard_delete() (DELETE + REINDEX both indexes + VACUUM): does the
     embedding's byte pattern actually disappear from the heap file and both
     index files?
  2. A plain soft-delete baseline (DELETE only, no reindex, no vacuum): does
     the pattern predictably survive, to show what the extra work buys?

Reads container-internal file paths via pg_relation_filepath() and pulls the
files out with `docker cp` so the search runs against the real bytes
PostgreSQL has on disk, not anything held only in a Python object.
"""

import struct
import subprocess
import tempfile
from pathlib import Path

from src.db.db import get_connection, insert_subject, insert_document
from src.eval.generate_corpus import generate_corpus
from src.logic.hard_delete import hard_delete

CONTAINER = "lethe-db-1"
DATA_DIRECTORY = "/var/lib/postgresql/data"
TENANT_1 = "00000000-0000-0000-0000-000000000001"
HEAP_RELATION = "documents_tenant_1"
HNSW_INDEX = "documents_tenant_1_hnsw_idx"
IVFFLAT_INDEX = "documents_tenant_1_ivfflat_idx"


def checkpoint():
    """Force dirty pages out of PostgreSQL's shared_buffers and onto disk.
    Without this, a raw file read can miss a recent write that's still only
    sitting in memory, or still show "old" bytes in place for a page whose
    update hasn't been flushed yet.
    """
    conn = get_connection()
    conn.commit()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CHECKPOINT")
    conn.close()


def relation_filepath(relname):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_relation_filepath(%s::regclass)", (relname,))
            return cur.fetchone()[0]
    finally:
        conn.close()


def copy_out(relname, scratch_dir, label):
    relpath = relation_filepath(relname)
    container_path = f"{DATA_DIRECTORY}/{relpath}"
    local_path = Path(scratch_dir) / f"{relname}__{label}.bin"
    subprocess.run(
        ["docker", "cp", f"{CONTAINER}:{container_path}", str(local_path)],
        check=True,
        capture_output=True,
    )
    return local_path


def embedding_pattern(embedding):
    """pgvector stores a vector's components as a flat sequence of IEEE-754
    float4s, native (little-endian on x86/x64) byte order. The full 384
    component sequence is distinctive enough that finding it verbatim
    anywhere in a file is strong evidence that exact vector's data is
    physically present there.
    """
    return struct.pack(f"<{len(embedding)}f", *embedding)


def fetch_embedding(document_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT embedding FROM {HEAP_RELATION} WHERE id = %s", (document_id,)
            )
            return cur.fetchone()[0].to_list()
    finally:
        conn.close()


def check_presence(scratch_dir, label, pattern):
    results = {}
    for relname in (HEAP_RELATION, HNSW_INDEX, IVFFLAT_INDEX):
        path = copy_out(relname, scratch_dir, label)
        data = path.read_bytes()
        results[relname] = pattern in data
    return results


def soft_delete(document_id):
    """Comparison baseline: what most systems actually do. No REINDEX, no
    VACUUM, just the DELETE.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {HEAP_RELATION} WHERE id = %s AND tenant_id = %s",
                (document_id, TENANT_1),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    scratch_dir = tempfile.mkdtemp(prefix="lethe_storage_check_")
    print(f"Scratch dir for copied-out files: {scratch_dir}")

    subject_id = insert_subject("Storage Check Subject", TENANT_1)
    records = generate_corpus(2)
    hard_delete_doc_id = insert_document(
        subject_id, TENANT_1, records[0]["content"], records[0]["embedding"]
    )
    soft_delete_doc_id = insert_document(
        subject_id, TENANT_1, records[1]["content"], records[1]["embedding"]
    )

    hard_embedding = fetch_embedding(hard_delete_doc_id)
    soft_embedding = fetch_embedding(soft_delete_doc_id)
    hard_pattern = embedding_pattern(hard_embedding)
    soft_pattern = embedding_pattern(soft_embedding)

    checkpoint()
    before = check_presence(scratch_dir, "before", hard_pattern)
    print(f"\nBefore any delete, pattern found in: {[k for k, v in before.items() if v]}")
    if not all(before.values()):
        raise RuntimeError(
            f"Embedding wasn't even found everywhere before deleting, can't "
            f"trust this test. Found in: {before}"
        )

    # --- hard_delete(): DELETE + REINDEX (both indexes) + VACUUM ---
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

    hard_delete(hard_delete_doc_id, TENANT_1, deletion_request_id)
    checkpoint()

    after_hard = check_presence(scratch_dir, "after_hard_delete", hard_pattern)
    print(f"After hard_delete(), pattern found in: {[k for k, v in after_hard.items() if v]}")

    # --- soft delete baseline: plain DELETE, no reindex, no vacuum ---
    checkpoint()
    before_soft = check_presence(scratch_dir, "before_soft", soft_pattern)
    soft_delete(soft_delete_doc_id)
    checkpoint()
    after_soft = check_presence(scratch_dir, "after_soft_delete", soft_pattern)
    print(f"After plain DELETE (no reindex/vacuum), pattern found in: {[k for k, v in after_soft.items() if v]}")

    print("\n--- Summary ---")
    for relname in (HEAP_RELATION, HNSW_INDEX, IVFFLAT_INDEX):
        print(
            f"{relname}: before={before[relname]}, "
            f"after hard_delete={after_hard[relname]}, "
            f"after plain DELETE={after_soft[relname]} (started present={before_soft[relname]})"
        )

    print("\nCleaning up test subject...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # soft-deleted doc's row is already gone; this also removes the
            # audit log entry and the subject itself.
            cur.execute("DELETE FROM data_subjects WHERE id = %s", (subject_id,))
        conn.commit()
    finally:
        conn.close()

    return before, after_hard, before_soft, after_soft


if __name__ == "__main__":
    main()
