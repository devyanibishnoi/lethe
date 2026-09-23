from src.db.db import get_connection
from src.logic.verify_deletion import verify_deletion

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


original_result = verify_deletion(
    document_id,
    content_hash,
    signed_at,
    previous_hash,
    signature,
)

print("Original signature verification:", original_result)

if not original_result:
    raise RuntimeError(
        "Original signature should be valid."
    )


tampered_hash = "tampered_hash"

tampered_result = verify_deletion(
    document_id,
    tampered_hash,
    signed_at,
    previous_hash,
    signature,
)

print("After modifying the hash:", tampered_result)
if tampered_result:
    raise RuntimeError(
        "Tampering was not detected."
    )

print(
    "TEST PASSED: Modified hash was detected "
    "by signature verification."
)