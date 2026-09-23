from src.db.db import (
    get_connection,
    insert_subject,
    insert_document,
    get_document,
)

from src.logic.erase_subject import erase_subject
TENANT_1 = "00000000-0000-0000-0000-000000000001"
TENANT_2 = "00000000-0000-0000-0000-000000000002"

embedding = [0.01] * 384

subject_id = insert_subject(
    "Subject Erasure Test",
    TENANT_1,
)

print("Created subject:", subject_id)

conn = get_connection()

try:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO deletion_requests (subject_id)
            VALUES (%s)
            RETURNING id;
            """,
            (subject_id,),
        )
        deletion_request_id = cur.fetchone()[0]

    conn.commit()

finally:
    conn.close()

print("Created deletion request:", deletion_request_id)


document_1 = insert_document(
    subject_id,
    TENANT_1,
    "Tenant 1 document",
    embedding,
)

document_2 = insert_document(
    subject_id,
    TENANT_2,
    "Tenant 2 document",
    embedding,
)

print("Created documents:", document_1, document_2)


erase_subject(
    subject_id,
    deletion_request_id,
)
print("Subject erasure completed.")


remaining_1 = get_document(document_1, TENANT_1)
remaining_2 = get_document(document_2, TENANT_2)

print("Document 1:", remaining_1)
print("Document 2:", remaining_2)

if remaining_1 is not None or remaining_2 is not None:
    raise RuntimeError("Some documents still exist.")


conn = get_connection()

try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status
            FROM deletion_requests
            WHERE id = %s;
            """,
            (deletion_request_id,),
        )
        status = cur.fetchone()[0]

finally:
    conn.close()
print("Deletion request status:", status)

if status != "completed":
    raise RuntimeError("Deletion request was not completed.")
print("TEST PASSED: Subject-level erasure completed.")



#Verify one audit entry was created for each deleted document
conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT document_id, deleted_hash, signature, signed_at
            FROM deletion_audit_log
            WHERE deletion_request_id = %s
            ORDER BY signed_at ASC;
            """,
            (deletion_request_id,),
        )
        audit_entries = cur.fetchall()
finally:
    conn.close()

print("\nAudit entries created:", len(audit_entries))

for entry in audit_entries:
    print("Document:", entry[0])
    print("Hash:", entry[1])
    print("Signature:", entry[2])
    print("Signed at:", entry[3])
    print()

expected_count = 2

if len(audit_entries) != expected_count:
    raise RuntimeError(
        f"Expected {expected_count} audit entries, "
        f"but found {len(audit_entries)}."
    )

print("TEST PASSED: One audit entry exists for each deleted document.")



#Verify one audit entry was created for each deleted document
conn = get_connection()

try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT document_id, deleted_hash, signature, signed_at
            FROM deletion_audit_log
            WHERE deletion_request_id = %s
            ORDER BY signed_at ASC;
            """,
            (deletion_request_id,),
        )

        audit_entries = cur.fetchall()

finally:
    conn.close()


print("\nAudit entries created:", len(audit_entries))

for entry in audit_entries:
    print("Document:", entry[0])
    print("Hash:", entry[1])
    print("Signature:", entry[2])
    print("Signed at:", entry[3])
    print()


expected_count = 2

if len(audit_entries) != expected_count:
    raise RuntimeError(
        f"Expected {expected_count} audit entries, "
        f"but found {len(audit_entries)}."
    )

print(
    "TEST PASSED: One audit entry exists "
    "for each deleted document."
)