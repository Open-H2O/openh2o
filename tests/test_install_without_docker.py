# SPDX-License-Identifier: AGPL-3.0-or-later
"""`docs/INSTALL-WITHOUT-DOCKER.md` and the container build may not drift apart.

That document tells an operator what to install on a bare machine. Its list was
DERIVED from the `Dockerfile` and `docker-compose.yml` line by line, not copied
from the one clean-room run that took this path — and a derivation is verified
exactly once, on the day it is written, and then it rots. The next person to add
a system library to the image, or to bump the database version in Compose, has
no reason to think about a Markdown file in `docs/`. This module is what makes
them find out.

**Four things it asserts**, each one a thing that would otherwise rot silently:

1. Every RUNTIME system library the `Dockerfile` installs is named in the
   document. The build-only and container-only packages are excluded by an
   explicit set, and every entry in that set carries the reason it is excluded.
   An exclusion set with no reasons is where a test like this goes to die.
2. The Python version the document names matches the `Dockerfile`'s `FROM` line.
3. The PostgreSQL and PostGIS versions the document names match
   `docker-compose.yml`'s database image tag.
4. The document never tells an operator to run `config.settings.local`. That is
   an inherited posture decision (111-01, and `LOCAL-POSTURE.md` F4/F4-bis),
   made mechanical here so a later well-meaning edit cannot quietly undo it.

**Everything goes through one ``scan()``.** Assertions and controls alike, in the
same shape as `tests/test_deploy_https_branches.py`. A control exercising a
different code path from the gate proves nothing — Phase 110 learned that one
the hard way.

The controls run against fixture strings, never the real files, so they keep
proving the scanner works after the real files change.
"""

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The `apt-get install` block in the Dockerfile: everything from the
#: `apt-get install` up to the `&& rm -rf` that closes it. Backslash
#: continuations and the `--no-install-recommends` flag are stripped by
#: `_apt_packages` below.
APT_BLOCK = re.compile(
    r"apt-get\s+install\s+(.*?)&&\s*rm\s+-rf", re.IGNORECASE | re.DOTALL
)

#: `FROM python:3.12-slim` -> "3.12".
FROM_PYTHON = re.compile(r"^FROM\s+python:(\d+\.\d+)", re.MULTILINE)

#: `image: postgis/postgis:16-3.4` -> ("16", "3.4").
POSTGIS_IMAGE = re.compile(r"postgis/postgis:(\d+)-(\d+\.\d+)")

#: Anything that is a flag rather than a package name.
_NOT_A_PACKAGE = re.compile(r"^-")

#: Packages the image installs that a native install must NOT be told to
#: install. Every entry carries its reason, because an exclusion with no reason
#: is indistinguishable from an oversight and will be deleted or extended by
#: someone who cannot tell which it was. Derived and MEASURED in
#: `.planning/phases/112-undocumented-install-paths/112-02-DEPENDENCY-DERIVATION.md`.
EXCLUDED_FROM_THE_DOCUMENT: dict = {
    # Container-only. `entrypoint.sh` uses gosu to drop from root to the
    # unprivileged `app` user before exec-ing gunicorn. A native install never
    # runs as root in the first place: systemd's `User=` is the same guarantee,
    # applied earlier. This package has no meaning outside a container.
    "gosu": "container-only — systemd's User= replaces it",
    # Build-only: C headers and the unversioned .so symlinks, needed only if a
    # Python package has to COMPILE against these libraries. Measured 2026-08-04
    # on Ubuntu 24.04: GeoDjango's own ctypes.util.find_library resolves and
    # loads GDAL and GEOS from the runtime libraries `gdal-bin` pulls in, with
    # these packages absent. On Ubuntu they drag in ~200 further packages.
    "libgdal-dev": "build-only — GDAL loads from gdal-bin's runtime library",
    "libgeos-dev": "build-only — GEOS loads from gdal-bin's runtime library",
    "libproj-dev": "build-only — PROJ is loaded by GDAL, not by Django",
    # Build-only compiler and Python headers, for the same reason. Measured
    # 2026-08-04: `pip install --require-hashes -r requirements.lock` completed
    # with exit 0 and every dependency resolving to a prebuilt wheel, with no
    # compiler and no Python.h present. The document names both as the REMEDY
    # for a build failure rather than as part of the ordinary install, because
    # that measurement covers one architecture.
    "gcc": "build-only — the lockfile resolves to prebuilt wheels",
    "python3-dev": "build-only — the lockfile resolves to prebuilt wheels",
    # Build tooling with nothing to build. gettext supplies `msgfmt` for
    # `manage.py compilemessages`; this repository has no .po file, no locale/
    # directory and no compilemessages call anywhere. USE_I18N=True loads .mo
    # catalogues through Python's own gettext module, not the binary.
    "gettext": "build-only, and nothing to build — no .po files exist here",
}

