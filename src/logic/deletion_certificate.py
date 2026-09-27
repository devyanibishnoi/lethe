from src.db.db import get_connection

def get_deletion_certificate(deletion_request_id):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    subject_id,
                    requested_at,
                    status
                FROM deletion_requests
                WHERE id = %s;
                """,
                (deletion_request_id,),
            )

            request = cur.fetchone()
            if request is None:
                raise ValueError(
                    f"Deletion request {deletion_request_id} not found"
                )

            request_id, subject_id, requested_at, status = request

            if status != "completed":
                raise ValueError(
                    "Deletion request is not completed."
                )

            cur.execute(
                """
                SELECT
                    document_id,
                    deleted_hash,
                    previous_hash,
                    signature,
                    signed_at
                FROM deletion_audit_log
                WHERE deletion_request_id = %s
                ORDER BY signed_at ASC;
                """,
                (deletion_request_id,),
            )
            audit_entries = cur.fetchall()

        completed_at = (
            audit_entries[-1][4]
            if audit_entries
            else None
        )

        return {
            "deletion_request_id": request_id,
            "subject_id": subject_id,
            "requested_at": requested_at,
            "completed_at": completed_at,
            "audit_entries": [
                {
                    "document_id": row[0],
                    "hash": row[1],
                    "previous_hash": row[2],
                    "signature": row[3],
                    # str(), not the datetime object itself: this must match the exact
                    # string that was embedded in the signed message (build_message()
                    # in sign_deletion.py uses plain f"{signed_at}"), or re-running
                    # verify_deletion() against this certificate will spuriously fail.
                    # The default JSON datetime encoding (isoformat, "T" separator)
                    # is NOT that string.
                    "signed_at": str(row[4]),
                }
                for row in audit_entries
            ],
        }

    finally:
        conn.close()