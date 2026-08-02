# Lethe — Coding Checklist (Step by Step)

This file assumes you are starting from zero. It describes exactly what to build and why, step by step, but not the literal code, write that yourselves so you actually understand what's running. Work through **Phase 0 together** first, then split into your three tracks. Check boxes off as you go.

**How the work is split:** by layer, not by feature. One person owns *all the schema/database structure* across the whole system, another owns *all the core logic* that runs on top of it, and the third owns *all the evaluation, benchmarking, and reporting*. This means the three of you build on top of each other in sequence rather than working fully in parallel, Layer 2 needs Layer 1's tables to exist first, and Layer 3 needs Layer 2's functions to exist first. Plan your weeks with that in mind: Layer 1 should get a head start, Layer 2 picks up once the schema is stable, Layer 3 picks up once there's something to actually measure. Talk to each other daily during the overlap points.

Read the **Research Paper Prep** section at the bottom now, not in October. A few small habits from day one save you weeks of work when it's time to write.

---

## Phase 0 — Shared Setup (all three of you, do this once, together)

### 0.1 Install Docker

We're running PostgreSQL inside Docker instead of installing it directly, this avoids version mismatches between your three laptops and means everyone runs the exact same database.

- [ ] Install Docker Desktop for your OS (search "Docker Desktop download" and grab the installer for Windows/Mac).
- [ ] Open Docker Desktop once after installing, so it finishes setup and is running in the background.
- [ ] Confirm it installed correctly by checking its version from a terminal, if the command isn't recognized, restart your machine and try again.

### 0.2 Spin up Postgres with pgvector

- [ ] In the project root, create a file named `docker-compose.yml`. In it, define one service (call it `db`) using the official `pgvector/pgvector:pg16` image, this already has the pgvector extension built in, so nothing needs to be compiled by hand. Set three environment variables on it for the username, password, and database name, pick memorable values (e.g. `lethe_user` / `lethe_pass` / `lethe_db`) and use the exact same values everywhere else in the project. Map the container's Postgres port to your machine's port 5432, and attach a named volume so your data survives a restart.
- [ ] Start the container and confirm it shows a status of "Up."
- [ ] Connect to the running database, either via a terminal session into the container or with a visual tool like DBeaver (free, search "DBeaver download," connect to `localhost:5432`, database `lethe_db`, with the username/password you set above).
- [ ] Once connected, turn on the pgvector extension inside the database, this is a single `CREATE EXTENSION` statement, look up the exact syntax for enabling an extension named `vector` if you haven't done this before.

### 0.3 Set up Python

