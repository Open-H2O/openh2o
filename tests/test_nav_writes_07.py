# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sidebar hides a write flow from a viewer by a flag on the entry.

A sidebar entry that opens a write flow (the setup wizard, adding a water
system, adding infrastructure) is hidden from a read-only account. Which
entries those are is a fact about the entry, so it lives on ``NavEntry`` and
the template reads it once. When it lived in the template as one URL-name
comparison per entry, a new write flow needed a new string in a file its
author had no reason to open, and the entry that arrived third did exactly that.
"""
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.modules import MODULE_REGISTRY, NavEntry, sidebar_entries

ROOT = Path(__file__).resolve().parent.parent
SIDEBAR = ROOT / "templates/partials/_sidebar.html"

WRITE_FLOWS = {"setup:wizard", "drinking:onboard", "infrastructure:add"}

User = get_user_model()


def _every_entry():
    return sidebar_entries(tuple(MODULE_REGISTRY.values()))


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        **flags,
    )


def _sidebar_hrefs(user):
    client = Client()
    client.force_login(user)
    client.cookies["nav_mode"] = "admin"
    html = client.get(reverse("about")).content.decode()
    return {name: reverse(name) for name in WRITE_FLOWS}, html


class TestTheRegistryNamesTheWriteFlows:
    def test_nav_entry_has_a_writes_field_that_defaults_to_false(self):
        assert NavEntry.__dataclass_fields__["writes"].default is False

    def test_exactly_the_three_write_flows_carry_the_flag(self):
        flagged = {e.url_name for e in _every_entry() if getattr(e, "writes", False)}
        assert flagged == WRITE_FLOWS


class TestTheSidebarReadsTheFlag:
    def test_the_template_compares_no_url_name(self):
        source = SIDEBAR.read_text()
        assert "url_name ==" not in source
        assert "entry.writes" in source

    @pytest.mark.django_db
    def test_a_viewer_does_not_see_the_write_flows(self, settings):
        settings.ACCESS_CONTROL_ENFORCED = True
        hrefs, html = _sidebar_hrefs(_user("nav-viewer", read_only=True, is_staff=True))
        for name, href in hrefs.items():
            assert f'href="{href}"' not in html, name

    @pytest.mark.django_db
    def test_an_operator_sees_the_write_flows(self, settings):
        settings.ACCESS_CONTROL_ENFORCED = True
        hrefs, html = _sidebar_hrefs(_user("nav-operator", is_staff=True))
        for name, href in hrefs.items():
            assert f'href="{href}"' in html, name
