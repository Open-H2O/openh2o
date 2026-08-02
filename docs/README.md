<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# docs/

Two kinds of file live here, and telling them apart saves you reading the wrong
one. Start from the root: [README.md](../README.md) for what OpenH2O is,
[DEPLOY.md](../DEPLOY.md) to run it, [CONTRIBUTING.md](../CONTRIBUTING.md) to
change it.

## For running and extending a deployment

| File | What it answers |
|---|---|
| [AI-OPERATOR-GUIDE.md](AI-OPERATOR-GUIDE.md) | Walks an AI agent from a bare server to a running, seeded instance. Start here if an agent is doing the deployment. |
| [DATA-IMPORT.md](DATA-IMPORT.md) | Getting an agency's existing data in. |
| [DATA-STANDARDS.md](DATA-STANDARDS.md) | The observed-property crosswalk and the `check_conformance` gate — what "born compliant" means and how to keep it true when you add an adapter. `crosswalk.csv` is its data. |
| [earth-engine-tier-setup.md](earth-engine-tier-setup.md) | Standing up the OpenET / Earth Engine tier, which is optional. |
| [ROADMAP.md](ROADMAP.md) | Where the product is going. |

## Design and audit history

Not instructions. These record decisions the code still depends on, which is why
they are versioned here rather than thrown away — several are cited by name from
code comments and tests, so moving or deleting one breaks a reference.

| File | Cited by |
|---|---|
| [2.0-UX-PATTERN-SPEC.md](2.0-UX-PATTERN-SPEC.md) | The "Bucket 1/2/3" page vocabulary, referenced from `accounting/views.py`, `surface/views.py`, `reporting/views.py`. |
| [2.0-ACCESSIBILITY-AUDIT.md](2.0-ACCESSIBILITY-AUDIT.md) | The WCAG 2.1 AA / Section 508 remediation, referenced from `tests/test_views.py`. |
| [drinking-copy-audit-2026-07-30.md](drinking-copy-audit-2026-07-30.md) | The measured evidence behind DESIGN.md's copy rules, referenced from `tests/test_drinking_readability.py`. |
| [2.0-UX-ROADMAP.md](2.0-UX-ROADMAP.md) | Historical — the 2.0 interface plan. Nothing depends on it. |
| [2.0-PHASE-F-DESIGN-PROPOSAL.md](2.0-PHASE-F-DESIGN-PROPOSAL.md) | Historical — the Phase F colour/contrast proposal. Nothing depends on it. |

The live design system is [DESIGN.md](../DESIGN.md) and
`static/css/tokens.css`, not anything in this section.
