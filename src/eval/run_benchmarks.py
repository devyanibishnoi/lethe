import csv
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.db.db import get_connection, insert_subject, insert_document, get_document
from src.eval.generate_corpus import generate_corpus
from src.eval.search import similarity_search
from src.logic.hard_delete import hard_delete, TENANT_CONFIG
from src.logic.erase_subject import erase_subject
from src.logic.sign_deletion import sign_deletion, save_audit_log

CSV_PATH = Path("docs/benchmark_results.csv")
PLOTS_DIR = Path("docs/benchmark_plots")
CSV_COLUMNS = ["run_timestamp", "metric", "value", "unit", "corpus_size", "k", "notes"]

BENCHMARK_TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "00000000-0000-0000-0000-000000000002"
CORPUS_SIZES = [100, 500, 1000, 5000]
ERASURE_BATCH_SIZE = 50
NUM_QUERY_VECTORS = 20
TOP_K = 10
RECALL_DELETE_BATCH_SIZE = 20

UNPARTITIONED_TABLE = "documents_unpartitioned_benchmark"
UNPARTITIONED_INDEX = "documents_unpartitioned_benchmark_hnsw_idx"

TESTED_TENANT_SIZE = 500
SCALING_CONFIGS = {
    2: [1500],
    4: [300, 900, 1800],
    8: [200, 400, 600, 800, 1000, 1200, 1400],
    16: [100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300],
}


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


NUM_VACUUM_FULL_REPEATS = 20


def measure_vacuum_full_cost(subject_id, tenant_id, rows):
    """Self-review ask: VACUUM FULL rewrites the whole table and rebuilds
    every index on it in the process, so "DELETE + VACUUM FULL" is a
    plausible alternative to hard_delete()'s current "DELETE + REINDEX
    (both indexes) + plain VACUUM", and it closes the heap-level byte gap
    the storage-erasure test found. Times it at the same corpus sizes as
    measure_index_rebuild_cost for a direct, real tradeoff table, instead of
    just asserting the lock cost grows with size.

    Repeated NUM_VACUUM_FULL_REPEATS times per size, not just once: VACUUM
    FULL doesn't change the row count (it rewrites the same live rows into
    a new file), so repeating it on the same corpus is valid and doesn't
    need regrowing between repeats, cheap enough to get a real range
    instead of a single-run number.
    """
    partition = TENANT_CONFIG[tenant_id]["partition"]

    for size in CORPUS_SIZES:
        grow_corpus_to(subject_id, tenant_id, size)

        for repeat in range(1, NUM_VACUUM_FULL_REPEATS + 1):
            conn = get_connection()
            conn.commit()
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    start = time.perf_counter()
                    cur.execute(f"VACUUM FULL {partition}")
                    elapsed_ms = (time.perf_counter() - start) * 1000
            finally:
                conn.close()

            log_row(
                rows,
                "vacuum_full_cost",
                elapsed_ms,
                "ms",
                corpus_size=size,
                notes=f"repeat={repeat}/{NUM_VACUUM_FULL_REPEATS}, full table rewrite + implicit rebuild of all indexes on the partition; compare against index_rebuild_cost at the same corpus_size (HNSW-only, non-blocking) to see the tradeoff",
            )


NUM_PATH_COMPARISON_REPEATS = 3


def _delete_vacuum_full_path(document_id, tenant_id, deletion_request_id):
    """Alternative design to hard_delete(): DELETE + VACUUM FULL instead of
    DELETE + REINDEX (both indexes) + plain VACUUM. Same signing/audit-log
    behavior as hard_delete(), so the timing comparison is apples-to-apples
    end to end, not just "how fast is a bare DELETE".
    """
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
        with conn.cursor() as cur:
            cur.execute(f"VACUUM FULL {partition}")
    finally:
        conn.close()


