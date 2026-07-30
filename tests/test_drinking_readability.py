# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The onboarding screens must read to a non-specialist.

Written 2026-07-20 after review. The screens were correct and unreadable: they
showed ``DST``, ``LCR`` and ``WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3`` and
assumed the reader knew the vocabulary. The reviewer's verdict was "it's just a
bunch of random letters and acronyms — it doesn't read to a human at all."

These tests exist because that class of defect is invisible to every other test
in the suite. A page can render, return 200, carry correct data, and still be
useless to the person who has to act on it. Correctness tests cannot catch that;
these assert the explanations are actually present.

They are deliberately assertions about *plain language being present*, not about
exact wording — the copy should be free to improve without breaking the suite.

**Phase 101-02 extended this file rather than starting another one.** The copy
and formatting pass wrote nine house rules into DESIGN.md's *Copy rules*
section; `TestCopyRules` at the foot of this file pins the half of them a
machine can check. It holds the same line the paragraph above draws: a rule, a
casing, a spelling or a proper name may be pinned — a sentence may not. The
measured evidence behind every one is in
``docs/drinking-copy-audit-2026-07-30.md``.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from drinking import glossary
from drinking.models import SamplingPoint, SystemFacility, WaterSystem
from tests.droppability.checks import visible_text
from tests.factories import (
    AnalyteFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)

PWSID = "CA1010001"


@pytest.fixture
def client_logged_in(db, django_user_model):
    user = django_user_model.objects.create(
        username="reader", email="reader@example.gov",
        password=make_password("pw"), is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def system(db):
    """Bakman's real shape: a sampled well, a sampled distribution system, and
    a pile of facilities that are never sampled."""
    system = WaterSystem.objects.create(pwsid=PWSID, name="BAKMAN WATER COMPANY")
    well = SystemFacility.objects.create(
        system=system, facility_id="010", name="WELL 10 - RAW",
        facility_type="WL", is_source=True,
    )
    dst = SystemFacility.objects.create(
        system=system, facility_id="DST", name="DISTRIBUTION SYSTEM",
        facility_type="DS",
    )
    SamplingPoint.objects.create(
        ps_code="CA1010001_010_010", facility=well, name="WELL 10 - RAW",
        point_type="source",
    )
    SamplingPoint.objects.create(
        ps_code="CA1010001_DST_LCR", facility=dst, name="LCR Tap Sample",
        point_type="tap",
    )
    # Never-sampled facilities — the 21 that used to be rendered as empty forms.
    for i in range(5):
        SystemFacility.objects.create(
            system=system, facility_id=f"9{i:02d}",
            name=f"WELL 0{i} - GAC EFFLUENT", facility_type="TP",
        )
    return system


class TestGlossary:
    def test_distribution_system_is_explained_as_pipes(self):
        text = glossary.facility_type_plain("DS")
        assert "pipes" in text.lower()

    def test_every_facility_type_choice_has_a_plain_description(self):
        """A code with no translation is the defect this module exists to fix."""
        from drinking.models import FACILITY_TYPE_CHOICES

        missing = [
            code for code, _ in FACILITY_TYPE_CHOICES
            if not glossary.facility_type_plain(code)
        ]
        assert missing == [], f"facility types with no plain description: {missing}"

    def test_shorthand_returns_only_terms_actually_present(self):
        """A full glossary on every page is just another wall."""
        found = dict(glossary.shorthand_in_use(["WELL 10 - RAW"]))
        assert "RAW" in found
        assert "GAC" not in found

    def test_shorthand_splits_epas_compound_names(self):
        """EPA runs terms together with underscores, hyphens and ampersands."""
        found = dict(
            glossary.shorthand_in_use(["WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3"])
        )
        for term in ("GAC", "IX", "NO3"):
            assert term in found, f"{term} not extracted from a real EPA name"


class TestBuilderReadsToAHuman:
    def test_page_says_what_it_is_for(self, client_logged_in, system):
        """The reviewer could not tell what the screen was for."""
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "What this page is for" in body
        assert "laborator" in body.lower()

    def test_distribution_system_is_explained_not_just_abbreviated(
        self, client_logged_in, system
    ):
        """"What does DST stand for?" must be answerable from the page."""
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "pipes that carry treated water" in body

    def test_abbreviations_appearing_on_the_page_are_defined(
        self, client_logged_in, system
    ):
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "What the abbreviations mean" in body
        # LCR and RAW both appear in this fixture's names.
        assert "Lead and Copper Rule" in body
        assert "Untreated water" in body

    def test_unsampled_facilities_are_collapsed_not_listed_flat(
        self, client_logged_in, system
    ):
        """21 identical empty forms buried the ones that mattered."""
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "Facilities that have sampling places (2)" in body
        assert "Facilities with no sampling places yet (5)" in body
        # Behind a disclosure control, still reachable.
        assert "<details" in body

    def test_context_separates_sampled_from_unsampled(self, client_logged_in, system):
        response = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        )
        assert len(response.context["facilities_with_points"]) == 2
        assert len(response.context["facilities_without_points"]) == 5


