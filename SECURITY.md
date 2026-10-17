<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Security Policy

## Reporting a vulnerability

Please report security problems privately, not in a public GitHub issue. Use
GitHub's private vulnerability reporting on this repository: open the
**Security** tab and choose **Report a vulnerability**. That starts a
confidential thread with the maintainers, who aim to reply within a few days.

## Scope

OpenH2O is self-hosted software, and each site serves one organization. The most
useful reports concern the code in this repository: sign-in, access control, data
exposure, injection, and the adapters that fetch external data.

A misconfiguration in an operator's own site, such as a weak `.env` file or an
open database port, is the operator's to fix. A setting OpenH2O ships with by
default that you believe is unsafe is in scope, and we want to hear about it.

## Supported versions

OpenH2O is a young project. Security fixes land on `main`, and every push to
`main` runs a clean-install check and the test suite on GitHub. The maintainer
updates the live demo at openh2o.com from `main`. Run a recent `main` to stay
current. Tags mark milestones, not security baselines, and can be several weeks
behind `main`.
