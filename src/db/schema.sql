CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS data_subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT NOT NULL,
    tenant_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS consent_status (
    subject_id UUID PRIMARY KEY
        REFERENCES data_subjects(id) ON DELETE CASCADE,
    consented BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS deletion_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL
        REFERENCES data_subjects(id) ON DELETE CASCADE,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed'))
);

CREATE TABLE IF NOT EXISTS deletion_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deletion_request_id UUID NOT NULL
        REFERENCES deletion_requests(id) ON DELETE CASCADE,
    document_id UUID NOT NULL,
    deleted_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    signed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE,

    PRIMARY KEY (id, tenant_id),

    FOREIGN KEY (subject_id)
        REFERENCES data_subjects(id)
        ON DELETE CASCADE
)
PARTITION BY LIST (tenant_id);

CREATE TABLE IF NOT EXISTS documents_tenant_1
    PARTITION OF documents
    FOR VALUES IN ('00000000-0000-0000-0000-000000000001');

CREATE TABLE IF NOT EXISTS documents_tenant_2
    PARTITION OF documents
    FOR VALUES IN ('00000000-0000-0000-0000-000000000002');

    -- HNSW: cosine similarity
CREATE INDEX IF NOT EXISTS documents_tenant_1_hnsw_idx
ON documents_tenant_1
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS documents_tenant_2_hnsw_idx
ON documents_tenant_2
USING hnsw (embedding vector_cosine_ops);


-- IVFFlat: cosine similarity
CREATE INDEX IF NOT EXISTS documents_tenant_1_ivfflat_idx
ON documents_tenant_1
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 10);

CREATE INDEX IF NOT EXISTS documents_tenant_2_ivfflat_idx
ON documents_tenant_2
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 10);