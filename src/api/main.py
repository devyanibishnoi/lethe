import csv

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.db.db import get_connection
from src.eval.generate_corpus import get_model
from src.eval.search import similarity_search
from src.eval.run_benchmarks import CSV_PATH
from src.logic.hard_delete import TENANT_CONFIG
from src.logic.erase_subject import erase_subject
from src.logic.verify_deletion import verify_deletion, verify_chain
from src.logic.deletion_certificate import get_deletion_certificate

app = FastAPI(title="Lethe Compliance Dashboard API")


class SearchRequest(BaseModel):
    tenant_id: str
    query_text: str
    k: int = 10


class DeletionRequestCreate(BaseModel):
    subject_id: str


@app.get("/subjects")
def list_subjects():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ds.id,
                    ds.display_name,
                    ds.tenant_id,
                    cs.consented,
                    count(d.id) AS document_count
                FROM data_subjects ds
                LEFT JOIN consent_status cs ON cs.subject_id = ds.id
                LEFT JOIN documents d ON d.subject_id = ds.id
                GROUP BY ds.id, ds.display_name, ds.tenant_id, cs.consented
                ORDER BY ds.tenant_id, ds.display_name;
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "subject_id": row[0],
            "display_name": row[1],
            "tenant_id": row[2],
            "consented": row[3],
            "document_count": row[4],
        }
        for row in rows
    ]


@app.post("/search")
def search(request: SearchRequest):
    if request.tenant_id not in TENANT_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown tenant ID: {request.tenant_id}")

    model = get_model()
    query_embedding = model.encode(request.query_text).tolist()

    return similarity_search(request.tenant_id, query_embedding, request.k)


@app.post("/deletion-requests")
def create_deletion_request(request: DeletionRequestCreate):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO deletion_requests (subject_id)
                VALUES (%s)
                RETURNING id, requested_at, due_at, status;
                """,
                (request.subject_id,),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    return {
        "deletion_request_id": row[0],
        "requested_at": row[1],
        "due_at": row[2],
        "status": row[3],
    }


@app.post("/deletion-requests/{request_id}/process")
def process_deletion_request(request_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT subject_id, status FROM deletion_requests WHERE id = %s;",
                (request_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")

    subject_id, status = row
    if status != "pending":
        raise HTTPException(status_code=400, detail=f"Deletion request is already '{status}'")

    erase_subject(subject_id, request_id)

    return {"deletion_request_id": request_id, "status": "completed"}


@app.get("/audit-log")
def list_audit_log():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, deletion_request_id, document_id,
                       deleted_hash, previous_hash, signature, signed_at
                FROM deletion_audit_log
                ORDER BY signed_at DESC;
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "deletion_request_id": row[1],
            "document_id": row[2],
            "deleted_hash": row[3],
            "previous_hash": row[4],
            "signature": row[5],
            "signed_at": row[6],
        }
        for row in rows
    ]


@app.get("/audit-log/{entry_id}/verify")
def verify_audit_entry(entry_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_id, deleted_hash, signed_at, previous_hash, signature
                FROM deletion_audit_log
                WHERE id = %s;
                """,
                (entry_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Audit log entry not found")

    document_id, deleted_hash, signed_at, previous_hash, signature = row
    valid = verify_deletion(document_id, deleted_hash, signed_at, previous_hash, signature)

    return {"entry_id": entry_id, "valid": valid}


@app.get("/audit-log/verify-chain")
def verify_audit_chain():
    return {"valid": verify_chain()}


@app.post("/audit-log/{entry_id}/corrupt-for-demo")
def corrupt_audit_entry_for_demo(entry_id: str):
    """Demo-only: mutates one stored hash so the audit trail page can show
    verification failing live. Never call this outside a demo/dev session."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE deletion_audit_log
                SET deleted_hash = substring(deleted_hash from 2) || '0'
                WHERE id = %s
                RETURNING id;
                """,
                (entry_id,),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Audit log entry not found")

    return {"entry_id": entry_id, "corrupted": True}


@app.get("/deletion-requests/{request_id}/certificate")
def deletion_certificate(request_id: str):
    try:
        return get_deletion_certificate(request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/benchmarks")
def benchmarks():
    if not CSV_PATH.exists():
        return []

    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))
