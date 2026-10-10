"""Self-review experiment: don't just trust that hard_delete() removed the
row, open the actual data files on disk before and after and check the
embedding's raw bytes are gone. Runs across N documents (not just one) to
report a rate rather than a single pass/fail, searches for both the full
embedding pattern and a short chunk of it (to catch partial remnants a
full-pattern search could miss), and checks WAL files in addition to the
heap and index files. Also runs VACUUM FULL as a reproducible, logged step,
not just an ad hoc one-off.

Two parts:
  1. hard_delete() (DELETE + REINDEX both indexes + VACUUM): does the
     embedding's byte pattern actually disappear from the heap file, both
     index files, and WAL?
  2. A plain soft-delete baseline (DELETE only, no reindex, no vacuum): does
     the pattern predictably survive, to show what the extra work buys?

Reads container-internal file paths via pg_relation_filepath() and pulls the
files out with `docker cp` so the search runs against the real bytes
PostgreSQL has on disk, not anything held only in a Python object.

Results are logged to docs/benchmark_results.csv (same file the rest of the
benchmark suite uses) so these rates are reproducible and citable, not just
asserted in a notes file.

KNOWN LIMITATION, found by actually running this at scale rather than
assumed: the heap-file search is reliable (100% consistent at every scale
tested). The HNSW/ivfflat index-file search is NOT reliable once the index
has real size/structure, a freshly inserted, still-alive document's own
embedding is sometimes not findable in its own index file by this plain
substring search, almost certainly because HNSW's graph-node page-packing
doesn't always lay a vector down as one contiguous byte run. Treat
storage_erasure_hnsw_full_pattern_rate / storage_erasure_ivfflat_full_pattern_rate
as inconclusive on a non-trivially-sized partition, not as confirmation
either way. See the second self-review entry in docs/LAB_NOTES.md. A
reliable index-level check would need to parse pgvector's actual page
format rather than search for a flat byte run.
"""

import struct
import subprocess
import tempfile
from pathlib import Path

from src.db.db import get_connection, insert_subject, insert_document
from src.eval.generate_corpus import generate_corpus
from src.eval.run_benchmarks import CSV_PATH, append_csv, log_row
from src.logic.hard_delete import hard_delete

CONTAINER = "lethe-db-1"
DATA_DIRECTORY = "/var/lib/postgresql/data"
TENANT_1 = "00000000-0000-0000-0000-000000000001"
HEAP_RELATION = "documents_tenant_1"
HNSW_INDEX = "documents_tenant_1_hnsw_idx"
IVFFLAT_INDEX = "documents_tenant_1_ivfflat_idx"
NUM_TRIALS = 20
NUM_SOFT_DELETE_TRIALS = 5
SHORT_CHUNK_FLOATS = 16  # first 16 of 384 components, a 64-byte sub-pattern


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


def copy_wal_dir(scratch_dir, label):
    local_dir = Path(scratch_dir) / f"pg_wal__{label}"
    subprocess.run(
        ["docker", "cp", f"{CONTAINER}:{DATA_DIRECTORY}/pg_wal", str(local_dir)],
        check=True,
        capture_output=True,
    )
    return [p for p in local_dir.iterdir() if p.is_file()]


def full_pattern(embedding):
    """pgvector stores a vector's components as a flat sequence of IEEE-754
    float4s, native (little-endian on x86/x64) byte order.
    """
    return struct.pack(f"<{len(embedding)}f", *embedding)


def short_pattern(embedding):
    return struct.pack(f"<{SHORT_CHUNK_FLOATS}f", *embedding[:SHORT_CHUNK_FLOATS])


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


def search_relations(scratch_dir, label, full_pat, short_pat):
    result = {}
    for relname in (HEAP_RELATION, HNSW_INDEX, IVFFLAT_INDEX):
        data = copy_out(relname, scratch_dir, label).read_bytes()
        result[relname] = {"full": full_pat in data, "short": short_pat in data}
    return result


def search_wal(scratch_dir, label, full_pat, short_pat):
    found_full = False
    found_short = False
    for wal_file in copy_wal_dir(scratch_dir, label):
        data = wal_file.read_bytes()
        if full_pat in data:
            found_full = True
        if short_pat in data:
            found_short = True
    return {"full": found_full, "short": found_short}


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


def vacuum_full():
    conn = get_connection()
    conn.commit()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"VACUUM FULL {HEAP_RELATION}")
    conn.close()


def run_trial(scratch_dir, subject_id, record):
    """One document, through hard_delete(), checked at the heap/index/WAL
    level both for the full pattern and a short 64-byte chunk of it.
    Returns dicts of what was still found after hard_delete().
    """
    doc_id = insert_document(subject_id, TENANT_1, record["content"], record["embedding"])
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

    hard_delete(doc_id, TENANT_1, deletion_request_id)
    checkpoint()

    relations = search_relations(scratch_dir, f"trial_{doc_id}", full_pat, short_pat)
    return relations, full_pat, short_pat


