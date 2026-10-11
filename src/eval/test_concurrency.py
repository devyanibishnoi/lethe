"""The one claim this whole investigation kept asserting but never measured:
that VACUUM FULL "blocks concurrent access" while the current hard_delete()
design doesn't. A quick isolated check found that assumption is WRONG,
plain REINDEX INDEX (not CONCURRENTLY) also blocks concurrent reads for its
full duration, same signature as VACUUM FULL. This runs the full,
repeated, both-windows version of that check.

A background thread runs a continuous loop of real similarity_search()
calls (the same function the live /search endpoint uses) against the
tenant partition while a deletion runs on the main thread, for both
designs. Two windows are measured per trial:
  - "pipeline window": the full user-facing deletion call (signing, audit
    log write, DELETE, index/vacuum work), what a real caller experiences.
  - "lock window": just the REINDEX/VACUUM statements themselves, isolating
    the actual lock-holding mechanism from the non-blocking setup work
    around it.

Each query records its own start and end time, so a query that started
before the lock window and only completed after it (the signature of
actually being blocked, not just slow) is attributed correctly.
"""

import threading
import time

from src.db.db import get_connection, insert_subject, insert_document, get_document
from src.eval.generate_corpus import generate_corpus
from src.eval.search import similarity_search
from src.eval.run_benchmarks import (
    ensure_benchmark_setup,
    grow_corpus_to,
    BENCHMARK_TENANT,
    log_row,
    append_csv,
    CSV_PATH,
)
from src.logic.hard_delete import TENANT_CONFIG
from src.logic.sign_deletion import sign_deletion, save_audit_log

CORPUS_SIZE_FOR_TEST = 5000
NUM_REPEATS = 5


def query_loop(stop_event, results, query_embedding):
    while not stop_event.is_set():
        start = time.perf_counter()
        start_wall = time.time()
        try:
            similarity_search(BENCHMARK_TENANT, query_embedding, 10)
        except Exception:
            pass
        end_wall = time.time()
        latency_ms = (time.perf_counter() - start) * 1000
        results.append({"start": start_wall, "end": end_wall, "latency_ms": latency_ms})


def current_design_deletion(document_id, tenant_id, deletion_request_id, windows):
    """Same steps as the fixed hard_delete(), instrumented to record the
    lock-window timestamps separately from the full pipeline.
    """
    config = TENANT_CONFIG[tenant_id]
    partition = config["partition"]
    hnsw_index = config["hnsw_index"]
    ivfflat_index = config["ivfflat_index"]

    conn = get_connection()
    try:
        document = get_document(document_id, tenant_id)
        signing_data = sign_deletion(document[3], document_id)
        save_audit_log(conn, deletion_request_id, document_id, signing_data)

        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {partition} WHERE id = %s AND tenant_id = %s",
                (document_id, tenant_id),
            )
        conn.commit()

        conn.autocommit = True
        windows["lock_start"] = time.time()
        with conn.cursor() as cur:
            cur.execute(f"REINDEX INDEX {hnsw_index}")
            cur.execute(f"REINDEX INDEX {ivfflat_index}")
            cur.execute(f"VACUUM {partition}")
        windows["lock_end"] = time.time()
    finally:
        conn.close()


def vacuum_full_deletion(document_id, tenant_id, deletion_request_id, windows):
    config = TENANT_CONFIG[tenant_id]
    partition = config["partition"]

    conn = get_connection()
    try:
        document = get_document(document_id, tenant_id)
        signing_data = sign_deletion(document[3], document_id)
        save_audit_log(conn, deletion_request_id, document_id, signing_data)

        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {partition} WHERE id = %s AND tenant_id = %s",
                (document_id, tenant_id),
            )
        conn.commit()

        conn.autocommit = True
        windows["lock_start"] = time.time()
        with conn.cursor() as cur:
            cur.execute(f"VACUUM FULL {partition}")
        windows["lock_end"] = time.time()
    finally:
        conn.close()


def run_one_trial(deletion_fn, query_embedding):
    stop_event = threading.Event()
    results = []
    thread = threading.Thread(target=query_loop, args=(stop_event, results, query_embedding))
    thread.start()

    time.sleep(0.3)

    windows = {}
    pipeline_start = time.time()
    deletion_fn(windows)
    pipeline_end = time.time()

    time.sleep(0.3)
    stop_event.set()
    thread.join()

    return pipeline_start, pipeline_end, windows, results


