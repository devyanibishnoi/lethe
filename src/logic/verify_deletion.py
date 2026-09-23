from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from src.db.db import get_connection

PUBLIC_KEY_FILE = Path("keys/public_key.pem")

def load_public_key():
    with open(PUBLIC_KEY_FILE, "rb") as key_file:
        public_key = serialization.load_pem_public_key(
            key_file.read()
        )

    return public_key

def verify_signature(message, signature, public_key):
    try:
        public_key.verify(
            bytes.fromhex(signature),
            message,
            ec.ECDSA(hashes.SHA256())
        )

        return True

    except Exception:
        return False

def verify_deletion(
    document_id,
    content_hash,
    signed_at,
    previous_hash,
    signature,
):
    message = (
        f"{document_id}, "
        f"{content_hash}, "
        f"{signed_at}, "
        f"{previous_hash}"
    ).encode("utf-8")

    public_key = load_public_key()

    return verify_signature(
        message,
        signature,
        public_key,
    )

def verify_chain():
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
                ORDER BY signed_at ASC;
                """
            )
            rows = cur.fetchall()

        expected_previous_hash = (
            "0000000000000000000000000000000000000000000000000000000000000000"
        )

        for row in rows:
            document_id, content_hash, signed_at, previous_hash, signature = row
            if previous_hash != expected_previous_hash:
                return False
            if not verify_deletion(
                document_id,
                content_hash,
                signed_at,
                previous_hash,
                signature,
            ):
                return False

            expected_previous_hash = content_hash
        return True

    finally:
        conn.close()