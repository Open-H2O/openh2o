#!/usr/bin/env python3
"""Run a command while holding a lock on the shared test database.

Two test runs against the same test database (test_openh2o) destroy each other's
data, so `make test` runs through this wrapper: it takes an exclusive flock on a
lock file, waiting (and saying so) when another run holds it, then runs the command
and exits with the command's exit status. The lock is released by the OS when this
process ends, so a killed run never leaves a stale lock.

macOS has no flock binary, hence Python's fcntl.

Usage: python3 scripts/with_test_lock.py COMMAND [ARGS...]
Set OPENH2O_TEST_LOCK_FILE to use a different lock file.
"""
import fcntl
import os
import subprocess
import sys
import time

LOCK_FILE = os.environ.get("OPENH2O_TEST_LOCK_FILE", "/tmp/openh2o-test-db.lock")
MESSAGE_EVERY = 15  # seconds between "still waiting" lines


def main(argv):
    if not argv:
        print("Usage: with_test_lock.py COMMAND [ARGS...]", file=sys.stderr)
        return 2
    with open(LOCK_FILE, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            started = time.monotonic()
            print(
                f"Another test run holds the shared test database lock ({LOCK_FILE}); waiting for it to finish...",
                flush=True,
            )
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(1)
                    waited = int(time.monotonic() - started)
                    if waited and waited % MESSAGE_EVERY == 0:
                        print(f"  still waiting for the test database lock ({waited}s)...", flush=True)
            print(f"Got the test database lock after {int(time.monotonic() - started)}s.", flush=True)
        # The child inherits the lock fd; keep it open until the child exits.
        return subprocess.call(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
