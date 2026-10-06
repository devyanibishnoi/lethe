from src.db.db import insert_subject, insert_document, get_connection
from src.eval.generate_corpus import generate_corpus
from src.logic.hard_delete import hard_delete

TENANT_1 = "00000000-0000-0000-0000-000000000001"
TENANT_2 = "00000000-0000-0000-0000-000000000002"

# A subject whose data was already (partially) erased, so the Audit Trail page
# has real, pre-existing chained history to show on first load, instead of an
# empty table until a visitor submits their own erasure request.
AUDIT_HISTORY_SUBJECT = (TENANT_1, "Vantage Property Group", True, 8, 5)

# (tenant_id, display_name, consented, document_count)
# consented=None means no consent_status row at all, to also show the "Unset" badge state.
DEMO_SUBJECTS = [
    (TENANT_1, "Meridian Health Systems", True, 24),
    (TENANT_1, "Northbridge Financial", True, 18),
    (TENANT_1, "Solace Retail Group", False, 12),
    (TENANT_2, "Arcfield Logistics", True, 20),
    (TENANT_2, "Bellwether Insurance", None, 15),
    (TENANT_2, "Cobalt Analytics", False, 9),
]


def set_consent(subject_id, consented):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO consent_status (subject_id, consented) VALUES (%s, %s)",
                (subject_id, consented),
            )
        conn.commit()
    finally:
        conn.close()


def seed_audit_history():
    tenant_id, name, consented, doc_count, delete_count = AUDIT_HISTORY_SUBJECT

    subject_id = insert_subject(name, tenant_id)
    set_consent(subject_id, consented)

    document_ids = [
        insert_document(subject_id, tenant_id, record["content"], record["embedding"])
        for record in generate_corpus(doc_count)
    ]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deletion_requests (subject_id, status) VALUES (%s, 'completed') RETURNING id",
                (subject_id,),
            )
            deletion_request_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    for document_id in document_ids[:delete_count]:
        hard_delete(document_id, tenant_id, deletion_request_id)

    print(
        f"Seeded '{name}': {doc_count} documents, {delete_count} already erased "
        f"(real signed, chained audit history)"
    )


def seed():
    for tenant_id, name, consented, doc_count in DEMO_SUBJECTS:
        subject_id = insert_subject(name, tenant_id)

        if consented is not None:
            set_consent(subject_id, consented)

        for record in generate_corpus(doc_count):
            insert_document(subject_id, tenant_id, record["content"], record["embedding"])

        print(f"Seeded '{name}': {doc_count} documents, consent={consented}")

    seed_audit_history()


if __name__ == "__main__":
    seed()
