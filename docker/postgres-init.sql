-- PostgreSQL initialization script for MIRAGE (runs once on fresh volume)
\set QUIET on

-- Ensure application user exists with configured password
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mirage') THEN
        CREATE ROLE mirage WITH LOGIN PASSWORD 'mirage_dev_secret';
    END IF;
END
$$;

-- Ensure database exists and is owned by application user
SELECT 'CREATE DATABASE mirage_db OWNER mirage'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mirage_db')\gexec

GRANT ALL PRIVILEGES ON DATABASE mirage_db TO mirage;
\connect mirage_db
GRANT ALL ON SCHEMA public TO mirage;
