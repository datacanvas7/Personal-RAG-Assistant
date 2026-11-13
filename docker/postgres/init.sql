-- Runs once, when the database volume is first created.
-- Phase 2's Alembic migration also executes `CREATE EXTENSION IF NOT EXISTS vector`,
-- so a database that did not run this script (managed Postgres, restored backup)
-- still ends up correctly configured. Both are idempotent.
CREATE EXTENSION IF NOT EXISTS vector;
