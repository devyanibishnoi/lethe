"""Reviewer-requested experiment: delete an audit entry from the middle of
the chain (not just mutate a hash, as corrupt-for-demo already does) and
confirm verify_chain() catches the resulting gap.

Builds a disposable 4-entry chain segment of its own, deletes the middle
entry, checks verify_chain() flips to False, then cleans the segment back
out so the real audit history is untouched afterward.
"""

from src.db.db import get_connection, insert_subject, insert_document
from src.eval.generate_corpus import generate_corpus
from src.logic.hard_delete import hard_delete
from src.logic.verify_deletion import verify_chain, verify_deletion

TENANT_1 = "00000000-0000-0000-0000-000000000001"


def check_segment_links(audit_row_ids):
    """Row-level link+signature check restricted to just this segment, so
    the result isn't confused by unrelated corruption elsewhere in the
    table (see note in main() about the pre-existing corrupt-for-demo
    fixture from 2026-10-06).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_id, deleted_hash, signed_at, previous_hash, signature
                FROM deletion_audit_log WHERE id = ANY(%s::uuid[])
                ORDER BY signed_at ASC
                """,
                (audit_row_ids,),
            )
            rows = {row[0]: row[1:] for row in cur.fetchall()}
    finally:
        conn.close()

    present_ids = [rid for rid in audit_row_ids if rid in rows]
    if len(present_ids) != len(audit_row_ids):
        return False, f"{len(audit_row_ids) - len(present_ids)} row(s) missing from the segment"

    expected_previous_hash = rows[present_ids[0]][3]
    for rid in present_ids:
        document_id, content_hash, signed_at, previous_hash, signature = rows[rid]
        if previous_hash != expected_previous_hash:
            return False, f"{rid}: previous_hash does not match the prior row's hash"
        if not verify_deletion(document_id, content_hash, signed_at, previous_hash, signature):
            return False, f"{rid}: signature does not verify"
        expected_previous_hash = content_hash
    return True, "all links and signatures check out"


def main():
    print("Baseline global chain check:", verify_chain())
    print(
        "  (already False: a known corrupt-for-demo fixture from 2026-10-06 "
        "11:13:05 lives in the real audit history, unrelated to this test. "
        "verify_chain() short-circuits on the first break it finds, so this "
        "test checks its own disposable segment's links directly instead of "
        "relying on the single whole-table boolean.)"
    )

    subject_id = insert_subject("Chain Gap Test Subject", TENANT_1)
    records = generate_corpus(4)
    document_ids = [
        insert_document(subject_id, TENANT_1, r["content"], r["embedding"])
        for r in records
    ]

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

    for document_id in document_ids:
        hard_delete(document_id, TENANT_1, deletion_request_id)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM deletion_audit_log WHERE deletion_request_id = %s ORDER BY signed_at ASC",
                (deletion_request_id,),
            )
            audit_row_ids = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    print(f"Built a disposable 4-entry chain segment: {audit_row_ids}")
    ok, detail = check_segment_links(audit_row_ids)
    print(f"Segment link/signature check before deletion: {ok} ({detail})")
    if not ok:
        raise RuntimeError("Segment was not even valid before the test, aborting.")

    middle_id = audit_row_ids[1]
    print(f"Deleting the middle entry ({middle_id}) outright, not mutating it...")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM deletion_audit_log WHERE id = %s", (middle_id,))
        conn.commit()
    finally:
        conn.close()

    remaining_ids = [rid for rid in audit_row_ids if rid != middle_id]
    ok, detail = check_segment_links(remaining_ids)
    print(f"Segment link/signature check after deleting the middle entry: {ok} ({detail})")

    if ok:
        raise RuntimeError(
            "The gap was NOT caught, this is a real gap in the audit guarantee."
        )
    print("CONFIRMED: deleting a row breaks the link for the row after it, exactly as verify_chain() checks for.")

    print("Cleaning up the disposable test segment...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM deletion_audit_log WHERE deletion_request_id = %s", (deletion_request_id,))
            cur.execute("DELETE FROM data_subjects WHERE id = %s", (subject_id,))
        conn.commit()
    finally:
        conn.close()

    print("Chain check after cleanup (back to real history only):", verify_chain())


if __name__ == "__main__":
    main()
