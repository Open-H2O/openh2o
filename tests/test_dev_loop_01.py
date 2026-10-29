# SPDX-License-Identifier: AGPL-3.0-or-later
"""The faster test loop: a development compose file, and make targets that use it.

The development file bind-mounts the source into the web container so an edit is
live without a rebuild. It is opt-in: no deploy, upgrade or release script may
name it, and Compose only loads it when a person names it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEV_FILE = ROOT / "docker-compose.dev.yml"
MAKEFILE = ROOT / "Makefile"

def _recipe(target):
    """The text of one Makefile target: its rule line and its indented recipe.

    Read as text because the test container has no make."""
    lines = MAKEFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"{re.escape(target)}:(?!=)", line))
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith(("\t", " ")) or not line.strip():
            body.append(line)
        else:
            break
    return "\n".join(body)


def _pytest_lines(target):
    return [line for line in _recipe(target).splitlines() if "pytest" in line]


def _web_service_text():
    text = DEV_FILE.read_text()
    assert "\n  web:" in text, "the development file does not describe the web service"
    return text.split("\n  web:", 1)[1]


def test_the_development_file_exists_and_bind_mounts_the_source_into_web():
    assert DEV_FILE.is_file()
    web = _web_service_text()
    assert ".:/app" in web.replace(" ", "")


def test_the_development_file_does_not_replace_the_volumes_the_image_depends_on():
    # The base file mounts a named volume over /app/staticfiles; the dev file may
    # not point that path back at the host.
    web = _web_service_text().replace(" ", "")
    assert "/app/staticfiles" not in web.replace("static_files:/app/staticfiles", "")


def test_the_dev_file_is_not_the_compose_override_name_so_nothing_loads_it_by_default():
    assert DEV_FILE.name != "docker-compose.override.yml"
    assert not (ROOT / "docker-compose.override.yml").exists()


@pytest.mark.parametrize("script", ["scripts/deploy.sh", "scripts/upgrade.sh", "scripts/release.sh", "deploy.sh"])
def test_no_deploy_script_names_the_development_file(script):
    path = ROOT / script
    if path.exists():
        assert "docker-compose.dev.yml" not in path.read_text()


@pytest.mark.parametrize("target", ["up", "build", "deploy", "release", "upgrade"])
def test_no_deploy_or_upgrade_target_names_the_development_file(target):
    assert "docker-compose.dev.yml" not in _recipe(target)
    assert "DEV_COMPOSE" not in _recipe(target)


def test_make_test_with_a_target_runs_only_that_path():
    lines = _pytest_lines("test")
    assert len(lines) == 1
    assert "$(T)" in lines[0]
    assert "pytest tests/ " not in lines[0]


def test_make_test_runs_the_whole_suite_when_no_target_is_given():
    assert re.search(r"T\s*\?=\s*tests/", MAKEFILE.read_text())


def test_make_test_keeps_the_freshness_guard_and_says_why_it_is_skipped():
    recipe = _recipe("test")
    assert "guard-fresh" in recipe
    assert "docker-compose.dev.yml" in recipe
    assert "echo" in recipe


def test_make_golden_update_needs_a_target_sets_the_flag_and_copies_goldens_out():
    recipe = _recipe("golden-update")
    assert "T=" in recipe and "exit 1" in recipe
    assert "GOLDEN_UPDATE=1" in recipe
    assert "$(T)" in recipe
    assert " cp " in recipe and "tests/golden" in recipe
    assert "guard-fresh" in recipe


def test_make_dev_up_loads_both_files():
    assert "-f docker-compose.yml -f docker-compose.dev.yml" in MAKEFILE.read_text()
    assert "$(DEV_COMPOSE)" in _recipe("dev-up")


def test_contributing_names_the_three_commands():
    text = (ROOT / "CONTRIBUTING.md").read_text()
    for command in ("make dev-up", "make test T=", "make golden-update T="):
        assert command in text
