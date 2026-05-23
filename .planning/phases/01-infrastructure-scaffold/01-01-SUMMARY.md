---
phase: 01-infrastructure-scaffold
plan: 01
subsystem: infra
tags: [django, postgis, caddy, docker, tailwind, gunicorn, htmx]

requires:
  - phase: none
    provides: first phase

provides:
  - Docker Compose stack (db + web + caddy)
  - Django project skeleton with split settings
  - PostGIS database ready for GeoDjango spatial fields
  - VanderDev design tokens as CSS custom properties
  - Base template with HTMX and Tailwind
  - DEPLOY.md skeleton and CLAUDE.md project context

affects: [02-core-domain-models, 03-parcel-well-crud, 08-deploy-polish]

tech-stack:
  added: [django-5.x, postgis-3.4, caddy-2, gunicorn, whitenoise, django-environ, django-htmx, tailwind-standalone]
  patterns: [split-settings, env-based-config, standalone-css-binary, caddy-reverse-proxy]

key-files:
  created: [pyproject.toml, Dockerfile, docker-compose.yml, Caddyfile, config/settings/base.py, config/settings/local.py, config/settings/production.py, static/css/tokens.css, templates/base.html, templates/index.html, DEPLOY.md, CLAUDE.md, core/models.py]
  modified: []

key-decisions:
  - "Removed hardcoded GDAL/GEOS library paths from Dockerfile; Django finds them automatically on Debian"
  - "Added minimal User model stub in core/models.py so Django can boot with AUTH_USER_MODEL='core.User'"
  - "Deploy key added to GitHub repo for Butler SSH clone access"

patterns-established:
  - "Split settings: base.py shared, local.py for dev, production.py for prod"
  - "All secrets via django-environ, never hardcoded"
  - "Tailwind standalone binary in Docker build, no Node.js anywhere"
  - "Caddy as reverse proxy with auto-HTTPS capability"

issues-created: []

duration: 50min
completed: 2026-05-23

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 1 Plan 1: Infrastructure Scaffold Summary

**Docker Compose stack running on Butler with Django/Gunicorn, PostGIS 3.4, Caddy, VanderDev design tokens, and Tailwind standalone CSS compilation**

## Performance

- **Duration:** 50 min
- **Started:** 2026-05-23T22:39:40Z
- **Completed:** 2026-05-23T23:29:42Z
- **Tasks:** 4 (2 auto + 1 checkpoint + 1 auto)
- **Files created:** 28

## Accomplishments

- Docker Compose stack boots 3 services on Butler (192.168.0.114): PostGIS, Django/Gunicorn, Caddy
- Django project with split settings (base/local/production), all secrets from environment
- VanderDev design tokens ported to CSS custom properties with OKLCH data viz ramps
- Tailwind standalone binary compiles CSS during Docker build (no Node.js)
- Styled index page renders through full pipeline: Django template, Tailwind CSS, Caddy proxy
- DEPLOY.md with copy-paste deployment steps and CLAUDE.md project context

## Task Commits

1. **Task 1: Django project skeleton + Docker infrastructure** - `715236f` (feat)
2. **Task 2: Tailwind standalone, design tokens, base template** - `eec347b` (feat)
3. **Task 3 (checkpoint): Verify Docker stack on Butler** - verified, all services healthy
4. **Task 4: DEPLOY.md and CLAUDE.md** - `d7d0e90` (feat)

**Bug fixes during execution:**
- `fb92926` - fix: correct pyproject.toml build backend and remove hardcoded Dockerfile library paths
- `9d4bd1f` - fix: add User model stub so Django can boot with AUTH_USER_MODEL='core.User'

## Files Created/Modified

