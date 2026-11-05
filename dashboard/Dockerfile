# Streamlit dashboard over the dbt marts. Small image: Python plus the
# pinned dependencies of the "dashboard" group, nothing from the pipeline.
FROM python:3.12.15-slim

# Never run as root inside the container
RUN useradd --create-home --uid 1000 dashboard
WORKDIR /app

# requirements.txt is exported from uv.lock with hashes, so pip installs
# exactly the locked versions (regenerate it when the "dashboard" group changes):
#   uv export --only-group dashboard --no-emit-project --format requirements-txt \
#     --no-header -o dashboard/requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app.py .
USER dashboard

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
