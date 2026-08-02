# Problem Statement — Lethe

## Key Concepts, In Plain English

Read this before the formal problem definition below if any of these terms are new.

- **RAG (Retrieval-Augmented Generation)**: instead of an LLM answering purely from what it memorized during training, it first looks up relevant documents from a database, then uses those documents to write its answer. This is how you get an LLM to answer questions about a specific company's private documents without retraining the model on them.
- **Vector database / embedding**: to "look up relevant documents," the system converts text into a list of numbers (a vector) that captures its meaning, called an embedding. Similar meanings produce similar vectors. A vector database stores these and can quickly find the ones closest to a given query.
- **HNSW / IVF (index types)**: comparing a query against millions of stored vectors one by one would be too slow, so vector databases build an index, a shortcut structure, to find close matches fast. HNSW and IVF are two different ways of building that shortcut, each with different speed and update-cost trade-offs, which is part of what this project benchmarks.
- **Soft delete vs. hard delete**: a soft delete just marks a record as "deleted" without removing it, the data is still physically there. A hard delete actually removes it. Most vector databases only do the former today, which is the whole problem this project addresses.
- **GDPR Article 17 (Right to Erasure)**: a regulation giving individuals the right to have their personal data deleted on request. If a system only soft-deletes, it cannot truthfully claim to comply.
- **Machine unlearning**: the broader research area of removing a specific piece of data's influence from a trained system, whether that's the model's own weights or, as here, an external knowledge base it retrieves from.

## Problem Definition

Enterprises are increasingly adopting Retrieval-Augmented Generation (RAG) pipelines to ground Large Language Model (LLM) outputs in their own private data, internal documents, incident reports, customer records, and threat-intelligence feeds, without exposing that data to third-party model training. This is central to a growing category of service, organizations offering companies their own privately hosted LLM deployments, where a core promise is that client data never leaves the client's control. These pipelines depend on vector databases (typically HNSW- or IVF-indexed) to retrieve semantically relevant context at query time.

When a data subject or client exercises their right to erasure under GDPR Article 17, or an internal retention policy requires it, most current vector database implementations perform only a soft delete: the record is flagged as removed at the metadata level while the underlying embedding remains physically present and recoverable from the raw index files on disk. This creates a direct compliance gap, a provider that promises "your data is deleted" may, in practice, still be storing a recoverable representation of it, exposing both the provider and the client to regulatory and contractual risk.

This problem is especially acute for private, enterprise-hosted LLM/RAG deployments offered as a service, since verifiable deletion is not a peripheral feature but a core part of the trust guarantee such a service is built on.

## Research Gap

Existing machine unlearning research has largely targeted a model's parametric weights, for example, sharded retraining (SISA) or gradient-based unlearning, or has restructured a RAG system's external knowledge base to simulate forgetting without touching the underlying LLM (Wang et al., 2025).

More recent work has begun to expose that the vector database layer itself is the weaker link: a 2026 analysis of soft-delete behaviour across multiple HNSW implementations found that deleted embeddings remain physically reconstructible directly from storage, bypassing the database's own API-level access controls, and proposed a cryptographically signed proof of deletion as an audit record (Chakraborttii et al., 2026).

However, this work stops at demonstrating the vulnerability and a basic proof-of-deletion mechanism. It does not address:

- Efficient hard-delete at scale, true removal today requires rebuilding the entire index, which is prohibitively expensive for large, frequently updated knowledge bases.
- Partition-aware indexing strategies that would let a deletion request rebuild only the affected shard, not the whole index.
- Benchmarked comparisons of hard-delete cost and retrieval-quality impact across index types (HNSW vs. IVF vs. IVF-PQ) and corpus sizes.
- Evaluation on security/threat-intelligence-style corpora, where records blend operational data with personally identifying details.

This is the gap the project addresses: an efficient, verifiable, database-native deletion layer for RAG knowledge bases.

## Proposed Objectives

- Design a relational schema (PostgreSQL with the pgvector extension) that stores embeddings alongside consent, provenance, and deletion-audit metadata.
- Partition the vector index by a sensitivity/tenant tag so a deletion request rebuilds only the affected partition.
- Implement a cryptographically signed deletion-audit table, joined to the vector store, as verifiable proof of erasure.
- Benchmark deletion latency, index-rebuild cost, and retrieval quality (recall@k) before and after deletion, across increasing corpus sizes.
- Evaluate the system on a synthetic security-incident / threat-intelligence corpus.
