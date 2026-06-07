# Open Water Accounting Platform - Development Shortcuts
#
# Usage: make <target>
# Run `make help` to see all available targets.

COMPOSE = docker compose
EXEC    = $(COMPOSE) exec web python manage.py

# Build version stamp from git, baked into the image and shown in the app footer.
# Recomputed inside `deploy` after the reset so it reflects the deployed commit.
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
export APP_VERSION = $(VERSION)

.PHONY: help up down build logs shell dbshell migrate makemigrations \
        createsuperuser collectstatic seed seed-roles seed-water-types \
        seed-data-sources seed-report-templates seed-water-right-types \
        seed-well-types demo flush-demo kaweah flush-kaweah merced teardown-demo \
        check test fresh verify-clean install-cron show-cron sync guard-prod deploy

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

up: guard-prod ## Start all services (refuses in prod — use `make deploy`)
	$(COMPOSE) up -d --build

down: guard-prod ## Stop all services (refuses in prod)
	$(COMPOSE) down

build: guard-prod ## Rebuild containers without starting (refuses in prod — use `make deploy`)
	$(COMPOSE) build

deploy: ## Ship origin/main to THIS checkout (prod-safe: rebuilds web only — no data loss, no logout)
	git fetch origin
	git reset --hard origin/main
	APP_VERSION=$$(git describe --tags --always --dirty 2>/dev/null || echo dev) $(COMPOSE) up -d --build web
	@echo ""
	@echo "Deployed $$(git describe --tags --always --dirty). Web container rebuilt; database untouched."

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

verify-clean: ## Assert this install has reference data only (no demo/agency content)
	$(EXEC) verify_clean_install

test: ## Run test suite (pinned to local settings; --ds outranks the container's prod env)
	$(COMPOSE) exec web python -m pytest tests/ -v --ds=config.settings.local

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

merced: ## Load the full Merced Subbasin demo (boundary, hydrography, GSAs, rights/PODs, selected parcels, recharge)
	$(EXEC) seed_merced

teardown-demo: ## Remove ALL Kaweah + Demo-Valley demo data (keeps Merced + shared reference data)
	$(EXEC) teardown_demo

# ---------------------------------------------------------------------------
# Health & Maintenance
# ---------------------------------------------------------------------------

health: ## Run health checks
	$(EXEC) run_health_checks

prune: ## Prune old staging data and sync logs
	$(EXEC) prune_old_data

install-cron: ## Install crontab.txt entries (appends, preserves existing entries)
	(crontab -l 2>/dev/null; cat crontab.txt) | crontab -
	@echo "Cron entries installed. Run 'make show-cron' to verify."

show-cron: ## Display current crontab entries
	crontab -l

sync: ## Run sync_all manually (syncs all active data sources)
	$(EXEC) sync_all

# ---------------------------------------------------------------------------
# Composite Targets
# ---------------------------------------------------------------------------

# Safety guard: destructive resets refuse to run in a checkout that carries a
# .production-lock marker (placed only in the live deployment). This is a human-
# error backstop on top of the real protection — prod and staging are separate
# compose projects with separate database volumes, so a reset can only ever wipe
# the data of the checkout it runs in. To intentionally reset a locked checkout,
# remove .production-lock, run the command, then recreate the marker.
guard-prod:
	@if [ -f .production-lock ]; then \
		echo ""; \
		echo "  REFUSING: this is a PROTECTED (production) checkout."; \
		echo "  '$(MAKECMDGOALS)' rebuilds or resets prod — it can interrupt the live demo, and a reset would wipe its data."; \
		echo "  To SHIP code to prod safely (rebuild web only, no logout): make deploy"; \
		echo "  To do DEV work: use the staging checkout instead (~/openh2o-staging)."; \
		echo "  To override here on purpose: rm .production-lock  (then recreate it after)."; \
		echo ""; \
		exit 1; \
	fi

fresh: guard-prod down ## Full reset: destroy volumes, rebuild, migrate, seed, Merced demo
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build
	@echo "Waiting for database to be healthy..."
	@sleep 5
	$(EXEC) migrate
	$(EXEC) seed_data
	$(EXEC) seed_merced
	@echo ""
	@echo "Fresh environment ready (Merced Subbasin demo). Run 'make createsuperuser' to create an admin."