#: The settings module that must never be recommended to an operator.
FORBIDDEN_SETTINGS_MODULE = "config.settings.local"

#: `Python 3.12` / `Python 3.12.x` in the document's prose. `\s+` spans a line
#: break on purpose: these documents wrap at 80 columns, and a version split
#: across two lines is the same claim to a reader.
DOC_PYTHON_VERSION = re.compile(r"[Pp]ython\s+(\d+\.\d+)")

#: `PostGIS 3.4` / `PostGIS 3.4.2` in the document's prose.
DOC_POSTGIS_VERSION = re.compile(r"PostGIS\s+(\d+\.\d+)", re.IGNORECASE)

#: The PostgreSQL major as it appears in an Ubuntu PACKAGE NAME —
#: `postgresql-16`, `postgresql-16-postgis-3` — not in prose.
#:
#: Prose is deliberately not scanned for the PostgreSQL major, and the reason is
#: a real sentence in the document: it says Debian 12 supplies **PostgreSQL 15**,
#: which is why these commands target Ubuntu. That contrast is the justification
#: for the whole distribution choice and must stay sayable. The package name is
#: the thing an operator actually types, so it is the thing pinned here.
DOC_POSTGRES_PACKAGE = re.compile(r"postgresql-(\d+)", re.IGNORECASE)


def _apt_packages(dockerfile_text: str) -> tuple:
    """Every package name in the Dockerfile's apt-get install block."""
    match = APT_BLOCK.search(dockerfile_text)
    if not match:
        return ()
    words = match.group(1).replace("\\", " ").split()
    return tuple(
        word for word in words if word and not _NOT_A_PACKAGE.match(word)
    )


@dataclass(frozen=True)
class Seam:
    """Both sides of the seam, read once. Every assertion reads this."""

    dockerfile_packages: tuple
    dockerfile_python: str
    compose_postgres: str
    compose_postgis: str
    document_text: str

    @property
    def required_runtime_packages(self) -> tuple:
        """Dockerfile packages a native install genuinely needs."""
        return tuple(
            package
            for package in self.dockerfile_packages
            if package not in EXCLUDED_FROM_THE_DOCUMENT
        )

    @property
    def missing_from_the_document(self) -> tuple:
        return tuple(
            package
            for package in self.required_runtime_packages
            if not re.search(rf"\b{re.escape(package)}\b", self.document_text)
        )

    @property
    def excluded_packages_wrongly_present(self) -> tuple:
        """A container-only package the document tells an operator to install.

        Only ``gosu`` is checked. The build-only packages are DELIBERATELY named
        in the document, as the remedy for a compile failure, so their presence
        is correct and only their absence from the required list matters.
        """
        return tuple(
            package
            for package in ("gosu",)
            if package in self.dockerfile_packages
            and re.search(rf"\b{re.escape(package)}\b", self.document_text)
        )

    @property
    def document_python_versions(self) -> tuple:
        return tuple(sorted(set(DOC_PYTHON_VERSION.findall(self.document_text))))

    @property
    def document_postgres_package_majors(self) -> tuple:
        return tuple(sorted(set(DOC_POSTGRES_PACKAGE.findall(self.document_text))))

    @property
    def document_postgis_versions(self) -> tuple:
        return tuple(sorted(set(DOC_POSTGIS_VERSION.findall(self.document_text))))

    @property
    def document_recommends_development_settings(self) -> bool:
        """True if the document tells an operator to RUN the dev settings.

        The document discusses ``config.settings.local`` on purpose — section 10
        names it in order to say why this path does not use it, and removing
        that passage would lose the warning. So a bare mention is not the
        defect. The defect is an instruction: the module appearing as the value
        of ``DJANGO_SETTINGS_MODULE``, which is the only form that actually
        selects it.
        """
        return bool(
            re.search(
                rf"DJANGO_SETTINGS_MODULE\s*=\s*{re.escape(FORBIDDEN_SETTINGS_MODULE)}",
                self.document_text,
            )
        )


