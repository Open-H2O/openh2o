# SPDX-License-Identifier: AGPL-3.0-or-later
"""`DEPLOY.md` §4 and the shipped `Caddyfile` may not contradict each other.

They did, for a year. §4 said *"replace `:80` with your domain for automatic
HTTPS"*; the `Caddyfile`'s own first five lines said that doing exactly that
behind a tunnel makes `SECURE_SSL_REDIRECT` "loop through the tunnel forever."
Two files, one seam, nothing watching it.

Fixing the text without guarding the seam re-arms it on the next edit, so this
module watches the seam rather than the wording. It asserts four things, all of
them structural:

1. §4 carries all three ``<!-- branch: … -->`` markers, exactly once each.
2. A Caddy site address in §4 that carries a hostname with no ``http://``
   prefix appears **only** inside the ``own-certificate`` branch. A bare domain
   offered anywhere else is the original defect returning.
3. The shipped `Caddyfile`'s first site address is still ``:80``. Two of the
   three branches tell the operator to leave the file as shipped, and that
   advice silently becomes wrong the day a domain is committed into it.
4. The `Caddyfile` still carries ``header_up X-Forwarded-Proto https``. The
   ``upstream-terminator`` branch's correctness rests on it, and
   ``production.py``'s ``SECURE_PROXY_SSL_HEADER`` is the other half of the pair.

**Everything goes through one ``scan()``.** Assertions and controls alike. A
control exercising a different code path from the gate proves nothing — Phase
110 learned that one the hard way.

The controls are fixture strings, never the real documents, so they keep proving
the scanner works after the documents themselves change.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# The fence regex is shared with the comprehension gate on purpose: two files
# disagreeing about what a code block is would be the same class of drift this
# module exists to catch. Only the marker keyword differs, so only the marker
# regex is written again below.
from tests.test_operator_vocabulary import FENCE

REPO_ROOT = Path(__file__).resolve().parent.parent

#: ``<!-- branch: own-certificate -->``. Hyphens allowed, unlike the
#: ``defines:`` slugs, because these name a section rather than a vocabulary term.
BRANCH_MARKER = re.compile(r"<!--\s*branch:\s*([A-Za-z0-9_-]+)\s*-->")

#: The three answers to "who can reach this instance", in the order §4 presents
#: them. Renaming one here without renaming it in DEPLOY.md fails loudly, which
#: is the point of pinning them.
REQUIRED_BRANCHES: tuple = (
    "no-public-access",
    "own-certificate",
    "upstream-terminator",
)

#: The one branch on which a bare hostname is the correct instruction.
CERTIFICATE_BRANCH = "own-certificate"

#: A Caddy site address: unindented, opens a block. Indented ``handle … {`` and
#: ``reverse_proxy … {`` lines are directives inside a site, not addresses.
SITE_ADDRESS = re.compile(r"^(\S.*?)\s*\{\s*$")

FORWARDED_PROTO = "header_up X-Forwarded-Proto https"


@dataclass(frozen=True)
class CaddyAddress:
    """One Caddy site address found in a fenced block in DEPLOY.md §4."""

    line: int
    address: str
    branch: str

    @property
    def is_bare_hostname(self) -> bool:
        """A name with no scheme in front of it — the form that orders a cert.

        ``:80`` is a port with no host and orders nothing.
        ``http://your-domain.com`` is explicitly plain and orders nothing.
        ``your-domain.com`` is the form that starts a certificate request.
        """
        if self.address.startswith(("http://", "https://")):
            return False
        return bool(re.search(r"[A-Za-z]", self.address))


@dataclass(frozen=True)
class Seam:
    """Everything the four assertions need, read once from both files."""

    branch_markers: dict
    section_four_addresses: tuple
    caddyfile_first_address: str
    caddyfile_has_forwarded_proto: bool

    @property
    def bare_hostnames_outside_the_certificate_branch(self) -> tuple:
        return tuple(
            address
            for address in self.section_four_addresses
            if address.is_bare_hostname and address.branch != CERTIFICATE_BRANCH
        )


def _section_four(deploy_text: str):
    """§4's lines, with their real line numbers, up to the next `## ` heading."""
    lines = deploy_text.splitlines()
    start = None
    for number, line in enumerate(lines, start=1):
        if re.match(r"^##\s+4\.", line):
            start = number
            continue
        if start is not None and re.match(r"^##\s", line):
            return list(enumerate(lines, start=1))[start - 1 : number - 1]
    if start is None:
        return []
    return list(enumerate(lines, start=1))[start - 1 :]


