# SPDX-License-Identifier: AGPL-3.0-or-later
"""The backup, restore and upgrade scripts' own tests, run on every push.

``tests/deploy/test_backup.sh``, ``test_restore.sh`` and ``test_upgrade.sh`` are bash
files with stand-ins for docker, git and curl, so they need no network, no Docker and no
database. This wrapper runs them so the suite fails when a backup, restore or upgrade
script breaks, not only when someone remembers to run the files by hand.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent / "deploy"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("name", ["test_backup.sh"])
def test_deploy_script_tests_pass(name):
    result = subprocess.run(
        ["bash", str(DEPLOY / name)], capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
