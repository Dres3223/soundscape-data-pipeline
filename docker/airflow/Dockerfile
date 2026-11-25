# Airflow image with the soundscape package and its dependencies installed,
# so DAG tasks can `import soundscape`. Same Python as the project (3.12).
FROM apache/airflow:3.3.2-python3.12

# Editable install: the code is also mounted at /opt/airflow/project/src by
# docker-compose.yml, so code changes apply without rebuilding the image.
# Only a change of dependencies (pyproject.toml) needs `docker compose build`.
WORKDIR /opt/airflow/project
COPY --chown=airflow:root pyproject.toml README.md LICENSE ./
COPY --chown=airflow:root src ./src

# Pinning apache-airflow keeps pip from upgrading or downgrading Airflow
# while it resolves our dependencies
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -e .

# BirdNET models (~90 MB) inside the image: tasks never download them, and a
# new container does not need the network to detect birds
RUN python -c "import birdnet; \
birdnet.load('acoustic', '2.4', 'tf', library='litert'); \
birdnet.load('geo', '2.4', 'tf', library='litert')"

WORKDIR /opt/airflow
