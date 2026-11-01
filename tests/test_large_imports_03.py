# SPDX-License-Identifier: AGPL-3.0-or-later
"""
151.6-03: one upload for a whole file, on all five import pages.

A clerk downloads three years of lab results (22,367 rows for the Merced
demonstration) and today cuts it into five pieces, because a page refuses more
rows than its cap and carries every parsed row through the browser between the
preview and Import. These tests are written against the plan's design and fail
on the code before it:

* the upload is saved once, on the preview, and the form carries only a token
  and the page's settings (never ``rows_json``);
* Import re-parses the stored file and commits it in a detached worker, then
  the page polls a status route and shows the same result block as before;
* a token that is missing, older than 24 hours, of another kind or another
  person's is refused with one sentence;
* the stored file is gone after Import, whether the commit succeeded or not,
  and cleanup removes what nobody finished.

Names these tests assume (stage 2 must match):

* model ``core.models.PendingImport`` with fields ``token`` (uuid), ``kind``
  (``water_rights``, ``diversions``, ``lab_results``, ``production``,
  ``infrastructure``), ``user``, ``original_name``, ``size_bytes``,
  ``stored_path``, ``settings``, ``created_at``, ``status`` (``waiting``,
  ``running``, ``finished``, ``failed``), ``result``, ``started_at``,
  ``finished_at``;
* the preview form carries ``<input name="token" value="<uuid>">`` and each
  page's Import posts ``token`` plus the page's own settings fields;
* GET route ``core:pending_import_status`` taking the token as its one path
  argument;
* setting ``OPENH2O_IMPORT_INLINE`` (True runs the worker in process);
* management command ``run_pending_import --token <uuid>``;
* files are stored under ``MEDIA_ROOT/imports/``;
* the worker is started through ``subprocess.Popen`` looked up on the
  ``subprocess`` module at call time, and the commit functions are looked up
  on their modules at call time (the tests patch them there).
"""
import calendar
import gzip
import io
import json
import re
import sys
import uuid
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import factory
import pytest
from django.apps import apps
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError, OutputWrapper
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from drinking import importer as lab_importer
from drinking import production_import
from drinking.models import SampleResult, SystemProduction
from infrastructure import importer as infra_importer
from surface import diversion_import, importer as rights_importer
from surface.models import DiversionRecord, WaterRight, WaterRightType
from tests.factories import (
    PointOfDiversionFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterRightFactory,
    WaterRightTypeFactory,
    WaterSystemFactory,
)
from tests.test_water_right_door import RIGHTS_LIST_HEADER, RIGHTS_LIST_ROW_A001885
from wells.models import Well

pytestmark = pytest.mark.django_db

