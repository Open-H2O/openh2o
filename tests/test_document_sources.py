# SPDX-License-Identifier: AGPL-3.0-or-later
"""tests/document_sources.toml covers every section of the twenty documents.

Phase 150.6 (2026-10-19). The file lists, for each section of the guides and
help pages, the code its sentences rest on; ``scripts/guide_reread.py`` reads
it at each phase's close to find the sections whose code changed. A list that
went stale quietly would leave a section out of every re-read, so this test
fails when:

- a document gains, loses or renames a heading the list does not match;
- a path under ``files`` or a label's ``where`` no longer exists;
- a section names no files and gives no ``why_none``;
- a ``checked_at`` is not a commit id, or (where git is available; the web
  image carries no history) not a commit in the history.

It does not judge whether the listed files are the right ones: that was
measured once, against the claims checks of October 2026, and is kept honest
by the re-reads themselves.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "guide_names.py"
HAS_HISTORY = shutil.which("git") is not None and (REPO_ROOT / ".git").exists()
#: Files .dockerignore leaves out of the web image, where the suite runs.
#: Where there is no checkout they are not looked for.
NOT_IN_IMAGE = (".gitignore", ".dockerignore")


def _load():
    spec = importlib.util.spec_from_file_location("guide_names_for_sources", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclass looks itself up there
    spec.loader.exec_module(module)
    return module


names = _load()
SECTIONS = names.load_sources()


def test_every_heading_of_every_document_is_listed_once():
    wanted = Counter((d, h) for d in names.DOCUMENTS for h, _, _ in names.sections(d))
    listed = Counter((entry["document"], entry["heading"]) for entry in SECTIONS)
    missing = sorted(f"{d}: {h}" for (d, h), n in wanted.items() if listed[(d, h)] < n)
    extra = sorted(f"{d}: {h}" for (d, h), n in listed.items() if wanted[(d, h)] < n)
    assert not missing, (
        "Sections with no entry in tests/document_sources.toml (list the code they "
        "rest on):\n" + "\n".join(missing))
    assert not extra, (
        "Entries whose heading no document has any more (rename or remove them):\n"
        + "\n".join(extra))


def test_every_listed_path_exists():
    gone = []
    for entry in SECTIONS:
        for path in entry["files"]:
            if path in NOT_IN_IMAGE and not HAS_HISTORY:
                continue
            if not (REPO_ROOT / path).exists():
                gone.append(f"{entry['document']} / {entry['heading']}: {path}")
        for label in entry.get("labels", []):
            if not (REPO_ROOT / label["where"]).exists():
                gone.append(f"{entry['document']} / {entry['heading']}: {label['where']}")
    assert not gone, "Paths in tests/document_sources.toml that no longer exist:\n" + "\n".join(gone)


def test_no_listed_file_is_a_test():
    tests = [f"{e['document']} / {e['heading']}: {p}" for e in SECTIONS
             for p in e["files"] if p.startswith("tests/")]
    assert not tests, "A section rests on product code, never on a test:\n" + "\n".join(tests)


def test_a_section_with_no_files_says_why():
    silent = [f"{e['document']} / {e['heading']}" for e in SECTIONS
              if not e["files"] and not e.get("why_none")]
    assert not silent, "Sections with files = [] and no why_none:\n" + "\n".join(silent)


def test_every_checked_at_is_a_commit_id():
    malformed = sorted({e["checked_at"] for e in SECTIONS
                        if not re.fullmatch(r"[0-9a-f]{7,40}", e["checked_at"])})
    assert not malformed, "checked_at values that are not commit ids: " + ", ".join(malformed)


@pytest.mark.skipif(not HAS_HISTORY, reason="no git history here (the web image carries none)")
def test_every_checked_at_is_a_commit():
    unknown = sorted({
        entry["checked_at"] for entry in SECTIONS
        if subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{entry['checked_at']}^{{commit}}"],
            capture_output=True,
        ).returncode != 0
    })
    assert not unknown, "checked_at values that are not commits: " + ", ".join(unknown)
