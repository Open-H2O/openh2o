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
        seed-well-types demo flush-demo merced teardown-demo \
        check test test-droppable guard-fresh fresh snapshot-demo reset-demo calc-rebuild verify-clean install-cron show-cron sync guard-prod guard-demo-host deploy rebuild-golden \
        verify-candidate promote-golden ci-gate release upgrade

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

up: guard-prod ## Start all services (refuses under .production-lock; to upgrade a live site use `make upgrade`)
	$(COMPOSE) up -d --build

down: guard-prod ## Stop all services (refuses in prod)
	$(COMPOSE) down

build: guard-prod ## Rebuild containers without starting (refuses under .production-lock; to upgrade a live site use `make upgrade`)
	$(COMPOSE) build

# Which ref `deploy` ships. A deliberate branch-deploy door: it lets a release be
# rehearsed against a throwaway branch (which is how the refusal path is proved)
# and it retires the old manual workaround of resetting to a branch first
# instead of running make deploy.
REF ?= origin/main

# ISS-106: a REFUSED promotion has to alert somebody, and it did not.
#
# `scripts/_demo-lib.sh` reads OPENH2O_NTFY_URL out of the SHELL environment,
# and promote-golden.sh runs on the HOST. Nothing under scripts/ sources .env —
# that file is consumed by `docker compose` to populate the CONTAINER's
# environment, so a key placed there never reaches the deploy path. The topic
# was set only inline on the crontab lines, which is why the nightly jobs alert
# and `make deploy` was silent.
#
# So the Makefile lifts the key out of .env itself and exports it for every
# recipe. `?=` means an operator's own `OPENH2O_NTFY_URL=… make deploy` still
# wins; a host whose .env has no such key gets an empty value and alerting stays
# disabled exactly as before, which is the case for most deployments.
#
# HARDCODE NO URL HERE. The repository ships the mechanism, never an address —
# this platform is meant to be self-deployed by agencies who have their own.
OPENH2O_NTFY_URL ?= $(shell sed -n 's/^OPENH2O_NTFY_URL=//p' .env 2>/dev/null | tail -1)
export OPENH2O_NTFY_URL

# THE ORDER BELOW IS LOAD-BEARING. Three things about it will look like waste to
# the next person who reads it, and all three are deliberate:
#
#   1. THE REBUILD RUNS AFTER `git reset`, NEVER BEFORE. Gate 3 refuses a
#      candidate whose source_commit is not HEAD, and refuses a -dirty tree.
#      Building first would fail every deploy, and the fix for that is not a
#      bypass flag — it is this ordering.
#   2. THE GATES RUN BEFORE `up -d --build`. Make aborts a target on the first
#      non-zero line, so a refused promotion stops the deploy with the OLD code
#      still serving, the OLD golden still installed, and the demo database
#      untouched. That is the strongest failure state available, and it is why
#      this order was chosen over ship-code-first.
#   3. promote-golden.sh RE-RUNS the gates even though nothing changed since
#      rebuild-golden.sh. That costs a few minutes per deploy and is deliberate
#      (103-02): promotion trusts no marker written by an earlier step. Do not
#      add a fast path.
#
# snapshot-demo.sh is deliberately ABSENT. It re-stamped the golden from the
# live database it had just restored — a closed loop, and the mechanism that let
# production's demonstration content drift out of reach of the repository for
# eight weeks. The repository is the source of truth now.
# THE MARKER IS A POSITIVE OPT-IN, AND THAT DIRECTION IS THE WHOLE POINT.
#
# `deploy` is the maintainer's own path for the public canned demonstration. It
# is destructive to everybody else: `git reset --hard` discards an operator's
# edited Caddyfile and every other local change, and reset-demo.sh restores the
# demonstration snapshot OVER the live database. `make help` lists it beside
# `up` and `down`, and its name is exactly what a new operator reaches for.
#
# So the guard refuses by DEFAULT and only the demo host opts in, rather than
# trying to detect "is this production" — a detector is wrong the one time it
# matters. `.demo-host` means "this checkout IS the public demonstration and its
# database is disposable"; it is gitignored and lives on the demo host alone.
#
# ⚠ DO NOT reuse `.production-lock` for this. It means "this checkout is
# PROTECTED" — the opposite claim — and an agency running real data might very
# reasonably create one after reading guard-prod below, which would arm this
# trap on the exact deployment that must never fire it. Both markers belong on
# the demo host, and they mean opposite things.
guard-demo-host:
	@if [ ! -f .demo-host ]; then \
		echo ""; \
		echo "  REFUSING: 'make deploy' is the demonstration host's target, not an upgrade path."; \
		echo ""; \
		echo "  If it had run here it would have thrown away every local change in this"; \
		echo "  checkout (git reset --hard), rebuilt the canned demonstration database, and"; \
		echo "  RESTORED THAT OVER YOUR LIVE DATABASE — replacing your agency's records with"; \
		echo "  demonstration data. That is correct on the public demo site and catastrophic"; \
		echo "  anywhere else, which is why this checkout has to opt in by name."; \
		echo ""; \
		echo "  TO UPGRADE AN AGENCY DEPLOYMENT, run these four instead — they update the"; \
		echo "  code and the database structure and leave your data alone:"; \
		echo "      git pull origin main"; \
		echo "      docker compose up -d --build"; \
		echo "      docker compose exec web python manage.py migrate"; \
		echo "      docker compose exec web python manage.py collectstatic --noinput"; \
		echo "  They are written out with their explanations in DEPLOY.md, section 11"; \
		echo "  ('Ongoing Operations' -> 'Upgrades')."; \
		echo ""; \
		echo "  If this genuinely IS the public demonstration host, create the marker file"; \
		echo "  once: touch .demo-host"; \
		echo ""; \
		exit 1; \
	fi

