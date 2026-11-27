# SPDX-License-Identifier: AGPL-3.0-or-later
"""Security fixes stay in: the lockfile never goes back below a fixed version.

A security update is a change to ``requirements.lock``, and a lock regenerated on
an older branch, or a merge that keeps the older side of the lock, would quietly
put a fixed hole back. This test reads the lock itself, not the installed
packages, so it fails on the file a commit would ship.

``FLOORS`` lists each package with the lowest version that carries its fixes.
Raise a floor when a newer security release is locked; never lower one. To
remove a package from the lock, remove its floor in the same commit and say why.

The image's system packages are kept current the same way: the Dockerfile
fetches Debian's release files before its ``apt-get`` step, so a new Debian
security or point release rebuilds that step, and ``apt-get upgrade`` installs
it. Without that, every build reused the system packages of the first build.
"""
import re
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent

FLOORS = {
    # 2026-11-26: Django's GeoDjango remote code execution fix (5.2.17) and later 5.2 releases.
    "django": "5.2.19",
    "cryptography": "50.0.2",
    "pyasn1": "0.6.5",
    "sqlparse": "0.6.1",
    "urllib3": "2.8.0",
    # 2026-11-06 security pins.
    "pillow": "13.0.0",
    "pyjwt": "2.14.0",
    "certifi": "2026.10.18",
}

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", re.M)


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _locked():
    text = (ROOT / "requirements.lock").read_text()
    return {_norm(n): v for n, v in PIN.findall(text)}


def test_every_floor_is_in_the_lock():
    locked = _locked()
    missing = sorted(n for n in FLOORS if _norm(n) not in locked)
    assert not missing, f"requirements.lock no longer pins {missing}; remove the floor only with a reason"


def test_no_locked_version_is_below_its_floor():
    locked = _locked()
    below = {
        n: f"{locked[_norm(n)]} < {floor}"
        for n, floor in FLOORS.items()
        if _norm(n) in locked and Version(locked[_norm(n)]) < Version(floor)
    }
    assert not below, f"requirements.lock went back below a security fix: {below}"


def test_pyproject_django_floor_matches():
    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'"Django>=([0-9.]+)', text)
    assert m, "pyproject.toml has no Django lower bound"
    assert Version(m.group(1)) >= Version(FLOORS["django"]), (
        f"pyproject.toml allows Django {m.group(1)}, below the security floor {FLOORS['django']}"
    )


def test_dockerfile_refreshes_system_packages():
    text = (ROOT / "Dockerfile").read_text()
    head, sep, _ = text.partition("apt-get install")
    assert sep, "the Dockerfile has no apt-get install step"
    assert re.search(r"^ADD https://deb\.debian\.org/debian-security/dists/\S+/InRelease ", head, re.M), (
        "the Dockerfile must fetch Debian's security release file before apt-get, or a rebuild reuses old packages"
    )
    assert "apt-get upgrade" in head, "the Dockerfile's apt step must run apt-get upgrade before installing"
