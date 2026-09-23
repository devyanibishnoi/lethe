from src.db.db import get_connection
from src.logic.deletion_certificate import get_deletion_certificate

conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM deletion_requests
            WHERE status = 'completed'
            ORDER BY requested_at DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()

finally:
    conn.close()

if row is None:
    raise RuntimeError("No completed deletion request found.")

deletion_request_id = row[0]

certificate = get_deletion_certificate(
    deletion_request_id
)

print("\nDELETION CERTIFICATE")
print("--------------------")
print("Request ID:", certificate["deletion_request_id"])
print("Subject ID:", certificate["subject_id"])
print("Requested:", certificate["requested_at"])
print("Completed:", certificate["completed_at"])

print("\nAudit entries:")
for entry in certificate["audit_entries"]:
    print("\nDocument:", entry["document_id"])
    print("Hash:", entry["hash"])
    print("Signature:", entry["signature"])
    print("Signed at:", entry["signed_at"])


if not certificate["audit_entries"]:
    raise RuntimeError("Certificate contains no audit entries.")
print("\nTEST PASSED: Deletion certificate generated.")