class TestReviewScreenSaysNothingIsSaved:
    def _render(self, skipped):
        from django.template.loader import render_to_string

        return render_to_string(
            "drinking/partials/_onboard_review.html",
            {
                "pwsid": PWSID, "name": "BAKMAN WATER COMPANY",
                "facilities": [], "facility_count": 35,
                "epa_facility_count": 36, "skipped": skipped,
                "warnings": [], "already_onboarded": False,
                "existing_facility_count": 0, "mailing": {},
                "geography": {},
            },
        )

    def test_leads_with_nothing_saved(self):
        """A lookup fetches real records, so it feels like something happened."""
        body = self._render([])
        assert "Nothing has been saved yet" in body
        assert body.index("Nothing has been saved yet") < body.index("PWSID")

    def test_skip_is_a_headline_not_a_buried_row(self):
        body = self._render(['EPA facility CA1010001001 ("WELL 01") has no state id.'])
        # Stated as a sentence with both numbers, not left to arithmetic.
        assert "will be left out" in body
        assert "35 will be" in body or "35 will not" in body or "36 facilities" in body

    def test_skip_section_is_not_duplicated(self):
        body = self._render(['EPA facility CA1010001001 has no state id.'])
        assert body.count("EPA facility CA1010001001 has no state id.") == 1


# ---------------------------------------------------------------------------
# Phase 101-02: the copy rules, pinned.
#
# DESIGN.md's "Copy rules" section is the prose; this is the half a machine can
# check. Every assertion below is about a RULE — a casing, a spelling, a proper
# name, the presence of a description — and never about a sentence. That is the
# same line this file's docstring already draws, and the reason it is drawn is
# that a copy pass which ends by freezing the copy has defeated the file it
# extended. If a rule cannot be expressed without pinning a sentence, it stays
# in DESIGN.md as prose; docs/drinking-copy-audit-2026-07-30.md records which.
# ---------------------------------------------------------------------------

#: Domain shorthand this module is allowed to write, paired with the expansion a
#: page must carry when it uses the term in PROSE. Keyed by the URL name of the
#: page the audit measured the term on.
#:
#: Proper names, not copy: "Groundwater Ambient Monitoring and Assessment
#: Program" is what the State Water Board calls its own program, so pinning it
#: constrains the facts a page must state and leaves every sentence around it
#: free to be rewritten. `GAMA` reaches three pages, `SDWIS` and `PWSID` reach
#: the onboarding front door — see the audit's D6, D7 and D8.
REQUIRED_EXPANSIONS = {
    "facility_detail": ["Groundwater Ambient Monitoring and Assessment Program"],
    "sampling_point_detail": ["Groundwater Ambient Monitoring and Assessment Program"],
    "sampling_points": ["Groundwater Ambient Monitoring and Assessment Program"],
    "onboard": [
        "Safe Drinking Water Information System",
        "Public Water System Identification",
    ],
}

