-- This script runs only when Docker initializes a new PostgreSQL data volume.
-- Versioned application tables and indexes belong in the migration history.
CREATE EXTENSION IF NOT EXISTS vector;