def scan(deploy_text: str, caddyfile_text: str) -> Seam:
    """Read the seam out of both files. Every assertion and control calls this."""
    branch_markers: dict = {}
    for number, line in enumerate(deploy_text.splitlines(), start=1):
        for match in BRANCH_MARKER.finditer(line):
            branch_markers.setdefault(match.group(1), []).append(number)

    # Assertion 2 is ABOUT the code blocks, so §4's fences are walked into
    # rather than blanked. Line numbers are the real ones throughout.
    addresses = []
    current_branch = ""
    inside_fence = False
    for number, line in _section_four(deploy_text):
        marker = BRANCH_MARKER.search(line)
        if marker and not inside_fence:
            current_branch = marker.group(1)
        if FENCE.match(line):
            inside_fence = not inside_fence
            continue
        if not inside_fence:
            continue
        match = SITE_ADDRESS.match(line)
        if match:
            addresses.append(CaddyAddress(number, match.group(1), current_branch))

    first_address = ""
    for line in caddyfile_text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        match = SITE_ADDRESS.match(line)
        if match:
            first_address = match.group(1)
            break

    return Seam(
        branch_markers=branch_markers,
        section_four_addresses=tuple(addresses),
        caddyfile_first_address=first_address,
        caddyfile_has_forwarded_proto=FORWARDED_PROTO in caddyfile_text,
    )


def _scan_the_real_files() -> Seam:
    return scan(
        (REPO_ROOT / "DEPLOY.md").read_text(),
        (REPO_ROOT / "Caddyfile").read_text(),
    )


# -- The four assertions ------------------------------------------------------


def test_section_four_carries_all_three_branches_exactly_once():
    markers = _scan_the_real_files().branch_markers

    missing = [slug for slug in REQUIRED_BRANCHES if slug not in markers]
    assert not missing, (
        "DEPLOY.md §4 must branch on who can reach the instance, and these "
        f"branches have no <!-- branch: … --> marker: {missing}. Without the "
        "marker the branch is invisible to this gate even if the prose is there."
    )

    duplicated = {
        slug: lines for slug, lines in markers.items() if len(lines) > 1
    }
    assert not duplicated, (
        "a branch marker appears more than once, so 'which branch is this "
        f"address in' has no single answer: {duplicated}"
    )


def test_a_bare_hostname_is_offered_only_where_a_certificate_is_wanted():
    offenders = _scan_the_real_files().bare_hostnames_outside_the_certificate_branch

    assert not offenders, (
        "DEPLOY.md §4 offers a bare hostname as a Caddy site address outside "
        f"the '{CERTIFICATE_BRANCH}' branch: "
        + "; ".join(
            f"line {a.line}: {a.address!r} in branch {a.branch or '(none)'}"
            for a in offenders
        )
        + ". A bare hostname is what makes Caddy order a certificate, and on "
        "any other branch that request cannot succeed while Django redirects "
        "to HTTPS — which is the loop the Caddyfile's own header warns about."
    )


def test_the_shipped_caddyfile_still_binds_a_bare_port():
    first = _scan_the_real_files().caddyfile_first_address

    assert first == ":80", (
        f"the shipped Caddyfile's first site address is {first!r}, not ':80'. "
        "Two of DEPLOY.md §4's three branches tell the operator to leave this "
        "file exactly as shipped; a hostname committed here makes that advice "
        "silently wrong and orders a certificate nobody asked for."
    )


