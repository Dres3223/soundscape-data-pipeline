"""Daily pipeline: ingest → features → load.

Each task only calls a module of the soundscape package; the logic lives
there and is tested with pytest. Every stage is idempotent, so re-running
any date (Clear in the UI) leaves the same data: nothing is duplicated.
Each run processes everything pending; see P1PDPS-32 for incremental features.
"""

from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, task

DEFAULT_ARGS = {
    "retries": 2,  # transient failures (network, S3 busy) are retried...
    "retry_delay": timedelta(minutes=2),  # ...after a short wait
    "execution_timeout": timedelta(hours=1),  # a hung task fails instead
}


@dag(
    schedule="@daily",
    start_date=datetime(2026, 11, 1, tzinfo=UTC),
    catchup=False,  # do not create runs for past dates when first enabled
    max_active_runs=1,  # two runs would write the same files at once
    default_args=DEFAULT_ARGS,
    tags=["soundscape"],
)
def soundscape_pipeline():
    # Imports inside the tasks: this file is parsed often and must stay light

    @task
    def ingest() -> dict:
        from soundscape import ingest
        from soundscape.config import Settings

        return ingest.run(Settings())

    @task
    def features() -> dict:
        from soundscape import features
        from soundscape.config import Settings

        results = features.run(Settings())
        ok = sum(result.status == "ok" for _, result in results)
        # Only the counts go to XCom: the results themselves are not JSON
        return {"ok": ok, "failed": len(results) - ok}

    @task
    def load() -> dict:
        from soundscape import load
        from soundscape.config import Settings

        return load.run(Settings())

    ingest() >> features() >> load()


soundscape_pipeline()
