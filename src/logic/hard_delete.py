from src.db.db import get_connection, get_document
from src.logic.sign_deletion import sign_deletion, save_audit_log

TENANT_CONFIG = {
    "00000000-0000-0000-0000-000000000001": {
        "partition": "documents_tenant_1",
        "hnsw_index": "documents_tenant_1_hnsw_idx",
        "ivfflat_index": "documents_tenant_1_ivfflat_idx",
    },
    "00000000-0000-0000-0000-000000000002": {
        "partition": "documents_tenant_2",
        "hnsw_index": "documents_tenant_2_hnsw_idx",
        "ivfflat_index": "documents_tenant_2_ivfflat_idx",
    },
}


def hard_delete(document_id, tenant_id, deletion_request_id):
    tenant_id = str(tenant_id)

    if tenant_id not in TENANT_CONFIG:
        raise ValueError(f"Unknown tenant ID: {tenant_id}")

    config = TENANT_CONFIG[tenant_id]
    partition = config["partition"]
    hnsw_index = config["hnsw_index"]
    ivfflat_index = config["ivfflat_index"]

    conn = get_connection()

    try:
        document = get_document(document_id, tenant_id)

        if document is None:
            raise ValueError(
                f"Document {document_id} not found for tenant {tenant_id}"
            )

        signing_data = sign_deletion(
                document[3],
                document_id,
            )

        save_audit_log(
            conn,
            deletion_request_id,
            document_id,
            signing_data,
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

            # ivfflat stores a copy of each vector inside its own index
            # pages, not just a pointer into the heap. Rebuilding only the
            # HNSW index left that copy physically recoverable, the exact
            # gap PROBLEM_STATEMENT.md says this project exists to close.
            cur.execute(f"REINDEX INDEX {hnsw_index}")
            cur.execute(f"REINDEX INDEX {ivfflat_index}")

        conn.commit()

        # DELETE only marks the heap tuple dead (MVCC); the bytes stay on
        # disk until vacuumed. VACUUM can't run inside a transaction block,
        # so it has to happen as its own autocommit statement after the
        # delete above has already committed.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"VACUUM {partition}")

        return True

    except Exception:
        if not conn.autocommit:
            conn.rollback()
        raise

    finally:
        conn.close()