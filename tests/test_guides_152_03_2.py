# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.2: the two guides and two onboarding templates say what the commands do.

The expected prose is one named constant per row (67 to 87) of
``.planning/phases/152-proven-by-strangers/152-03.2-ROWS.md``, Fixed column, with
the Now column kept beside it so the old sentence is shown to be gone. Whitespace
and line wraps are normalised before comparing; the guides wrap near 88 columns.
Nothing here is data: no invented system is needed, except the invented onboarding
flow in the last two tests, which serves the recorded EPA fixtures.
"""

import json
import re
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking import envirofacts

ROOT = Path(__file__).resolve().parent.parent
DATA_IMPORT = ROOT / "docs" / "DATA-IMPORT.md"
OPERATOR = ROOT / "docs" / "AI-OPERATOR-GUIDE.md"
FIXTURES = ROOT / "drinking" / "fixtures"

ROW_65 = "OpenH2O updates the system from EPA's record."
ROW_65_NOW = "Updated from EPA's current record."
ROW_66 = "OpenH2O updated {name} ({pwsid}) from EPA's record."
ROW_66_NOW = "from EPA's current record"

ROW_67 = (
    "To import a lab results file, use the `import_lab_results` command or the "
    "import screen at `/drinking/import/`. The Import lab results button on the "
    "Sample Results page opens that screen."
)
ROW_67_NOW = (
    "To import a lab results file, use the Import lab results button on the Sample "
    "Results page (`/drinking/import/`). There is no command for lab results."
)
ROW_68 = (
    "The file can be a .csv, .tab or .txt file. The screen takes a file of up to "
    "25 MB."
)
ROW_68_NOW = "The file can be a .csv, .tab or .txt file of up to 25 MB."
ROW_69 = (
    "OpenH2O skips a row whose result is already on file and a row that repeats an "
    "earlier row of the same file. The preview counts the first as already on file "
    "and the second as repeated in this file."
)
ROW_69_NOW = (
    "It skips a row that repeats a result already on file or an earlier row of the "
    "same file, and counts it as a duplicate."
)
ROW_70 = (
    "Add the sampling point first with `add_sampling_point` or with Add sampling "
    "points on the Water Systems page (Drinking water > Water Systems). Then import "
    "the file again."
)
ROW_70_NOW = (
    "Add the sampling point first with Add sampling points on the Water Systems page "
    "(Drinking water > Water Systems), then import the file again."
)
ROW_71 = (
    "The `add_water_system` command and the Add a water system page "
    "(`/drinking/onboard/`) look up the PWSID in EPA's Envirofacts records."
)
ROW_71_NOW = (
    "The Add a water system page (`/drinking/onboard/`) looks up the PWSID in EPA's "
    "Envirofacts records."
)
ROW_72 = (
    "The page shows the water system's record and its facilities. When you confirm, "
    "the page saves both. The command saves both as soon as it runs. With "
    "`--dry-run`, the command prints the review and does not save anything."
)
ROW_72_NOW = (
    "It shows the water system's record and its facilities, and it saves them when "
    "you confirm."
)
ROW_73 = (
    "A site keeps the records of one water system. Once a system is on the site, "
    "OpenH2O refuses any other PWSID and does not save anything."
)
ROW_73_NOW = (
    "A site keeps the records of one water system, so once a system is on the site, "
    "OpenH2O rejects any other PWSID on this page and saves nothing."
)
ROW_74 = (
    "OpenH2O skips a facility that has no state facility ID. The review and the "
    "command list each facility it skips."
)
ROW_74_NOW = "A facility that has no state facility ID is skipped, and the review lists it."
ROW_75 = "When the PWSID is already on the site, the review and the dry run say so."
ROW_75_NOW = "When the PWSID is already on the site, the review says so."
ROW_76 = (
    "If you confirm, OpenH2O updates the system and its facilities from EPA's record."
)
ROW_76_NOW = (
    "If you confirm, OpenH2O updates the system and its facilities from EPA's "
    "current record."
)
ROW_77 = (
    "OpenH2O keeps a copy of each record it reads from EPA for 30 days. A lookup "
    "within those 30 days reads the copy and not EPA's service."
)
ROW_78 = (
    "Then add the sampling points. The `add_sampling_point` command adds one "
    "sampling point to a facility. You can also add points one at a time on the "
    "Sampling points page. The Add sampling points link on the Water Systems page "
    "opens it. For a California water system, give the facility ID and the point "
    "number. OpenH2O builds the PS Code from the PWSID, the facility ID and the "
    "point number. For a system outside California, give the point's code with "
    "`--ps-code` exactly as it appears in the lab results file."
)
ROW_79 = (
    "In these commands, replace `XX1234567` with your system's PWSID and `010` with "
    "one of its facility IDs."
)
ROW_80 = (
    "Sampling points: Add sampling points on the Water Systems page (Drinking water "
    "> Water Systems) or `add_sampling_point`"
)
ROW_81 = (
    "For a drinking-water system, add the system from its PWSID with "
    "`add_water_system` or on the Add a water system page. Then add its sampling "
    "points with `add_sampling_point` or with Add sampling points on the Water "
    "Systems page. Then import lab results with `import_lab_results` or the import "
    "screen. Import production with `import_production` or the Production page's "
    "Import button."
)
ROW_81_NOW = (
    "For a drinking-water system, add the system from its PWSID, then add its "
    "sampling points, then import lab results and production."
)
ROW_82 = (
    "Type the results into a CSV file with the lab import's columns. Import the "
    "file with `import_lab_results` or at `/drinking/import/`."
)
ROW_82_NOW = (
    "A CSV file with the lab import's columns, typed up from the paper and imported "
    "at `/drinking/import/`."
)
ROW_83 = (
    "Most import screens show a preview and save only after you confirm. The Upload "
    "CSV page of the Use Ledger saves the file at once unless you tick Dry run."
)
ROW_83_NOW = "An import screen shows a preview and saves only after you confirm."
ROW_84 = "`add_water_system` or `/drinking/onboard/`"
ROW_85 = (
    "A PWSID is the identification number of a public water system in EPA's records. "
    "The command and the page add the system and its facilities from EPA's "
    "Envirofacts records. A site keeps the records of one water system. Once a "
    "system is on the site, OpenH2O refuses a different PWSID. To update the system "
    "from EPA's record, run the command again or look up the same PWSID and press "
    "Refresh. Add the sampling points with `add_sampling_point` or on the page that "
    "follows."
)
ROW_85_NOW = (
    "Once a system is on the site, the page rejects a different PWSID, and entering "
    "the same PWSID again updates the system from EPA's current record."
)
ROW_86 = "`import_lab_results` or `/drinking/import/`"
ROW_87 = (
    "The command and the screen read the column headings of California's Division of "
    "Drinking Water and several headings that commercial labs use."
)
ROW_87_NOW = (
    "It matches the column headings of California's Division of Drinking Water and "
    "several headings that commercial labs use."
)

#: row -> (guide, fixed, now). ``now`` is "" for a new row.
GUIDE_ROWS = {
    67: (DATA_IMPORT, ROW_67, ROW_67_NOW),
    68: (DATA_IMPORT, ROW_68, ROW_68_NOW),
    69: (DATA_IMPORT, ROW_69, ROW_69_NOW),
    70: (DATA_IMPORT, ROW_70, ROW_70_NOW),
    71: (DATA_IMPORT, ROW_71, ROW_71_NOW),
    72: (DATA_IMPORT, ROW_72, ROW_72_NOW),
    73: (DATA_IMPORT, ROW_73, ROW_73_NOW),
    74: (DATA_IMPORT, ROW_74, ROW_74_NOW),
    75: (DATA_IMPORT, ROW_75, ROW_75_NOW),
    76: (DATA_IMPORT, ROW_76, ROW_76_NOW),
    77: (DATA_IMPORT, ROW_77, ""),
    78: (DATA_IMPORT, ROW_78, ""),
    79: (DATA_IMPORT, ROW_79, ""),
    80: (DATA_IMPORT, ROW_80, ""),
    81: (DATA_IMPORT, ROW_81, ROW_81_NOW),
    82: (OPERATOR, ROW_82, ROW_82_NOW),
    83: (OPERATOR, ROW_83, ROW_83_NOW),
    84: (OPERATOR, ROW_84, ""),
    85: (OPERATOR, ROW_85, ROW_85_NOW),
    86: (OPERATOR, ROW_86, ""),
    87: (OPERATOR, ROW_87, ROW_87_NOW),
}


def _flat(text):
    return " ".join(text.split())


@pytest.mark.parametrize("row", sorted(GUIDE_ROWS))
def test_the_fixed_sentence_is_in_its_guide(row):
    guide, fixed, _ = GUIDE_ROWS[row]
    assert fixed in _flat(guide.read_text(encoding="utf-8")), f"row {row}"


@pytest.mark.parametrize("row", sorted(GUIDE_ROWS))
def test_the_now_sentence_is_gone(row):
    guide, fixed, now = GUIDE_ROWS[row]
    if not now or now in fixed:
        pytest.skip("a new row, or a Now that the Fixed text contains")
    text = _flat(guide.read_text(encoding="utf-8"))
    assert fixed in text  # the guide must carry the replacement, so this fails today
    assert now not in text, f"row {row}"


def test_data_import_no_longer_says_there_is_no_command():
    text = _flat(DATA_IMPORT.read_text(encoding="utf-8"))
    assert ROW_67 in text
    assert "There is no command for lab results" not in text


def test_no_guide_still_calls_the_record_current():
    for guide in (DATA_IMPORT, OPERATOR):
        text = _flat(guide.read_text(encoding="utf-8"))
        assert "EPA's current record" not in text, guide.name
        assert ROW_77 in _flat(DATA_IMPORT.read_text(encoding="utf-8"))


def test_the_new_command_examples_are_in_the_data_import_guide():
    text = DATA_IMPORT.read_text(encoding="utf-8")
    for command in (
        "docker compose cp lab-results.tab web:/tmp/",
        "docker compose exec web python manage.py import_lab_results /tmp/lab-results.tab --dry-run",
        "docker compose exec web python manage.py import_lab_results /tmp/lab-results.tab",
        "docker compose exec web python manage.py add_water_system XX1234567 --dry-run",
        "docker compose exec web python manage.py add_water_system XX1234567",
        "docker compose exec web python manage.py add_sampling_point --facility 010 --point-number 010 --type source",
    ):
        assert command in text, command


# -- rows 65 and 66: the screens ------------------------------------------------


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"guides{n}")
    email = factory.Sequence(lambda n: f"guides{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def epa(monkeypatch):
    def load(name):
        return json.loads((FIXTURES / f"envirofacts_{name}.json").read_text())

    monkeypatch.setattr(envirofacts, "fetch_water_system", lambda p, refresh=False: load("water_system")[0])
    monkeypatch.setattr(envirofacts, "fetch_facilities", lambda p, refresh=False: load("facilities"))
    monkeypatch.setattr(envirofacts, "fetch_geographic_area", lambda p, refresh=False: load("geographic_area")[0])


def _text_of(response):
    # Inline tags such as <span> sit inside a sentence, so they go without a space.
    html = re.sub(r"</?(span|strong|em|a)\b[^>]*>", "", response.content.decode())
    return _flat(re.sub(r"<[^>]+>", " ", html))


def test_the_templates_no_longer_say_current():
    root = ROOT / "templates" / "drinking" / "partials"
    for name in ("_onboard_review.html", "_onboard_result.html"):
        assert "EPA's current record" not in (root / name).read_text(encoding="utf-8"), name


def test_the_review_of_a_system_on_the_site_says_row_65(client_in, epa):
    client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "CA1010001"})
    client_in.post(reverse("drinking:onboard_commit"))
    review = client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "CA1010001"})
    text = _text_of(review)
    assert ROW_65 in text
    assert ROW_65_NOW not in text


def test_the_result_after_refresh_says_row_66(client_in, epa):
    from drinking.models import WaterSystem

    client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "CA1010001"})
    client_in.post(reverse("drinking:onboard_commit"))
    client_in.post(reverse("drinking:onboard_lookup"), {"pwsid": "CA1010001"})
    result = client_in.post(reverse("drinking:onboard_commit"))
    name = WaterSystem.objects.get(pwsid="CA1010001").name
    text = _text_of(result)
    assert ROW_66.format(name=name, pwsid="CA1010001") in text
    assert ROW_66_NOW not in text
