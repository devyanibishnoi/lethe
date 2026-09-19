from src.db.db import get_connection, get_document

TENANT_CONFIG = {
    "00000000-0000-0000-0000-000000000001": {
        "partition": "documents_tenant_1",
        "hnsw_index": "documents_tenant_1_hnsw_idx",
    },
    "00000000-0000-0000-0000-000000000002": {
        "partition": "documents_tenant_2",
        "hnsw_index": "documents_tenant_2_hnsw_idx",
    },
}


def hard_delete(document_id, tenant_id):
    tenant_id = str(tenant_id)

    if tenant_id not in TENANT_CONFIG:
        raise ValueError(f"Unknown tenant ID: {tenant_id}")

    config = TENANT_CONFIG[tenant_id]
    partition = config["partition"]
    hnsw_index = config["hnsw_index"]

    conn = get_connection()

    try:
        document = get_document(document_id, tenant_id)

        if document is None:
            raise ValueError(
                f"Document {document_id} not found for tenant {tenant_id}"
            )

        with conn.cursor() as cur:
            delete_query = f"""
                DELETE FROM {partition}
                WHERE id = %s
                  AND tenant_id = %s
            """

            cur.execute(
                delete_query,
                (document_id, tenant_id),
            )

            if cur.rowcount != 1:
                raise RuntimeError(
                    f"Expected to delete 1 document, "
                    f"but deleted {cur.rowcount}"
                )
            cur.execute(f"REINDEX INDEX {hnsw_index}")

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()