# One-step commands for the pipeline. Run `make` to list them.
# First time on a new machine: make setup && make data && make up && make run

# .env only when it exists: in CI the settings come from environment variables
ENV_FILE := $(if $(wildcard .env),--env-file .env)
DBT := uv run $(ENV_FILE) --group dbt dbt
DBT_ARGS := --project-dir dbt --profiles-dir dbt

# Infrastructure: ENV=moto (local emulator) or ENV=aws (real account)
ENV ?= moto
AWS_ENV := uv run --env-file .env.$(ENV)
TF := $(AWS_ENV) terraform -chdir=infra/terraform
TF_VARS := -var-file=envs/$(ENV).tfvars
# The emulator is disposable; on a real account a person confirms every change
ifeq ($(ENV),moto)
TF_AUTO := -auto-approve
# Inside the Compose network; empty means real AWS
CLOUD_S3_ENDPOINT := http://moto:5000
endif
CLOUD_COMPOSE := CLOUD_ENV=$(ENV) CLOUD_S3_ENDPOINT_URL=$(CLOUD_S3_ENDPOINT) \
	docker compose -f docker-compose.yml -f docker-compose.cloud.yml

.DEFAULT_GOAL := help
.PHONY: help setup data up down run test test-dags lint emulator emulator-down \
	infra-init infra-plan infra-apply infra-check infra-destroy \
	sync-storage airflow-cloud airflow-local

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

infra-init: ## Create the state bucket and initialize Terraform (ENV=moto|aws)
	$(AWS_ENV) python scripts/bootstrap_state.py infra/terraform/envs/$(ENV).backend.hcl
	$(TF) init -reconfigure -input=false -backend-config=envs/$(ENV).backend.hcl

infra-plan: infra-init ## Show what Terraform would change
	$(TF) plan $(TF_VARS)

infra-apply: infra-init ## Create the infrastructure and the pipeline's key
	$(TF) apply $(TF_AUTO) $(TF_VARS)
	$(AWS_ENV) python scripts/create_pipeline_key.py $(ENV)

infra-check: ## Check the pipeline's key can do only what it should
	$(AWS_ENV) python scripts/check_pipeline_permissions.py $(ENV)

infra-destroy: infra-init ## Delete the infrastructure
	$(TF) destroy $(TF_AUTO) $(TF_VARS)

sync-storage: ## Copy the objects of the local bucket to the ENV bucket, same paths
	uv run python -m soundscape.sync_storage $(ENV)

airflow-cloud: ## Point Airflow at the ENV bucket, with its own catalog database
	docker compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' \
		< docker/postgres/create_cloud_db.sql
	$(CLOUD_COMPOSE) up -d --no-deps --wait airflow-scheduler

airflow-local: ## Point Airflow back at the local bucket and database
	docker compose up -d --no-deps --wait airflow-scheduler
