# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Windows schedule: crontab.txt put into Windows Task Scheduler.

Windows has no cron. scripts/windows/install-schedule.ps1 puts the jobs in
crontab.txt into Task Scheduler instead, one task per job, and each task runs
the job's own line through run-job.ps1. These tests run that script with -List,
which prints the tasks it would write and changes nothing. They need PowerShell
(pwsh), which the web image does not have, so they run on the host.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "scripts" / "windows"
INSTALL_SCHEDULE = WINDOWS / "install-schedule.ps1"
RUN_JOB = WINDOWS / "run-job.ps1"
CRONTAB = ROOT / "crontab.txt"

needs_pwsh = pytest.mark.skipif(
    shutil.which("pwsh") is None,
    reason="the Windows schedule scripts need PowerShell; the web image has none",
)

#: What each cron timing in crontab.txt becomes in Task Scheduler: the time of
#: day the trigger starts, the days it runs on, and how often it repeats after
#: that within the day ("none" for once a day).
TASK_TIMING = {
    "0 * * * *": ("00:00", "daily", "PT1H"),
    "25 1 * * *": ("01:25", "daily", "none"),
    "0 2 * * *": ("02:00", "daily", "none"),
    "30 3 * * *": ("03:30", "daily", "none"),
    "0 */6 * * *": ("00:00", "daily", "PT6H"),
    "0 3 1 * *": ("03:00", "monthly day 1", "none"),
}


def _cron_jobs(path=CRONTAB):
    """Each job in a crontab file as (timing, command)."""
    jobs = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" in line.split()[0]:
            continue
        fields = line.split(None, 5)
        jobs.append((" ".join(fields[:5]), fields[5]))
    return jobs


def _windows_plan(*args):
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(INSTALL_SCHEDULE), "-List", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    rows = [line.split("\t") for line in result.stdout.splitlines() if "\t" in line]
    return result, rows


def test_crontab_holds_the_six_jobs_the_windows_tests_know():
    # A new timing in crontab.txt needs its Task Scheduler form added above.
    timings = [timing for timing, _ in _cron_jobs()]
    assert len(timings) == 6
    assert set(timings) <= set(TASK_TIMING)


@needs_pwsh
def test_every_crontab_job_has_a_task_with_the_same_command_and_timing():
    result, rows = _windows_plan()
    assert result.returncode == 0, result.stderr
    jobs = _cron_jobs()
    assert len(rows) == len(jobs)
    planned = {(row[1], row[5]): row for row in rows}
    for timing, command in jobs:
        row = planned.get((timing, command))
        assert row is not None, f"no task for: {timing} {command}"
        assert tuple(row[2:5]) == TASK_TIMING[timing], row


@needs_pwsh
def test_every_task_has_its_own_name():
    _, rows = _windows_plan()
    names = [row[0] for row in rows]
    assert len(set(names)) == len(names) == len(_cron_jobs())


@needs_pwsh
def test_a_timing_task_scheduler_is_not_given_stops_it_and_writes_nothing(tmp_path):
    crontab = tmp_path / "crontab.txt"
    crontab.write_text(
        "0 2 * * * $OPENH2O_DIR/scripts/backup.sh\n"
        "0 4 * * 1 $OPENH2O_DIR/scripts/run-sync.sh usgs\n"
    )
    result, rows = _windows_plan("-From", str(crontab))
    assert result.returncode != 0
    assert rows == []
    assert "0 4 * * 1" in result.stderr
    assert "nothing changed" in result.stderr.lower()


@needs_pwsh
def test_a_job_runs_with_the_checkout_and_log_folder_even_with_spaces(tmp_path):
    # run-job.ps1 gives the line what cron's block gives it, and a folder name
    # with a space in it (common under C:\Users) must not split the command.
    checkout = tmp_path / "my checkout"
    (checkout / "scripts" / "windows").mkdir(parents=True)
    shutil.copy(RUN_JOB, checkout / "scripts" / "windows" / "run-job.ps1")
    logs = tmp_path / "the logs"
    line = "cd $OPENH2O_DIR && pwd > $OPENH2O_LOG_DIR/where.log 2>&1 && printf '%s' \"$MSYS_NO_PATHCONV\" >> $OPENH2O_LOG_DIR/where.log"
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(checkout / "scripts" / "windows" / "run-job.ps1"),
            "-Job",
            line,
            "-LogDir",
            str(logs),
            "-Bash",
            shutil.which("bash"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    where = (logs / "where.log").read_text().splitlines()
    assert Path(where[0]).resolve() == checkout.resolve()
    assert where[1] == "1"
    record = (logs / "schedule.log").read_text()
    assert "exit 0" in record and "pwd" in record


@needs_pwsh
def test_a_failing_job_passes_its_exit_code_to_task_scheduler(tmp_path):
    logs = tmp_path / "logs"
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(RUN_JOB),
            "-Job",
            "exit 3",
            "-LogDir",
            str(logs),
            "-Bash",
            shutil.which("bash"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 3
    assert "exit 3" in (logs / "schedule.log").read_text()
