<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Maintainer operations

**This file describes the hosts the maintainer runs OpenH2O on — openh2o.com and
its staging twin — not how to run your own.** If you are deploying OpenH2O,
[DEPLOY.md](DEPLOY.md) is your file and this one will only confuse you: the
paths, hostnames and the standing staging login below exist on one specific
Tailscale network and mean nothing off it.

It is versioned here rather than kept out of the repo because it is operational
truth an agent working on this codebase needs, and because keeping it beside the
code is what stops it drifting from the code.

## Staging & production access (READ before authenticating to either)

**Staging login is standing, documented, and NON-SECRET by design.**
`admin@staging.local` / `staging-demo-2026`, applied by `ensure_superuser` from
`~/openh2o-staging/.env` on every container boot (so it survives rebuilds and
`make fresh`). It is intentionally shareable in plain text — the Tailscale
network is the real gate, exactly like AgenticOS/VanderOps. Do **not** treat it
as a secret, do **not** store it in Bitwarden, and do **not** mirror it on prod.

- **Never invent access.** If a login does not work, the answer is in this file
  or `~/dotfiles/docs/INFRASTRUCTURE.md` (line ~193) — read it. Never create an
  account, generate a password, or hand-build identity in a shared environment:
  staging's whole value is that its state is reproducible from config. A
  hand-made account is undocumented drift in the one place that must have none.
  (Incident 2026-07-20: post-mortem in
  `~/Documents/Infrastructure/Claude-Tooling/staging-environment-mutation-postmortem-2026-07-20.md`.)
- **Two deployments on Butler.** `~/openh2o` = PRODUCTION (openh2o.com);
  `~/openh2o-staging` = STAGING. Confirm which with
  `docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project.working_dir"}}'`
  before touching anything.

  **What staging runs, and what it does NOT override (2026-08-29, ISS-137).**
  Staging runs the **tracked** `Caddyfile` and the **tracked** `docker-compose.yml`
  caddy volume list. The only staging-specific override is the host port, in the
  untracked `~/openh2o-staging/docker-compose.override.yml`, and it exists because
  production's caddy holds host ports 80 and 443 on this same machine.

  - Staging is reached at `https://butler.tail7ae369.ts.net` through
    `tailscale serve` → `http://127.0.0.1:8081`. It is **tailnet-only**, which is
    why it carries no basic auth and needs none. There is no Cloudflare tunnel to
    staging; `staging.openh2o.com` returns 404.
  - **Do not re-introduce a second Caddyfile.** The retired copy is
    `~/openh2o-staging/Caddyfile.staging.retired-20260829`. Mounting it again puts
    back exactly the class of defect ISS-137 recorded: a shadow file that silently
    stops receiving every change made to the shipped one.
  - ⚠ **`ports: !override` REPLACES the base list rather than merging into it**, so
    a port added to the tracked `docker-compose.yml` will **not** reach staging on
    its own — it has to be added to the override too. That is the one piece of the
    original defect that survives on purpose. The override deliberately carries no
    `volumes:` key, so volumes DO merge through from the tracked file.
- **Staging deploy** = git checkout on Butler: `git fetch && git reset --hard
  origin/main`, then `docker compose up -d --build web` (code is baked into the
  image, not bind-mounted — a sync alone changes nothing the container serves).

  ⚠ **`--build web` does NOT reload Caddy, and a `Caddyfile` change needs
  `docker compose restart caddy`.** The `Caddyfile` is a BIND MOUNT, so editing
  it changes what the container can read but nothing tells Caddy to re-read it;
  and because the caddy image and service definition are unchanged, `up -d
  --build` leaves that container running untouched. Measured 2026-08-29: a
  `Caddyfile` fix was deployed and staging kept serving the previous config for
  two hours — the container's `StartedAt` was 05:32 PDT against a file mtime of
  07:51 PDT. **Symptom to recognise: the file on disk is right and the served
  behaviour is the old one.** Confirm with
  `docker inspect --format '{{.State.StartedAt}}' $(docker compose ps -q caddy)`
  against the file's mtime, never by re-reading the file.
  Never rsync with `--delete`. **Production deploy is Brent's separate, explicit
  call** — `deploy.sh` / `make deploy` in the prod checkout, never run as a side
  effect.
- **`make deploy` requires a `.demo-host` marker file in the checkout and
  refuses without one.** openh2o.com's production checkout (`~/openh2o`) has it;
  it is gitignored, so it survives `git reset --hard` but does not survive a
  fresh clone — recreate it with `touch .demo-host` if that checkout is ever
  rebuilt. **Staging gets no marker**: it deploys by `git reset --hard
  origin/main` plus `docker compose up -d --build`, never by `make deploy`. The
  marker means "this checkout is the public demonstration and its database is
  disposable", which is the opposite claim to `.production-lock` ("this checkout
  is protected") — both live on the prod checkout and neither replaces the other.
