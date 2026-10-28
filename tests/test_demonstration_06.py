# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading and removing the demonstration data, its page, and what retired with it.

The full load takes minutes and is covered by a timed round trip on a scratch
stack; no test here runs it. A test that needs a load replaces the step runner
with one that writes a few rows.
"""
import re
import subprocess
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from core import demonstration as demo
from core import modules as mod
from core.models import SiteConfig
from tests import factories as f

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


# -- helpers ---------------------------------------------------------------


def _all_counts():
    """Rows in every model there is, content or not, keyed by label."""
    import pghistory.models as ph

    counts = {}
    for model in apps.get_models():
        if issubclass(model, ph.Event) or model._meta.proxy or not model._meta.managed:
            continue
        if model._meta.app_label in {"gis", "pghistory"}:
            continue
        counts[model._meta.label] = model.objects.count()
    return counts


def _content_total():
    return sum(demo.content_counts().values())


def _write_a_few_rows(stdout=None):
    """Stands in for the full sequence: a boundary, a parcel and the site name."""
    f.BoundaryFactory(name=demo.DEMONSTRATION_BOUNDARY)
    f.ParcelFactory()
    SiteConfig.objects.create(agency_name=demo.DEMONSTRATION_NAME)


@pytest.fixture
def few_rows(monkeypatch):
    monkeypatch.setattr(demo, "run_steps", _write_a_few_rows)


def _admin():
    return User.objects.create_user(
        username="boss", password="x", is_staff=True, is_superuser=True
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


# -- the refusal -----------------------------------------------------------


def test_a_load_is_refused_when_the_site_holds_a_parcel(monkeypatch):
    f.ParcelFactory()
    calls = []
    monkeypatch.setattr(demo, "run_step", lambda *a, **k: calls.append(a))
    before = _all_counts()
    with pytest.raises(CommandError) as err:
        call_command("load_demonstration", stdout=StringIO())
    assert "1 use area" in str(err.value)
    assert "not loaded" in str(err.value)
    assert calls == []
    assert _all_counts() == before


def test_a_load_is_refused_when_a_section_is_off(settings, monkeypatch):
    settings.OPENH2O_MODULES = [n for n in mod.ALL_MODULE_NAMES if n != "wells"]
    calls = []
    monkeypatch.setattr(demo, "run_step", lambda *a, **k: calls.append(a))
    before = _all_counts()
    with pytest.raises(CommandError) as err:
        call_command("load_demonstration", stdout=StringIO())
    assert "Wells" in str(err.value)
    assert "nothing was loaded" in str(err.value)
    assert calls == []
    assert _all_counts() == before


def test_a_failed_load_saves_nothing(monkeypatch):
    def boom(stdout=None):
        f.ParcelFactory()
        raise RuntimeError("a step stopped")

    monkeypatch.setattr(demo, "run_steps", boom)
    before = _all_counts()
    with pytest.raises(RuntimeError):
        call_command("load_demonstration", stdout=StringIO())
    assert {k: v for k, v in _all_counts().items() if k != "health.HealthCheckResult"} == {
        k: v for k, v in before.items() if k != "health.HealthCheckResult"
    }
    assert demo.last_record().details["state"] == "failed"


# -- the step list ---------------------------------------------------------


EXPECTED_STEPS = [
    "seed_data",
    "seed_observed_properties",
    "seed_merced_base",
    "loaddata",
    "seed_merced",
    "load_station_fixture",
    "load_reading_fixture",
    "load_openet_fixture",
    "seed_calculation_plan",
    "refresh_merced_accounting",
    "seed_merced_measurements",
]


def test_the_steps_are_the_sequence_the_build_runs():
    assert [name for name, _ in demo.STEPS] == EXPECTED_STEPS
    script = (ROOT / "scripts" / "rebuild-golden.sh").read_text()
    run = re.findall(r"^run_step (\w+)", script, re.M)
    assert run == [
        "migrate",
        "createcachetable",
        "load_demonstration",
        "clear_change_history",
    ], "the build script runs a step of its own; add it to the demonstration's steps"


def test_the_steps_run_in_order_with_their_arguments(monkeypatch):
    seen = []
    monkeypatch.setattr(demo, "run_step", lambda name, args, stdout=None: seen.append(name))
    monkeypatch.setattr(demo, "load_refusal", lambda: None)
    demo.run_steps()
    assert seen == EXPECTED_STEPS


# -- the content list ------------------------------------------------------


def test_the_three_lists_and_the_registry_describe_each_other():
    import pghistory.models as ph

    named = demo.CONTENT_LABELS + demo.REFERENCE_LABELS + demo.KEPT_LABELS
    assert len(named) == len(set(named)), "a model is in two lists"
    own = set()
    for model in apps.get_models():
        if issubclass(model, ph.Event) or model._meta.app_label in demo.KEPT_APPS:
            continue
        own.add(model._meta.label)
    assert own == set(named), (
        f"not classed: {sorted(own - set(named))}; named but absent: {sorted(set(named) - own)}"
    )
    assert set(demo.SCREEN_NAMES) == set(demo.CONTENT_LABELS)


def test_a_clean_install_holds_no_content_row():
    call_command("seed_data", stdout=StringIO())
    assert demo.content_counts() == {}


def test_the_clean_install_check_reads_the_same_list():
    f.ParcelFactory()
    err = StringIO()
    with pytest.raises(CommandError):
        call_command("verify_clean_install", stderr=err)
    assert "Use areas: 1" in err.getvalue()


# -- removal ---------------------------------------------------------------


def _hand_built(name=demo.DEMONSTRATION_NAME):
    user = _admin()
    f.WaterTypeFactory()
    f.DataSourceFactory()
    boundary = f.BoundaryFactory(name=demo.DEMONSTRATION_BOUNDARY)
    zone = f.ZoneFactory(boundary=boundary)
    parcel = f.ParcelFactory()
    f.ParcelZoneFactory(parcel=parcel, zone=zone)
    well = f.WellFactory()
    f.WellIrrigatedParcelFactory(well=well, parcel=parcel)
    f.MonitoredStationFactory()
    account = f.WaterAccountFactory()
    f.WaterAccountParcelFactory(water_account=account, parcel=parcel)
    period = f.ReportingPeriodFactory()
    f.ParcelLedgerFactory(parcel=parcel, transaction_date=date(2024, 1, 15),
                          effective_date=date(2024, 1, 15))
    # A finalized year locks its rows against change; removal has to get past it.
    type(period).objects.filter(pk=period.pk).update(is_finalized=True)
    SiteConfig.objects.create(agency_name=name, demonstration_mode=True)
    return user


def test_removal_empties_every_content_table_and_keeps_the_rest():
    user = _hand_built()
    assert _content_total() > 10
    kept = {
        label: apps.get_model(label).objects.count()
        for label in demo.REFERENCE_LABELS + ["core.User"]
        if label.split(".")[0] in {"accounting", "datasync", "core"}
    }
    call_command("remove_demonstration", stdout=StringIO())
    assert demo.content_counts() == {}
    assert {
        label: apps.get_model(label).objects.count() for label in kept
    } == kept
    assert User.objects.filter(pk=user.pk).exists()
    assert not SiteConfig.objects.exists()


def test_removal_keeps_a_site_name_that_is_not_the_demonstrations():
    _hand_built(name="Example County Water Agency")
    call_command("remove_demonstration", stdout=StringIO())
    site = SiteConfig.objects.get()
    assert site.agency_name == "Example County Water Agency"
    assert site.demonstration_mode is False


def test_removal_puts_the_reference_lists_back_as_a_clean_install_has_them():
    """The demonstration's lab file teaches the analyte list new names and DDW
    codes, and its wells add a well type; a removal takes those back out."""
    from drinking.management.commands.seed_drinking import SEED
    from drinking.models import Analyte
    from wells.management.commands.seed_well_types import WELL_TYPES
    from wells.models import WellType

    call_command("seed_data", stdout=StringIO())
    seeded_analytes = Analyte.objects.count()
    seeded_types = WellType.objects.count()
    _hand_built()
    first_seeded = Analyte.objects.get(name=SEED[0][0])
    Analyte.objects.filter(pk=first_seeded.pk).update(ddw_code="9999")
    Analyte.objects.create(name="Learned From A Lab File", ddw_code="8888")
    WellType.objects.get_or_create(name="Agricultural")
    call_command("remove_demonstration", stdout=StringIO())
    assert Analyte.objects.count() == seeded_analytes
    assert not Analyte.objects.filter(name="Learned From A Lab File").exists()
    assert Analyte.objects.get(pk=first_seeded.pk).ddw_code is None
    assert WellType.objects.count() == seeded_types
    assert set(WellType.objects.values_list("name", flat=True)) == {
        t["name"] for t in WELL_TYPES
    }


def test_removal_is_refused_when_nothing_is_loaded():
    f.ParcelFactory()
    with pytest.raises(CommandError) as err:
        call_command("remove_demonstration", stdout=StringIO())
    assert "not loaded" in str(err.value)
    assert _content_total() == 1


def test_removal_reports_what_it_removed_by_screen_name():
    _hand_built()
    out = StringIO()
    call_command("remove_demonstration", stdout=out)
    assert "Removed the demonstration data (" in out.getvalue()
    assert "1 use area" in out.getvalue()


# -- change history --------------------------------------------------------


def test_a_removal_deletes_its_own_changes_and_keeps_an_earlier_one():
    from parcels.models import Parcel

    _hand_built()
    parcel = Parcel.objects.first()
    before = parcel.events.count()
    assert before >= 1
    call_command("remove_demonstration", stdout=StringIO())
    from parcels.models import ParcelEvent

    mine = ParcelEvent.objects.filter(pgh_obj_id=parcel.pk)
    assert mine.count() == before
    assert not mine.filter(pgh_label="delete").exists()
    from pghistory.models import Context

    assert not Context.objects.filter(metadata__action="remove_demonstration").exists()


def test_a_load_deletes_its_own_changes_and_keeps_an_earlier_one(few_rows):
    earlier = _admin()
    seen = earlier.events.count()
    call_command("load_demonstration", stdout=StringIO())
    from parcels.models import ParcelEvent

    assert ParcelEvent.objects.count() == 0
    assert earlier.events.count() == seen
    from pghistory.models import Context

    assert not Context.objects.filter(metadata__action="load_demonstration").exists()


def test_a_run_leaves_one_site_health_record(few_rows):
    call_command("load_demonstration", stdout=StringIO())
    record = demo.last_record()
    assert record.message.startswith("Loaded the demonstration data (")
    assert record.details["state"] == "succeeded"
    call_command("remove_demonstration", stdout=StringIO())
    from health.models import HealthCheckResult

    assert HealthCheckResult.objects.filter(category=demo.HEALTH_CATEGORY).count() == 2
    assert demo.last_record().message.startswith("Removed the demonstration data (")


def test_a_golden_build_writes_no_site_health_record(few_rows):
    call_command("load_demonstration", "--golden-build", stdout=StringIO())
    assert demo.last_record() is None


def test_a_load_turns_demonstration_mode_on_for_an_existing_site_name(monkeypatch):
    def rows(stdout=None):
        f.BoundaryFactory(name=demo.DEMONSTRATION_BOUNDARY)

    SiteConfig.objects.create(agency_name="My District")
    monkeypatch.setattr(demo, "run_steps", rows)
    call_command("load_demonstration", stdout=StringIO())
    assert SiteConfig.objects.get().demonstration_mode is True


# -- the page and its buttons ---------------------------------------------


URL = reverse("setup:demonstration")


def test_the_page_offers_load_on_a_clean_site(admin_client):
    body = admin_client.get(URL).content.decode()
    assert "Load the demonstration data" in body
    assert 'value="load"' in body


def test_the_page_gives_a_refusal_and_no_button_when_the_site_has_records(admin_client):
    f.ParcelFactory()
    body = admin_client.get(URL).content.decode()
    assert "This site already holds 1 use area" in body
    assert 'value="load"' not in body


def test_the_page_names_a_section_that_is_off(admin_client, settings):
    settings.OPENH2O_MODULES = [n for n in mod.ALL_MODULE_NAMES if n != "recharge"]
    body = admin_client.get(URL).content.decode()
    assert "Recharge" in body and 'value="load"' not in body


def test_the_load_button_loads_and_the_page_then_offers_remove(admin_client, few_rows):
    response = admin_client.post(URL, {"action": "load"})
    assert response.status_code == 302
    assert demo.is_loaded()
    body = admin_client.get(URL).content.decode()
    assert "The demonstration data is loaded" in body
    assert "?remove=1" in body
    assert "Loaded the demonstration data (" in body


def test_the_remove_step_lists_what_goes_and_what_people_added(admin_client, few_rows):
    admin_client.post(URL, {"action": "load"})
    # The suite runs in one transaction, whose clock is older than the load's
    # record; move the record back so the load reads as older, as it is in life.
    from datetime import timedelta

    from django.utils import timezone
    from health.models import HealthCheckResult

    HealthCheckResult.objects.update(checked_at=timezone.now() - timedelta(days=1))
    # A record a signed-in person adds after the load.
    from pghistory import context as ctx

    user = User.objects.filter(is_superuser=True).first() or _admin()
    with ctx(user=user.pk, url="/parcels/"):
        f.ParcelFactory()
    body = admin_client.get(URL + "?remove=1").content.decode()
    assert "Removing deletes every record on this site, 3 in all" in body
    assert "1 of these records was added by people since the load" in body
    assert "Use areas" in body
    # The load made the site's name and settings, so the step says they go.
    assert "so they go too, with any setting changed since the load" in body


def test_the_remove_button_returns_the_site_to_empty(admin_client, few_rows):
    admin_client.post(URL, {"action": "load"})
    admin_client.post(URL, {"action": "remove"})
    assert demo.content_counts() == {}
    assert not demo.is_loaded()
    assert "Removed the demonstration data (" in admin_client.get(URL).content.decode()


@override_settings(ACCESS_CONTROL_ENFORCED=True)
def test_a_person_who_is_not_an_administrator_is_turned_away(few_rows):
    operator = User.objects.create_user(username="op", password="x")
    client = _client(operator)
    assert client.get(URL).status_code == 302
    client.post(URL, {"action": "load"})
    assert not demo.is_loaded()


@override_settings(ACCESS_CONTROL_ENFORCED=False)
def test_with_the_switch_off_only_an_administrator_can_press_a_button(few_rows):
    operator = User.objects.create_user(username="op", password="x")
    client = _client(operator)
    page = client.get(URL).content.decode()
    assert "Load the demonstration data" in page and 'value="load"' not in page
    client.post(URL, {"action": "load"})
    assert not demo.is_loaded()
    assert demo.last_record() is None


def test_a_second_press_while_a_run_holds_the_lock_starts_nothing(admin_client, few_rows):
    other = connection.copy()
    cursor = other.cursor()
    cursor.execute("SELECT pg_advisory_lock(%s)", [demo.ADVISORY_LOCK_KEY])
    try:
        response = admin_client.post(URL, {"action": "load"}, follow=True)
        assert "A run is in progress" in response.content.decode()
        assert not demo.is_loaded()
        assert demo.last_record() is None
        partial = admin_client.get(URL, HTTP_HX_REQUEST="true").content.decode()
        assert "hx-trigger" in partial and "<html" not in partial
    finally:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [demo.ADVISORY_LOCK_KEY])
        other.close()


def test_the_worker_is_started_after_commit_with_fixed_arguments(settings, monkeypatch, admin_client):
    settings.OPENH2O_CALCULATION_INLINE = False
    launched = []
    monkeypatch.setattr(demo.transaction, "on_commit", lambda fn: launched.append(fn))
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    admin_client.post(URL, {"action": "load"})
    assert len(launched) == 1
    launched[0]()
    argv = launched[1]
    assert argv[1:3] == ["manage.py", "load_demonstration"]
    assert all(a.isdigit() for a in argv[4::2])


def test_the_links_to_the_page(admin_client):
    assert URL in admin_client.get(reverse("setup:wizard")).content.decode()
    assert URL in admin_client.get(reverse("demonstration_data")).content.decode()
    assert URL in admin_client.get(reverse("getting_started")).content.decode()



# -- the Setup Wizard asks first (ruling 33) --------------------------------


WIZARD = reverse("setup:wizard")


def test_the_wizard_opens_with_the_choice_on_a_clean_site(admin_client):
    body = admin_client.get(WIZARD).content.decode()
    assert "How do you want to start?" in body
    assert f'action="{URL}"' in body and 'value="load"' in body
    assert f'href="{WIZARD}?start=own"' in body
    assert "Upload a boundary file" not in body


def test_starting_with_your_own_records_shows_the_boundary_step(admin_client):
    body = admin_client.get(WIZARD + "?start=own").content.decode()
    assert "Upload a boundary file" in body
    assert "How do you want to start?" not in body
    assert f'href="{WIZARD}"' in body  # back to the choice


def test_a_site_with_records_goes_straight_to_the_boundary_step(admin_client):
    f.BoundaryFactory(name="Own Boundary")
    body = admin_client.get(WIZARD).content.decode()
    assert "How do you want to start?" not in body
    assert "Upload a boundary file" in body


def test_a_site_with_a_section_off_goes_straight_to_the_boundary_step(admin_client, settings):
    settings.OPENH2O_MODULES = [n for n in mod.ALL_MODULE_NAMES if n != "recharge"]
    body = admin_client.get(WIZARD).content.decode()
    assert "How do you want to start?" not in body
    assert "Upload a boundary file" in body


def test_the_wizard_says_when_the_demonstration_is_loaded(admin_client, few_rows):
    admin_client.post(URL, {"action": "load"})
    body = admin_client.get(WIZARD).content.decode()
    assert "How do you want to start?" not in body
    assert ("The demonstration data is loaded. Remove it on "
            f'<a href="{URL}"') in body


def test_the_choices_load_button_loads(admin_client, few_rows):
    admin_client.post(URL, {"action": "load"})  # what the choice's form sends
    assert demo.is_loaded()


# -- a refusal gives a next step --------------------------------------------


def test_a_refusal_for_records_gives_a_next_step(admin_client):
    f.ParcelFactory()
    body = admin_client.get(URL).content.decode()
    assert "To try it on this site, delete those records first." in body
    assert "install a second copy of OpenH2O and load it there" in body


def test_a_refusal_for_a_section_names_the_setting(admin_client, settings):
    settings.OPENH2O_MODULES = [n for n in mod.ALL_MODULE_NAMES if n != "recharge"]
    body = admin_client.get(URL).content.decode()
    assert "OPENH2O_MODULES" in body and "section 12 of DEPLOY.md" in body
    assert "does not hold records of its own" not in body

# -- the retired sample district is gone -------------------------------------


_RETIRED = [
    "demo " + "valley",
    "demo-" + "valley",
    "demo" + "valley",
    "seed_demo" + "_data",
    "teardown" + "_demo",
    "teardown" + "-demo",
    "flush" + "-demo",
]
#: Files that mention the retired names and are not part of this change; the
#: first two need a one line edit each.
_NOT_YET: set[str] = set()
_SKIP_DIRS = {
    ".git", ".planning", "staticfiles", "media", "node_modules", ".venv", "__pycache__",
    ".pytest_cache", ".ruff_cache",
}


def _tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split("\n")
        return [p for p in out if p]
    except (OSError, subprocess.CalledProcessError):
        found = []
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if path.is_file() and not (set(rel.parts) & _SKIP_DIRS):
                found.append(str(rel))
        return found


def test_the_retired_sample_district_is_named_nowhere():
    hits = []
    for rel in _tracked_files():
        if rel.startswith(".planning/") or rel in _NOT_YET:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore").lower()
        except OSError:
            continue
        for word in _RETIRED:
            if word in text:
                hits.append((rel, word))
    assert hits == []


def test_the_retired_commands_are_gone():
    with pytest.raises(CommandError):
        call_command("seed_" + "demo_data")
    with pytest.raises(CommandError):
        call_command("teardown" + "_demo")


# -- Getting started without the infrastructure section ---------------------


def test_getting_started_names_import_wells_when_infrastructure_is_off(admin_client, settings):
    settings.OPENH2O_MODULES = [n for n in mod.ALL_MODULE_NAMES if n != "infrastructure"]
    body = admin_client.get(reverse("getting_started")).content.decode()
    assert "import_wells" in body
    assert "Add well" not in body
    assert "with Import" not in body
    assert "add each point of diversion" not in body
    assert "add each site" not in body


def test_getting_started_names_the_buttons_when_infrastructure_is_on(admin_client):
    body = admin_client.get(reverse("getting_started")).content.decode()
    assert "Add wells one at a time with Add well" in body
    assert "add each point of diversion" in body
    assert "add each site" in body
    assert "import_wells" not in body


def test_site_health_leaves_out_a_runs_record(client):
    """A refused or failed run is the Demonstration data page's to show; it must
    not hold the whole site at "degraded" until the next run."""
    from health.models import HealthCheckResult

    HealthCheckResult.objects.create(
        category=demo.HEALTH_CATEGORY, status="yellow", message="refused"
    )
    assert client.get("/health/api/").json()["status"] == "unknown"


def test_add_ledger_entry_lists_use_areas_in_number_order():
    """The use-area list read the table's storage order, which changes with how
    the rows were written; it is in number order."""
    from accounting.forms import ParcelLedgerForm

    for number in ("APN-003", "APN-001", "APN-002"):
        f.ParcelFactory(parcel_number=number)
    from parcels.models import Parcel

    Parcel.objects.filter(parcel_number="APN-001").update(address="moved")
    listed = [p.parcel_number for p in ParcelLedgerForm().fields["parcel"].queryset]
    assert listed == ["APN-001", "APN-002", "APN-003"]
