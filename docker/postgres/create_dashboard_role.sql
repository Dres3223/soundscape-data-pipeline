-- Read-only role for the dashboard: it may only read the marts.
-- Idempotent: safe to run on every `docker compose up`.
-- Run by the postgres-init service with:
--   psql -v dashboard_password=... -v app_db=... -v app_user=...
--
-- SELECT on the mart tables is granted by dbt (+grants in dbt_project.yml):
-- dbt recreates the tables on every build, which drops grants made here.

SELECT format('CREATE ROLE dashboard LOGIN PASSWORD %L', :'dashboard_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dashboard')
\gexec

-- Keep the password in sync with .env if it was changed
SELECT format('ALTER ROLE dashboard PASSWORD %L', :'dashboard_password')
\gexec

GRANT CONNECT ON DATABASE :"app_db" TO dashboard;

-- The schema is owned by the pipeline role; dbt fills it
CREATE SCHEMA IF NOT EXISTS marts AUTHORIZATION :"app_user";
GRANT USAGE ON SCHEMA marts TO dashboard;
