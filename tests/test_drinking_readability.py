# SPDX-License-Identifier: AGPL-3.0-or-later
"""
The onboarding screens must be usable by the operator who runs the system.

**Read this before adding a test here. The sentence above used to read "must
read to a non-specialist," and that one word did more damage than any string in
this repository.**

Written 2026-07-20 after review. The screens were correct and unreadable: they
showed ``DST``, ``LCR`` and ``WELL 08 - AFT_GAC & PARTIAL FLW-IX_NO3`` and
assumed the reader knew the vocabulary. The reviewer's verdict was "it's just a
bunch of random letters and acronyms — it doesn't read to a human at all."

**That verdict was about EPA's codes, and only about EPA's codes.** The fix it
called for was a key to a federal record. What got written down instead was
*assume the reader is a non-specialist*, and it has governed this screen ever
since. It produced two distinct defects, a month apart, and they are separate
failures that this file must now guard against in both directions.

1. **It explained the domain to the domain expert (ISS-129, 2026-08-06).** Three
   tests here MANDATED that the screens say what a well, a treatment plant and a
   distribution system physically are — to water district engineers. Because the
   tests held those sentences up, every correction made by hand was reverted by
   the suite on the next run; the mechanism, not the wording, was the defect. All
   three are gone, replaced by
   `test_the_panel_names_its_facility_type_and_never_describes_it`. **A test in
   this file may never mandate a description of a water term.** The rule is
   `DESIGN.md` copy rule 11; the gate is `tests/test_domain_vocabulary.py`.

2. **It wrote the screen in a register nobody would use with a colleague
   (2026-08-06, raised by Brent looking at the live builder).** "For people to
   read. Anything that identifies the spot." · "Kind of place" · "Add this
   place" · "Whatever the state uses for this spot." That is not explaining
   water, so copy rule 11 passes it clean — a different axis, and the reason a
   gate did not catch it. Rule 11 asks *whose domain does this word belong to*;
   this asks *what register am I writing in*. The reader is a state water-system
   operator entering a state record, so the screen uses **the state's own
   vocabulary** — sampling point, PS Code, facility, point type — and form help
   says what goes in the field rather than reassuring anyone. Phase 80-03's
   "sampling place", invented to be gentler than the state's "sampling point",
   was reversed here along with the test that pinned it.

**The distinction that keeps both fixed.** The reader does not know *this
software*, and owes nothing for learning it — so the platform explains its own
screens, its own concepts, and codes inside records it did not author. The reader
knows *water* better than we ever will. Explain the software; use their words for
everything else.

These tests exist because that class of defect is invisible to every other test
in the suite. A page can render, return 200, carry correct data, and still be
useless to the person who has to act on it.

They are deliberately assertions about *a rule* — a casing, a spelling, a proper
name, a term's presence or absence — never about a sentence. The copy stays free
to improve without breaking the suite.

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


class TestBuilderIsUsable:
    def test_page_says_what_it_is_for(self, client_logged_in, system):
        """The reviewer could not tell what the screen was for.

        Asserts the page names the thing it exists to serve — a lab file and the
        PS Code it carries — never the sentence that names them.
        """
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        assert "What this page is for" in body
        assert "lab file" in body.lower()
        assert "PS Code" in body

    def test_the_panel_names_its_facility_type_and_never_describes_it(
        self, client_logged_in, system
    ):
        """ISS-129 / DESIGN.md copy rule 11. This one test replaced three.

        **What was here before, and why it had to go.** Three tests in this file
        *mandated* a physical description for the facility panel — one demanded
        the word "pipes" on the rendered page, one demanded a sentence for all 22
        EPA codes, one demanded ``glossary.facility_type_plain("DS")`` say what a
        distribution system is. The reader is a water district engineer or
        operator, so every one of those sentences told an expert what a well is;
        and because the tests held them up, every correction made by hand was
        reverted by the suite on the next run. That mechanism, not the wording,
        is the defect ISS-129 was filed over.

        The panel heading renders EPA's own label from ``FACILITY_TYPE_CHOICES``
        and that is the whole job. **A shorter panel here is deliberate.** If you
        are reading this because a panel looks bare, the missing sentence was
        removed on purpose and may not be restored.
        """
        body = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()

        # EPA's own label still names each kind of facility — the data
        # convention is the legitimate half of the boundary and stays.
        assert "Distribution System" in body
        assert "Well" in body

        # Nothing beneath that heading says what the thing physically is. These
        # are the exact strings the deleted dictionary put on this page.
        for lecture in (
            "pipes that carry treated water",
            "A drilled well",
            "Water comes up out of the ground",
            "taken out in the neighborhood",
            "where water is filtered or treated",
        ):
            assert lecture not in body, (
                "the facility panel is explaining water to a water operator: "
                f"{lecture!r}. DESIGN.md copy rule 11 — explain the software and "
                "the data conventions, never the water (ISS-129)."
            )

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
        assert "Facilities with sampling points (2)" in body
        assert "Facilities with no sampling points yet (5)" in body
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
    """Every string `drinking/glossary.py` can put in front of a reader.

    `SHORTHAND` renders into the onboarding builder's abbreviation legend, and
    the legend only lists terms that actually appear in the names on screen — so
    which of these a given page shows depends on the DATA, which is exactly how
    a defect in one of them survives a fixture that never triggers it.

    This read both dictionaries until 2026-08-06. `FACILITY_TYPE_PLAIN` was
    deleted whole by ISS-129 and there is no second dictionary to read.
    """
    return list(glossary.SHORTHAND.values())


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

    #: Words this screen invented to be gentler than the state's own, and the
    #: state's word that replaces each. Phase 80-03 coined "sampling place"
    #: deliberately, as a "plain-English rewrite", and a test in this file used
    #: to pin the split in place. Both were reversed on 2026-08-06.
    #:
    #: **Why a rewrite that was trying to help made the screen worse.** The
    #: operator does not read "sampling place" and feel comforted; they read it
    #: and wonder whether it is the same thing as the sampling point on the state
    #: form in front of them. Softening a term the reader already owns adds a
    #: translation step and takes away the word they would search for. The state
    #: writes PS Code, sampling point, facility — so this screen does.
    INVENTED_VOCABULARY = {
        "sampling place": "sampling point",
        "kind of place": "point type",
        "add this place": "add sampling point",
        "for people to read": "say what goes in the field",
        "whatever the state uses for this spot": "the last segment of the PS Code",
        "code a lab file would use": "PS Code",
        "water comes from here": "Source",
    }

    def test_the_builder_uses_the_states_vocabulary_not_a_softer_one(
        self, client_logged_in, unlocated
    ):
        """The register rule, and the second defect this file's old thesis caused.

        Copy rule 11 does not catch this and is not supposed to: "For people to
        read" defines no water term, so the vocabulary gate passes it clean. That
        rule asks *whose domain does a word belong to*; this asks *what register
        am I writing in*. Two different axes, and this screen failed the second
        one for six weeks while passing the first.

        Raised by Brent on 2026-08-06 against the live builder, on the help text
        under the Description field: *"'For people to read' ?? — this is
        ridiculous, why would that be helpful?"* He was looking at a form for
        entering a state record, written as though he might not know what a
        description was for.
        """
        text = visible_text(
            client_logged_in.get(
                reverse("drinking:onboard_points", args=[PWSID])
            ).content.decode()
        ).lower()

        found = {
            invented: instead
            for invented, instead in self.INVENTED_VOCABULARY.items()
            if invented in text
        }
        assert found == {}, (
            "the sampling-point builder is writing down to a state water-system "
            "operator instead of using the state's own words: "
            + "; ".join(f"{k!r} -> say {v!r}" for k, v in found.items())
        )

        # And the state's vocabulary is actually present, so this cannot be
        # satisfied by deleting the words rather than correcting them.
        for required in ("ps code", "sampling point"):
            assert required in text, (
                f"the builder no longer uses the state's term {required!r}"
            )

    def test_a_control_names_the_page_it_opens(self, client_logged_in, unlocated):
        """Rule 4. A control that navigates to a named page carries that page's
        name, so the button landing on Sampling Points says "sampling points".

        This used to exist to police a split vocabulary — the builder said
        "place", the destination said "point", and the button had to bridge them.
        The split is gone (see ``INVENTED_VOCABULARY`` above); the rule it
        enforces is not, because it applies to every control on the platform.
        """
        html = client_logged_in.get(
            reverse("drinking:onboard_points", args=[PWSID])
        ).content.decode()
        target = reverse("drinking:sampling_points")
        labels = re.findall(
            rf'<a href="{re.escape(target)}"[^>]*>(.*?)</a>', html, re.S
        )
        assert labels, "no control on the builder links to the Sampling Points page"
        for label in labels:
            assert "sampling point" in visible_text(label).lower(), (
                "a control that opens the Sampling Points page does not name it: "
                f"{visible_text(label).strip()!r}"
            )

    def test_the_builder_caps_its_prose_measure(self):
        """Rule 6. Body prose caps at 75ch, and this page is the one that broke it.

        Measured on staging 2026-08-06, before 117-01: the opening paragraph
        rendered 1085px wide at a 1440px window — 127 characters to the line,
        against a rule of 75 and against six sibling drinking templates that
        already cap at 70–75ch. The template held exactly one ``max-width``, the
        1400px page container, and none on any paragraph.

        Source-level and ``ch``-based on purpose. The suite has no browser, and
        the rule DESIGN.md writes is a ``ch`` rule rather than a pixel one — a
        pixel assertion would pass or fail on the viewport a headless run
        happened to pick. The page container deliberately stays at 1400px: the
        facility panels and their four-column add form need that width. Only the
        prose was over-wide.
        """
        source = (
            Path(settings.BASE_DIR)
            / "templates"
            / "drinking"
            / "onboard_points.html"
        ).read_text()
        uncapped = []
        for tag in re.findall(r"<p\s[^>]*>", source, re.S):
            if "text-base" not in tag or "text-secondary" not in tag:
                continue
            if not re.search(r"max-width:\s*\d+(?:\.\d+)?ch", tag):
                uncapped.append(" ".join(tag.split()))
        assert uncapped == [], (
            "body prose on the sampling-point builder carries no ch measure — "
            f"DESIGN.md copy rule 6 caps it at 75ch: {uncapped}"
        )
