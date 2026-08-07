# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demonstration rebuild must create every table `migrate` does not.

**The defect this guards, caught by gate 4 on 2026-08-07.** A production
promotion was refused because 1 page of 1,952 returned 500:
``/datasync/monitoring/`` died on ``relation "feedback_cache" does not exist``.
``datasync/views.py::monitoring_dashboard`` calls
``OpenETAdapter().account_status()``, whose first statement is a ``cache.get``,
and the project's cache backend is the **database** — so that read needs a table
no migration creates.

**Why the rebuild lost it.** ``entrypoint.sh``'s no-argument boot chain runs
collectstatic + migrate + createcachetable + ensure_superuser.
``scripts/rebuild-golden.sh`` deliberately bypasses that chain and calls each
management command itself, because ``ensure_superuser`` would bake the
checkout's ``.env`` admin into the candidate — the exact mechanism by which
staging admin rows once reached production, and the reason that script carries
the rule **the candidate must contain zero user rows**. Avoiding the user row
silently took the cache table with it.

The two are not in tension: ``createcachetable`` creates a TABLE and no rows, so
running it explicitly satisfies the zero-user-rows rule rather than weakening it.

This test reads the shell script rather than the running database on purpose.
The database is rebuilt from this script, so the script is the thing that can
regress; a passing crawl on one candidate proves nothing about the next one.
"""
import re
from pathlib import Path

REBUILD_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "rebuild-golden.sh"
)


def _steps(script_text):
    """The management commands the rebuild runs, in order, ignoring comments."""
    steps = []
    for line in script_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = re.match(r"^run_step\s+([\w-]+)", stripped)
        if match:
            steps.append(match.group(1))
    return steps


def test_the_rebuild_script_exists_where_the_deploy_expects_it():
    assert REBUILD_SCRIPT.is_file(), f"{REBUILD_SCRIPT} is missing"


def test_the_rebuild_creates_the_database_cache_table():
    """Without this the candidate 500s on any page that reads the cache."""
    steps = _steps(REBUILD_SCRIPT.read_text())
    assert "createcachetable" in steps, (
        "scripts/rebuild-golden.sh no longer runs `createcachetable`. The "
        "database cache table is not created by any migration, and the boot "
        "chain that used to create it is deliberately bypassed by this script. "
        "A candidate built without it returns 500 on /datasync/monitoring/ and "
        "the promotion gate will refuse the deploy."
    )


def test_the_cache_table_is_created_before_anything_is_seeded():
    """Seeding runs application code, which is free to read the cache."""
    steps = _steps(REBUILD_SCRIPT.read_text())
    assert "createcachetable" in steps and "seed_data" in steps
    assert steps.index("createcachetable") < steps.index("seed_data"), (
        "`createcachetable` must run before the seed steps — a seed command is "
        "ordinary application code and may read the cache."
    )


def test_the_rebuild_still_refuses_to_create_a_superuser():
    """The rule the bypass exists to protect, pinned beside the fix.

    `ensure_superuser` in this script would bake the checkout's .env admin into
    the candidate. That is how staging admin rows once reached production.
    """
    steps = _steps(REBUILD_SCRIPT.read_text())
    assert "ensure_superuser" not in steps, (
        "scripts/rebuild-golden.sh must never run `ensure_superuser` — the "
        "candidate must contain zero user rows."
    )