def measure_deletion_path_comparison(subject_id, tenant_id, deletion_request_id, rows):
    """Self-review ask: time the current deletion path end to end against
    the alternative (DELETE + VACUUM FULL) at equal corpus sizes, not just
    the index-rebuild or vacuum pieces in isolation, to actually inform
    which design to ship. Repeated NUM_PATH_COMPARISON_REPEATS times per
    size for a range, not a single-run number.
    """
    for size in CORPUS_SIZES:
        grow_corpus_to(subject_id, tenant_id, size)

        for repeat in range(1, NUM_PATH_COMPARISON_REPEATS + 1):
            record = generate_corpus(1)[0]
            doc_id = insert_document(subject_id, tenant_id, record["content"], record["embedding"])
            start = time.perf_counter()
            hard_delete(doc_id, tenant_id, deletion_request_id)
            elapsed_ms = (time.perf_counter() - start) * 1000
            log_row(
                rows, "deletion_path_current", elapsed_ms, "ms", corpus_size=size,
                notes=f"repeat={repeat}/{NUM_PATH_COMPARISON_REPEATS}, DELETE + REINDEX(HNSW) + REINDEX(ivfflat) + plain VACUUM, the current hard_delete() design",
            )
            grow_corpus_to(subject_id, tenant_id, size)

            record = generate_corpus(1)[0]
            doc_id = insert_document(subject_id, tenant_id, record["content"], record["embedding"])
            start = time.perf_counter()
            _delete_vacuum_full_path(doc_id, tenant_id, deletion_request_id)
            elapsed_ms = (time.perf_counter() - start) * 1000
            log_row(
                rows, "deletion_path_vacuum_full", elapsed_ms, "ms", corpus_size=size,
                notes=f"repeat={repeat}/{NUM_PATH_COMPARISON_REPEATS}, DELETE + VACUUM FULL, the alternative design that also closes the heap-level gap",
            )
            grow_corpus_to(subject_id, tenant_id, size)


def setup_unpartitioned_benchmark_table():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {UNPARTITIONED_TABLE}")
            cur.execute(
                f"""
                CREATE TABLE {UNPARTITIONED_TABLE} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
                    tenant_id UUID NOT NULL,
                    embedding VECTOR (384) NOT NULL
                )
                """
            )
            cur.execute(
                f"CREATE INDEX {UNPARTITIONED_INDEX} ON {UNPARTITIONED_TABLE} "
                f"USING hnsw (embedding vector_cosine_ops)"
            )
        conn.commit()
    finally:
        conn.close()


def measure_unpartitioned_rebuild_cost(rows):
    """Comparison baseline for measure_index_rebuild_cost: one HNSW index
    spanning both tenants' data combined, instead of a separate per-tenant
    partitioned index. At total size 2*N (both tenants at N each), this
    rebuilds everyone's data to process a single tenant's deletion, the
    cost the partitioned design avoids.
    """
    setup_unpartitioned_benchmark_table()

    for size in CORPUS_SIZES:
        total_size = size * 2
        records = generate_corpus(total_size)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for i, record in enumerate(records):
                    tenant = BENCHMARK_TENANT if i % 2 == 0 else OTHER_TENANT
                    cur.execute(
                        f"INSERT INTO {UNPARTITIONED_TABLE} (tenant_id, embedding) VALUES (%s, %s)",
                        (tenant, record["embedding"]),
                    )
            conn.commit()
        finally:
            conn.close()

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                start = time.perf_counter()
                cur.execute(f"REINDEX INDEX {UNPARTITIONED_INDEX}")
                elapsed_ms = (time.perf_counter() - start) * 1000
            conn.commit()
        finally:
            conn.close()

        log_row(
            rows,
            "unpartitioned_index_rebuild_cost",
            elapsed_ms,
            "ms",
            corpus_size=total_size,
            notes=(
                f"single combined HNSW index over both tenants, "
                f"{size} docs/tenant; compare against index_rebuild_cost "
                f"corpus_size={size} (the partitioned rebuild for the same "
                f"per-tenant volume)"
            ),
        )

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE {UNPARTITIONED_TABLE}")
            conn.commit()
        finally:
            conn.close()


def _make_scaling_table(name):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
            cur.execute(
                f"""
                CREATE TABLE {name} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
                    tenant_no INT NOT NULL,
                    embedding VECTOR (384) NOT NULL
                )
                """
            )
            cur.execute(f"CREATE INDEX {name}_hnsw_idx ON {name} USING hnsw (embedding vector_cosine_ops)")
        conn.commit()
    finally:
        conn.close()


