from src.db.db import insert_subject, insert_document, get_connection
from src.eval.generate_corpus import generate_corpus

TENANT_1 = "00000000-0000-0000-0000-000000000001"
TENANT_2 = "00000000-0000-0000-0000-000000000002"

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


def seed():
    for tenant_id, name, consented, doc_count in DEMO_SUBJECTS:
        subject_id = insert_subject(name, tenant_id)

        if consented is not None:
            set_consent(subject_id, consented)

        for record in generate_corpus(doc_count):
            insert_document(subject_id, tenant_id, record["content"], record["embedding"])

        print(f"Seeded '{name}': {doc_count} documents, consent={consented}")


if __name__ == "__main__":
    seed()
