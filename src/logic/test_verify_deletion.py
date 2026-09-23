from src.db.db import get_connection
from src.logic.verify_deletion import verify_deletion, verify_chain

conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                document_id,
                deleted_hash,
                signed_at,
                previous_hash,
                signature
            FROM deletion_audit_log
            ORDER BY signed_at DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()

finally:
    conn.close()

if row is None:
    raise RuntimeError("No audit records found.")

document_id, content_hash, signed_at, previous_hash, signature = row
result = verify_deletion(
    document_id,
    content_hash,
    signed_at,
    previous_hash,
    signature,
)

print("Single signature verification:", result)
if not result:
    raise RuntimeError("Signature verification failed.")

chain_result = verify_chain()
print("Full chain verification:", chain_result)

if not chain_result:
    raise RuntimeError("Chain verification failed.")
print("TEST PASSED: Signature and chain are valid.")