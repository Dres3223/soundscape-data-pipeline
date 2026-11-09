# One-step commands for the pipeline. Run `make` to list them.
# First time on a new machine: make setup && make data && make up && make run

# .env only when it exists: in CI the settings come from environment variables
ENV_FILE := $(if $(wildcard .env),--env-file .env)
DBT := uv run $(ENV_FILE) --group dbt dbt
DBT_ARGS := --project-dir dbt --profiles-dir dbt

.DEFAULT_GOAL := help
.PHONY: help setup data up down run test test-dags lint emulator emulator-down

help: ## List the available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) \
		| awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

setup: ## Install dependencies and git hooks; create .env with random secrets
	uv sync
	uv run pre-commit install
	bash scripts/make_env.sh

data: ## Download the dataset metadata and the 16-recording sample (Kaggle token)
	uv run bash scripts/download_metadata.sh
	uv run bash scripts/list_files.sh
	uv run bash scripts/download_sample.sh

up: ## Build the images and start every service, waiting until they are healthy
	docker compose up -d --build --wait

down: ## Stop the services (data is kept in the Docker volumes)
	docker compose --profile emulator down

run: ## Run the pipeline once: ingest, features, load, then dbt build
	uv run python -m soundscape.ingest
	uv run python -m soundscape.features
	uv run python -m soundscape.load
	$(DBT) deps $(DBT_ARGS)
	$(DBT) build $(DBT_ARGS)

test: ## Run the tests with coverage (integration tests need `make up`)
	uv run pytest $(PYTEST_ARGS)

test-dags: ## Check the Airflow DAGs load (installs Airflow in .venv)
	uv run --group airflow pytest tests/test_dags.py --no-cov

lint: ## Run every pre-commit hook on the whole repository
	uv run pre-commit run --all-files

emulator: ## Start a fresh AWS emulator (Moto) and create its admin user
	docker compose --profile emulator up -d --build --wait --force-recreate moto
	uv run $(ENV_FILE) python scripts/bootstrap_emulator.py

emulator-down: ## Stop the AWS emulator and erase everything in it
	docker compose --profile emulator rm --stop --force moto
