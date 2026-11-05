# Image of the pipeline package: runs one stage (ingest, features or load).
#   docker run --env-file .env ghcr.io/dres3223/soundscape-data-pipeline ingest
# Multi-stage: the builder has uv and installs the locked dependencies; the
# runtime image only receives the resulting virtual environment.

# ---- 1. builder ----------------------------------------------------------
FROM python:3.12.15-slim AS builder

# uv from PyPI, pinned (the official uv image lives on ghcr.io)
RUN pip install --no-cache-dir uv==0.13.6

# Compile bytecode now (faster start), copy files instead of hard links
# (the venv moves to another image), use the image's Python as it is
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer is reused while uv.lock does not change
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project

# Then the package itself, as a regular (non-editable) install
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- 2. runtime ----------------------------------------------------------
FROM python:3.12.15-slim AS runtime

# Links the image to its repository on GitHub (and to its description)
LABEL org.opencontainers.image.source="https://github.com/Dres3223/soundscape-data-pipeline" \
      org.opencontainers.image.description="Soundscape pipeline stages: ingest, features, load" \
      org.opencontainers.image.licenses="MIT"

# Never run as root inside the container
RUN useradd --create-home --uid 1000 soundscape

COPY --from=builder /app/.venv /app/.venv
COPY docker/entrypoint.sh /usr/local/bin/soundscape
ENV PATH="/app/.venv/bin:$PATH"

USER soundscape
WORKDIR /home/soundscape
ENTRYPOINT ["soundscape"]
CMD ["--help"]
