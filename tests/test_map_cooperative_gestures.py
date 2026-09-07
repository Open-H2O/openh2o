# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every map hands a plain scroll back to the page.

Maps sit at the top of most pages here. Before Phase 138 a wheel or two-finger
scroll that started over one of them was swallowed by the map and zoomed it, so
the page underneath never moved: the reader had to find a sliver of margin to
scroll past a map at all. MapLibre ships the fix as one option,
``cooperativeGestures``, which lets a plain scroll through to the page and asks
for Cmd/Ctrl+scroll to zoom.

**Why this is a test and not a note in DESIGN.md.** The option is per-map, and
there are eleven maps: two in shared JS and nine initialised inline in a
template. A twelfth added tomorrow without it is invisible until somebody
scrolls that one page and it snags. So this asserts the COUNT as well as the
option, and a new map fails the suite until it opts in or is written into the
exemption list with a reason.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = [ROOT / "static", ROOT / "templates"]

INIT = re.compile(r"new\s+maplibregl\.Map\s*\(")

# Every map that exists today. Eleven, found by grep on 2026-09-06 and
# reconciled against ISS-149's own list before the option was added.
EXPECTED_SITES = 11

# A map allowed to keep swallowing scroll, with the reason. Empty on purpose:
# no map has earned an exemption. An entry here is a design decision.
EXEMPT = {}


def _files():
    for directory in SEARCH_DIRS:
        for pattern in ("*.js", "*.html"):
            yield from sorted(directory.rglob(pattern))


def _init_sites():
    """Every ``new maplibregl.Map(`` as (relpath, line, options_text)."""
    sites = []
    for path in _files():
        text = path.read_text()
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            if not INIT.search(line):
                continue
            # The options object opens on this line; read forward to its close.
            # A dozen lines covers every call site in this codebase and keeps the
            # scan from wandering into the next function.
            options = "\n".join(lines[number - 1 : number + 12])
            sites.append((str(path.relative_to(ROOT)), number, options))
    return sites


class TestEveryMapReleasesTheScroll:
    def test_the_site_count_is_what_we_swept(self):
        """A twelfth map must not slip past the guard below unnoticed."""
        sites = _init_sites()
        listing = "\n  ".join(f"{rel}:{number}" for rel, number, _ in sites)
        assert len(sites) == EXPECTED_SITES, (
            f"Found {len(sites)} map initialisations, expected {EXPECTED_SITES}. "
            "If a map was added, give it cooperativeGestures and raise this "
            "number in the same commit; if one was removed, lower it.\n  "
            + listing
        )

    def test_every_map_carries_cooperative_gestures(self):
        offenders = [
            f"{rel}:{number}"
            for rel, number, options in _init_sites()
            if "cooperativeGestures" not in options and rel not in EXEMPT
        ]
        assert not offenders, (
            "A map initialisation is missing `cooperativeGestures: true`, so a "
            "scroll starting over it zooms the map instead of moving the page:\n  "
            + "\n  ".join(offenders)
        )
