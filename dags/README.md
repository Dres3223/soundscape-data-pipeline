# dags

Apache Airflow DAGs that orchestrate ingest → features → load (epic E3).
Mounted into the Airflow containers at `/opt/airflow/dags`.

DAG files only wire tasks together: the logic lives in the `soundscape`
package, imported inside each task so parsing the file stays fast.

| DAG | Schedule | Purpose |
|---|---|---|
| `smoke_check` | manual | Checks that tasks can import `soundscape` |
