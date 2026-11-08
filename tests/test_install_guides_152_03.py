# SPDX-License-Identifier: AGPL-3.0-or-later
"""The approved 152-03 wording is in the install guides.

Each guide is read as text and every run of whitespace is collapsed to one
space, because the guides wrap their lines.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE = "docs/AI-OPERATOR-GUIDE.md"
DEPLOY = "DEPLOY.md"


def _raw(name):
    return (REPO_ROOT / name).read_text()


def _flat(name):
    return re.sub(r"\s+", " ", _raw(name))


UNHEALTHY = (
    "If `docker compose up` stops with a message that the `web` container is "
    "unhealthy, read `docker compose logs web`."
)

SENTENCES = [
    (GUIDE, "The command `hostname -I` prints the address on a Linux computer."),
    (GUIDE, "Ask the person to set the office router to give this computer the same address every time."),
    (GUIDE, "The line `OPENH2O_FORWARDED_PROTO=http` makes Caddy pass each request to OpenH2O as plain HTTP."),
    (DEPLOY, "Set the office router to give this computer the same address every time."),
    (DEPLOY, "Every request fails if the address changes and `ALLOWED_HOSTS` still holds the old address."),
    (GUIDE, "The sections `parcels` and `accounting` go on or off together."),
    (GUIDE, UNHEALTHY),
    (DEPLOY, UNHEALTHY),
]


@pytest.mark.parametrize("name,sentence", SENTENCES)
def test_guide_holds_the_approved_sentence(name, sentence):
    assert sentence in _flat(name)


def test_guide_lists_the_office_module_line():
    lines = [line_.strip() for line_ in _raw(GUIDE).splitlines()]
    assert (
        "OPENH2O_MODULES=core,geography,measurements,standards,drinking,setup,infrastructure,health,feedback"
        in lines
    )


def test_deploy_branch_a_code_block_sets_the_forwarded_proto():
    text = _raw(DEPLOY)
    section4 = re.search(r"^#+ *4\..*?(?=^#+ *5\.)", text, re.S | re.M)
    assert section4, "section 4 not found"
    branch_a = re.search(r"^### Branch A.*?(?=^### Branch B|\Z)", section4.group(0), re.S | re.M)
    assert branch_a, "Branch A not found in section 4"
    blocks = re.findall(r"```[^\n]*\n(.*?)```", branch_a.group(0), re.S)
    assert any(
        "OPENH2O_FORWARDED_PROTO=http" in [line_.strip() for line_ in b.splitlines()]
        for b in blocks
    )


def test_guide_has_calculation_plan_heading_before_sync_openet_parcels():
    text = _raw(GUIDE)
    assert "### Create the calculation plan" in text.splitlines()
    assert "seed_calculation_plan" in text
    assert "sync_openet_parcels" in text
    assert text.index("seed_calculation_plan") < text.index("sync_openet_parcels")
