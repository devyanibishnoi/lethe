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
            audit_entries[-1][3]
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
                    "signature": row[2],
                    "signed_at": row[3],
                }
                for row in audit_entries
            ],
        }

    finally:
        conn.close()