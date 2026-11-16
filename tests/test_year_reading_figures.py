# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every figure the year's pages print stays exactly as it was before the pages read the year at once.

The dashboard, the water accounts list, a zone's page and the figures a filed
year keeps (``accounting.statements.collect_figures``) used to add up a year one
place at a time. They now read the year's records once and add up from that one
reading. These tests hold every figure still while that changes:
``tests/data/year_figures_before.json`` holds every figure the four printed on
``tests/year_reading_world.py``'s records BEFORE the change, and each test
compares the figures now with it, figure by figure, naming the first that differs.

The file is written by this module on the commit before the change, with the
records built the same way:

    docker compose exec -T -e YEAR_FIGURES_WRITE=1 web python -m pytest \
        tests/test_year_reading_figures.py --ds=config.settings.local -p no:randomly

and is then never written again. A figure that must change for a reason of its
own changes the file in the same commit, with the reason in the message.
"""
import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.test import Client
from django.urls import reverse

from accounting.statements import collect_figures
from geography.models import Zone
from tests import year_reading_world as world

pytestmark = pytest.mark.django_db

FILE = Path(__file__).parent / "data" / "year_figures_before.json"
WRITE = os.environ.get("YEAR_FIGURES_WRITE") == "1"

#: The dashboard's figures and counts, beside its rows (its dates are not figures).
DASHBOARD_KEYS = (
    "grand_consumptive_use", "grand_supply_total", "grand_supply_surface", "grand_supply_groundwater",
    "grand_supply_precip", "grand_surface_lines", "grand_groundwater_lines", "grand_not_consumed",
    "grand_uses_total", "grand_net", "accounts_with_estimates", "grand_calculation_runs",
    "accounts_in_surplus", "accounts_in_deficit", "accounts_balanced", "has_allocations",
    "engine_has_never_run", "accounts_over_budget", "unmet_demand_rows", "unmet_demand_total",
    "unmet_demand_count", "attention_total", "periods_to_close",
)
ACCOUNTS_LIST_KEYS = (
    "grand_consumptive_use", "grand_supply_total", "grand_supply_surface", "grand_supply_groundwater",
    "grand_supply_precip", "grand_not_consumed", "grand_net", "has_allocations", "engine_has_never_run",
    "total_count", "matched_count",
)


def plain(value):
    """A value as JSON can hold it: a Decimal as ``"D:<text>"``, a record as its name or number."""
    if isinstance(value, Decimal):
        return f"D:{value}"
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, Model):
        for name in ("account_number", "parcel_number", "code", "name"):
            if hasattr(value, name):
                return f"{type(value).__name__}:{getattr(value, name)}"
        return f"{type(value).__name__}"
    if isinstance(value, set):
        return sorted(plain(v) for v in value)
    return value


def _figures_rows(period):
    return [
        [f.scope, f.scope_name, f.month.isoformat() if f.month else None, f.figure, plain(f.value), f.method, f.detail]
        for f in collect_figures(period)
    ]


def _row_fields(row):
    return {k: plain(v) for k, v in row.items() if k not in ("account", "zone")}


def _dashboard(client, period):
    response = client.get(reverse("accounting:dashboard"), {"period": period.pk})
    assert response.status_code == 200
    c = response.context
    found = {key: plain(c[key]) for key in DASHBOARD_KEYS}
    # A row names its use area by number; its primary key differs from one run of the tests to the next.
    found["unmet_demand_rows"] = [
        {k: plain(v) for k, v in row.items() if k != "parcel"} for row in c["unmet_demand_rows"]
    ]
    return {
        **found,
        "accounts": [[r["account"].account_number, _row_fields(r)] for r in c["account_summaries"]],
        "zones": [[r["zone"].name, _row_fields(r)] for r in c["zone_summaries"]],
    }


def _accounts_list(client, period):
    response = client.get(reverse("accounting:accounts_list"), {"period": period.pk})
    assert response.status_code == 200
    c = response.context
    return {
        **{key: plain(c[key]) for key in ACCOUNTS_LIST_KEYS},
        "accounts": [[r["account"].account_number, _row_fields(r)] for r in c["account_summaries"]],
    }


def _zone_pages(client):
    pages = {}
    for zone in Zone.objects.order_by("name"):
        response = client.get(reverse("geography:zone_detail", args=[zone.pk]))
        assert response.status_code == 200
        pages[zone.name] = [
            {k: plain(v) for k, v in row.items() if not k.endswith("_caption")}
            for row in response.context["budgets"]
        ]
    return pages


def everything():
    client = Client()
    client.force_login(
        get_user_model().objects.create_user(
            username="figures", email="figures@example.org", password="a-good-passw0rd", agency_admin=True
        )
    )
    found = {"zone_pages": _zone_pages(client)}
    for period in world.periods():
        found[period.name] = {
            "figures": _figures_rows(period),
            "dashboard": _dashboard(client, period),
            "accounts_list": _accounts_list(client, period),
        }
    return found


def first_difference(before, now, path="figures"):
    """The path and the two values of the first place ``before`` and ``now`` differ, or None."""
    if isinstance(before, str) and before.startswith("D:") and isinstance(now, str) and now.startswith("D:"):
        return None if Decimal(before[2:]) == Decimal(now[2:]) else (path, before, now)
    if isinstance(before, dict) and isinstance(now, dict):
        for key in list(before) + [k for k in now if k not in before]:
            if key not in before or key not in now:
                return (f"{path}.{key}", before.get(key, "<absent>"), now.get(key, "<absent>"))
            found = first_difference(before[key], now[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(before, list) and isinstance(now, list):
        for i, (b, n) in enumerate(zip(before, now)):
            found = first_difference(b, n, f"{path}[{i}]")
            if found:
                return found
        if len(before) != len(now):
            return (f"{path} length", len(before), len(now))
        return None
    return None if before == now else (path, before, now)


@pytest.fixture
def figures_now():
    world.build_world()
    return everything()


def test_the_records_hold_every_case_the_reading_must_keep(figures_now):
    """Else the comparison below proves less than it says."""
    wy25 = figures_now["WY 2024-2025"]
    scopes = {(row[0], row[1]) for row in wy25["figures"]}
    assert ("use_area", "V1") not in scopes  # voided
    assert ("use_area", "N1") not in scopes  # no runs, so no Water use card
    assert any(row[3] == "credit" for row in wy25["figures"])
    assert any(row[3] == "carryover" for row in figures_now["WY 2025-2026"]["figures"])
    methods = {row[5] for row in wy25["figures"] if row[0] == "account"}
    assert "" in methods and len(methods) > 1
    lines = wy25["dashboard"]["grand_surface_lines"]
    assert {line["kind"] for line in lines} >= {"metered", "estimated", "unknown"}
    numbers = [number for number, _ in wy25["dashboard"]["accounts"]]
    assert "D3-F" not in numbers and "S-H" not in numbers  # not active
    assert wy25["dashboard"]["unmet_demand_rows"]


def test_every_figure_is_as_it_was_before_the_pages_read_the_year_at_once(figures_now):
    if WRITE:
        FILE.parent.mkdir(exist_ok=True)
        FILE.write_text(json.dumps(figures_now, indent=1, sort_keys=False) + "\n")
        pytest.skip(f"wrote {FILE}")
    before = json.loads(FILE.read_text())
    difference = first_difference(before, json.loads(json.dumps(figures_now)))
    assert difference is None, f"first figure that differs (where, before, now): {difference}"