REFUSED = "This upload has expired or belongs to someone else. Upload the file again."
UNEXPECTED = (
    "An unexpected error stopped the import, and OpenH2O saved nothing from this file."
)
MB = 1024 * 1024
MERCED_FILE = (
    Path(__file__).resolve().parent.parent
    / "data" / "merced" / "drinking" / "merced_lab_results_3yr.tab.gz"
)
MERCED_ROWS = 22_367


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"bigimportuser{n}")
    email = factory.Sequence(lambda n: f"bigimportuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture(autouse=True)
def media_root_and_inline_worker(settings, tmp_path):
    """Stored uploads land in a temp folder; the worker runs in process."""
    settings.MEDIA_ROOT = tmp_path
    settings.OPENH2O_IMPORT_INLINE = True


@pytest.fixture
def auth_client(db):
    client = Client()
    client.force_login(_UserFactory())
    return client


@pytest.fixture
def other_client(db):
    client = Client()
    client.force_login(_UserFactory())
    return client


def _pending():
    return apps.get_model("core", "PendingImport")


def _stored_files(settings):
    folder = Path(settings.MEDIA_ROOT) / "imports"
    return sorted(p for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


# ---------------------------------------------------------------------------
# The five pages, each with a file builder of any length
# ---------------------------------------------------------------------------


def _rights_file(n):
    rows = [
        RIGHTS_LIST_ROW_A001885.replace("A001885", f"A{i:06d}", 1) for i in range(n)
    ]
    text = RIGHTS_LIST_HEADER + "\n" + "\n".join(rows) + "\n"
    return "rights-list.csv", text.encode()


def _rights_setup(n):
    WaterRightType.objects.get_or_create(
        code="POST14", defaults={"name": "Post-1914 Appropriative"}
    )


def _diversions_file(n):
    lines = ["APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT"]
    for i in range(n):
        lines.append(f"D{i // 12:04d},2024,{i % 12 + 1},DIRECT,{10 + i % 7}")
    return "monthly-diversion-2024.csv", ("\n".join(lines) + "\n").encode()


def _diversions_setup(n):
    right_type = WaterRightTypeFactory()
    for r in range(-(-n // 12)):
        right = WaterRightFactory(right_id=f"D{r:04d}", right_type=right_type)
        PointOfDiversionFactory(water_right=right, name=f"D{r:04d}_01")


def _lab_file(n):
    lines = ["PS Code,Sample Date,Analyte Name,Result"]
    start = date(1990, 1, 1)
    for i in range(n):
        lines.append(
            f"CA0000042_001_001,{(start + timedelta(days=i)).isoformat()},Arsenic,0.004"
        )
    return "lab-results.csv", ("\n".join(lines) + "\n").encode()


def _lab_setup(n):
    call_command("seed_drinking", verbosity=0)
    system = WaterSystemFactory(pwsid="CA0000042", name="Demonstration Water District")
    well = SystemFacilityFactory(system=system, facility_id="001", facility_type="WL")
    SamplingPointFactory(
        ps_code="CA0000042_001_001", facility=well, point_type="source"
    )


_PRODUCTION_CODES = [
    "GW", "SW", "Purchased", "Sold", "Recycled", "NonPotable", "NonPotableSold",
]


def _production_file(n):
    lines = [
        "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,"
        "Quantity as in Units Reported"
    ]
    for i in range(n):
        year, rem = 2000 + i // 84, i % 84
        month = rem // 7 + 1
        code = _PRODUCTION_CODES[rem % 7]
        lines.append(
            f"CA2410011,{year},{calendar.month_name[month]},{month}/1/{year},"
            f"{code},G,{1000 + i}"
        )
    return "ear-production.csv", ("\n".join(lines) + "\n").encode()


def _production_setup(n):
    WaterSystemFactory(pwsid="CA2410011", name="Le Grand Community Services District")


def _wells_file(n):
    lines = ["name,LAT,LON"]
    for i in range(n):
        lines.append(f"Well {i:05d},{37.2 + (i % 100) * 0.001:.3f},-119.5")
    return "wells.csv", ("\n".join(lines) + "\n").encode()


def _wells_setup(n):
    pass


_RIGHTS_MAP = {
    f"map:{field}": col
    for field, col in rights_importer.auto_map_columns(RIGHTS_LIST_HEADER.split(",")).items()
}


class Page:
    def __init__(self, kind, preview, commit, build, setup, old_cap, model,
                 created_text, preview_fields=None, commit_fields=None,
                 failing_function=None):
        self.kind = kind
        self.preview_name = preview
        self.commit_name = commit
        self.build = build
        self.setup = setup
        self.old_cap = old_cap
        self.model = model
        self.created_text = created_text
        self.preview_fields = preview_fields or {}
        self.commit_fields = commit_fields or {}
        self.failing_function = failing_function

    def __repr__(self):
        return self.kind

    @property
    def preview_url(self):
        return reverse(self.preview_name)

    @property
    def commit_url(self):
        return reverse(self.commit_name)


PAGES = [
    Page(
        "water_rights", "surface:water_right_import_preview",
        "surface:water_right_import_commit", _rights_file, _rights_setup, 500,
        WaterRight, lambda n: f"Created {n}",
        commit_fields=_RIGHTS_MAP, failing_function=(rights_importer, "commit_rows"),
    ),
    Page(
        "diversions", "surface:diversion_import_preview",
        "surface:diversion_import_commit", _diversions_file, _diversions_setup,
        2000, DiversionRecord, lambda n: f"Created {n}",
        commit_fields={"method": "", "data_state": "provisional"},
        failing_function=(diversion_import, "import_diversion_rows"),
    ),
    Page(
        "lab_results", "drinking:import_preview", "drinking:import_commit",
        _lab_file, _lab_setup, 5000, SampleResult, lambda n: f"{n} result",
        failing_function=(lab_importer, "commit_rows"),
    ),
    Page(
        "production", "drinking:production_import_preview",
        "drinking:production_import_commit", _production_file, _production_setup,
        2000, SystemProduction, lambda n: f"{n} imported",
        failing_function=(production_import, "import_production_rows"),
    ),
    Page(
        "infrastructure", "infrastructure:import_preview",
        "infrastructure:import_commit", _wells_file, _wells_setup, 500, Well,
        lambda n: f"Created {n}",
        preview_fields={"infra_type": "well"},
        commit_fields={
            "infra_type": "well", "map:name": "name",
            "map:latitude": "LAT", "map:longitude": "LON",
        },
        failing_function=(infra_importer, "commit_rows"),
    ),
]
PAGE_IDS = [p.kind for p in PAGES]


def _preview(client, page, name, data, **extra):
    payload = {
        "file": SimpleUploadedFile(name, data, content_type="text/csv"),
        **page.preview_fields,
        **extra,
    }
    return client.post(page.preview_url, payload, HTTP_HX_REQUEST="true")


def _token(response):
    body = response.content.decode()
    for tag in re.findall(r"<input[^>]*>", body):
        if re.search(r'name="token"', tag):
            return unescape(re.search(r'value="([^"]+)"', tag).group(1))
    raise AssertionError("the preview form has no token field")


def _status(client, token):
    return client.get(
        reverse("core:pending_import_status", args=[token]), HTTP_HX_REQUEST="true"
    )


def _import(client, page, token, **extra):
    """Press Import, then read the status route the page would poll."""
    response = client.post(
        page.commit_url,
        {"token": token, **page.commit_fields, **extra},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    return _status(client, token).content.decode()


def _upload_through_preview(client, page, n):
    page.setup(n)
    name, data = page.build(n)
    preview = _preview(client, page, name, data)
    assert preview.status_code == 200
    return _token(preview)


# ---------------------------------------------------------------------------
# (a) every page imports a file over its old cap, preview then Import
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_a_file_over_the_old_cap_imports_whole(auth_client, settings, page):
    n = page.old_cap + 100
    token = _upload_through_preview(auth_client, page, n)

    body = _import(auth_client, page, token)

    assert page.created_text(n) in body
    assert page.model.objects.count() == n
    assert _stored_files(settings) == []


# ---------------------------------------------------------------------------
# (b) the Merced three-year lab file, whole
# ---------------------------------------------------------------------------


def test_the_merced_three_year_lab_file_imports_whole(auth_client, settings):
    from drinking.management.commands.seed_merced_drinking import Command

    call_command("seed_well_types")
    call_command("seed_drinking", verbosity=0)
    seed = Command()
    seed.stdout = OutputWrapper(io.StringIO())
    system = seed._seed_system()
    rows, _columns = seed._load_lab_file()
    assert len(rows) == MERCED_ROWS
    seed._apply_state_fields(system, rows)
    seed._seed_points(system)
    assert SampleResult.objects.count() == 0

    with gzip.open(MERCED_FILE, "rb") as handle:
        data = handle.read()
    upload = SimpleUploadedFile(
        "merced_lab_results_3yr.tab", data, content_type="text/tab-separated-values"
    )
    preview = auth_client.post(
        reverse("drinking:import_preview"), {"file": upload}, HTTP_HX_REQUEST="true"
    )
    assert preview.status_code == 200
    token = _token(preview)

    page = PAGES[2]
    body = _import(auth_client, page, token)

    assert re.search(r"\b22,?367 result", body)
    assert SampleResult.objects.count() == MERCED_ROWS
    assert _stored_files(settings) == []


# ---------------------------------------------------------------------------
# (c) the preview form carries a token and no rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_the_preview_form_carries_a_token_and_no_rows(auth_client, settings, page):
    page.setup(12)
    name, data = page.build(12)

    preview = _preview(auth_client, page, name, data)

    body = preview.content.decode()
    assert "rows_json" not in body
    token = _token(preview)
    uuid.UUID(token)
    pending = _pending().objects.get(token=token)
    assert pending.kind == page.kind
    assert pending.original_name == name
    assert pending.size_bytes == len(data)
    assert str(pending.user_id) == str(auth_client.session["_auth_user_id"])
    stored = _stored_files(settings)
    assert len(stored) == 1
    assert stored[0].read_bytes() == data
    assert name not in stored[0].name


# ---------------------------------------------------------------------------
# (d) a bad token is refused in one sentence; the file does not outlive Import
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_an_expired_token_is_refused(auth_client, page):
    token = _upload_through_preview(auth_client, page, 12)
    _pending().objects.filter(token=token).update(
        created_at=timezone.now() - timedelta(hours=25)
    )

    response = auth_client.post(
        page.commit_url, {"token": token, **page.commit_fields}, HTTP_HX_REQUEST="true"
    )

    assert REFUSED in unescape(response.content.decode())
    assert page.model.objects.count() == 0


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_another_persons_token_is_refused(auth_client, other_client, page):
    token = _upload_through_preview(auth_client, page, 12)

    response = other_client.post(
        page.commit_url, {"token": token, **page.commit_fields}, HTTP_HX_REQUEST="true"
    )

    assert REFUSED in unescape(response.content.decode())
    assert REFUSED in unescape(_status(other_client, token).content.decode())
    assert page.model.objects.count() == 0


@pytest.mark.parametrize("index", range(len(PAGES)), ids=PAGE_IDS)
def test_a_token_from_another_page_is_refused(auth_client, index):
    page = PAGES[index]
    token = _upload_through_preview(auth_client, page, 12)
    wrong = PAGES[(index + 1) % len(PAGES)]

    response = auth_client.post(
        wrong.commit_url, {"token": token, **wrong.commit_fields},
        HTTP_HX_REQUEST="true",
    )

    assert REFUSED in unescape(response.content.decode())
    assert wrong.model.objects.count() == 0
    assert page.model.objects.count() == 0


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
@pytest.mark.parametrize("given", ["", "not-a-uuid", str(uuid.uuid4())])
def test_a_missing_or_unknown_token_is_refused(auth_client, page, given):
    response = auth_client.post(
        page.commit_url, {"token": given, **page.commit_fields}, HTTP_HX_REQUEST="true"
    )

    assert REFUSED in unescape(response.content.decode())


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_the_stored_file_is_gone_after_a_good_import(auth_client, settings, page):
    token = _upload_through_preview(auth_client, page, 12)
    assert len(_stored_files(settings)) == 1

    body = _import(auth_client, page, token)

    assert page.created_text(12) in body
    assert _stored_files(settings) == []
    # The status view deletes the row once it has shown the result.
    assert not _pending().objects.filter(token=token).exists()


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_the_stored_file_is_gone_after_a_failed_import(
    auth_client, settings, monkeypatch, page
):
    token = _upload_through_preview(auth_client, page, 12)
    assert len(_stored_files(settings)) == 1
    owner, attribute = page.failing_function
    real = getattr(owner, attribute)

    def failing(*args, **kwargs):
        # The preview runs the same function as a dry run; only a write fails.
        if kwargs.get("dry_run") is True:
            return real(*args, **kwargs)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(owner, attribute, failing)

    body = unescape(_import(auth_client, page, token))

    assert UNEXPECTED in body
    assert "synthetic failure" not in body
    assert page.model.objects.count() == 0
    assert _stored_files(settings) == []
    assert not _pending().objects.filter(token=token).exists()


# ---------------------------------------------------------------------------
# (e) a settings change re-parses the stored file, with no rows posted
# ---------------------------------------------------------------------------


def test_a_diversion_point_change_re_parses_the_stored_file(auth_client):
    right = WaterRightFactory(right_id="A001885")
    PointOfDiversionFactory(water_right=right, name="A001885_01")
    point = PointOfDiversionFactory(water_right=right, name="A001885_02")
    name = "monthly-diversion-2024.csv"
    lines = ["APPL_ID,YEAR,MONTH,DIVERSION_TYPE,AMOUNT"] + [
        f"A001885,2024,{m},DIRECT,{20 + m}" for m in range(1, 13)
    ]
    data = ("\n".join(lines) + "\n").encode()
    page = PAGES[1]

    first = _preview(auth_client, page, name, data)
    token = _token(first)
    assert len(first.context["unresolved_rows"]) > 0

    second = auth_client.post(
        page.preview_url,
        {"token": token, "point": point.pk, "method": "", "data_state": "provisional"},
        HTTP_HX_REQUEST="true",
    )

    assert second.status_code == 200
    assert "rows_json" not in second.content.decode()
    assert _token(second) == token
    assert second.context["unresolved_rows"] == []
    assert second.context["created"] == 12
    assert _pending().objects.filter(token=token).count() == 1
    assert str(point.pk) in json.dumps(_pending().objects.get(token=token).settings)


def test_a_production_unit_change_re_parses_the_stored_file(auth_client):
    WaterSystemFactory(pwsid="CA2410011", name="Le Grand Community Services District")
    text = (
        "PWSID,Year,Month,DateStartOfMonth,TypeCode,Units of Measure As Reported,"
        "Quantity as in Units Reported\n"
        "CA2410011,2022,January,1/1/2022,GW,,4007800\n"
        "CA2410011,2022,February,2/1/2022,GW,,3567300\n"
        "CA2410011,2022,March,3/1/2022,GW,,4037700\n"
    )
    page = PAGES[3]

    first = _preview(auth_client, page, "ear-2022-production.csv", text.encode())
    token = _token(first)
    assert len(first.context["errors"]) == 3

    second = auth_client.post(
        page.preview_url,
        {"token": token, "unit_for_blank": "G"},
        HTTP_HX_REQUEST="true",
    )

    assert second.status_code == 200
    assert "rows_json" not in second.content.decode()
    assert _token(second) == token
    assert second.context["errors"] == []
    assert _pending().objects.filter(token=token).count() == 1
    assert "G" in json.dumps(_pending().objects.get(token=token).settings)


# ---------------------------------------------------------------------------
# (f) the 25 MB guard still refuses a 26 MB file, and stores nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_the_25_mb_guard_still_refuses_a_26_mb_file(auth_client, settings, page):
    page.setup(12)
    data = b"a,b,c\n".ljust(26 * MB, b"x")

    response = _preview(auth_client, page, "too-big.csv", data)

    body = unescape(response.content.decode())
    assert "26 MB" in body
    assert "25 MB" in body
    assert not _pending().objects.exists()
    assert _stored_files(settings) == []


# ---------------------------------------------------------------------------
# (g) cleanup: a new preview, and prune_old_data
# ---------------------------------------------------------------------------


def _age(token, hours=25):
    _pending().objects.filter(token=token).update(
        created_at=timezone.now() - timedelta(hours=hours)
    )


def test_a_new_preview_removes_pending_imports_older_than_a_day(
    auth_client, other_client, settings
):
    page = PAGES[4]
    name, data = page.build(12)
    old = _token(_preview(other_client, page, name, data))
    recent = _token(_preview(other_client, page, name, data))
    _age(old)
    _age(recent, hours=1)
    assert len(_stored_files(settings)) == 2

    _preview(auth_client, page, name, data)

    tokens = set(map(str, _pending().objects.values_list("token", flat=True)))
    assert old not in tokens
    assert recent in tokens
    assert len(tokens) == 2
    assert len(_stored_files(settings)) == 2


def test_prune_old_data_removes_pending_imports_older_than_a_day(
    auth_client, settings
):
    page = PAGES[4]
    name, data = page.build(12)
    old = _token(_preview(auth_client, page, name, data))
    recent = _token(_preview(auth_client, page, name, data))
    _age(old)
    _age(recent, hours=1)
    assert len(_stored_files(settings)) == 2

    call_command("prune_old_data", "--confirm", stdout=io.StringIO())

    tokens = set(map(str, _pending().objects.values_list("token", flat=True)))
    assert tokens == {recent}
    assert len(_stored_files(settings)) == 1


# ---------------------------------------------------------------------------
# The detached worker, as production starts it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_import_starts_a_detached_worker_and_the_page_polls(
    auth_client, settings, monkeypatch, django_capture_on_commit_callbacks, page
):
    settings.OPENH2O_IMPORT_INLINE = False
    started = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            started.append((args, kwargs))

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    token = _upload_through_preview(auth_client, page, 12)
    name, _data = page.build(12)

    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client.post(
            page.commit_url, {"token": token, **page.commit_fields},
            HTTP_HX_REQUEST="true",
        )

    body = response.content.decode()
    assert len(started) == 1
    args, kwargs = started[0]
    assert args == [sys.executable, "manage.py", "run_pending_import", "--token", token]
    assert kwargs["start_new_session"] is True
    assert Path(kwargs["cwd"]) == Path(settings.BASE_DIR)
    assert 'hx-trigger="every 2s"' in body
    assert reverse("core:pending_import_status", args=[token]) in body
    assert f"OpenH2O is importing {name}." in unescape(body)
    assert page.model.objects.count() == 0
    assert _pending().objects.get(token=token).status == "waiting"
    assert len(_stored_files(settings)) == 1

    # While the worker has not run, the status route keeps the waiting block.
    waiting = _status(auth_client, token).content.decode()
    assert 'hx-trigger="every 2s"' in waiting

    # The worker, run by hand as the spawned process would.
    call_command("run_pending_import", "--token", token)
    assert _pending().objects.get(token=token).status == "finished"
    done = _status(auth_client, token).content.decode()
    assert page.created_text(12) in done
    assert 'hx-trigger="every 2s"' not in done
    assert page.model.objects.count() == 12
    assert _stored_files(settings) == []
    assert not _pending().objects.filter(token=token).exists()


def test_the_worker_command_refuses_a_token_that_is_not_a_uuid():
    with pytest.raises(CommandError, match="--token must be a UUID"):
        call_command("run_pending_import", "--token", "1; rm -rf /")


# ---------------------------------------------------------------------------
# The upload pages no longer name a row cap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route",
    [
        "drinking:import",
        "drinking:production_import",
        "surface:diversion_import",
        "surface:water_right_import",
        "infrastructure:import",
    ],
)
def test_no_import_page_names_a_row_cap(auth_client, route):
    url = reverse(route)
    if route == "infrastructure:import":
        url += "?type=well"

    body = auth_client.get(url).content.decode()

    assert not re.search(r"up to [\d,]+ (rows|records|map features)", body, re.I)
    assert not re.search(r"[\d,]+ (rows|records) per file", body, re.I)
