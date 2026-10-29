<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# docs/

This folder holds the guides for running and extending an OpenH2O site. For an
overview, start at the top of the repository: [README.md](../README.md) says what
OpenH2O is, [DEPLOY.md](../DEPLOY.md) how to run it and
[CONTRIBUTING.md](../CONTRIBUTING.md) how to change it.

| File | What it covers |
|---|---|
| [AI-OPERATOR-GUIDE.md](AI-OPERATOR-GUIDE.md) | Takes an AI agent from a bare server to a running site with demonstration data. Start here if an agent is doing the installation. |
| [DATA-IMPORT.md](DATA-IMPORT.md) | How to load an organization's existing records. |
| [DATA-STANDARDS.md](DATA-STANDARDS.md) | The crosswalk from each source's codes to OpenH2O's measured quantities, and the `check_conformance` check, which reports a kind of measurement with no UCUM unit. `crosswalk.csv` holds its data. |
| [water-budget-terms.md](water-budget-terms.md) | How each of OpenH2O's water quantities lines up with DWR's draft water-budget handbook and the C2VSimFG model's budget columns, and which quantities have no state term. |
| [INSTALL-WITHOUT-DOCKER.md](INSTALL-WITHOUT-DOCKER.md) | Installing OpenH2O directly on a computer, without Docker. |
| [earth-engine-tier-setup.md](earth-engine-tier-setup.md) | Setting up the optional Earth Engine tier for satellite ET. |
| [ROADMAP.md](ROADMAP.md) | What is finished and what comes next. |

The design rules for anyone changing the screens are in [DESIGN.md](../DESIGN.md),
with the colors and sizes in `static/css/tokens.css`.