# THE CI GATE. `deploy` refuses a commit whose `tests` run on GitHub did not
# pass, BEFORE its `git reset --hard`, so a red, still-running or never-tested
# commit leaves the old code, the old golden and the demo database exactly as
# they were. Three things about it are deliberate:
#
#   1. The gate resolves REF to one full SHA and `deploy` resets to THAT SHA,
#      read back from .deploy-verified-sha, never to $(REF) again. origin/main
#      moving between the check and the reset cannot ship a commit nobody
#      checked.
#   2. .deploy-verified-sha is deleted first thing on every run, so a file left
#      by an earlier run can never stand in for this run's check.
#   3. It FAILS CLOSED. When GitHub cannot be asked (no network, an HTTP error,
#      the anonymous rate limit of 60 requests an hour), the deploy is refused
#      and the reason printed. It does not fall back to running the suite here:
#      the suite needs PostGIS in Docker and takes close to half an hour, on the
#      machine serving the live site. Wait and retry, or check the run by hand.
#
# `make ci-gate REF=<sha>` runs the check alone and changes nothing but the
# marker file. CI_REPO names the repository whose Actions runs are asked; a
# fork that runs its own `tests` workflow sets CI_REPO=<owner>/<name>.
CI_REPO ?= Open-H2O/openh2o

ci-gate: ## Refuse unless REF's `tests` run on GitHub passed (make deploy runs this before its reset); REF=<sha> to check one commit
	@rm -f .deploy-verified-sha
	git fetch origin
	@sha=$$(git rev-parse --verify --quiet "$(REF)^{commit}") || { \
		echo ""; \
		echo "  REFUSING: '$(REF)' is not a commit in this checkout, even after git fetch origin."; \
		echo ""; \
		exit 1; \
	}; \
	python3 scripts/ci_gate.py --fetch --repo "$(CI_REPO)" --workflow tests.yml --sha "$$sha" || { \
		code=$$?; \
		echo ""; \
		echo "  REFUSING to deploy $$sha: its \`tests\` run did not pass, or GitHub could not be asked (ci_gate exit $$code)."; \
		echo "  Nothing was changed. Deploy a commit whose run is green, or wait for this one's run to finish."; \
		echo ""; \
		exit 1; \
	}; \
	echo "$$sha" > .deploy-verified-sha; \
	echo "ci-gate: $$sha passed its tests run; wrote .deploy-verified-sha"

deploy: guard-demo-host ## REFUSES unless this checkout is the demo host (.demo-host) and REF's `tests` run passed (ci-gate) — it resets code to that commit and REPLACES THE LIVE DATABASE with the demonstration snapshot; agencies upgrade via DEPLOY.md §11
	@$(MAKE) --no-print-directory ci-gate REF="$(REF)"
	sha=$$(cat .deploy-verified-sha) && test -n "$$sha" && git reset --hard "$$sha"
	@echo ""
	@echo "Building the demonstration database from this commit (nothing is promoted yet)…"
	bash scripts/rebuild-golden.sh
	@echo ""
	@echo "Running the four promotion gates. A refusal here stops the deploy with the old code and the old golden both still in place…"
	bash scripts/promote-golden.sh
	# up the WHOLE stack, not just web: caddy must be recreated so it picks up
	# the readiness gate (depends_on: service_healthy) and reloads the Caddyfile
	# (the lb_try_duration retry). `up -d --build web` alone leaves caddy on its
	# old config, so a Caddyfile/compose change would silently never deploy.
	APP_VERSION=$$(git describe --tags --always --dirty 2>/dev/null || echo dev) $(COMPOSE) up -d --build
	@echo ""
	@echo "Restoring the newly promoted golden into the live database…"
	FORCE=1 bash scripts/reset-demo.sh
	@echo ""
	@echo "Deployed $$(git describe --tags --always --dirty)."
	@echo "  The demonstration database was BUILT from this commit, passed all four gates,"
	@echo "  and was promoted to golden (the previous golden is backed up beside it as"
	@echo "  golden.dump.bak-pre-<version>-<date>). The live database now holds that build,"
	@echo "  and so will every nightly reset until the next deploy."

