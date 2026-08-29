# SPDX-License-Identifier: AGPL-3.0-or-later
"""The outage page's status must agree with the page and the headers it ships with.

**ISS-138, measured live on staging 2026-08-29.** The shipped ``Caddyfile``'s
``handle_errors`` block served ``error-pages/503.html`` as the *body* and set
``Cache-Control: no-store`` and ``Retry-After: 30`` — and set **no status at
all**, so Caddy preserved the originating error's own. An unreachable upstream
is 502, so a real outage answered **502** while the page said "OpenH2O is
starting up" and the header said "come back in 30 seconds". Three signals, two
of them 503 semantics, one of them not. The filename is not the status.

A second defect sat underneath it: the block carried no status list, so it
caught **every** error Caddy produced, including a 404 from the ``/static/*``
``file_server``. A missing stylesheet rendered the outage page — and once the
first defect was fixed in isolation it would have rendered it as a *503*, which
is worse: an uptime monitor would read "whole site down" from one absent file.

**Why this is a file scan and not a live request.** Neither ``caddy validate``
nor ``caddy adapt`` can see either defect — both accepted the broken form and
printed a valid config, which is exactly how this shipped. The live proof (stop
``web``, wait past the 30 s retry budget, read the status line) is recorded in
``.planning/phases/128-staging-runs-the-shipped-files/128-01-EVIDENCE.md`` §5.
This module is the ratchet that keeps the seam closed afterwards.

Every assertion and every control goes through the same :func:`scan`. A control
that exercises a different code path from the gate proves nothing — the lesson
``test_deploy_https_branches.py`` records from Phase 110.
"""

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: ``handle_errors`` plus everything up to the closing brace at its own indent.
_BLOCK = re.compile(
    r"^(?P<indent>[ \t]*)handle_errors(?P<codes>[^\n{]*)\{"
    r"(?P<body>.*?)"
    r"^(?P=indent)\}",
    re.MULTILINE | re.DOTALL,
)

#: ``status 503`` anywhere inside a ``file_server { … }`` sub-block.
_FILE_SERVER_STATUS = re.compile(
    r"file_server[^\n{]*\{(?P<body>.*?)\}", re.DOTALL
)

#: The gateway-class errors that mean "the app did not answer", as opposed to
#: "that file is not there". 503 is included so the block still catches an
#: upstream that returns one itself.
GATEWAY_ERRORS = frozenset({"502", "503", "504"})


@dataclass(frozen=True)
class Outage:
    """What one ``handle_errors`` block actually declares."""

    codes: frozenset
    served_status: str | None
    headers: dict

    @property
    def is_scoped(self) -> bool:
        return bool(self.codes)


def scan(text: str) -> Outage | None:
    """Read the first ``handle_errors`` block out of a Caddyfile source."""
    match = _BLOCK.search(text)
    if match is None:
        return None

    codes = frozenset(match.group("codes").split())
    body = match.group("body")

    served_status = None
    for fs in _FILE_SERVER_STATUS.finditer(body):
        for line in fs.group("body").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "status":
                served_status = parts[1]

    headers = {}
    for line in body.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0] == "header":
            headers[parts[1]] = parts[2].strip('"')

    return Outage(codes=codes, served_status=served_status, headers=headers)


def shipped() -> Outage:
    scanned = scan((REPO_ROOT / "Caddyfile").read_text())
    assert scanned is not None, "the shipped Caddyfile has no handle_errors block"
    return scanned


# --------------------------------------------------------------------------
# Gates — the shipped file
# --------------------------------------------------------------------------


def test_the_outage_page_is_served_with_an_explicit_status():
    """Without this, Caddy keeps the upstream's status and a real outage is 502."""
    assert shipped().served_status == "503", (
        "the outage page must be served with an explicit `status 503` inside "
        "file_server; without it Caddy preserves the originating error's own "
        "status and a real outage answers 502 (ISS-138)"
    )


def test_the_outage_page_is_scoped_to_gateway_errors():
    """Unscoped, a missing static file renders 'OpenH2O is starting up'."""
    assert shipped().codes == GATEWAY_ERRORS, (
        "handle_errors must name 502 503 504; unscoped it also catches a 404 "
        "from the /static/* file_server, so a missing stylesheet renders the "
        "outage page — as a 503, once the status above is set (ISS-138)"
    )


def test_the_status_agrees_with_the_headers_it_ships_with():
    """The three signals must tell a monitor the same story."""
    outage = shipped()
    assert outage.headers.get("Retry-After") == "30"
    assert outage.headers.get("Cache-Control") == "no-store"
    assert outage.served_status == "503", (
        "Retry-After and no-store are 503 semantics ('temporary, come back'); "
        "a status that disagrees with them is the ISS-138 defect"
    )


def test_the_served_file_is_the_one_that_exists():
    """A status of 503 pointing at an absent file is a 503 with no page."""
    body = _BLOCK.search((REPO_ROOT / "Caddyfile").read_text()).group("body")
    assert "/503.html" in body
    assert (REPO_ROOT / "error-pages" / "503.html").is_file()


# --------------------------------------------------------------------------
# Controls — fixture strings, so they keep proving the scanner works after the
# real file changes. Each is the defect as it actually shipped.
# --------------------------------------------------------------------------

#: Exactly the block that shipped before 2026-08-29.
AS_IT_SHIPPED = """\
example.com {
    handle_errors {
        root * /srv/error
        rewrite * /503.html
        file_server
        header Cache-Control "no-store"
        header Retry-After "30"
    }
}
"""

#: The status fixed, the scoping still missing — the half-fix this module
#: exists to stop, because it is worse than the original.
STATUS_ONLY = """\
example.com {
    handle_errors {
        root * /srv/error
        rewrite * /503.html
        file_server {
            status 503
        }
        header Cache-Control "no-store"
        header Retry-After "30"
    }
}
"""


def test_control_the_original_defect_is_detected():
    """The scanner must see the absent status, or the gate above cannot fail."""
    outage = scan(AS_IT_SHIPPED)
    assert outage is not None
    assert outage.served_status is None
    assert not outage.is_scoped


def test_control_the_half_fix_is_detected():
    """Setting the status without scoping is caught as its own defect."""
    outage = scan(STATUS_ONLY)
    assert outage.served_status == "503"
    assert not outage.is_scoped, "an unscoped block must not read as scoped"


def test_control_the_scanner_reads_headers_it_is_given():
    """A scanner that returned {} for everything would pass gate 3 blindly."""
    assert scan(AS_IT_SHIPPED).headers == {
        "Cache-Control": "no-store",
        "Retry-After": "30",
    }


def test_control_a_file_with_no_block_is_not_read_as_a_passing_one():
    """`None` must not be mistaken for a compliant block."""
    assert scan("example.com {\n    respond \"hi\"\n}\n") is None
