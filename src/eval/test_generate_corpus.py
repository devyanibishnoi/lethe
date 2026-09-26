from src.db.db import insert_subject, insert_document, get_document
from src.eval.generate_corpus import generate_corpus, TENANT_IDS

subject_ids = {
    tenant_id: insert_subject("Corpus Test Subject", tenant_id)
    for tenant_id in TENANT_IDS
}

print("Created subjects:", subject_ids)

records = generate_corpus(6)

document_ids = []
for record in records:
    subject_id = subject_ids[record["tenant_id"]]
    document_id = insert_document(
        subject_id,
        record["tenant_id"],
        record["content"],
        record["embedding"],
    )
    document_ids.append((document_id, record["tenant_id"]))

print("Inserted", len(document_ids), "documents")

document_id, tenant_id = document_ids[0]
fetched = get_document(document_id, tenant_id)

print("Fetched back:", fetched)

assert fetched is not None
assert len(fetched[4].to_list()) == 384
