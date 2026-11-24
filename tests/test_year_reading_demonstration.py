# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every figure the year's pages print on the Merced demonstration stays exactly as it was.

The same comparison as ``tests/test_year_reading_figures.py``, on the
demonstration itself (``load_demonstration``: 76 use areas, a finalized year and
an open one). Loading it takes many minutes, so the test is marked ``release``:
tests.yml and ``make test`` leave it out and deploy-checks.yml runs it before a
release. ``tests/data/demonstration_figures_before.json`` was written by this
module on the commit before the pages read the year at once:

    docker compose exec -T -e OPENH2O_MODULES=all -e YEAR_FIGURES_WRITE=1 web python -m pytest \
        tests/test_year_reading_demonstration.py --ds=config.settings.local -m release

With ``-e YEAR_FIGURES_OUT=<path>`` instead, it writes there and leaves the stored file as it is;
``make figures-moved`` does that and lists every figure that differs (scripts/figures_moved.py).

It was written again, the same way, once a headgate's delivery was divided by
exact shares with the rounding leftover to the largest part: that change moves
printed figures by design, and the commit that rewrote the file says which. A
figure that moves for any other reason is a fault to find, not a file to rewrite.
"""
import io
import json
from pathlib import Path

import pytest
from django.core.management import call_command

from tests.test_year_reading_figures import WRITE, everything, figures_out_path, first_difference

pytestmark = pytest.mark.django_db

FILE = Path(__file__).parent / "data" / "demonstration_figures_before.json"


@pytest.mark.release
def test_every_figure_on_the_demonstration_is_as_it_was_before_the_pages_read_the_year_at_once():
    call_command("load_demonstration", stdout=io.StringIO())
    now = json.loads(json.dumps(everything()))
    assert now["WY 2024-2025"]["figures"] and now["WY 2025-2026"]["figures"]
    out = figures_out_path(FILE)
    if WRITE or out != FILE:
        out.write_text(json.dumps(now, indent=1) + "\n")
        pytest.skip(f"wrote {out}")
    difference = first_difference(json.loads(FILE.read_text()), now)
    assert difference is None, f"first figure that differs (where, before, now): {difference}"