- [ ] Confirm you have Python 3.11 or newer installed.
- [ ] From the repo root, create and activate a virtual environment (search "python venv" if you haven't set one up before), this keeps each person's installed packages isolated and consistent.
- [ ] Install the packages the whole project needs: `psycopg2-binary`, `sqlalchemy`, `pgvector`, `sentence-transformers`, `cryptography`, `pandas`, `matplotlib`, and `python-dotenv`. All three of you should install the exact same list so your environments match.
- [ ] Create a `.env` file in the repo root (already covered by `.gitignore`, so it won't get committed) listing the five values every script will need to connect to the database: host, port, database name, username, and password, matching whatever you set in `docker-compose.yml`.

### 0.4 Sanity check — everyone runs this before moving on

- [ ] Write a short script, `src/db/test_connection.py`, that reads your `.env` values (the `python-dotenv` package makes this simple), opens a connection to the database with `psycopg2`, runs the simplest possible query, and prints the result. If it prints back successfully, your environment is correctly wired up.
- [ ] Run it. If it fails, double-check Docker is actually running and that your `.env` values match `docker-compose.yml` exactly.

Once all three of you get a successful connection, move to your individual layer below.

---

## Layer 1 — Foundations: Environment, Schema & Indexes (Hridya)

**What this is, in plain terms:** everything about *what the data looks like and where it lives*, before anyone writes a line of logic against it. Every table, every column, every index definition. Get this right and stable early, since Layers 2 and 3 are both built directly on top of it.

### 1.1 Design and create the core schema

- [ ] Create a file, `src/db/schema.sql`. In it, define four tables:
  - **`data_subjects`**: one row per person or organization whose data might appear in the corpus. Needs a unique auto-generated ID, a display name, a `tenant_id` linking it to whichever client/organization owns that data, and a created-at timestamp.
  - **`consent_status`**: whether a subject has consented to their data being stored, keyed by subject ID, with a boolean consented flag and an updated-at timestamp.
  - **`deletion_requests`**: one row per erasure request, referencing the subject it's about, when it came in, and a status (pending / completed).
  - **`deletion_audit_log`**: the proof-of-deletion record Layer 2 will write to. It needs to reference the deletion request, record which document was deleted, store a hash of what was deleted, a cryptographic signature over that hash, and when it was signed.
  - Look up Postgres's UUID type and its auto-generation function, and the `TIMESTAMPTZ` type, if these are new to you, you'll use them in every table here.
- [ ] Apply this file to your database (both `psql` and DBeaver can run a `.sql` file directly).

### 1.2 Design and create the partitioned documents table

**What this is, in plain terms:** if every document from every client sits in one giant table, deleting one client's data means touching a table with everyone's data in it, slow and risky. Partitioning splits the table into separate physical chunks by tenant, so deleting Client A's data only ever touches Client A's chunk.

- [ ] Add a fifth table, `documents`, to your schema file (or a separate `partitions.sql`). This one needs to be partitioned by `tenant_id` rather than being a single flat table, look up Postgres's list-partitioning syntax for how this is declared. Give it a document ID, the subject it belongs to, its `tenant_id`, the raw text content, a vector-embedding column (pgvector's vector type, sized to 384 to match the embedding model you'll use in Layer 3), a created-at timestamp, and a boolean `deleted` flag (kept only so you can compare soft-delete against your hard-delete later).
- [ ] Create one partition table per test tenant, two is enough to start, each declared as a partition of `documents` for that tenant's specific ID value.

### 1.3 Create the indexes

- [ ] Learn the two concepts you're setting up (5 minute read, worth it): **HNSW vs. IVF** are two different ways to make "find the 10 most similar vectors out of a million" fast instead of comparing against every single one. HNSW builds a graph structure, generally faster to query but costlier to update. IVF clusters vectors into buckets, faster to update but can be slightly less accurate. Layer 3 will benchmark both.
- [ ] On each tenant partition, create a similarity-search index using HNSW with cosine distance, this is the baseline. Look up pgvector's index-creation syntax for this.
- [ ] Alongside it (don't remove the HNSW one, Layer 3 needs both), create a second index on the same column using IVF (pgvector calls this `ivfflat`). You'll need to choose a "lists" parameter, look up what a reasonable default is for a dataset a few thousand rows in size.
- [ ] Note in your write-up that IVF-PQ isn't natively supported by pgvector, that's a real limitation worth stating plainly rather than quietly working around.

### 1.4 Write basic CRUD helpers

- [ ] Create `src/db/db.py` with:
  - A function that builds and returns a database connection/engine using the values from your `.env` file, every other script should go through this one place to talk to the database.
  - A function to insert a new row into `data_subjects` and return its generated ID.
  - A function to insert a new row into `documents` (taking the subject, tenant, text content, and the embedding vector) and return the new document's ID.
  - A function to fetch a single document back by its ID.
- [ ] Test these by writing a throwaway script that inserts a fake subject and a fake document (any random 384-number list works for testing purposes) and fetches it back to confirm it round-trips correctly.

### 1.5 Hand off to the team

- [ ] Create a `.env.example` file (same variable names, no real password) so teammates setting up on a new machine know what to fill in.
- [ ] Message Anshika once the schema, partitions, indexes, and CRUD helpers all run cleanly, Layer 2 builds directly on top of this.

---

## Layer 2 — Core Logic: Hard-Delete, Signing & Verification (Anshika)

**What this is, in plain terms:** everything about *what the system actually does* with the data Layer 1 set up. This is the heart of the project, making deletion real (not just flagged) and making it provable.

### 2.1 Implement hard-delete (this is the core contribution, take your time here)

- [ ] Create `src/logic/hard_delete.py` with a function that takes a document ID and tenant ID, and does two things, in order: physically deletes that row from the correct tenant partition table (a straightforward delete, not a flag update), then rebuilds only that tenant's HNSW index, not the whole table's index, look up Postgres's command for rebuilding a single named index. That second step, rebuilding only the affected partition's index instead of the whole dataset, is the actual contribution this project is arguing for, comment your code to explain why, you'll want that explanation again for the paper.
- [ ] Test it: insert a handful of documents into one tenant, delete one, and confirm with a direct query that the row is genuinely gone, not just flagged.

### 2.2 Generate a signing key (do this once)

- [ ] Create `src/logic/generate_keys.py`, a one-time script using Python's `cryptography` library. Generate an elliptic-curve key pair (SECP256R1 is a solid, standard choice), and write the private and public keys out to two separate files.
- [ ] Run this script once, then immediately add both key files to `.gitignore`, the private key should never be committed, even for a class project, it's good habit for the real thing this could become.

### 2.3 Sign every deletion

- [ ] Create `src/logic/sign_deletion.py` with a function that takes the content about to be deleted and its document ID. It should: hash the content (SHA-256 is fine), build a message combining the document ID, that hash, and the current UTC timestamp, then sign that message with the private key from 2.2 using ECDSA. Return the hash, the signature, and the timestamp, these are what get written into `deletion_audit_log`.
- [ ] Call this function from inside your hard-delete function, right before the row is actually removed, since you need the content to still exist in order to hash it.

### 2.4 Verify a signature (proves the audit log hasn't been tampered with)

- [ ] Create `src/logic/verify_deletion.py` with a function that takes a document ID, a hash, a timestamp, and a signature. It should rebuild the same message string used when signing, load the public key, and check whether the signature is valid for that message, returning true or false.
- [ ] This is your demo moment: pull a real row from `deletion_audit_log`, verify it and show it returns true, then change one character of the stored hash and show it now returns false. That's the "certified" in Certified Forgetting.

### 2.5 Hand off to the team

- [ ] Message Devyani once hard-delete, signing, and verification all work end to end, Layer 3's benchmarks call these functions directly.

---

## Layer 3 — Evaluation: Corpus, Benchmarking, Demo & Docs (Devyani)

**What this is, in plain terms:** proving the whole thing actually works and is actually fast enough to matter. This layer generates the test data, measures the system Layers 1 and 2 built, and turns those numbers into something presentable.

### 3.1 Build the synthetic corpus

- [ ] Create `src/eval/generate_corpus.py`. You'll need the `sentence-transformers` library and a small pretrained model, `all-MiniLM-L6-v2` is a good choice, it downloads once (roughly 90MB) and then runs fully offline, no API calls needed, and its output size is 384 numbers per piece of text, which is why every embedding column in this project is sized 384.
- [ ] Write a function that generates a given number of fake security-incident records. A simple, effective approach: write a handful of sentence templates that sound like real incident log lines (a failed login alert, suspicious outbound traffic, a flagged process, an unusual cloud-storage access), each with placeholders for a name, IP address, hostname, and timestamp, then fill those in with randomly generated values per record. Feed each finished sentence through the embedding model to get its vector, and return the text/embedding pairs ready to insert via Layer 1's document-insert helper. Spread the generated documents across your two test tenants.

### 3.2 Benchmark suite

- [ ] Create `src/eval/run_benchmarks.py`. At minimum it should measure and log, to a CSV file you append to rather than overwrite, with a timestamp on every run:
  - **Deletion latency**: how long a single hard-delete call takes, time it immediately before and after the call.
  - **Index rebuild cost**: time the reindex step specifically, and repeat at a few different corpus sizes (say 100, 500, 1000, and 5000 documents), so you can plot cost against corpus size.
  - **Recall@k before and after deletion**: pick a fixed set of query vectors (20 is a reasonable number), run a similarity search for each before deleting anything and save which documents come back, then delete a batch of documents and run the exact same queries again, measuring how much the results overlap. This shows deletion doesn't quietly degrade search quality for everyone else's data.
- [ ] Plot the results with `matplotlib`, save the plots as image files rather than leaving them only on screen, a couple of clean charts are worth more in the demo (and later the paper) than a wall of numbers.

### 3.3 Document findings as you go

- [ ] Keep short dated notes in `docs/LAB_NOTES.md` (see Research Paper Prep below) on what settings you tried and what happened, this becomes the methodology and results write-up almost verbatim later.
- [ ] Keep `README.md`'s "Getting Started" section current if any setup steps change.

---

## Phase 4 — Integration (all three, in the last few weeks before Review-3)

- [ ] Build one end-to-end demo that walks through the full story: insert a batch of synthetic documents, run a similarity search, submit a deletion request, hard-delete the document, show the signed audit record, re-run the same search and show the deleted document no longer appears, then attempt to read the raw deleted row directly and show it's genuinely gone, not just flagged.
- [ ] Rehearse this demo out loud at least once before Review-3, not just running it silently.
- [ ] Do a final read-through of the whole codebase together, since the layers were built somewhat sequentially, this is the point where all three of you should understand the whole system, not just your own layer.

---

## Research Paper Prep 

- [ ] Create `docs/LAB_NOTES.md` right now, a shared, running log. Every time one of you tries something, add a dated entry: what you tried, what happened, any numbers you got, even failed attempts. Failed approaches are often a whole paragraph in a paper's "Discussion" section, don't let them evaporate.
- [ ] Never overwrite a benchmark result. Save each run as its own row (with a timestamp) in `docs/benchmark_results.csv`, and each plot as its own file in `docs/benchmark_plots/`. Early numbers will be worth comparing to later, more optimized ones.
- [ ] Take a screenshot or short screen recording of the working demo as soon as it works the first time, not just at the end. "Before" states are surprisingly hard to reconstruct later.
- [ ] Roughly, the three layers map onto standard paper sections later: Layer 1 (schema, partitions, indexes) becomes the **System Design** section, Layer 2 (hard-delete, signing, verification) becomes most of the **Methodology** section, and Layer 3 (corpus, benchmarking, results) becomes the **Evaluation** and **Results** sections. Keep that mapping in mind so notes end up in the right bucket.
- [ ] Re-read the two papers cited in `PROBLEM_STATEMENT.md` (Wang et al. 2025, Chakraborttii et al. 2026) properly, not just the summary here, once closer to writing. The "Related Work" section needs genuine understanding of what they did and did not do, that's what makes the contribution look like a contribution and not a restatement.
