-- Catalog database for runs against another S3 (emulator or real AWS), apart
-- from the main one: raw.recordings must describe what is in the bucket in use.
-- Idempotent: safe to run every time.
SELECT 'CREATE DATABASE soundscape_cloud'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soundscape_cloud')
\gexec

-- Only its owner may open it (new databases accept every role by default)
REVOKE ALL ON DATABASE soundscape_cloud FROM PUBLIC;