def scan(dockerfile_text: str, compose_text: str, document_text: str) -> Seam:
    """Read both sides of the seam. Every assertion and control calls this."""
    python_match = FROM_PYTHON.search(dockerfile_text)
    image_match = POSTGIS_IMAGE.search(compose_text)

    return Seam(
        dockerfile_packages=_apt_packages(dockerfile_text),
        dockerfile_python=python_match.group(1) if python_match else "",
        compose_postgres=image_match.group(1) if image_match else "",
        compose_postgis=image_match.group(2) if image_match else "",
        document_text=document_text,
    )


def _scan_the_real_files() -> Seam:
    return scan(
        (REPO_ROOT / "Dockerfile").read_text(),
        (REPO_ROOT / "docker-compose.yml").read_text(),
        (REPO_ROOT / "docs" / "INSTALL-WITHOUT-DOCKER.md").read_text(),
    )


# -- The four assertions ------------------------------------------------------


def test_every_runtime_system_library_reaches_the_document():
    seam = _scan_the_real_files()

    assert seam.dockerfile_packages, (
        "no apt-get install block was found in the Dockerfile at all, so this "
        "gate is scanning nothing. If the block moved, fix APT_BLOCK."
    )

    missing = seam.missing_from_the_document
    assert not missing, (
        "the Dockerfile installs these system packages and "
        "docs/INSTALL-WITHOUT-DOCKER.md never names them: "
        f"{list(missing)}. A native install that skips a runtime library does "
        "not start. Either add the package to the document, or add it to "
        "EXCLUDED_FROM_THE_DOCUMENT **with the reason it is not needed "
        "natively** — an exclusion with no reason is indistinguishable from an "
        "oversight."
    )

    wrong = seam.excluded_packages_wrongly_present
    assert not wrong, (
        f"the document tells an operator to install {list(wrong)}, which only "
        "means anything inside a container. entrypoint.sh uses gosu to drop "
        "privileges; a native install has systemd's User= instead."
    )


def test_the_python_version_matches_the_image():
    seam = _scan_the_real_files()

    assert seam.dockerfile_python, (
        "the Dockerfile's FROM line no longer names a python:X.Y image, so the "
        "version this gate compares against cannot be read."
    )
    # Set equality, not membership. Membership only asks "is the right version
    # mentioned SOMEWHERE", which a half-finished edit satisfies: update one
    # sentence, miss the line-wrapped one three sections down, stay green. That
    # exact hole was found by mutating this document on 2026-08-04 and is why
    # all three version assertions below compare sets.
    assert set(seam.document_python_versions) == {seam.dockerfile_python}, (
        f"the Dockerfile builds on Python {seam.dockerfile_python} and "
        "docs/INSTALL-WITHOUT-DOCKER.md names "
        f"{list(seam.document_python_versions)}. Every Python version the "
        "document states must be the one the platform is built and tested "
        "against — including any left behind by a partial edit."
    )


def test_the_database_versions_match_the_compose_image():
    seam = _scan_the_real_files()

    assert seam.compose_postgres and seam.compose_postgis, (
        "docker-compose.yml no longer carries a postgis/postgis:MAJOR-MINOR "
        "image tag, so the versions this gate compares against cannot be read."
    )
    assert set(seam.document_postgres_package_majors) == {seam.compose_postgres}, (
        f"docker-compose.yml pins PostgreSQL {seam.compose_postgres} and the "
        "document's own package names carry "
        f"{list(seam.document_postgres_package_majors)}. Those names are what "
        "an operator types, so a bump in the image is a bump in every one of "
        "them."
    )
    assert set(seam.document_postgis_versions) == {seam.compose_postgis}, (
        f"docker-compose.yml pins PostGIS {seam.compose_postgis} and the "
        f"document states {list(seam.document_postgis_versions)}. Every stated "
        "PostGIS version must match the image, so a half-finished edit fails "
        "here rather than shipping two different answers in one document."
    )


