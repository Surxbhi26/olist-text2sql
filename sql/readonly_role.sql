-- Read-only role used to execute LLM-generated SQL.
-- Defense in depth: even if the validator is bypassed, the database refuses writes.
-- Safe to rerun.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'olist_readonly') THEN
        CREATE ROLE olist_readonly LOGIN PASSWORD 'readonly_pw';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE olist TO olist_readonly;
GRANT USAGE ON SCHEMA public TO olist_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO olist_readonly;

-- Tables created later by postgres (e.g. Spark summary tables) are readable automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO olist_readonly;

-- Explicitly no write or create rights anywhere.
REVOKE CREATE ON SCHEMA public FROM olist_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM olist_readonly;

-- Session defaults for this role: every transaction is read-only, and queries time out.
ALTER ROLE olist_readonly SET default_transaction_read_only = on;
ALTER ROLE olist_readonly SET statement_timeout = '10s';

-- Check
SELECT rolname, rolconfig FROM pg_roles WHERE rolname = 'olist_readonly';
