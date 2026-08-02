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
- **Staging deploy** = git checkout on Butler: `git fetch && git reset --hard
  origin/main`, then `docker compose up -d --build web` (code is baked into the
  image, not bind-mounted — a sync alone changes nothing the container serves).
  Never rsync with `--delete`. **Production deploy is Brent's separate, explicit
  call** — `deploy.sh` / `make deploy` in the prod checkout, never run as a side
  effect.
