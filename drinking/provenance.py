# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Who published the values on a drinking-water screen.

**Why this module exists.** The site-wide demonstration notice tells every
reader this deployment "mixes invented sample data with real published records"
and gives them no way to tell which half they are looking at. Inside ``drinking``
the answer is always the same and always favourable: it is published record,
carried unaltered. Nothing on the screens said so, which meant the banner argued
against the truth on precisely the pages carrying chain-of-custody notes, ELAP
certification numbers and named laboratories — the values an evaluator will
discount if the page gives them no provenance.

**Why a module rather than eight templates.** Eight templates repeating "EPA
Envirofacts (SDWIS)" by hand will drift, and `/about/demonstration-data/` had
already drifted into three different shapes for the same two publishers before
this file existed. One module means one edit when the wording changes, and
``tests/test_drinking_provenance.py`` reads these constants rather than a
sentence so a rename fails loudly instead of silently un-labelling a page.

**Why there is no ``provenance`` FIELD and no migration.** Measured at planning
time and re-measured here: ``drinking/urls.py`` exposes reads plus the three
ingest paths and nothing else, there is no ``drinking/forms.py``, and no
``ModelForm`` anywhere in ``drinking/views.py``. Every field on ``WaterSystem``,
``SystemFacility``, ``SamplingPoint``, ``SampleEvent`` and ``SampleResult`` is
written by exactly one of the code paths named below and is never subsequently
edited through the UI, so a template-level statement of publisher cannot go
stale. **If an edit path is ever added to this module, this file becomes a lie
and a stored field becomes mandatory.**

**Why the labels are NOT flag-gated.** ``partials/_demo_marker.html`` is gated on
``SiteConfig.demonstration_mode`` because it claims "this value is fake", which is
only true on a demonstration. A source label claims "this value came from EPA's
federal record", which is true on ANY deployment that onboarded through the Phase
79/80 wizard. On a real agency instance it answers a live operator question — can
I change this, and where do I go to fix it — so suppressing it there would remove
information from the deployment that needs it most.

**Wording convention.** Every constant is a publisher noun phrase that reads
correctly after "Source: ", which is what ``partials/_source_label.html`` renders.
Proper nouns keep their capitals; the two "composed by this deployment" values
start lowercase because they are descriptions, not names. Keep them short: these
render inline beside a section header, not as body copy.

**Vocabulary constraint.** These strings reach rendered page text, so none of
them may contain *well*, *parcel*, *diversion*, *recharge* or *allocation* — the
droppability vocabulary gate reads the words a reader sees and fails a kept page
that names a module the deployment does not have
(``tests/droppability/checks.py::_FORBIDDEN_VOCABULARY``).
"""

#: EPA's federal record, read through the Envirofacts SDWIS REST service.
#:
#: Written by ``drinking.envirofacts_mapping.commit_system``, which the Phase
#: 79/80 onboarding wizard drives: ``WaterSystem`` identity and its two published
#: aggregates, plus ``SystemFacility`` identity. Note EPA publishes NO
#: coordinates at all — see ``GAMA`` below, which is why the facility detail page
#: needs a row-level label and not just a section-level one.
EPA_SDWIS = "EPA Envirofacts (SDWIS)"

#: The state laboratory file: California's own SDWIS4 export from the DDW EDT
#: Library, parsed with no transformation.
#:
#: Written by ``drinking.importer.validate_rows`` / ``commit_rows`` — the import
#: screen an operator uses and the path ``seed_merced_drinking`` runs through:
#: ``SampleEvent``, ``SampleResult`` and ``Analyte``. This is the publisher the
#: site-wide banner most undermines, because these are the rows carrying named
#: laboratories and ELAP certification numbers.
DDW_LAB = "State Water Board Division of Drinking Water"

#: GAMA — the state's Groundwater Ambient Monitoring and Assessment programme.
#:
#: The source of ``SystemFacility.location`` (backfilled by
#: ``drinking/migrations/0006``) and of the screen intervals on the demonstration's
#: municipal supply sources. GAMA publishes a position for the SOURCE, never for
#: the tap, which is why a sampling point is drawn at its facility's coordinate
#: and says so.
GAMA = "State Water Board GAMA programme"

#: A ``SamplingPoint`` record, which no publisher ships as a row.
#:
#: Written by the Phase 80 point builder through
#: ``drinking.ps_codes.compose_ps_code``. Two different claims in one phrase, on
#: purpose: the PS-code FORMAT is the state's published convention and the
#: ``{pwsid}_{facility_id}_{point_number}`` join key every lab row is matched on,
#: while the point RECORD is composed here on an operator's explicit action.
PS_CODE_COMPOSED = (
    "composed by this deployment from the State Water Board's PS-code convention"
)

#: An identifier this deployment minted for its own registry.
#:
#: The case that matters is ``wells.Well.well_registration_id`` (``MER-PWS-001``
#: in the demonstration, ``core/management/commands/seed_merced_drinking.py``),
#: which names no state or federal registry and deliberately is not written to
#: ``state_well_number`` or ``wcr_number``.
LOCAL_REGISTRY = "composed by this deployment"

#: The water system's own annual Consumer Confidence Report.
#:
#: Not a value this platform stores at all — a composed link out to the report the
#: system itself published for the year a sample was taken
#: (``drinking.views``' CCR gating). It is the one thing on the result detail page
#: that is neither the lab file nor EPA, and the section carrying it inherits the
#: wrong publisher without a label of its own.
CCR_SYSTEM = "the water system's own annual report"

#: The published identity of a municipal supply source, as it reaches the wells
#: module.
#:
#: Deliberately names both publishers rather than one, because MEASURED against
#: ``drinking/management/commands/seed_merced_drinking.py::_seed_wells`` and
#: ``data/merced/drinking/README.md`` the identity of a ``MER-PWS-*`` source is
#: genuinely split: ``Well.name`` is the state's own name for the source, carried
#: from the DDW lab file; ``Well.owner_name`` is the system name from EPA
#: Envirofacts; ``Well.location`` is GAMA's published coordinate. None of it is
#: invented — which is the claim this label makes, and the reason those 21 rows
#: must not carry a blanket "sample data" pill.
PUBLISHED_SUPPLY_SOURCE = "EPA and State Water Board published record"

#: Every constant above, keyed by its own name.
#:
#: The ``{% source_label %}`` tag looks a publisher up here, so a template names a
#: publisher by its CONSTANT and never by a literal string — a missing key raises
#: at render rather than printing an empty label. Order matters only for the
#: readability of the completeness assertion in
#: ``tests/test_drinking_provenance.py``.
PUBLISHERS = {
    "EPA_SDWIS": EPA_SDWIS,
    "DDW_LAB": DDW_LAB,
    "GAMA": GAMA,
    "PS_CODE_COMPOSED": PS_CODE_COMPOSED,
    "LOCAL_REGISTRY": LOCAL_REGISTRY,
    "CCR_SYSTEM": CCR_SYSTEM,
    "PUBLISHED_SUPPLY_SOURCE": PUBLISHED_SUPPLY_SOURCE,
}


def publisher(key: str) -> str:
    """The publisher wording for ``key``.

    Raises ``KeyError`` on an unknown key rather than returning a default: a
    label that silently renders "Source: " is worse than a 500 in development,
    because it ships looking deliberate.
    """
    return PUBLISHERS[key]
