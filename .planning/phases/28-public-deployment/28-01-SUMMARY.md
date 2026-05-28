---
phase: 28-public-deployment
plan: 01
subsystem: infra
tags: [cloudflare-tunnel, cloudflared, caddy, django-production, deployment, dns]
requires: [26]
provides:
  - openh2o.com publicly reachable over HTTPS via Cloudflare Tunnel
  - Django production settings live on Butler (DEBUG=False)
  - Demo login account for showing off the platform
affects: [27-02, 20, 21]
tech-stack:
  added:
    - cloudflared 2026.5.2 (systemd service on Butler)
  patterns:
    - Cloudflare Tunnel (no exposed ports) → Caddy :80 → web:8000
    - Caddy asserts X-Forwarded-Proto=https so Django production SSL redirect doesn't loop
    - Single environment (no staging); the 186-test suite is the deploy gate
key-files:
  created:
    - .planning/phases/28-public-deployment/28-01-PLAN.md
  modified:
    - Caddyfile
    - "Butler ~/openh2o/.env (not in git): DJANGO_SETTINGS_MODULE, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SECRET_KEY"
    - "Butler /etc/cloudflared/config.yml (not in git)"
key-decisions:
  - Public URL = openh2o.com apex (Hostinger domain moved to Cloudflare DNS)
  - Access = app login only; no Cloudflare Access wall
  - Single environment, push straight to production; no staging box
  - cloudflared runs as a locally-managed systemd service (origin cert), not a token/docker tunnel
issues-created: [ISS-012]
duration: single session (part of 2026-05-28 work)
completed: 2026-05-28
---

# Phase 28 Plan 01: Public Deployment (openh2o.com) Summary

The Open Water Accounting Platform is live and public at https://openh2o.com via a Cloudflare Tunnel on Butler, running Django production settings (DEBUG=False), gated by the app's own email login.

## Accomplishments
- **Public HTTPS site.** openh2o.com (Hostinger domain) moved onto Cloudflare DNS; a Cloudflare Tunnel (`openh2o`, id `50ea2a0d…`) on Butler routes the apex → Caddy → Django. No ports exposed — Butler dials out to Cloudflare. Verified 4 edge connections (LAX/SJC), survives `systemctl restart cloudflared`.
- **Production hardening.** Flipped Butler from dev to `config.settings.production`: `DEBUG=False`, fresh `SECRET_KEY`, `ALLOWED_HOSTS=openh2o.com,…`, `CSRF_TRUSTED_ORIGINS=https://openh2o.com`. `manage.py check --deploy` clean. Confirmed a 404 returns a plain page with zero Django debug/stack-trace leakage.
- **Redirect-loop fix.** Caddy now sends `X-Forwarded-Proto https` to the app, so production `SECURE_SSL_REDIRECT` + `SECURE_PROXY_SSL_HEADER` don't bounce tunnel traffic forever.
- **End-to-end login verified.** Drove a real browser through openh2o.com, logged in with a new demo account, landed on the dashboard. Email auth + CSRF + secure cookies all work over the tunnel. Computed styles confirm the dark OKLCH theme + Public Sans load (5 stylesheets). Screenshot: `~/Desktop/Screenshots/Claude/openh2o-public-dashboard-2026-05-28.png`.
- **Demo account:** `demo@openh2o.com` / `OpenWaterDemo2026` (regular user, verified email, not admin).

## Steps that required the user (human-action)
- Added openh2o.com to Cloudflare + switched Hostinger nameservers from parking (lunar/solar.dns-parking.com) to dawn/rex.ns.cloudflare.com. Propagated in minutes.
- Deleted the imported parking A-record (2.57.91.91) that blocked the tunnel CNAME.
- Authorized `cloudflared` in the browser (origin cert).

## Decisions Made
- openh2o.com apex; app-login only; single environment (no staging); cloudflared as a systemd service using the origin cert.

## Issues Encountered
- API token is scoped to vanderdev.net, so it could not create the openh2o.com zone or delete the parking DNS record — those were done by the user in the dashboard. Not a blocker, just a permissions boundary.
- Logged **ISS-012**: Postgres still uses the default password `openh2o` (low risk — DB not internet-exposed; rotate before real data).

## Verification
- https://openh2o.com → 200 (homepage), login 200, no redirect loop, valid cert.
- DEBUG=False; `check --deploy` clean; 404 leaks nothing.
- Static CSS + theme tokens load; demo login reaches dashboard.
- cloudflared survives restart.

## Next Step
- **Final human sign-off pending** (user to eyeball the live site next session) — all automated/visual checks pass.
- Run **27-02** (Allocation → "Water Budget" terminology sweep): the dashboard table column and sidebar still say "Allocation". Do this before the real demo.
- Then optional: ISS-011 (login page polish), ISS-012 (rotate DB password), Phase 20 (AI Operator Guide).
