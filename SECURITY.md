<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public GitHub issue.

**Preferred:** use GitHub's private vulnerability reporting on this repository
(the **Security** tab → **Report a vulnerability**). It opens a confidential
thread with the maintainers.

If you cannot use that, email **security@openh2o.com** with the details and a way
to reach you. We aim to acknowledge within a few days.

## Scope

OpenH2O is single-tenant, self-hosted software, so the most useful reports concern
the code in this repository — authentication, access control, data exposure,
injection, or the external data-sync adapters.

A misconfiguration in one operator's own deployment (a weak `.env`, an exposed
database port) is theirs to fix. But if you believe a **default we ship** is
unsafe, that is in scope and we want to hear about it.

## Supported versions

This is a young project; security fixes land on `main`. Run a recent `main`, or
the latest tag, to stay current.
