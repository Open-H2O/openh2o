# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/release.sh's own tests, run on every push.

``tests/deploy/test_release.sh`` is a bash file with stand-ins for make, docker,
git and curl, so it needs no network, no Docker and no database. This wrapper runs
it so the suite fails when the release wrapper's rollback breaks, not only when
someone remembers to run the file by hand.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

TEST = Path(__file__).resolve().parent / "deploy" / "test_release.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_release_script_tests_pass():
    result = subprocess.run(
        ["bash", str(TEST)], capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
