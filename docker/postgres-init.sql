-- PostgreSQL initialization script for MIRAGE (runs once on fresh volume)
\set QUIET on

-- Ensure database migration owner exists with configured password
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mirage') THEN
        CREATE ROLE mirage WITH LOGIN PASSWORD 'mirage_dev_secret';
    END IF;
END
$$;

-- Ensure unprivileged runtime application role exists with NOBYPASSRLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mirage_app') THEN
        CREATE ROLE mirage_app WITH LOGIN PASSWORD 'mirage_app_secret'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

-- Ensure database exists and is owned by migration owner
SELECT 'CREATE DATABASE mirage_db OWNER mirage'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mirage_db')\gexec

GRANT ALL PRIVILEGES ON DATABASE mirage_db TO mirage;
GRANT CONNECT ON DATABASE mirage_db TO mirage_app;

\connect mirage_db
GRANT ALL ON SCHEMA public TO mirage;
GRANT USAGE ON SCHEMA public TO mirage_app;

-- Configure default schema privileges for unprivileged application role
ALTER DEFAULT PRIVILEGES FOR ROLE mirage IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mirage_app;

ALTER DEFAULT PRIVILEGES FOR ROLE mirage IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO mirage_app;
