import os

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

load_dotenv()


def get_connection():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

    register_vector(conn)
    return conn


def insert_subject(display_name, tenant_id):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_subjects (display_name, tenant_id)
                VALUES (%s, %s)
                RETURNING id;
                """,
                (display_name, tenant_id),
            )

            subject_id = cur.fetchone()[0]

        conn.commit()
        return subject_id

    finally:
        conn.close()


def insert_document(subject_id, tenant_id, content, embedding):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents
                    (subject_id, tenant_id, content, embedding)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (subject_id, tenant_id, content, embedding),
            )

            document_id = cur.fetchone()[0]

        conn.commit()
        return document_id

    finally:
        conn.close()


def get_document(document_id, tenant_id):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, subject_id, tenant_id, content,
                       embedding, created_at, deleted
                FROM documents
                WHERE id = %s
                  AND tenant_id = %s;
                """,
                (document_id, tenant_id),
            )

            return cur.fetchone()

    finally:
        conn.close()
