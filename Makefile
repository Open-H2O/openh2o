# Open Water Accounting Platform - Development Shortcuts
#
# Usage: make <target>
# Run `make help` to see all available targets.

COMPOSE = docker compose
EXEC    = $(COMPOSE) exec web python manage.py

.PHONY: help up down build logs shell dbshell migrate makemigrations \
        createsuperuser collectstatic seed seed-roles seed-water-types \
        seed-data-sources seed-report-templates seed-water-right-types \
        seed-well-types demo flush-demo kaweah flush-kaweah check test fresh

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

up: ## Start all services
	$(COMPOSE) up -d --build

down: ## Stop all services
	$(COMPOSE) down

build: ## Rebuild containers without starting
	$(COMPOSE) build

logs: ## Tail web container logs
	$(COMPOSE) logs -f web

# ---------------------------------------------------------------------------
# Django Management
# ---------------------------------------------------------------------------

shell: ## Open Django shell_plus
	$(EXEC) shell_plus

dbshell: ## Open PostgreSQL shell
	$(COMPOSE) exec db psql -U openh2o -d openh2o

migrate: ## Run database migrations
	$(EXEC) migrate

makemigrations: ## Generate new migration files
	$(EXEC) makemigrations

createsuperuser: ## Create admin user
	$(EXEC) createsuperuser

collectstatic: ## Collect static files
	$(EXEC) collectstatic --noinput

check: ## Run Django system checks (deployment readiness)
	$(EXEC) check --deploy

test: ## Run test suite
	$(EXEC) test

# ---------------------------------------------------------------------------
# Seed Data
# ---------------------------------------------------------------------------

seed: ## Run ALL required seed commands (reference data)
	$(EXEC) seed_data

seed-roles: ## Seed user roles
	$(EXEC) seed_roles

seed-water-types: ## Seed water type definitions
	$(EXEC) seed_water_types

seed-data-sources: ## Seed external data source definitions
	$(EXEC) seed_data_sources

seed-report-templates: ## Seed report template definitions
	$(EXEC) seed_report_templates

seed-water-right-types: ## Seed water right type definitions
	$(EXEC) seed_water_right_types

seed-well-types: ## Seed well type definitions
	$(EXEC) seed_well_types

demo: ## Load demo data (fictional Demo Valley GSA)
	$(EXEC) seed_demo_data

flush-demo: ## Delete and reload demo data
	$(EXEC) seed_demo_data --flush

kaweah: ## Load Kaweah Subbasin demo data (real basin data)
	$(EXEC) seed_kaweah

flush-kaweah: ## Delete and reload Kaweah data
	$(EXEC) seed_kaweah --flush

# ---------------------------------------------------------------------------
# Health & Maintenance
# ---------------------------------------------------------------------------

health: ## Run health checks
	$(EXEC) run_health_checks

prune: ## Prune old staging data and sync logs
	$(EXEC) prune_old_data

# ---------------------------------------------------------------------------
# Composite Targets
# ---------------------------------------------------------------------------

fresh: down ## Full reset: destroy volumes, rebuild, migrate, seed, demo
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build
	@echo "Waiting for database to be healthy..."
	@sleep 5
	$(EXEC) migrate
	$(EXEC) seed_data
	$(EXEC) seed_demo_data
	$(EXEC) seed_kaweah
	@echo ""
	@echo "Fresh environment ready. Run 'make createsuperuser' to create an admin."
