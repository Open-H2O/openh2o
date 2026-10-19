# SPDX-License-Identifier: AGPL-3.0-or-later
"""The guides and help pages name only commands, settings, labels and places that exist.

Phase 150.6 (2026-10-19). ``scripts/guide_names.py`` reads the names the twenty
documents (the twelve public guides, About and the seven help pages) write in
a fixed form, and asks the code whether each one is real:

- commands: ``manage.py <name>`` and its ``--flags`` in code formatting, "the
  <name> command", and ``make <target>``;
- settings: an UPPER_SNAKE name in code formatting, DEPLOY.md section 12's
  tables against the settings the code reads (both ways), and each setting
  Settings explained names against its settings screen;
- screen labels: the sidebar paths on the pages and in the guides, and each
  label ``tests/document_sources.toml`` lists for a section;
- places: links to other documents and their anchors, DEPLOY.md section
  numbers, and a heading quoted after a link.

A failure names the document, the line, the name and the closest real one.
Fix the document, or, where the check is wrong, add the name to the script's
``EXCEPTIONS`` with its reason.

This test never checks a description, and never that a sentence is present
(ISS-129): a renamed button fails here, a changed behaviour does not. Those
are found by re-reading the sections ``scripts/guide_reread.py`` lists at each
phase's close.

Before it was installed the check was run against the five guides as the
October claims checks read them and against every commit since 2026-09-01
that changed one of the twenty documents; the counts are in the phase's
replay note.

**Kill switch:** ``OPENH2O_GUIDE_NAMES_CHECK=0`` skips this module.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENH2O_GUIDE_NAMES_CHECK", "1") == "0",
    reason="OPENH2O_GUIDE_NAMES_CHECK=0",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "guide_names.py"


def _load():
    if not SCRIPT.exists():
        pytest.fail(f"{SCRIPT} is missing; update SCRIPT if it moved.")
    spec = importlib.util.spec_from_file_location("guide_names_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclass looks itself up there
    spec.loader.exec_module(module)
    return module


names = _load()
_EXCEPTIONS = names.EXCEPTIONS


def _report(findings) -> str:
    return "\n".join(str(finding) for finding in findings)


@pytest.mark.parametrize("document", names.DOCUMENTS)
def test_commands_flags_and_make_targets_exist(document):
    findings = names.check_commands(document, names.read(document))
    assert not findings, _report(findings)


@pytest.mark.parametrize("document", names.DOCUMENTS)
def test_settings_exist(document):
    findings = names.check_settings(document, names.read(document))
    assert not findings, _report(findings)


def test_deploy_section_12_lists_every_setting_the_code_reads():
    findings = names.check_deploy_table(names.read("DEPLOY.md"))
    assert not findings, _report(findings)


def test_settings_explained_names_settings_on_their_screens():
    document = "templates/help/settings_explained.html"
    findings = names.check_settings_explained(names.read(document))
    assert not findings, _report(findings)


@pytest.mark.parametrize("document", names.DOCUMENTS)
def test_sidebar_paths_exist(document):
    findings = names.check_sidebar_paths(document, names.read(document))
    assert not findings, _report(findings)


def test_listed_screen_labels_are_still_on_screen():
    findings = names.check_listed_labels()
    assert not findings, _report(findings)


@pytest.mark.parametrize("document", names.DOCUMENTS)
def test_links_anchors_and_section_numbers_resolve(document):
    findings = names.check_places(document, names.read(document))
    assert not findings, _report(findings)


def test_every_exception_is_still_needed(monkeypatch):
    """An entry no finding needs any more is removed, so the list stays true."""
    monkeypatch.setattr(names, "EXCEPTIONS", ())
    raised = {(finding.document, finding.name) for finding in names.all_findings()}
    unused = [f"{document}: {name}" for document, name, _ in _EXCEPTIONS
              if (document, name) not in raised]
    assert not unused, "EXCEPTIONS entries no finding needs:\n" + "\n".join(unused)


def test_every_settings_explained_name_is_on_the_page():
    """A name in SETTINGS_EXPLAINED_WORDS that the page no longer uses is removed."""
    page = names.page_text(names.read("templates/help/settings_explained.html"))
    gone = [name for name in names.SETTINGS_EXPLAINED_WORDS if name not in page]
    assert not gone, "SETTINGS_EXPLAINED_WORDS entries the page no longer names: " + ", ".join(gone)


def test_the_check_reads_the_real_registries():
    """The check asks Django and the Makefile; it holds no copy of either."""
    assert "seed_data" in names.commands()
    assert "test" in names.make_targets()
    assert ("Administration", "Zones") in names.sidebar()
    assert "SECRET_KEY" in names.settings_read_from_environment()
