"""Smoke check: proves Airflow sees dags/ and can import the soundscape package.

Trigger it by hand from the UI; it has no schedule.
"""

from airflow.sdk import dag, task


@dag(schedule=None, catchup=False, tags=["smoke"])
def smoke_check():
    @task
    def import_soundscape() -> str:
        # Imported inside the task: the DAG file is parsed often and must stay light
        import librosa

        import soundscape.features

        module = soundscape.features.__name__
        return f"soundscape OK ({module}), librosa {librosa.__version__}"

    import_soundscape()


smoke_check()