def test_the_document_never_selects_the_development_settings():
    seam = _scan_the_real_files()

    assert not seam.document_recommends_development_settings, (
        "docs/INSTALL-WITHOUT-DOCKER.md sets DJANGO_SETTINGS_MODULE to "
        f"{FORBIDDEN_SETTINGS_MODULE}. That module turns DEBUG on, which prints "
        "the site's internals onto any broken page, and it is not the answer "
        "for an agency's data on any hardware. Clean-room run 004 took that "
        "path and Django's own `check --deploy` named it a defect "
        "(LOCAL-POSTURE.md F4-bis). Use config.settings.production with the "
        "three plain-HTTP flips."
    )


# -- The controls -------------------------------------------------------------
#
# Fixture strings run through the same scan(). Each is a miniature of the real
# files with exactly one thing broken, and each proves one assertion can go red.

_GOOD_DOCKERFILE = """\
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \\
    gdal-bin \\
    libgdal-dev \\
    gettext \\
    gcc \\
    python3-dev \\
    curl \\
    gosu \\
    && rm -rf /var/lib/apt/lists/*
"""

_GOOD_COMPOSE = """\
services:
  db:
    image: postgis/postgis:16-3.4
"""

_GOOD_DOCUMENT = """\
# Installing OpenH2O without Docker

Install `curl` and `gdal-bin` from your distribution.

OpenH2O needs Python 3.12 or newer.

Install postgresql-16 and postgresql-16-postgis-3.
PostgreSQL 16 and PostGIS 3.4 are the database. Debian 12 supplies
PostgreSQL 15 instead, which is why these commands target Ubuntu.

Ubuntu supplies PostGIS
3.4.2, wrapped across a line break on purpose.

Set DJANGO_SETTINGS_MODULE=config.settings.production in your settings file.
"""

_DOCUMENT_MISSING_A_RUNTIME_PACKAGE = _GOOD_DOCUMENT.replace(
    "Install `curl` and `gdal-bin` from your distribution.",
    "Install `curl` from your distribution.",
)

_DOCUMENT_WITH_A_WRONG_PYTHON = _GOOD_DOCUMENT.replace(
    "Python 3.12 or newer", "Python 3.10 or newer"
)

_DOCUMENT_WITH_A_WRONG_POSTGIS = _GOOD_DOCUMENT.replace(
    "PostGIS 3.4 are", "PostGIS 3.2 are"
)

#: The half-finished edit: the obvious mention updated, the line-wrapped one
#: three paragraphs down left behind. A membership check calls this clean.
_DOCUMENT_WITH_A_HALF_FINISHED_POSTGIS_EDIT = _GOOD_DOCUMENT.replace(
    "PostGIS 3.4 are", "PostGIS 3.5 are"
)

_DOCUMENT_WITH_A_STALE_POSTGRES_PACKAGE = _GOOD_DOCUMENT.replace(
    "postgresql-16-postgis-3", "postgresql-15-postgis-3"
)

_DOCUMENT_SELECTING_DEVELOPMENT_SETTINGS = _GOOD_DOCUMENT.replace(
    "config.settings.production", "config.settings.local"
)


def test_the_fixtures_are_clean_before_anything_is_broken():
    """Without this, a control going red proves nothing about the mutation."""
    seam = scan(_GOOD_DOCKERFILE, _GOOD_COMPOSE, _GOOD_DOCUMENT)

    assert seam.dockerfile_packages == (
        "gdal-bin",
        "libgdal-dev",
        "gettext",
        "gcc",
        "python3-dev",
        "curl",
        "gosu",
    ), f"the apt block parser read {seam.dockerfile_packages}"
    assert seam.required_runtime_packages == ("gdal-bin", "curl")
    assert not seam.missing_from_the_document
    assert not seam.excluded_packages_wrongly_present
    assert seam.dockerfile_python == "3.12"
    assert set(seam.document_python_versions) == {"3.12"}
    assert (seam.compose_postgres, seam.compose_postgis) == ("16", "3.4")
    assert set(seam.document_postgres_package_majors) == {"16"}
    # The fixture states PostGIS 3.4 twice, once wrapped across a line break,
    # and states PostgreSQL 15 in prose as the Debian contrast. A clean fixture
    # has to carry both, or the two controls below prove nothing about the
    # cases they exist for.
    assert set(seam.document_postgis_versions) == {"3.4"}
    assert not seam.document_recommends_development_settings


