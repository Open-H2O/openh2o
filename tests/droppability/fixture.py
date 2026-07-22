# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rows for the droppability harness — the database state it never had.

Until Plan 90-01 every configuration `checks.py` booted rendered against an
**empty** database. Every list page showed its empty state, every detail route
had no row to fetch, and every code path that only runs when data exists was
never executed. That is not a small gap: 89-03 pointed a reduced module set at a
copy of the real demo database and found **eight live HTTP 500s** that three
phases of green gates had missed, because a CalWATRS ``ReportSubmission`` row
outlives the ``surface`` module and nothing here could build one (ISS-091).

Green on an empty database proves a reduced deployment works for a brand-new
agency with no data. It says nothing about an agency that has been *using* the
platform and then switches a module off — which is the realistic case, and the
one this module seeds.

**Rules this fixture holds itself to, each for a measured reason:**

* **Ask the registry, never a hardcoded module list.** Every block below is
  guarded by ``core.modules.is_enabled``, the same predicate ``tests/factories.py``
  uses. A hardcoded list stops seeding silently the day a module is renamed, and
  the harness would go on reporting green over a database it quietly stopped
  filling.
* **A schema-resident module that is switched OFF must stay empty.** ``wells``,
  ``datasync``, ``parcels`` and ``accounting`` keep their tables when demoted,
  and ``test_schema_resident_module_tables_are_present_and_empty`` asserts those
  tables have no rows in them. ``is_enabled`` is what keeps that true: a
  factory for a demoted module still resolves its model perfectly well, so
  nothing but the guard stops this file from failing that assertion.
* **One row per domain, not a demo dataset.** A ``Boundary`` (so ``needs_setup``
  is False and the *other* branch of ``_empty_onboarding.html`` is live), one row
  behind each list page the configuration keeps, and one CalWATRS submission.
* **No network, ever.** This runs 12 times per ``make test-droppable``. Calling
  ``seed_merced`` or ``seed_data`` would reach external APIs and make the gate
  people rely on depend on the weather — which is exactly why real-data-on-every-run
  was rejected in favour of two tiers (Brent, 2026-07-22). The real demo database
  is Plan 90-03's separate staging gate.
* **Deterministic.** Fixed dates and explicit identifiers rather than factory
  sequences, so two runs produce the same rows. A fixture that varies makes a
  flaky gate indistinguishable from a real defect.

It is a plain callable, not a pytest fixture, on purpose: ``checks.py`` decides
where it attaches (see ``seeded_client`` there), and Plan 90-03's staging work
calls it outside pytest entirely.
"""

from datetime import date

#: The reporting period every seeded configuration shares. Fixed, because
#: ``accounting.ReportingPeriod`` carries a ``reporting_period_no_overlap``
#: exclusion constraint — two periods over the same dates is an IntegrityError,
#: not two rows. ``ReportingPeriodFactory`` reuses a matching row rather than
#: raising. (The identifiers below are unique per row on purpose, so this is a
#: fixture to be laid down ONCE per database, not an idempotent upsert — a second
#: call inside the same transaction hits ``parcels_parcel_parcel_number_key``.
#: pytest rolls each test back, which is why that is the right shape here.)
FIXTURE_PERIOD_START = date(2023, 10, 1)
FIXTURE_PERIOD_END = date(2024, 9, 30)


def seed_droppable_fixture() -> dict:
    """Put one row per surviving domain into the database.

    Returns what it created, keyed by the module that owns the rows — so an
    assertion can say "this configuration seeded nothing for ``reporting``"
    instead of silently proving nothing. A module absent from the returned dict
    was not seeded, and that is a fact the caller can test rather than a fact it
    has to assume.

    Imports live inside the function for the same reason ``checks.py`` imports
    ``tests.factories`` inside its test bodies: this module is importable in every
    configuration, including the ones where half those factories do not exist.
    """
    from core.modules import is_enabled
    from tests import factories

    created: dict = {}

    def record(module, *rows):
        created.setdefault(module, []).extend(rows)

    # -- geography: the row that flips `needs_setup` --------------------------
    # A required module, guarded anyway. The rule is "ask the registry", and a
    # block that opts out because it is confident is how the rule erodes.
    if is_enabled("geography"):
        record("geography", factories.BoundaryFactory(name="Fixture Basin"))

    if is_enabled("parcels"):
        record(
            "parcels",
            factories.ParcelFactory(
                parcel_number="APN-900001", owner_name="Fixture Owner"
            ),
        )

    if is_enabled("wells"):
        well_type = factories.WellTypeFactory(name="Fixture Well Type")
        record("wells", factories.WellFactory(name="Fixture Well", well_type=well_type))

    if is_enabled("datasync"):
        source = factories.DataSourceFactory(name="Fixture Source", code="FIXSRC")
        record(
            "datasync",
            factories.MonitoredStationFactory(
                data_source=source,
                external_station_id="FIX-0001",
                station_name="Fixture Station",
            ),
        )

    if is_enabled("recharge"):
        record(
            "recharge",
            factories.RechargeSiteFactory(name="Fixture Recharge Site"),
        )

    # -- surface: TWO rows, because it owns two list pages --------------------
    # `/surface/` lists points of diversion and `/surface/rights/` lists water
    # rights. The POD hangs off the right rather than making a second one, so the
    # two pages describe the same water instead of two unrelated fixtures.
    if is_enabled("surface"):
        right_type = factories.WaterRightTypeFactory(
            name="Fixture Right Type", code="FIXRT"
        )
        water_right = factories.WaterRightFactory(
            right_id="WR-900001", right_type=right_type, holder_name="Fixture Holder"
        )
        record(
            "surface",
            water_right,
            factories.PointOfDiversionFactory(
                name="Fixture Diversion", water_right=water_right
            ),
        )

    # -- accounting: the period the filing below is filed FOR ------------------
    period = None
    if is_enabled("accounting"):
        period = factories.ReportingPeriodFactory(
            name="Fixture WY 2024",
            start_date=FIXTURE_PERIOD_START,
            end_date=FIXTURE_PERIOD_END,
        )
        record("accounting", period)

    # -- reporting: the row this whole plan exists for -------------------------
    # A CalWATRS `ReportSubmission` is what 89-03 found reaching
    # `reporting/views.py::calwatrs_worksheet` on a deployment with `surface`
    # dropped, where it raised `RuntimeError: Model class
    # surface.models.WaterRightType doesn't declare an explicit app_label`. Both
    # that view and `::report_prefill` branch on the report TYPE, not on module
    # availability, so the row shape is the defect's precondition — a filing that
    # outlived the module that produced it.
    #
    # Both guards, deliberately. `reporting` is what makes the model exist;
    # `accounting` is what makes its `reporting_period` FK fillable.
    if is_enabled("reporting") and is_enabled("accounting"):
        record(
            "reporting",
            factories.ReportSubmissionFactory(reporting_period=period),
        )

    return created