def main():
    scratch_dir = tempfile.mkdtemp(prefix="lethe_storage_check_")
    print(f"Scratch dir for copied-out files: {scratch_dir}")

    rows = []
    subject_id = insert_subject("Storage Check Subject", TENANT_1)
    records = generate_corpus(NUM_TRIALS + 1)  # +1 for the soft-delete baseline doc

    heap_full_found = 0
    heap_short_found = 0
    hnsw_full_found = 0
    ivfflat_full_found = 0

    print(f"\nRunning {NUM_TRIALS} hard_delete() trials...")
    for i in range(NUM_TRIALS):
        relations, _, _ = run_trial(scratch_dir, subject_id, records[i])
        if relations[HEAP_RELATION]["full"]:
            heap_full_found += 1
        if relations[HEAP_RELATION]["short"]:
            heap_short_found += 1
        if relations[HNSW_INDEX]["full"]:
            hnsw_full_found += 1
        if relations[IVFFLAT_INDEX]["full"]:
            ivfflat_full_found += 1
        print(f"  trial {i + 1}/{NUM_TRIALS}: heap full-pattern found={relations[HEAP_RELATION]['full']}")

    heap_rate = heap_full_found / NUM_TRIALS
    heap_short_rate = heap_short_found / NUM_TRIALS
    hnsw_rate = hnsw_full_found / NUM_TRIALS
    ivfflat_rate = ivfflat_full_found / NUM_TRIALS

    print(f"\nAfter hard_delete() across {NUM_TRIALS} trials:")
    print(f"  heap, full 1536-byte pattern still found: {heap_full_found}/{NUM_TRIALS} ({heap_rate:.0%})")
    print(f"  heap, short 64-byte chunk still found:    {heap_short_found}/{NUM_TRIALS} ({heap_short_rate:.0%})")
    print(f"  HNSW index, full pattern still found:     {hnsw_full_found}/{NUM_TRIALS} ({hnsw_rate:.0%})")
    print(f"  ivfflat index, full pattern still found:  {ivfflat_full_found}/{NUM_TRIALS} ({ivfflat_rate:.0%})")

    log_row(rows, "storage_erasure_heap_full_pattern_rate", heap_rate, "fraction", corpus_size=NUM_TRIALS, notes="fraction of trials where the deleted embedding's full 1536-byte pattern was still found in the heap file after hard_delete()")
    log_row(rows, "storage_erasure_heap_short_pattern_rate", heap_short_rate, "fraction", corpus_size=NUM_TRIALS, notes=f"fraction of trials where a {SHORT_CHUNK_FLOATS}-float (64-byte) chunk of the deleted embedding was still found in the heap file after hard_delete()")
    log_row(rows, "storage_erasure_hnsw_full_pattern_rate", hnsw_rate, "fraction", corpus_size=NUM_TRIALS, notes="fraction of trials where the deleted embedding's full pattern was still found in the HNSW index file after hard_delete()")
    log_row(rows, "storage_erasure_ivfflat_full_pattern_rate", ivfflat_rate, "fraction", corpus_size=NUM_TRIALS, notes="fraction of trials where the deleted embedding's full pattern was still found in the ivfflat index file after hard_delete()")

    # --- WAL check, on one representative document (expensive: copies the
    # whole pg_wal directory, not worth repeating per trial) ---
    print("\nChecking WAL files for a representative deleted document...")
    wal_doc_id = insert_document(subject_id, TENANT_1, records[NUM_TRIALS - 1]["content"], records[NUM_TRIALS - 1]["embedding"])
    wal_embedding = fetch_embedding(wal_doc_id)
    wal_full_pat = full_pattern(wal_embedding)
    wal_short_pat = short_pattern(wal_embedding)
    checkpoint()
    wal_result = search_wal(scratch_dir, "wal_check", wal_full_pat, wal_short_pat)
    print(f"  WAL, full pattern found: {wal_result['full']}, short chunk found: {wal_result['short']}")
    log_row(rows, "storage_erasure_wal_full_pattern_found", int(wal_result["full"]), "bool", notes="whether the embedding's full pattern was found anywhere in current pg_wal segments, checked before any delete (WAL is append-only and not rewritten by REINDEX/VACUUM)")
    log_row(rows, "storage_erasure_wal_short_pattern_found", int(wal_result["short"]), "bool", notes="same check with the short 64-byte chunk pattern")

    # --- VACUUM FULL: does it close the heap-level gap? Logged, not just observed ---
    print("\nTesting VACUUM FULL as the heap-level fix...")
    vacfull_doc_id = insert_document(subject_id, TENANT_1, records[NUM_TRIALS]["content"], records[NUM_TRIALS]["embedding"])
    vacfull_embedding = fetch_embedding(vacfull_doc_id)
    vacfull_pat = full_pattern(vacfull_embedding)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deletion_requests (subject_id, status) VALUES (%s, 'completed') RETURNING id",
                (subject_id,),
            )
            vacfull_request_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    hard_delete(vacfull_doc_id, TENANT_1, vacfull_request_id)
    checkpoint()
    before_vacuum_full = full_pattern(vacfull_embedding) in copy_out(HEAP_RELATION, scratch_dir, "before_vacuum_full").read_bytes()

    vacuum_full()
    checkpoint()
    after_vacuum_full = full_pattern(vacfull_embedding) in copy_out(HEAP_RELATION, scratch_dir, "after_vacuum_full").read_bytes()

    print(f"  before VACUUM FULL, pattern present: {before_vacuum_full}")
    print(f"  after VACUUM FULL, pattern present: {after_vacuum_full}")
    log_row(rows, "storage_erasure_heap_pattern_before_vacuum_full", int(before_vacuum_full), "bool", notes="heap pattern presence after hard_delete()'s plain VACUUM, right before testing VACUUM FULL on the same row")
    log_row(rows, "storage_erasure_heap_pattern_after_vacuum_full", int(after_vacuum_full), "bool", notes="heap pattern presence after running VACUUM FULL on the partition; expected False, full table rewrite into a new relfilenode")

    # --- soft delete baseline: plain DELETE, no reindex, no vacuum ---
    # Repeated NUM_SOFT_DELETE_TRIALS times, not just once: an earlier
    # single-trial version of this check occasionally produced a false
    # negative (pattern not found in an index file even BEFORE any delete
    # happened, on a table that had already been through many prior
    # REINDEX cycles in this same run), which only a repeat run caught.
    # Reporting both a "before" and "after" rate makes that search
    # methodology's own reliability visible instead of silently trusting one
    # sample. See the second self-review entry in LAB_NOTES.md.
    print(f"\nChecking the soft-delete baseline (plain DELETE, no reindex, no vacuum) over {NUM_SOFT_DELETE_TRIALS} trials...")
    before_found = {HEAP_RELATION: 0, HNSW_INDEX: 0, IVFFLAT_INDEX: 0}
    after_found = {HEAP_RELATION: 0, HNSW_INDEX: 0, IVFFLAT_INDEX: 0}

    for i in range(NUM_SOFT_DELETE_TRIALS):
        soft_doc_id = insert_document(subject_id, TENANT_1, records[i % len(records)]["content"], records[i % len(records)]["embedding"])
        soft_embedding = fetch_embedding(soft_doc_id)
        soft_pat = full_pattern(soft_embedding)
        checkpoint()
        before_soft = search_relations(scratch_dir, f"before_soft_{i}", soft_pat, short_pattern(soft_embedding))
        soft_delete(soft_doc_id)
        checkpoint()
        after_soft = search_relations(scratch_dir, f"after_soft_delete_{i}", soft_pat, short_pattern(soft_embedding))
        print(f"  trial {i + 1}/{NUM_SOFT_DELETE_TRIALS}: before={ {k: v['full'] for k, v in before_soft.items()} }, after={ {k: v['full'] for k, v in after_soft.items()} }")
        for relname in (HEAP_RELATION, HNSW_INDEX, IVFFLAT_INDEX):
            if before_soft[relname]["full"]:
                before_found[relname] += 1
            if after_soft[relname]["full"]:
                after_found[relname] += 1

    for relname in (HEAP_RELATION, HNSW_INDEX, IVFFLAT_INDEX):
        log_row(
            rows,
            "storage_erasure_soft_delete_before_rate",
            before_found[relname] / NUM_SOFT_DELETE_TRIALS,
            "fraction",
            corpus_size=NUM_SOFT_DELETE_TRIALS,
            notes=f"relation={relname}, fraction of trials where the pattern was found BEFORE any delete, expected ~1.0, a sanity check on the search methodology's own false-negative rate",
        )
        log_row(
            rows,
            "storage_erasure_soft_delete_after_rate",
            after_found[relname] / NUM_SOFT_DELETE_TRIALS,
            "fraction",
            corpus_size=NUM_SOFT_DELETE_TRIALS,
            notes=f"relation={relname}, fraction of trials where the pattern was STILL found after a plain DELETE with no reindex/vacuum, expected ~1.0 (bytes survive, this is the soft-delete baseline)",
        )

    append_csv(rows)
    print(f"\nAppended {len(rows)} rows to {CSV_PATH}")

    print("\nCleaning up test subject...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM data_subjects WHERE id = %s", (subject_id,))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
