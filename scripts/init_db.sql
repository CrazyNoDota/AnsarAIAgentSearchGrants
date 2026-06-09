-- ============================================================
-- PostgreSQL Initialization Script
-- Runs once when the database container first starts.
-- Enables pgvector extension required for RAG/semantic search.
-- ============================================================

-- Enable pgvector for vector similarity search (RAG architecture)
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable pg_trgm for full-text search acceleration
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Log initialization
DO $$ BEGIN
    RAISE NOTICE 'Database extensions initialized: vector, pg_trgm';
END $$;
