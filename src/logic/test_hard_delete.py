from src.db.db import insert_subject, insert_document, get_document
from src.logic.hard_delete import hard_delete


TENANT_ID = "00000000-0000-0000-0000-000000000001"
embedding = [0.01] * 384

subject_id = insert_subject("Hard Delete Test Subject", TENANT_ID)
print("Created subject:", subject_id)

document_id = insert_document(
    subject_id,
    TENANT_ID,
    "This document will be permanently deleted.",
    embedding
)

print("Created document:", document_id)

document_before = get_document(document_id, TENANT_ID)

print("\nBefore deletion:")
print(document_before)

if document_before is None:
    raise RuntimeError("Document was not created correctly.")


hard_delete(document_id, TENANT_ID)
print("\nHard delete completed.")

document_after = get_document(document_id, TENANT_ID)

print("\nAfter deletion:")
print(document_after)

if document_after is None:
    print("\nTEST PASSED: Document was physically deleted.")
else:
    print("\nTEST FAILED: Document still exists.")