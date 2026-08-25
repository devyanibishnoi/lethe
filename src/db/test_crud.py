from db import insert_subject, insert_document, get_document

TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Fake 384-dimensional embedding
embedding = [0.01] * 384

subject_id = insert_subject("Test Subject", TENANT_ID)

print("Created subject:", subject_id)

document_id = insert_document(
    subject_id, TENANT_ID, "This is a fake test document.", embedding
)

print("Created document:", document_id)

document = get_document(document_id, TENANT_ID)

print("Fetched document:")
print(document)
