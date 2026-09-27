import csv
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.db.db import get_connection, insert_subject, insert_document
from src.eval.generate_corpus import generate_corpus
from src.eval.search import similarity_search
from src.logic.hard_delete import hard_delete, TENANT_CONFIG
from src.logic.erase_subject import erase_subject

CSV_PATH = Path("docs/benchmark_results.csv")
PLOTS_DIR = Path("docs/benchmark_plots")
CSV_COLUMNS = ["run_timestamp", "metric", "value", "unit", "corpus_size", "k", "notes"]

BENCHMARK_TENANT = "00000000-0000-0000-0000-000000000001"
CORPUS_SIZES = [100, 500, 1000, 5000]
ERASURE_BATCH_SIZE = 50
NUM_QUERY_VECTORS = 20
TOP_K = 10
RECALL_DELETE_BATCH_SIZE = 20


def log_row(rows, metric, value, unit, corpus_size=None, k=None, notes=""):
    rows.append(
        {
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "metric": metric,
            "value": value,
            "unit": unit,
            "corpus_size": corpus_size,
            "k": k,
            "notes": notes,
        }
    )


def append_csv(rows):
    file_exists = CSV_PATH.exists()
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def current_corpus_size(tenant_id):
    partition = TENANT_CONFIG[tenant_id]["partition"]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {partition}")
            return cur.fetchone()[0]
    finally:
        conn.close()


def ensure_benchmark_setup():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM data_subjects WHERE display_name = %s AND tenant_id = %s",
                ("Benchmark Subject", BENCHMARK_TENANT),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    subject_id = row[0] if row else insert_subject("Benchmark Subject", BENCHMARK_TENANT)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deletion_requests (subject_id) VALUES (%s) RETURNING id",
                (subject_id,),
            )
            deletion_request_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    return subject_id, deletion_request_id


def reset_benchmark_corpus(subject_id, tenant_id):
    partition = TENANT_CONFIG[tenant_id]["partition"]
    hnsw_index = TENANT_CONFIG[tenant_id]["hnsw_index"]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {partition} WHERE subject_id = %s", (subject_id,))
            cur.execute(f"REINDEX INDEX {hnsw_index}")
        conn.commit()
    finally:
        conn.close()


def grow_corpus_to(subject_id, tenant_id, target_size):
    to_add = target_size - current_corpus_size(tenant_id)
    if to_add <= 0:
        return

    for record in generate_corpus(to_add):
        insert_document(subject_id, tenant_id, record["content"], record["embedding"])


def measure_deletion_latency(subject_id, tenant_id, deletion_request_id, rows):
    record = generate_corpus(1)[0]
    document_id = insert_document(subject_id, tenant_id, record["content"], record["embedding"])

    start = time.perf_counter()
    hard_delete(document_id, tenant_id, deletion_request_id)
    elapsed_ms = (time.perf_counter() - start) * 1000

    log_row(rows, "hard_delete_latency", elapsed_ms, "ms", corpus_size=current_corpus_size(tenant_id))


def measure_erasure_latency(tenant_id, num_documents, rows):
    subject_id = insert_subject("Erasure Latency Subject", tenant_id)

    for record in generate_corpus(num_documents):
        insert_document(subject_id, tenant_id, record["content"], record["embedding"])

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deletion_requests (subject_id) VALUES (%s) RETURNING id",
                (subject_id,),
            )
            deletion_request_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    start = time.perf_counter()
    erase_subject(subject_id, deletion_request_id)
    elapsed_ms = (time.perf_counter() - start) * 1000

    log_row(
        rows,
        "cascading_erasure_latency",
        elapsed_ms,
        "ms",
        corpus_size=num_documents,
        notes=f"documents_deleted={num_documents}",
    )


def measure_index_rebuild_cost(subject_id, tenant_id, rows):
    hnsw_index = TENANT_CONFIG[tenant_id]["hnsw_index"]

    for size in CORPUS_SIZES:
        grow_corpus_to(subject_id, tenant_id, size)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                start = time.perf_counter()
                cur.execute(f"REINDEX INDEX {hnsw_index}")
                elapsed_ms = (time.perf_counter() - start) * 1000
            conn.commit()
        finally:
            conn.close()

        log_row(rows, "index_rebuild_cost", elapsed_ms, "ms", corpus_size=size)


