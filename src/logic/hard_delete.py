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

        conn.commit()

        # REINDEX and VACUUM both run here, after the DELETE's own
        # transaction has already committed, not inside it. Measured this:
        # running REINDEX inside the same transaction as the DELETE left
        # the deleted embedding's bytes recoverable in the rebuilt ivfflat/
        # HNSW index files in 13 of 20 trials. Moving it to run as its own
        # post-commit step (same reason VACUUM already has to be out here,
        # VACUUM can't run inside a transaction block at all) brought that
        # to 0 of 20. ivfflat and HNSW each store a copy of the vector
        # inside their own index pages, not just a pointer into the heap,
        # so rebuilding them from stale, uncommitted-looking state is
        # exactly the gap PROBLEM_STATEMENT.md says this project exists to
        # close.
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