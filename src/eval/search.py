from src.db.db import get_connection
from src.logic.hard_delete import TENANT_CONFIG


def similarity_search(tenant_id, query_embedding, k, exclude_id=None):
    partition = TENANT_CONFIG[tenant_id]["partition"]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if exclude_id is not None:
                cur.execute(
                    f"""
                    SELECT id, content, embedding <=> %s::vector AS distance
                    FROM {partition}
                    WHERE id != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_embedding, exclude_id, query_embedding, k),
                )
            else:
                cur.execute(
                    f"""
                    SELECT id, content, embedding <=> %s::vector AS distance
                    FROM {partition}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_embedding, query_embedding, k),
                )

            return [
                {"id": row[0], "content": row[1], "distance": row[2]}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()
