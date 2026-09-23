from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from src.db.db import get_connection
from datetime import datetime, timezone

PRIVATE_KEY_FILE = Path("keys/private_key.pem")

def load_private_key():
    with open(PRIVATE_KEY_FILE, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
        )

    return private_key

def hash_content(content):
    content_bytes = content.encode("utf-8")

    digest = hashes.Hash(hashes.SHA256())
    digest.update(content_bytes)

    return digest.finalize().hex()


GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

def get_previous_hash():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT deleted_hash
                FROM deletion_audit_log
                ORDER BY signed_at DESC
                LIMIT 1;
                """
            )
            result = cur.fetchone()

            if result is None:
                return GENESIS_HASH
            return result[0]

    finally:
        conn.close()

def build_message(document_id, content_hash, signed_at, previous_hash):
    message = (
        f"{document_id}, "
        f"{content_hash}, "
        f"{signed_at}, "
        f"{previous_hash}"
    )

    return message.encode("utf-8")

def sign_message(message, private_key):
    signature = private_key.sign(
        message,
        ec.ECDSA(hashes.SHA256())
    )

    return signature.hex()

def get_current_timestamp():
    return datetime.now(timezone.utc)


def sign_deletion(content, document_id):
    content_hash = hash_content(content)
    previous_hash = get_previous_hash()
    signed_at = get_current_timestamp()

    message = build_message(
        document_id,
        content_hash,
        signed_at,
        previous_hash,
    )

    private_key = load_private_key()
    signature = sign_message(message, private_key)

    return {
        "content_hash": content_hash,
        "signature": signature,
        "signed_at": signed_at,
        "previous_hash": previous_hash,
    }

def save_audit_log(
    conn,
    deletion_request_id,
    document_id,
    signing_data,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO deletion_audit_log (
                deletion_request_id,
                document_id,
                deleted_hash,
                signature,
                signed_at,
                previous_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (
                deletion_request_id,
                document_id,
                signing_data["content_hash"],
                signing_data["signature"],
                signing_data["signed_at"],
                signing_data["previous_hash"],
            ),
        )