def summarize_window(window_start, window_end, results):
    overlapping = [r for r in results if r["start"] < window_end and r["end"] > window_start]
    before = [r for r in results if r["end"] <= window_start]
    baseline_latency_ms = (sum(r["latency_ms"] for r in before) / len(before)) if before else 0
    max_overlap_latency = max((r["latency_ms"] for r in overlapping), default=0)
    return {
        "window_duration_ms": (window_end - window_start) * 1000,
        "num_overlapping": len(overlapping),
        "max_overlap_latency_ms": max_overlap_latency,
        "baseline_latency_ms": baseline_latency_ms,
        "blocked_evidence": max_overlap_latency > baseline_latency_ms * 3 if baseline_latency_ms else max_overlap_latency > 0,
    }


def run_design(label, deletion_fn, subject_id, tenant_id, query_embedding):
    print(f"\n=== {label} ===")
    trial_results = []
    for trial in range(1, NUM_REPEATS + 1):
        record = generate_corpus(1)[0]
        doc_id = insert_document(subject_id, tenant_id, record["content"], record["embedding"])

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO deletion_requests (subject_id, status) VALUES (%s, 'completed') RETURNING id",
            (subject_id,),
        )
        req_id = cur.fetchone()[0]
        conn.commit()
        conn.close()

        def bound_fn(windows, doc_id=doc_id, req_id=req_id):
            deletion_fn(doc_id, tenant_id, req_id, windows)

        pipeline_start, pipeline_end, windows, results = run_one_trial(bound_fn, query_embedding)

        pipeline_summary = summarize_window(pipeline_start, pipeline_end, results)
        lock_summary = summarize_window(windows["lock_start"], windows["lock_end"], results)

        trial_results.append({"pipeline": pipeline_summary, "lock": lock_summary})
        print(
            f"  trial {trial}/{NUM_REPEATS}: "
            f"lock_duration={lock_summary['window_duration_ms']:.1f}ms, "
            f"baseline_query={lock_summary['baseline_latency_ms']:.1f}ms, "
            f"queries_overlapping_lock={lock_summary['num_overlapping']}, "
            f"max_overlapping_latency={lock_summary['max_overlap_latency_ms']:.1f}ms, "
            f"blocked_evidence={lock_summary['blocked_evidence']}"
        )

    return trial_results


def main():
    subject_id, _ = ensure_benchmark_setup()
    print(f"Growing corpus to {CORPUS_SIZE_FOR_TEST} docs for a meaningful test window...")
    grow_corpus_to(subject_id, BENCHMARK_TENANT, CORPUS_SIZE_FOR_TEST)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT embedding FROM documents_tenant_1 LIMIT 1")
    query_embedding = cur.fetchone()[0].to_list()
    conn.close()

    current_results = run_design(
        "Current design (REINDEX x2 + VACUUM, post-commit) -- lock window only",
        current_design_deletion,
        subject_id,
        BENCHMARK_TENANT,
        query_embedding,
    )

    vacuum_full_results = run_design(
        "DELETE + VACUUM FULL -- lock window only",
        vacuum_full_deletion,
        subject_id,
        BENCHMARK_TENANT,
        query_embedding,
    )

    print("\n=== Summary (lock window only, the mechanistic comparison) ===")
    rows = []
    for label, trial_results, metric_prefix in [
        ("Current design", current_results, "concurrency_lock_current_design"),
        ("VACUUM FULL", vacuum_full_results, "concurrency_lock_vacuum_full"),
    ]:
        locks = [t["lock"] for t in trial_results]
        blocked_trials = sum(1 for l in locks if l["blocked_evidence"])
        avg_duration = sum(l["window_duration_ms"] for l in locks) / len(locks)
        avg_overlapping = sum(l["num_overlapping"] for l in locks) / len(locks)
        max_latency = max(l["max_overlap_latency_ms"] for l in locks)
        print(
            f"{label}: {blocked_trials}/{len(locks)} trials show blocking evidence, "
            f"avg lock duration {avg_duration:.1f}ms, "
            f"avg {avg_overlapping:.1f} queries overlapped the lock window, "
            f"worst overlapping query latency {max_latency:.1f}ms"
        )
        for i, l in enumerate(locks, start=1):
            log_row(
                rows,
                f"{metric_prefix}_max_overlapping_query_latency",
                l["max_overlap_latency_ms"],
                "ms",
                corpus_size=CORPUS_SIZE_FOR_TEST,
                notes=(
                    f"trial={i}/{NUM_REPEATS}, lock_window_duration_ms={l['window_duration_ms']:.1f}, "
                    f"baseline_query_ms={l['baseline_latency_ms']:.1f}, "
                    f"queries_overlapping_lock_window={l['num_overlapping']}, "
                    f"blocked_evidence={l['blocked_evidence']}, "
                    f"real concurrent similarity_search() query loop, window measured around only the REINDEX/VACUUM statements, not the full pipeline"
                ),
            )

    append_csv(rows)
    print(f"\nAppended {len(rows)} rows to {CSV_PATH}")


if __name__ == "__main__":
    main()