#: Spellings that must never reach a reader.
#:
#: `GAMA programme` shipped to staging in 101-01 across four surfaces and was
#: caught by Brent's eye rather than by any gate. `test_drinking_provenance.py`
#: closed the half of that hole covering the provenance constants; this closes
#: the other half — the rendered page and the glossary strings.
BRITISH_SPELLINGS = (
    "programme", "neighbourhood", "colour", "labelled", "labelling",
    "analysed", "analyse", "recognised", "recognise", "organised",
    "behaviour", "licence", "centre", "metre", "litre", "defence",
    "catalogue", "modelling", "travelling", "whilst", "amongst",
)

#: Every drinking template — 10 pages and 12 partials.
DRINKING_TEMPLATES = sorted(
    (Path(settings.BASE_DIR) / "templates" / "drinking").rglob("*.html")
)

_STRIPPED = (
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<script.*?</script>", re.S),
    re.compile(r"<style.*?</style>", re.S),
    #: Data-table column headers are exempt from the casing rule by DESIGN.md
    #: and are uppercased in CSS regardless.
    re.compile(r"<th[^>]*>.*?</th>", re.S),
)


def template_prose(path):
    """A template's source with everything that is not copy removed.

    **Why the source and not only the rendered page.** Twelve of the twenty-two
    templates here are HTMX partials that a GET never reaches: the import
    preview, the import result, the onboarding review and the point builder are
    all swapped in by a POST. Measured on the very first run of this file, three
    of the four lowercase prose `id`s the audit found lived in exactly those
    partials, and a rendered-pages-only assertion passed while the defect was
    reintroduced. Source-level checking also reaches the arm of an `{% if %}`
    no fixture happens to take.

    It cannot tell a variable name from prose — `{% if recognised %}` reads as
    the word — so it is a companion to the rendered assertions, never a
    replacement. Where the two disagree the rendered page is the authority.
    """
    text = path.read_text()
    for pattern in _STRIPPED:
        text = pattern.sub(" ", text)
    return text


def _glossary_strings():
    """Every sentence `drinking/glossary.py` can put in front of a reader.

    Both dicts, because both render: `FACILITY_TYPE_PLAIN` into the onboarding
    builder's facility panels and `SHORTHAND` into its abbreviation legend. The
    legend only lists terms that actually appear in the names on screen, so
    which of these a given page shows depends on the DATA — which is exactly how
    a defect in one of them survives a fixture that never triggers it.
    """
    return list(glossary.FACILITY_TYPE_PLAIN.values()) + list(
        glossary.SHORTHAND.values()
    )


@pytest.fixture
def unlocated(db):
    """One system deep enough to reach every read surface, with NO coordinate.

    Deliberately unlocated. Each of the three map-bearing pages branches on
    whether it has geometry, and the GAMA prose this file pins lives in the
    no-map branch on `facility_detail` — a located fixture renders the source
    label there instead and the expansion is never exercised. The other two
    pages carry it on both branches, so one unlocated fixture reaches all three.
    """
    system = WaterSystemFactory(pwsid=PWSID, name="BAKMAN WATER COMPANY")
    facility = SystemFacilityFactory(
        system=system, facility_id="010", name="WELL 10 - RAW",
        facility_type="WL", is_source=True, location=None,
    )
    point = SamplingPointFactory(
        facility=facility, ps_code=f"{PWSID}_010_010", name="Raw tap"
    )
    event = SampleEventFactory(sampling_point=point)
    result = SampleResultFactory(
        event=event, analyte=AnalyteFactory(name="Nitrate"), lab_name="State lab"
    )
    return {"system": system, "facility": facility, "point": point, "result": result}