def _fill_table(name, tenant_no, count):
    records = generate_corpus(count)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for record in records:
                cur.execute(
                    f"INSERT INTO {name} (tenant_no, embedding) VALUES (%s, %s)",
                    (tenant_no, record["embedding"]),
                )
        conn.commit()
    finally:
        conn.close()


def _reindex_cost(index_name):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            start = time.perf_counter()
            cur.execute(f"REINDEX INDEX {index_name}")
            elapsed_ms = (time.perf_counter() - start) * 1000
        conn.commit()
    finally:
        conn.close()
    return elapsed_ms


NUM_SCALING_REPEATS = 3


def measure_tenant_scaling(rows):
    """Self-review ask: the earlier partitioned-vs-unpartitioned comparison
    only used 2 equal-sized tenants, so the 2x gap was just "twice the rows."
    This repeats it at 2, 4, 8, and 16 tenants with deliberately uneven
    sizes, holding one "tenant under test" fixed at 500 docs throughout, to
    show the partitioned cost for that tenant stays flat no matter how many
    other tenants exist or how large they are, while an unpartitioned
    design's cost keeps climbing with total system size.

    Both "partitioned" and "unpartitioned" tables here are disposable
    standalone tables, not real partitions of the documents table, they
    stand in for what a partitioned vs. unpartitioned schema would cost;
    the "partitioned" line is flat by construction, since it is the same
    500-doc table being rebuilt each time regardless of config, the point of
    the experiment is showing the *unpartitioned* line's cost growing
    against that fixed baseline as total system size grows.

    Each config is repeated NUM_SCALING_REPEATS times and logs every
    individual run (not just a mean), so the CSV supports reporting a range,
    not a single number that hides run-to-run noise.
    """
    for num_tenants, other_sizes in SCALING_CONFIGS.items():
        total_size = TESTED_TENANT_SIZE + sum(other_sizes)

        for repeat in range(1, NUM_SCALING_REPEATS + 1):
            tested_table = "documents_scaling_tested"
            _make_scaling_table(tested_table)
            _fill_table(tested_table, 0, TESTED_TENANT_SIZE)

            combined_table = "documents_scaling_combined"
            _make_scaling_table(combined_table)
            _fill_table(combined_table, 0, TESTED_TENANT_SIZE)
            for i, size in enumerate(other_sizes, start=1):
                _fill_table(combined_table, i, size)

            partitioned_ms = _reindex_cost(f"{tested_table}_hnsw_idx")
            unpartitioned_ms = _reindex_cost(f"{combined_table}_hnsw_idx")

            log_row(
                rows,
                "partitioned_rebuild_at_scale",
                partitioned_ms,
                "ms",
                corpus_size=TESTED_TENANT_SIZE,
                notes=f"num_tenants={num_tenants}, total_system_size={total_size}, repeat={repeat}/{NUM_SCALING_REPEATS}, rebuilding only the 500-doc tenant under test (a standalone table standing in for a partition, not a real partition of documents)",
            )
            log_row(
                rows,
                "unpartitioned_rebuild_at_scale",
                unpartitioned_ms,
                "ms",
                corpus_size=total_size,
                notes=f"num_tenants={num_tenants}, repeat={repeat}/{NUM_SCALING_REPEATS}, one combined index over all tenants' {total_size} docs, uneven sizes",
            )

            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP TABLE IF EXISTS {tested_table}")
                    cur.execute(f"DROP TABLE IF EXISTS {combined_table}")
                conn.commit()
            finally:
                conn.close()