def test_a_runtime_package_dropped_from_the_document_is_reported():
    seam = scan(
        _GOOD_DOCKERFILE, _GOOD_COMPOSE, _DOCUMENT_MISSING_A_RUNTIME_PACKAGE
    )

    assert seam.missing_from_the_document == ("gdal-bin",), (
        "a document that no longer names gdal-bin was not reported, so the "
        "package assertion cannot fail and is not a measurement; it reported "
        f"{seam.missing_from_the_document}"
    )


def test_a_mismatched_python_version_is_reported():
    seam = scan(_GOOD_DOCKERFILE, _GOOD_COMPOSE, _DOCUMENT_WITH_A_WRONG_PYTHON)

    assert set(seam.document_python_versions) != {seam.dockerfile_python}, (
        "a document naming Python 3.10 against an image built on 3.12 was not "
        f"reported; the document read {seam.document_python_versions}"
    )


def test_a_mismatched_postgis_version_is_reported():
    seam = scan(_GOOD_DOCKERFILE, _GOOD_COMPOSE, _DOCUMENT_WITH_A_WRONG_POSTGIS)

    assert set(seam.document_postgis_versions) != {seam.compose_postgis}, (
        "a document naming PostGIS 3.2 against a 16-3.4 image was not "
        f"reported; the document read {seam.document_postgis_versions}"
    )


def test_a_half_finished_version_edit_is_reported():
    """The hole a membership check leaves, kept open as a control.

    One mention updated to 3.5, one line-wrapped mention left at 3.4. The
    document now states two different answers, and the correct one is still
    present — which is exactly what an `in` check calls clean.
    """
    seam = scan(
        _GOOD_DOCKERFILE,
        _GOOD_COMPOSE,
        _DOCUMENT_WITH_A_HALF_FINISHED_POSTGIS_EDIT,
    )

    assert seam.compose_postgis in seam.document_postgis_versions, (
        "this control only means something while the ORIGINAL version is still "
        "present in the document — that is the whole point of it"
    )
    assert set(seam.document_postgis_versions) != {seam.compose_postgis}, (
        "a document stating both PostGIS 3.5 and PostGIS 3.4 was not reported, "
        "so a half-finished version edit ships silently; it read "
        f"{seam.document_postgis_versions}"
    )


def test_a_stale_postgres_package_name_is_reported():
    seam = scan(
        _GOOD_DOCKERFILE, _GOOD_COMPOSE, _DOCUMENT_WITH_A_STALE_POSTGRES_PACKAGE
    )

    assert set(seam.document_postgres_package_majors) != {seam.compose_postgres}, (
        "a document telling an operator to install postgresql-15-postgis-3 "
        "against a 16-3.4 image was not reported; the package names read "
        f"{seam.document_postgres_package_majors}"
    )


def test_a_planted_development_settings_module_is_reported():
    seam = scan(
        _GOOD_DOCKERFILE, _GOOD_COMPOSE, _DOCUMENT_SELECTING_DEVELOPMENT_SETTINGS
    )

    assert seam.document_recommends_development_settings, (
        "a document setting DJANGO_SETTINGS_MODULE=config.settings.local was "
        "not reported, so the posture assertion cannot fail"
    )


def test_every_exclusion_carries_a_reason():
    """The exclusion set is the one place this gate can be silently widened.

    Adding a package here removes it from the required list forever. A blank or
    placeholder reason makes that removal indistinguishable from an oversight,
    which is how a drift guard stops guarding.
    """
    thin = {
        package: reason
        for package, reason in EXCLUDED_FROM_THE_DOCUMENT.items()
        if len(reason.strip()) < 20 or "—" not in reason
    }

    assert not thin, (
        "these EXCLUDED_FROM_THE_DOCUMENT entries carry no real reason: "
        f"{thin}. Write why the package is not needed on a native install, in "
        "the form 'class — why', and put the evidence in "
        "112-02-DEPENDENCY-DERIVATION.md."
    )
