<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Security Policy

## Reporting a vulnerability

Please report security problems privately, not in a public GitHub issue. Use
GitHub's private vulnerability reporting on this repository: open the
**Security** tab and choose **Report a vulnerability**. That starts a
confidential thread with the maintainer, who aims to reply within a few days.

## Scope

OpenH2O is self-hosted software, and each site serves one organization. The most
useful reports concern the code in this repository: sign-in, access control, data
exposure, injection, and the adapters that fetch external data.

A misconfiguration in an operator's own site, such as a weak `.env` file or an
open database port, is the operator's to fix. A setting OpenH2O ships with by
default that you believe is unsafe is in scope, and we want to hear about it.

## Supported versions

OpenH2O is a young project. The supported version is a recent `main`. Security
fixes land there, and every push to `main` runs a clean-install check and the
test suite on GitHub. Tags mark milestones, not security baselines, and can be
several weeks behind `main`. Run a recent `main` to stay current.

A release puts one commit from `main` on the live demo at openh2o.com. Its
checks run before it goes out, and it goes out only if they pass. After it goes
out, a check of the live home page runs, and a failure there puts the previous
release back. The footer of every page shows the most recent tag before the
commit the site was built from. That tag is not always the latest release. When
the build is past that tag, the footer also shows the number of commits since
the tag and the commit. On 22 November 2026, openh2o.com showed
v3.1-5-gffb4ee54: tag v3.1, five commits later, commit ffb4ee54. To run what
openh2o.com runs, use the commit its footer names.
