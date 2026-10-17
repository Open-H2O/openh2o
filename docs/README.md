<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# docs/

This folder holds two kinds of file: guides for running a site, and records of
past design decisions. For an overview, start at the top of the repository:
[README.md](../README.md) says what OpenH2O is, [DEPLOY.md](../DEPLOY.md) how to
run it and [CONTRIBUTING.md](../CONTRIBUTING.md) how to change it.

## Guides for running and extending a site

| File | What it covers |
|---|---|
| [AI-OPERATOR-GUIDE.md](AI-OPERATOR-GUIDE.md) | Takes an AI agent from a bare server to a running site with demonstration data. Start here if an agent is doing the installation. |
| [DATA-IMPORT.md](DATA-IMPORT.md) | How to load an organization's existing records. |
| [DATA-STANDARDS.md](DATA-STANDARDS.md) | The crosswalk from each source's codes to OpenH2O's measured quantities, and the `check_conformance` check that keeps it complete when you add an adapter. `crosswalk.csv` holds its data. |
| [water-budget-terms.md](water-budget-terms.md) | How each of OpenH2O's water quantities lines up with DWR's draft water-budget handbook and the C2VSimFG model's budget columns, and which quantities have no state term. |
| [earth-engine-tier-setup.md](earth-engine-tier-setup.md) | Setting up the optional Earth Engine tier for satellite ET. |
| [ROADMAP.md](ROADMAP.md) | What is finished and what comes next. |

## Design and audit history

These files are records, not instructions. Code comments and tests cite several
of them by name, so they stay here: moving or deleting one would break a
reference.

| File | Cited by |
|---|---|
| [2.0-UX-PATTERN-SPEC.md](2.0-UX-PATTERN-SPEC.md) | The "Bucket 1/2/3" page vocabulary, cited in `accounting/views.py`, `surface/views.py` and `reporting/views.py`. |
| [2.0-ACCESSIBILITY-AUDIT.md](2.0-ACCESSIBILITY-AUDIT.md) | The WCAG 2.1 AA and Section 508 fixes, cited in `tests/test_views.py`. |
| [drinking-copy-audit-2026-07-30.md](drinking-copy-audit-2026-07-30.md) | The measurements behind DESIGN.md's copy rules, cited in `tests/test_drinking_readability.py`. |
| [2.0-UX-ROADMAP.md](2.0-UX-ROADMAP.md) | The 2.0 interface plan. Nothing cites it. |
| [2.0-PHASE-F-DESIGN-PROPOSAL.md](2.0-PHASE-F-DESIGN-PROPOSAL.md) | The Phase F color and contrast proposal. Nothing cites it. |

The design system in use is [DESIGN.md](../DESIGN.md) with
`static/css/tokens.css`.