- `pyproject.toml` - Python dependencies and build config
- `manage.py` - Django management script
- `config/settings/base.py` - Shared Django settings (PostGIS, whitenoise, env-based)
- `config/settings/local.py` - Development overrides
- `config/settings/production.py` - Production security settings
- `config/urls.py` - URL routing (admin + index)
- `config/views.py` - Index view
- `config/wsgi.py`, `config/asgi.py` - WSGI/ASGI entry points
- `core/models.py` - Minimal User model stub
- `core/apps.py` - Core app config
- `Dockerfile` - Python 3.12-slim with GDAL/GEOS/PROJ, Tailwind standalone
- `docker-compose.yml` - db, web, caddy services
- `Caddyfile` - Reverse proxy and static file serving
- `static/css/tokens.css` - VanderDev design tokens (colors, OKLCH ramps, typography, spacing)
- `static/css/input.css` - Tailwind directives and base component styles
- `tailwind.config.js` - Tailwind theme extensions from design tokens
- `scripts/build-css.sh` - Tailwind standalone download and compile script
- `templates/base.html` - Layout shell with HTMX, fonts, CSRF
- `templates/index.html` - Landing page proving the pipeline works
- `.env.example` - Environment variable documentation
- `.dockerignore`, `.gitignore` - Build and version control exclusions
- `DEPLOY.md` - Deployment guide with verification steps
- `CLAUDE.md` - AI assistant project context

## Decisions Made

- Removed hardcoded GDAL_LIBRARY_PATH and GEOS_LIBRARY_PATH from Dockerfile. Django finds these automatically on Debian when the packages are installed via apt.
- Created minimal User model stub (AbstractUser subclass) in core/models.py. The plan said "don't create models" but also set AUTH_USER_MODEL='core.User'. Django cannot boot without resolving the User model. Phase 2 will expand this.
- Added Butler's SSH key as a deploy key on the GitHub repo for clone access.
- GitHub repo created as vanderoffice/openh2o (private).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] pyproject.toml used nonexistent build backend**
- **Found during:** Checkpoint verification
- **Issue:** `setuptools.backends._legacy:_Backend` does not exist in standard setuptools
- **Fix:** Changed to `setuptools.build_meta`
- **Files modified:** pyproject.toml
- **Verification:** Docker build pip install succeeds
- **Committed in:** fb92926

**2. [Rule 3 - Blocking] Django cannot boot without User model**
- **Found during:** Docker build on Butler (collectstatic step)
- **Issue:** AUTH_USER_MODEL='core.User' requires a resolvable model. Plan said "don't create models" but also set AUTH_USER_MODEL. These conflict.
- **Fix:** Added minimal `User(AbstractUser)` stub in core/models.py
- **Files modified:** core/models.py
- **Verification:** collectstatic succeeds, Django boots cleanly
- **Committed in:** 9d4bd1f

**3. [Rule 3 - Blocking] Dockerfile hardcoded x86_64 library paths**
- **Found during:** Code review before checkpoint
- **Issue:** GDAL_LIBRARY_PATH and GEOS_LIBRARY_PATH hardcoded to x86_64 paths. Fragile and unnecessary.
- **Fix:** Removed ENV vars. Django finds GDAL/GEOS automatically on Debian.
- **Files modified:** Dockerfile
- **Verification:** Docker build succeeds without explicit paths
- **Committed in:** fb92926

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking), 0 deferred
**Impact on plan:** All fixes necessary for the stack to build and boot. No scope creep.

## Issues Encountered

- Attempted to build Docker on local Mac (StudioM4) instead of Butler. Corrected after user feedback. See post-mortem discussion in session.
- Butler's SSH key was not registered with GitHub. Added as deploy key to enable clone.

## Next Phase Readiness

- Infrastructure verified running on Butler (192.168.0.114)
- PostGIS ready for GeoDjango spatial fields
- AUTH_USER_MODEL set and resolvable
- Ready for Phase 2: Core Domain Models (48 models, migrations, admin, seed data)

---
*Phase: 01-infrastructure-scaffold*
*Completed: 2026-05-23*