# An agency's upgrade, and NOT `make deploy` (the demonstration host's own target, above). It is
# deliberately not behind guard-prod: upgrading a live site is its job, so it runs under a
# .production-lock too. scripts/upgrade.sh backs up first, stops if the backup fails, and
# computes the new version itself AFTER it updates the code, because APP_VERSION at the top of
# this file is worked out when make starts, before the update.
upgrade: ## Back up, update the code, rebuild and check; stops if the backup fails (an agency's upgrade; allowed under .production-lock)
	@bash scripts/upgrade.sh

# `make deploy` checks before it ships and nothing after. `make release` (and deploy.sh, which
# runs the same script from origin/main) runs it, then asks the live home page for its title and
# the new version, and when that fails puts the previous code, web image and demonstration
# database back in the same run. Exit codes are in the header of scripts/release.sh.
release: guard-demo-host ## make deploy, then a smoke test of the live home page; a failure puts the previous release back (scripts/release.sh); REF=<sha>
	bash scripts/release.sh REF="$(REF)"

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

guard-fresh: ## Fail loudly if the web image's source has drifted from the working tree (ISS-075)
	@COMPOSE="$(COMPOSE)" bash scripts/assert-image-fresh.sh

test: guard-fresh ## Run test suite (pinned to local settings; --ds outranks the container's prod env; every module on, reporting included)
	$(COMPOSE) exec -e OPENH2O_MODULES=all web python -m pytest tests/ -v --ds=config.settings.local

test-droppable: guard-fresh ## Prove every optional module can be dropped (see tests/droppability/README.md)
	$(COMPOSE) exec -e OPENH2O_MODULES=all web python -m pytest tests/test_droppability_acceptance.py -v --ds=config.settings.local

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

rebuild-golden: ## Build a candidate demo database from the repository in a disposable stack (does NOT promote it)
	bash scripts/rebuild-golden.sh

verify-candidate: ## Run the four promotion gates against candidate.dump (read-only; promotes nothing)
	bash scripts/verify-candidate.sh

promote-golden: ## Verify the candidate and, only if all four gates pass, install it as the golden snapshot
	bash scripts/promote-golden.sh

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
		echo "  '$(MAKECMDGOALS)' stops, rebuilds or resets this site, and a reset deletes its records."; \
		echo "  To upgrade this site to a new version: make upgrade (it backs up first)."; \
		echo "  For development work, use a separate checkout that has no .production-lock."; \
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
	# --allow-prod-clobber because this target has ALREADY destroyed the volumes
	# two lines up. On a DEBUG=False deployment seed_merced_operations' guard
	# would otherwise stop the sequence at step 3 of 10 and leave the database
	# half-seeded (ISS-095) — refusing to clobber data this target just deleted.
	$(EXEC) seed_merced --allow-prod-clobber
	@echo ""
	@echo "Fresh environment ready (Merced Subbasin demo). Run 'make createsuperuser' to create an admin."

# Kept as an explicitly-labelled MANUAL escape hatch, not part of any automated
# path. It stamps a golden from whatever the live database happens to hold, which
# is the photocopy habit this milestone replaced — so what it writes is temporary
# by construction.
snapshot-demo: ## ESCAPE HATCH: stamp a golden from the LIVE database — the next `make deploy` REPLACES it (the repository is the source of truth)
	bash scripts/snapshot-demo.sh

reset-demo: ## Restore the demo DB to its golden snapshot NOW (wipes visitor-added data); the same script runs nightly via cron
	bash scripts/reset-demo.sh

calc-rebuild: ## Re-run accounting calc for PERIOD=YYYY-MM and re-stamp the golden — TEMPORARY, the next deploy replaces it (durable fix = change the seed)
	@test -n "$(PERIOD)" || { echo "Usage: make calc-rebuild PERIOD=YYYY-MM"; exit 1; }
	$(EXEC) run_calculations --period $(PERIOD)
	# The snapshot call stays. Without it a recalculation would survive until the
	# next nightly reset and then vanish with no warning at all, which is worse
	# than a golden everyone knows is temporary.
	bash scripts/snapshot-demo.sh
	@echo ""
	@echo "Recalculated $(PERIOD) and re-stamped the golden snapshot."
	@echo "  This golden is TEMPORARY: the next 'make deploy' rebuilds the demonstration"
	@echo "  from the repository and replaces it. The durable fix for a calculation the"
	@echo "  demonstration should always show is to change the seed, commit it, and deploy."
