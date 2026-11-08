# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Dockerfile HEALTHCHECK must give a first start time to finish its setup (152-03)."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _healthcheck_options():
    text = (REPO_ROOT / "Dockerfile").read_text()
    # Join backslash continuations so the whole instruction is one line.
    text = re.sub(r"\\\n", " ", text)
    line = next(line_ for line_ in text.splitlines() if line_.startswith("HEALTHCHECK"))
    return dict(re.findall(r"--([a-z-]+)=(\d+)s", line))


def test_first_start_has_at_least_180_seconds_before_failures_count():
    options = _healthcheck_options()
    assert int(options.get("start-period", 0)) >= 180, options


def test_start_interval_is_set_so_a_ready_site_is_noticed_quickly():
    assert "start-interval" in _healthcheck_options()