def test_the_shipped_caddyfile_still_asserts_the_forwarded_protocol():
    assert _scan_the_real_files().caddyfile_has_forwarded_proto, (
        f"the shipped Caddyfile no longer carries {FORWARDED_PROTO!r}. The "
        "upstream-terminator branch's correctness rests on it: without the "
        "header Django cannot know the visitor's connection was encrypted, and "
        "SECURE_SSL_REDIRECT redirects a request that is already as encrypted "
        "as it is going to get. production.py's SECURE_PROXY_SSL_HEADER is the "
        "other half of the pair."
    )


# -- The controls -------------------------------------------------------------
#
# Fixture strings, run through the same scan(). Each one is the real documents
# with a single thing broken, and each proves one assertion can go red.

_GOOD_DEPLOY = """\
## 4. Caddy / HTTPS Configuration

<!-- branch: no-public-access -->
### Branch A

Leave it as shipped.

<!-- branch: own-certificate -->
### Branch B

```caddy
your-domain.com {
    handle {
        reverse_proxy web:8000
    }
}
```

<!-- branch: upstream-terminator -->
### Branch C

```caddy
http://your-domain.com {
    handle {
        reverse_proxy web:8000
    }
}
```

## 5. Build and Start
"""

_GOOD_CADDYFILE = """\
# A comment that mentions example.com and must not be read as an address.
:80 {
    handle {
        reverse_proxy web:8000 {
            header_up X-Forwarded-Proto https
        }
    }
}
"""

_DEPLOY_MISSING_A_BRANCH = _GOOD_DEPLOY.replace(
    "<!-- branch: upstream-terminator -->\n", ""
)

_DEPLOY_WITH_A_BARE_DOMAIN_ON_THE_WRONG_BRANCH = _GOOD_DEPLOY.replace(
    "http://your-domain.com {", "example.com {"
)

_CADDYFILE_WITH_A_DOMAIN = _GOOD_CADDYFILE.replace(":80 {", "example.com {")


def test_the_fixtures_are_clean_before_anything_is_broken():
    """Without this, a control that goes red proves nothing about the mutation."""
    seam = scan(_GOOD_DEPLOY, _GOOD_CADDYFILE)

    assert set(REQUIRED_BRANCHES).issubset(seam.branch_markers)
    assert not seam.bare_hostnames_outside_the_certificate_branch
    assert seam.caddyfile_first_address == ":80"
    assert seam.caddyfile_has_forwarded_proto


def test_deleting_a_branch_marker_is_reported():
    seam = scan(_DEPLOY_MISSING_A_BRANCH, _GOOD_CADDYFILE)

    assert "upstream-terminator" not in seam.branch_markers, (
        "a §4 with one branch marker deleted still reported all three, so the "
        "marker assertion cannot fail and is not a measurement"
    )


def test_a_bare_domain_on_the_wrong_branch_is_reported():
    seam = scan(_DEPLOY_WITH_A_BARE_DOMAIN_ON_THE_WRONG_BRANCH, _GOOD_CADDYFILE)
    offenders = seam.bare_hostnames_outside_the_certificate_branch

    assert offenders, (
        "a bare example.com offered inside the upstream-terminator branch was "
        "not reported — this is the original defect and the scanner walked "
        "straight past it"
    )
    assert offenders[0].branch == "upstream-terminator"
    assert offenders[0].address == "example.com"


def test_a_caddyfile_carrying_a_domain_is_reported():
    seam = scan(_GOOD_DEPLOY, _CADDYFILE_WITH_A_DOMAIN)

    assert seam.caddyfile_first_address == "example.com", (
        "a Caddyfile whose first site address is a hostname still read as "
        f"{seam.caddyfile_first_address!r}, so the assertion cannot fail"
    )
