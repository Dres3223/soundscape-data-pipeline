"""Check the DAG files load in Airflow and are wired as intended.

Needs Airflow, which is not in the default environment:
    uv run --group airflow pytest tests/test_dags.py
Skipped when Airflow is not installed.
"""

import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

# Before importing Airflow: keep its home (config, SQLite file) out of ~/airflow
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-test-"))
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "false")

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS_FOLDER = Path(__file__).parent.parent / "dags"


@pytest.fixture(scope="module")
def dags() -> dict:
    """DAGs parsed from the files only; no metadata database is needed."""
    dagbag = DagBag(dag_folder=DAGS_FOLDER)
    assert dagbag.import_errors == {}
    return dagbag.dags


def test_dags_load_without_import_errors(dags):
    assert {"soundscape_pipeline", "smoke_check"} <= set(dags)


def test_pipeline_runs_ingest_then_features_then_load(dags):
    tasks = dags["soundscape_pipeline"].task_dict

    assert tasks["ingest"].downstream_task_ids == {"features"}
    assert tasks["features"].downstream_task_ids == {"load"}
    assert tasks["load"].downstream_task_ids == set()


def test_pipeline_tasks_retry_and_time_out(dags):
    dag = dags["soundscape_pipeline"]

    assert dag.max_active_runs == 1
    for task in dag.tasks:
        assert task.retries == 2
        assert task.retry_delay == timedelta(minutes=2)
        assert task.execution_timeout == timedelta(hours=1)
