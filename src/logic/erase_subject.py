from src.db.db import get_connection
from src.logic.hard_delete import hard_delete

def erase_subject(subject_id, deletion_request_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id
                FROM documents
                WHERE subject_id = %s;
                """,
                (subject_id,),
            )

            documents = cur.fetchall()

    finally:
        conn.close()

    for document_id, tenant_id in documents:
        hard_delete(
            document_id,
            tenant_id,
            deletion_request_id,
        )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE deletion_requests
                SET status = 'completed'
                WHERE id = %s;
                """,
                (deletion_request_id,),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()