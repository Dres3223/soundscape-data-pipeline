-- Create Airflow's metadata database and its own role inside our Postgres.
-- Idempotent: safe to run on every `docker compose up`.
-- Run by the airflow-db-init service with:
--   psql -v airflow_password=... -v app_db=...
--
-- CREATE ROLE / CREATE DATABASE have no IF NOT EXISTS, so each statement is
-- built with SELECT ... WHERE NOT EXISTS and executed with \gexec.

SELECT format('CREATE ROLE airflow LOGIN PASSWORD %L', :'airflow_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'airflow')
\gexec

-- Keep the password in sync with .env if it was changed
SELECT format('ALTER ROLE airflow PASSWORD %L', :'airflow_password')
\gexec

SELECT 'CREATE DATABASE airflow OWNER airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')
\gexec

-- By default every role may connect to every database (via PUBLIC):
-- remove that so the airflow role cannot open the pipeline's data
REVOKE ALL ON DATABASE :"app_db" FROM PUBLIC;