def measure_recall_at_k(tenant_id, deletion_request_id, rows):
    partition = TENANT_CONFIG[tenant_id]["partition"]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, embedding FROM {partition} ORDER BY random() LIMIT %s",
                (NUM_QUERY_VECTORS,),
            )
            queries = [(row[0], row[1].to_list()) for row in cur.fetchall()]
    finally:
        conn.close()

    query_ids = {qid for qid, _ in queries}

    before_results = {
        qid: [r["id"] for r in similarity_search(tenant_id, embedding, TOP_K, exclude_id=qid)]
        for qid, embedding in queries
    }

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id FROM {partition}
                WHERE id NOT IN %s
                ORDER BY random()
                LIMIT %s
                """,
                (tuple(query_ids), RECALL_DELETE_BATCH_SIZE),
            )
            to_delete = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    for document_id in to_delete:
        hard_delete(document_id, tenant_id, deletion_request_id)

    after_results = {
        qid: [r["id"] for r in similarity_search(tenant_id, embedding, TOP_K, exclude_id=qid)]
        for qid, embedding in queries
    }

    overlaps = [
        len(set(before_results[qid]) & set(after_results[qid])) / TOP_K
        for qid in query_ids
    ]
    avg_recall = statistics.mean(overlaps)

    log_row(
        rows,
        "recall_at_k",
        avg_recall,
        "fraction",
        corpus_size=current_corpus_size(tenant_id),
        k=TOP_K,
        notes=f"num_queries={NUM_QUERY_VECTORS}, num_deleted={len(to_delete)}",
    )


def plot_results():
    df = pd.read_csv(CSV_PATH)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    rebuild = df[df["metric"] == "index_rebuild_cost"]
    if not rebuild.empty:
        plt.figure()
        plt.plot(rebuild["corpus_size"], rebuild["value"], marker="o")
        plt.xlabel("Corpus size (documents)")
        plt.ylabel("Index rebuild time (ms)")
        plt.title("HNSW index rebuild cost vs corpus size")
        plt.savefig(PLOTS_DIR / f"index_rebuild_cost_{run_stamp}.png")
        plt.close()

    recall = df[df["metric"] == "recall_at_k"]
    if not recall.empty:
        plt.figure()
        plt.plot(range(len(recall)), recall["value"], marker="o")
        plt.xlabel("Benchmark run")
        plt.ylabel(f"Recall@{TOP_K} overlap (fraction)")
        plt.title("Recall@k before vs after deletion, across runs")
        plt.ylim(0, 1.05)
        plt.savefig(PLOTS_DIR / f"recall_at_k_{run_stamp}.png")
        plt.close()

    latency = df[df["metric"].isin(["hard_delete_latency", "cascading_erasure_latency"])]
    if not latency.empty:
        plt.figure()
        for metric, group in latency.groupby("metric"):
            plt.plot(range(len(group)), group["value"], marker="o", label=metric)
        plt.xlabel("Benchmark run")
        plt.ylabel("Latency (ms)")
        plt.title("Deletion latency across runs")
        plt.legend()
        plt.savefig(PLOTS_DIR / f"deletion_latency_{run_stamp}.png")
        plt.close()


def main():
    rows = []

    try:
        print("Setting up benchmark subject and deletion request...")
        subject_id, deletion_request_id = ensure_benchmark_setup()

        print("Resetting benchmark corpus to a clean, empty state...")
        reset_benchmark_corpus(subject_id, BENCHMARK_TENANT)

        print("Measuring single hard-delete latency...")
        measure_deletion_latency(subject_id, BENCHMARK_TENANT, deletion_request_id, rows)

        print(f"Measuring cascading erasure latency ({ERASURE_BATCH_SIZE} documents)...")
        measure_erasure_latency(BENCHMARK_TENANT, ERASURE_BATCH_SIZE, rows)

        print(f"Measuring index rebuild cost across corpus sizes {CORPUS_SIZES}...")
        measure_index_rebuild_cost(subject_id, BENCHMARK_TENANT, rows)

        print("Measuring recall@k before/after deletion...")
        measure_recall_at_k(BENCHMARK_TENANT, deletion_request_id, rows)

    finally:
        if rows:
            append_csv(rows)
            print(f"Appended {len(rows)} rows to {CSV_PATH}")

    plot_results()
    print(f"Saved plots to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