def measure_recall_vs_exact(tenant_id, rows):
    partition = TENANT_CONFIG[tenant_id]["partition"]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, embedding FROM {partition} ORDER BY random() LIMIT %s",
                (NUM_QUERY_VECTORS,),
            )
            queries = [(row[0], row[1].to_list()) for row in cur.fetchall()]

            # Which index the planner actually picks for a live query, logged
            # for transparency since pgvector doesn't let us pin one by hint.
            cur.execute(
                f"EXPLAIN SELECT id FROM {partition} ORDER BY embedding <=> %s::vector LIMIT %s",
                (queries[0][1], TOP_K),
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
            ann_index_used = (
                "ivfflat" if "ivfflat" in plan else "hnsw" if "hnsw" in plan else "seqscan"
            )
    finally:
        conn.close()

    recalls = []

    exact_conn = get_connection()
    ann_conn = get_connection()

    try:
        with exact_conn.cursor() as cur:
            cur.execute("SET enable_indexscan = off")
            cur.execute("SET enable_bitmapscan = off")

        for qid, embedding in queries:
            with exact_conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id FROM {partition}
                    WHERE id != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (qid, embedding, TOP_K),
                )
                exact_ids = {row[0] for row in cur.fetchall()}

            with ann_conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id FROM {partition}
                    WHERE id != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (qid, embedding, TOP_K),
                )
                ann_ids = {row[0] for row in cur.fetchall()}

            recalls.append(len(exact_ids & ann_ids) / TOP_K)
    finally:
        exact_conn.close()
        ann_conn.close()

    avg_recall = statistics.mean(recalls)

    log_row(
        rows,
        "recall_vs_exact_knn",
        avg_recall,
        "fraction",
        corpus_size=current_corpus_size(tenant_id),
        k=TOP_K,
        notes=f"num_queries={NUM_QUERY_VECTORS}, ann_index_used={ann_index_used}",
    )


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

    scaling = df[df["metric"].isin(["partitioned_rebuild_at_scale", "unpartitioned_rebuild_at_scale"])].copy()
    if not scaling.empty:
        scaling["num_tenants"] = scaling["notes"].str.extract(r"num_tenants=(\d+)").astype(int)
        scaling["run_timestamp"] = pd.to_datetime(scaling["run_timestamp"])
        # keep only the most recent NUM_SCALING_REPEATS rows per (metric,
        # num_tenants), independently for each num_tenants value. A single
        # shared "latest batch" cutoff (e.g. floor-to-hour) is fragile, a run
        # that happens to straddle an hour boundary silently drops whichever
        # configs landed in the earlier hour.
        scaling = (
            scaling.sort_values("run_timestamp", ascending=False)
            .groupby(["metric", "num_tenants"])
            .head(NUM_SCALING_REPEATS)
        )
        scaling = scaling.sort_values("num_tenants")

        plt.figure()
        for metric, group in scaling.groupby("metric"):
            label = "Partitioned (rebuild only the affected tenant)" if metric == "partitioned_rebuild_at_scale" else "Unpartitioned (rebuild the whole combined index)"
            agg = group.groupby("num_tenants")["value"].agg(["mean", "min", "max"])
            lower_err = agg["mean"] - agg["min"]
            upper_err = agg["max"] - agg["mean"]
            plt.errorbar(agg.index, agg["mean"], yerr=[lower_err, upper_err], marker="o", capsize=4, label=label)
        plt.xlabel("Number of tenants in the system (uneven sizes)")
        plt.ylabel("Rebuild time for the same 500-doc tenant's deletion (ms)")
        plt.title(f"Partitioned vs. unpartitioned rebuild cost as the system grows\n(mean of {NUM_SCALING_REPEATS} repeats, error bars show min/max)")
        plt.legend()
        plt.savefig(PLOTS_DIR / f"tenant_scaling_{run_stamp}.png")
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

        print("Resetting benchmark corpus again before the VACUUM FULL sweep (needs the same clean starting sizes)...")
        reset_benchmark_corpus(subject_id, BENCHMARK_TENANT)

        print(f"Measuring VACUUM FULL cost across corpus sizes {CORPUS_SIZES} (alternative to REINDEX x2 + plain VACUUM)...")
        measure_vacuum_full_cost(subject_id, BENCHMARK_TENANT, rows)

        print("Measuring unpartitioned (combined-tenant) index rebuild cost for comparison...")
        measure_unpartitioned_rebuild_cost(rows)

        print(f"Measuring partitioned vs. unpartitioned rebuild cost at scale: {sorted(SCALING_CONFIGS)} tenants, uneven sizes...")
        measure_tenant_scaling(rows)

        print("Measuring recall@k before/after deletion...")
        measure_recall_at_k(BENCHMARK_TENANT, deletion_request_id, rows)

        print("Measuring ANN recall@k against exact nearest-neighbour search...")
        measure_recall_vs_exact(BENCHMARK_TENANT, rows)

    finally:
        if rows:
            append_csv(rows)
            print(f"Appended {len(rows)} rows to {CSV_PATH}")

    plot_results()
    print(f"Saved plots to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
