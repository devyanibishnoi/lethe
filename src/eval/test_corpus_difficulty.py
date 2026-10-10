"""Self-review ask: the 1.0 recall result in run_benchmarks.py's
recall_vs_exact_knn is suspicious on a small, four-template synthetic
corpus, "it mostly shows the corpus is easy." Two things, both logged to
docs/benchmark_results.csv so they're reproducible, not just asserted:

1. Quantify how easy the corpus actually is: pairwise cosine similarity
   across a sample of documents. This explains why recall came out high,
   it doesn't test whether recall holds under harder conditions.
2. Actually test recall under harder conditions: a table with only ONE
   index type (so the index being tested is pinned, not planner-chosen) at
   a deliberately low accuracy setting (low ivfflat probes / low HNSW
   ef_search), compared against exact search. If recall is still high even
   when deliberately starved of search effort, that's much stronger
   evidence the corpus itself is easy, not just that the default settings
   happen to be generous.
"""

import statistics

import numpy as np

from src.db.db import get_connection
from src.eval.generate_corpus import generate_corpus
from src.eval.run_benchmarks import log_row, append_csv

NUM_SIMILARITY_DOCS = 200
STRESS_TABLE_SIZE = 2000
NUM_STRESS_QUERIES = 20
TOP_K = 10
IVFFLAT_LOW_PROBES = 1
HNSW_LOW_EF_SEARCH = 10


def measure_corpus_similarity(rows):
    records = generate_corpus(NUM_SIMILARITY_DOCS)
    embeddings = np.array([r["embedding"] for r in records])
    norm = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    sim = norm @ norm.T
    iu = np.triu_indices(len(embeddings), k=1)
    pairwise = sim[iu]

    mean_sim = float(pairwise.mean())
    frac_above_90 = float((pairwise > 0.9).mean())
    frac_above_70 = float((pairwise > 0.7).mean())
    max_sim = float(pairwise.max())

    print(f"Mean pairwise cosine similarity across {NUM_SIMILARITY_DOCS} docs ({len(pairwise)} pairs): {mean_sim:.3f}")
    print(f"Fraction of pairs > 0.9 similarity: {frac_above_90:.3f}")
    print(f"Fraction of pairs > 0.7 similarity: {frac_above_70:.3f}")
    print(f"Max pairwise similarity: {max_sim:.3f}")

    log_row(rows, "corpus_pairwise_similarity_mean", mean_sim, "cosine_similarity", corpus_size=NUM_SIMILARITY_DOCS, notes=f"num_pairs={len(pairwise)}")
    log_row(rows, "corpus_pairwise_similarity_frac_above_0.9", frac_above_90, "fraction", corpus_size=NUM_SIMILARITY_DOCS, notes="near-duplicate rate, same template with different filled-in entities")
    log_row(rows, "corpus_pairwise_similarity_frac_above_0.7", frac_above_70, "fraction", corpus_size=NUM_SIMILARITY_DOCS)
    log_row(rows, "corpus_pairwise_similarity_max", max_sim, "cosine_similarity", corpus_size=NUM_SIMILARITY_DOCS)


def _build_single_index_table(table_name, index_type, index_opts=""):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table_name}")
            cur.execute(
                f"""
                CREATE TABLE {table_name} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
                    embedding VECTOR (384) NOT NULL
                )
                """
            )
        conn.commit()

        records = generate_corpus(STRESS_TABLE_SIZE)
        with conn.cursor() as cur:
            for record in records:
                cur.execute(f"INSERT INTO {table_name} (embedding) VALUES (%s)", (record["embedding"],))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(f"CREATE INDEX {table_name}_idx ON {table_name} USING {index_type} (embedding vector_cosine_ops) {index_opts}")
        conn.commit()
    finally:
        conn.close()


def _measure_stressed_recall(table_name, set_statement, rows, metric_name, notes):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id, embedding FROM {table_name} ORDER BY random() LIMIT %s", (NUM_STRESS_QUERIES,))
            queries = [(row[0], row[1].to_list()) for row in cur.fetchall()]
    finally:
        conn.close()

    exact_conn = get_connection()
    ann_conn = get_connection()
    try:
        with exact_conn.cursor() as cur:
            cur.execute("SET enable_indexscan = off")
            cur.execute("SET enable_bitmapscan = off")
        with ann_conn.cursor() as cur:
            cur.execute(set_statement)

        recalls = []
        for qid, embedding in queries:
            with exact_conn.cursor() as cur:
                cur.execute(
                    f"SELECT id FROM {table_name} WHERE id != %s ORDER BY embedding <=> %s::vector LIMIT %s",
                    (qid, embedding, TOP_K),
                )
                exact_ids = {row[0] for row in cur.fetchall()}
            with ann_conn.cursor() as cur:
                cur.execute(
                    f"SELECT id FROM {table_name} WHERE id != %s ORDER BY embedding <=> %s::vector LIMIT %s",
                    (qid, embedding, TOP_K),
                )
                ann_ids = {row[0] for row in cur.fetchall()}
            recalls.append(len(exact_ids & ann_ids) / TOP_K)
    finally:
        exact_conn.close()
        ann_conn.close()

    avg_recall = statistics.mean(recalls)
    print(f"{metric_name}: {avg_recall:.3f} (over {NUM_STRESS_QUERIES} queries)")
    log_row(rows, metric_name, avg_recall, "fraction", corpus_size=STRESS_TABLE_SIZE, k=TOP_K, notes=notes)


def measure_stressed_recall(rows):
    print(f"\nBuilding a {STRESS_TABLE_SIZE}-doc table with ONLY an ivfflat index (lists=10)...")
    _build_single_index_table("documents_difficulty_ivfflat", "ivfflat", "WITH (lists = 10)")
    _measure_stressed_recall(
        "documents_difficulty_ivfflat",
        f"SET ivfflat.probes = {IVFFLAT_LOW_PROBES}",
        rows,
        "recall_vs_exact_ivfflat_low_probes",
        f"ivfflat.probes={IVFFLAT_LOW_PROBES} (default would search more lists; this deliberately starves accuracy to stress-test whether the corpus is trivially easy or genuinely well-indexed)",
    )

    print(f"\nBuilding a {STRESS_TABLE_SIZE}-doc table with ONLY an HNSW index...")
    _build_single_index_table("documents_difficulty_hnsw", "hnsw")
    _measure_stressed_recall(
        "documents_difficulty_hnsw",
        f"SET hnsw.ef_search = {HNSW_LOW_EF_SEARCH}",
        rows,
        "recall_vs_exact_hnsw_low_ef_search",
        f"hnsw.ef_search={HNSW_LOW_EF_SEARCH} (default is 40; this deliberately starves accuracy to stress-test whether the corpus is trivially easy or genuinely well-indexed)",
    )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS documents_difficulty_ivfflat")
            cur.execute("DROP TABLE IF EXISTS documents_difficulty_hnsw")
        conn.commit()
    finally:
        conn.close()


def main():
    rows = []
    measure_corpus_similarity(rows)
    measure_stressed_recall(rows)
    append_csv(rows)
    print(f"\nAppended {len(rows)} rows to docs/benchmark_results.csv")


if __name__ == "__main__":
    main()