def _read_surfaces(rows):
    """(url_name, path) for the seven read surfaces plus the three flow pages."""
    return [
        ("overview", reverse("drinking:overview")),
        ("facilities", reverse("drinking:facilities")),
        ("facility_detail",
         reverse("drinking:facility_detail", args=[rows["facility"].pk])),
        ("sampling_points", reverse("drinking:sampling_points")),
        ("sampling_point_detail",
         reverse("drinking:sampling_point_detail", args=[rows["point"].pk])),
        ("results", reverse("drinking:results")),
        ("result_detail",
         reverse("drinking:result_detail", args=[rows["result"].pk])),
        ("onboard", reverse("drinking:onboard")),
        ("onboard_points", reverse("drinking:onboard_points", args=[PWSID])),
        ("import", reverse("drinking:import")),
    ]


class TestCopyRules:
    """DESIGN.md → Copy rules. Evidence in docs/drinking-copy-audit-2026-07-30.md."""

    def test_the_states_field_name_keeps_the_states_casing(
        self, client_logged_in, unlocated
    ):
        """Rule 2. California's own SDWIS4 export heads the column `PS Code`.

        Measured before the sweep: three prose uses spelled it `PS Code` and
        four spelled it `PS code`, on six files. The state's file is the
        authority, not preference.
        """
        offenders = []
        for name, path in _read_surfaces(unlocated):
            text = visible_text(client_logged_in.get(path).content.decode())
            if "PS code" in text:
                offenders.append(name)
        for template in DRINKING_TEMPLATES:
            if "PS code" in template_prose(template):
                offenders.append(template.name)
        if any("PS code" in s for s in _glossary_strings()):
            offenders.append("drinking/glossary.py")
        assert offenders == [], (
            f"writing the state's field name as 'PS code': {offenders}. "
            "The state writes 'PS Code' — see DESIGN.md rule 2."
        )

    def test_identifier_is_capitalised_in_prose(self, client_logged_in, unlocated):
        """Rule 2. `Facility ID` seven times against four prose `id`s.

        Three of those four were in HTMX partials no GET renders, which is why
        this reads the templates as well as the pages — see `template_prose`.
        An HTML `id=` attribute is markup, not copy, and is excluded.

        **The glossary strings are swept too, and that is not belt-and-braces.**
        The first version of this test read only templates and rendered pages
        and was green while `SHORTHAND["DST"]` said "The state's id for the
        distribution system" — a string that reaches a reader ONLY when a
        facility name on the page contains `DST`, which the real Merced data has
        and no fixture here did. It was caught by grepping the deployed page at
        this plan's checkpoint, not by this suite. A string is copy wherever it
        is stored.
        """
        bare_id = re.compile(r"(?<![\w/-])id(?![\w-])")
        offenders = []
        for name, path in _read_surfaces(unlocated):
            if bare_id.search(visible_text(client_logged_in.get(path).content.decode())):
                offenders.append(name)
        for template in DRINKING_TEMPLATES:
            source = re.sub(r'\bid\s*=\s*"[^"]*"', " ", template_prose(template))
            if bare_id.search(source):
                offenders.append(template.name)
        if any(bare_id.search(s) for s in _glossary_strings()):
            offenders.append("drinking/glossary.py")
        assert offenders == [], (
            f"writing a bare lowercase 'id' in prose: {offenders}"
        )

    @pytest.mark.parametrize("spelling", BRITISH_SPELLINGS)
    def test_no_british_spelling_reaches_a_reader(
        self, client_logged_in, unlocated, spelling
    ):
        """Rule 3, and the one defect class that has actually shipped here.

        Rendered pages AND the glossary strings, because `glossary.py` renders
        into the onboarding builder and carried `neighbourhood` for ten days.
        Comments and docstrings are not copy and are not read.
        """
        offenders = []
        for name, path in _read_surfaces(unlocated):
            text = visible_text(client_logged_in.get(path).content.decode())
            if spelling in text.lower():
                offenders.append(name)
        for template in DRINKING_TEMPLATES:
            #: `recognised` is also a CONTEXT KEY set in drinking/views.py. The
            #: rule binds rendered text, so a variable name is not a violation;
            #: the rendered-page half of this test is what covers that word.
            source = re.sub(r"\{[%{][^%}]*[%}]\}", " ", template_prose(template))
            if spelling in source.lower():
                offenders.append(template.name)
        if any(spelling in s.lower() for s in _glossary_strings()):
            offenders.append("drinking/glossary.py")
        assert offenders == [], f"'{spelling}' reaches a reader on: {offenders}"

    def test_every_page_carries_a_non_empty_description(
        self, client_logged_in, unlocated
    ):
        """Rule 1's neighbour: a page that does not say what it is.

        Asserts a description EXISTS and has words in it, never which words.
        """
        bare = []
        for name, path in _read_surfaces(unlocated):
            html = client_logged_in.get(path).content.decode()
            blocks = re.findall(
                r'<p class="page-description">(.*?)</p>', html, re.S
            )
            if not blocks or not visible_text(blocks[0]).strip():
                bare.append(name)
        assert bare == [], f"pages with no page description: {bare}"

    def test_a_domain_acronym_is_expanded_where_its_page_uses_it(
        self, client_logged_in, unlocated
    ):
        """Rule 5. Expand once per page, in prose, at first use.

        Pins the PROPER NAME the expansion states, not the sentence carrying it.
        A page is free to rewrite around the name; it is not free to drop it and
        leave a reader with four capital letters.
        """
        missing = []
        for name, path in _read_surfaces(unlocated):
            if name not in REQUIRED_EXPANSIONS:
                continue
            text = visible_text(client_logged_in.get(path).content.decode())
            for expansion in REQUIRED_EXPANSIONS[name]:
                if expansion not in text:
                    missing.append(f"{name}: {expansion}")
        assert missing == [], f"acronym used with no expansion on its page: {missing}"

    def test_no_expansion_fires_twice_on_one_page(self, client_logged_in, unlocated):
        """Rule 5's other half, and the reason it says *once*.

        A mechanical rule applied to two branches of the same template is how a
        term ends up spelled out three times on one screen. The branches are
        mutually exclusive by construction; this is what proves it stays true.
        """
        repeated = []
        for name, path in _read_surfaces(unlocated):
            if name not in REQUIRED_EXPANSIONS:
                continue
            text = visible_text(client_logged_in.get(path).content.decode())
            for expansion in REQUIRED_EXPANSIONS[name]:
                if text.count(expansion) > 1:
                    repeated.append(f"{name}: {expansion} ×{text.count(expansion)}")
        assert repeated == [], f"an expansion rendered more than once: {repeated}"

    def test_every_page_breadcrumb_starts_at_its_nav_section(
        self, client_logged_in, unlocated
    ):
        """Rule 1. Every Water Data page on the platform roots its breadcrumb at
        the section name the sidebar shows — 19 of 19 non-drinking pages did,
        and 6 of 10 drinking pages did not.
        """
        offenders = []
        for name, path in _read_surfaces(unlocated):
            html = client_logged_in.get(path).content.decode()
            nav = re.search(r'<nav class="breadcrumb".*?</nav>', html, re.S)
            crumbs = [
                c.strip()
                for c in re.findall(r">([^<>]+)</(?:a|span)>", nav.group(0))
                if c.strip() and c.strip() != "/"
            ]
            if crumbs[:2] != ["Water Data", "Drinking Water"]:
                offenders.append(f"{name}: {crumbs[:2]}")
        assert offenders == [], (
            f"breadcrumbs not rooted at Water Data / Drinking Water: {offenders}"
        )

    def test_a_control_names_the_page_it_opens(self, client_logged_in, unlocated):
        """Rule 4. The builder's teaching prose says "sampling place" on purpose
        (80-03's plain-English rewrite, kept) — but the button that lands on the
        Sampling Points page may not, because a reader who clicks "places" and
        arrives at "points" has been told there are two things.
        """
        html = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        target = reverse("drinking:sampling_points")
        for label in re.findall(
            rf'<a href="{re.escape(target)}"[^>]*>(.*?)</a>', html, re.S
        ):
            assert "place" not in visible_text(label).lower(), (
                "a link to the Sampling Points page is labelled with a word that "
                f"page does not use: {visible_text(label).strip()!r}"
            )
