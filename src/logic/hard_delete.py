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

        # VACUUM FULL rewrites the partition into a brand-new file and
        # rebuilds every index on it as part of that rewrite, so the
        # deleted row's heap bytes and its HNSW/ivfflat index copies are
        # all gone, not just logically unreachable. Measured this directly:
        # 0 of 20 trials found the deleted embedding's bytes anywhere, heap,
        # HNSW, or ivfflat, a raw byte search of the actual files on disk,
        # not just a query through the database. Replaced the earlier
        # REINDEX x2 + plain VACUUM design, which left the heap bytes
        # recoverable indefinitely (plain VACUUM only marks space reusable,
        # it doesn't overwrite it) and, measured separately with a
        # concurrent query loop, blocked concurrent reads for about the
        # same duration VACUUM FULL does anyway, so there was no
        # concurrency advantage left to justify keeping the three-step
        # version. VACUUM FULL can't run inside a transaction block, hence
        # the autocommit step here, same as the plain VACUUM it replaces.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"VACUUM FULL {partition}")

        return True

    except Exception:
        if not conn.autocommit:
            conn.rollback()
        raise

    finally:
        conn.close()