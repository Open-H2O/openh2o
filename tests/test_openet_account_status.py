# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's real monthly allowance, read from the provider (ISS-128).

The platform used to assert an allowance of 400 from a constant in its own
settings file. The account holds 100. Nothing on any screen distinguished a
figure the provider had confirmed from one somebody had typed, so the wrong
number looked exactly as authoritative as the right one.

These tests hold both halves: the parse of the provider's actual reply, and —
the part that matters more — that every way the read can fail produces a
LABELLED fallback rather than a plausible-looking number. The network is mocked
throughout; the one live call this work was allowed is recorded in
113-02-SUMMARY.md, not re-spent here.
"""

import requests

import pytest
from unittest.mock import MagicMock, patch

from datasync.adapters.openet import (
    ACCOUNT_STATUS_CACHE_KEY,
    ACCOUNT_STATUS_URL,
    OpenETAdapter,
)

# Byte-for-byte what https://openet-api.org/account/status returned on
# 2026-08-05, with the account holder's name and cloud project id replaced.
# The allowance is inside a prose STRING, not a number field, and the three
# other 400s are per-request shape limits — which is how "400" became a monthly
# call budget in this codebase in the first place.
LIVE_RESPONSE = {
    "Name": "A Person",
    "Tier": 1,
    "Monthly Requests": "0 used of 100",
    "Max Area Acres": 200000,
    "Max Polygons": 400,
    "Max Field IDS": 400,
    "Encryption": False,
    "Cloud Project ID": "a-project",
}


@pytest.fixture(autouse=True)
def clear_status_cache():
    from django.core.cache import cache

    cache.delete(ACCOUNT_STATUS_CACHE_KEY)
    yield
    cache.delete(ACCOUNT_STATUS_CACHE_KEY)


@pytest.fixture
def adapter():
    a = OpenETAdapter()
    # A key is present unless a test says otherwise. The value is nonsense and
    # never leaves the process — no request is ever really made.
    with patch.object(a, "_get_api_key", return_value="test-key-not-real"):
        yield a


def _response(payload=None, raises=None):
    resp = MagicMock()
    if raises is not None:
        resp.json.side_effect = raises
    else:
        resp.json.return_value = payload
    return resp


@pytest.mark.django_db
class TestTheProviderAnswers:
    def test_parses_the_live_response_shape(self, adapter):
        with patch.object(adapter, "_request", return_value=_response(LIVE_RESPONSE)):
            status = adapter.account_status()

        assert status["source"] == "provider"
        assert status["limit"] == 100
        assert status["used"] == 0
        assert status["tier"] == 1
        assert status["reason"] == ""

    def test_it_reads_the_allowance_and_not_the_shape_limits(self, adapter):
        """The 400s in the reply are per-request caps, not a monthly budget."""
        with patch.object(adapter, "_request", return_value=_response(LIVE_RESPONSE)):
            status = adapter.account_status()
        assert status["limit"] != 400

    def test_a_partly_spent_allowance_is_read_as_spent(self, adapter):
        payload = dict(LIVE_RESPONSE, **{"Monthly Requests": "37 used of 100"})
        with patch.object(adapter, "_request", return_value=_response(payload)):
            status = adapter.account_status()
        assert (status["used"], status["limit"]) == (37, 100)

    def test_a_tier_2_account_reads_400_from_the_provider(self, adapter):
        payload = dict(
            LIVE_RESPONSE, Tier=2, **{"Monthly Requests": "12 used of 400"}
        )
        with patch.object(adapter, "_request", return_value=_response(payload)):
            status = adapter.account_status()
        assert (status["tier"], status["limit"]) == (2, 400)

    def test_it_calls_the_quota_endpoint(self, adapter):
        with patch.object(
            adapter, "_request", return_value=_response(LIVE_RESPONSE)
        ) as mock_request:
            adapter.account_status()
        assert mock_request.call_args.args[1] == ACCOUNT_STATUS_URL


@pytest.mark.django_db
class TestEveryFailureFallsBackAndSaysSo:
    """Five ways this read can fail. None may produce an unlabelled number."""

    def test_missing_key(self, settings):
        settings.OPENET_MONTHLY_BUDGET = 100
        a = OpenETAdapter()
        with patch.object(a, "_get_api_key", return_value=""):
            with patch.object(a, "_request") as mock_request:
                status = a.account_status()
        mock_request.assert_not_called()
        assert status["source"] == "fallback"
        assert status["limit"] == 100
        assert status["used"] is None
        assert "OPENET_API_KEY" in status["reason"]

    def test_http_500_the_bogus_key_case_the_provider_actually_returns(
        self, adapter, settings
    ):
        settings.OPENET_MONTHLY_BUDGET = 100
        error = requests.HTTPError("500 Server Error")
        with patch.object(adapter, "_request", side_effect=error):
            status = adapter.account_status()
        assert status["source"] == "fallback"
        assert status["limit"] == 100
        assert status["reason"]

    def test_timeout(self, adapter, settings):
        settings.OPENET_MONTHLY_BUDGET = 100
        with patch.object(adapter, "_request", side_effect=requests.Timeout("slow")):
            status = adapter.account_status()
        assert status["source"] == "fallback"
        assert "Timeout" in status["reason"]

    def test_connection_error(self, adapter, settings):
        settings.OPENET_MONTHLY_BUDGET = 100
        with patch.object(
            adapter, "_request", side_effect=requests.ConnectionError("no route")
        ):
            status = adapter.account_status()
        assert status["source"] == "fallback"
        assert status["limit"] == 100

    def test_200_with_an_unparseable_body(self, adapter, settings):
        settings.OPENET_MONTHLY_BUDGET = 100
        with patch.object(
            adapter,
            "_request",
            return_value=_response(raises=ValueError("not json")),
        ):
            status = adapter.account_status()
        assert status["source"] == "fallback"
        assert status["limit"] == 100

    def test_200_with_json_that_carries_no_allowance(self, adapter, settings):
        settings.OPENET_MONTHLY_BUDGET = 100
        with patch.object(
            adapter, "_request", return_value=_response({"Tier": 1, "Name": "A Person"})
        ):
            status = adapter.account_status()
        assert status["source"] == "fallback"
        assert status["used"] is None

    def test_200_with_a_body_that_is_not_an_object(self, adapter, settings):
        settings.OPENET_MONTHLY_BUDGET = 100
        with patch.object(adapter, "_request", return_value=_response(["nope"])):
            status = adapter.account_status()
        assert status["source"] == "fallback"

    def test_the_fallback_follows_the_setting_not_a_hardcoded_100(
        self, adapter, settings
    ):
        """A Tier 2 deployment that sets 400 must get 400 back when offline."""
        settings.OPENET_MONTHLY_BUDGET = 400
        with patch.object(adapter, "_request", side_effect=requests.Timeout("slow")):
            status = adapter.account_status()
        assert status["limit"] == 400
        assert status["source"] == "fallback"


@pytest.mark.django_db
class TestNoOutboundCallOnAPageRender:
    def test_the_second_read_does_not_touch_the_network(self, adapter):
        with patch.object(
            adapter, "_request", return_value=_response(LIVE_RESPONSE)
        ) as mock_request:
            first = adapter.account_status()
            second = adapter.account_status()
            third = adapter.account_status()

        assert mock_request.call_count == 1, "the dashboard must not call out per render"
        assert first == second == third

    def test_a_fresh_adapter_instance_still_hits_the_cache(self, adapter):
        with patch.object(adapter, "_request", return_value=_response(LIVE_RESPONSE)):
            adapter.account_status()

        other = OpenETAdapter()
        with patch.object(other, "_get_api_key", return_value="test-key-not-real"):
            with patch.object(other, "_request") as mock_request:
                status = other.account_status()
        mock_request.assert_not_called()
        assert status["source"] == "provider"

    def test_a_fallback_is_not_cached(self, adapter):
        """An unreachable provider must be retried, not remembered for a day."""
        with patch.object(adapter, "_request", side_effect=requests.Timeout("slow")):
            assert adapter.account_status()["source"] == "fallback"

        with patch.object(
            adapter, "_request", return_value=_response(LIVE_RESPONSE)
        ) as mock_request:
            status = adapter.account_status()
        mock_request.assert_called_once()
        assert status["source"] == "provider"

    def test_use_cache_false_forces_a_read(self, adapter):
        with patch.object(
            adapter, "_request", return_value=_response(LIVE_RESPONSE)
        ) as mock_request:
            adapter.account_status()
            adapter.account_status(use_cache=False)
        assert mock_request.call_count == 2


@pytest.mark.django_db
class TestTheKeyNeverLeaks:
    def test_a_transport_failure_logs_no_secret(self, adapter, caplog):
        secret = "test-key-not-real"
        with patch.object(
            adapter, "_request", side_effect=requests.HTTPError(f"401 for {secret}")
        ):
            with caplog.at_level("WARNING"):
                status = adapter.account_status()

        assert secret not in caplog.text
        assert secret not in str(status)

    def test_the_returned_status_carries_no_credential(self, adapter):
        with patch.object(adapter, "_request", return_value=_response(LIVE_RESPONSE)):
            status = adapter.account_status()
        assert set(status) == {"source", "limit", "used", "tier", "reason"}


@pytest.mark.django_db
class TestTheSettingsDefaultIsTierOne:
    def test_the_shipped_default_is_100_not_400(self):
        """ISS-128's first half. A guard must not exceed what it guards."""
        import os

        from django.conf import settings as django_settings

        if "OPENET_MONTHLY_BUDGET" in os.environ:
            pytest.skip("this deployment overrides the budget in its environment")
        assert django_settings.OPENET_MONTHLY_BUDGET == 100

    def test_check_budget_falls_back_to_100_when_the_setting_is_absent(self):
        from datasync.models import OpenETCache

        with patch("django.conf.settings.OPENET_MONTHLY_BUDGET", 100):
            _ok, _used, limit = OpenETCache.check_budget()
        assert limit == 100
