# SPDX-License-Identifier: AGPL-3.0-or-later
"""The well page keeps its promise: it shows the measurement history it names.

ISS-145. ``templates/wells/detail.html`` has said *"Well details, linked
meters, and measurement history"* since the page was written, and the view
never queried a single reading. Phase 132 seeded the readings and 133-02
doubled them to two water years; this test is what makes the sentence true.

Every expected figure is a pasted literal worked out by hand from the fixture
below, never ``> 0`` and never a re-derivation of the page's own arithmetic
(DESIGN.md rule 12, review questions 1 and 2). The hand computation:

* Meter reads. Three totalizer reads on one meter, 1,200.00 -> 1,234.50 ->
  1,300.00 -> 1,412.25. The deltas the seed writes into ``calculated_volume``
  are 34.50, 65.50 and 112.25 AF. The first read is 30 September 2025, the last
  day of WY 2024-2025; the other two are October and November 2025, WY
  2025-2026. So the page carries both water-year headings and lists the reads
  newest first.
* Water levels from a logger. Daily readings on a second well's transducer,
  a few days at the end of each of four months. The month's close is its LAST
  non-anomalous reading:
    Aug 2025 close 79.50 (readings 79.00, 79.50)
    Sep 2025 close 80.35 (80.10, 80.20, 80.35), change 80.35 - 79.50 = 0.85
    Oct 2025 close 81.75 (81.00, 81.75), change 1.40
    Nov 2025 close 82.90 (82.00, 82.90, and an anomalous 2.14 logged LATER the
      same day that must not win), change 1.15
  Aug and Sep 2025 fall in WY 2024-2025; Oct and Nov 2025 in WY 2025-2026.
* Water levels from a hand-entered record, on a well with no logger: 86.9398
  on 10 September 2025 and 87.5136 on 10 October 2025 render as 86.94 and
  87.51, and the October change is 87.5136 - 86.9398 = 0.5738 -> 0.57.
"""
from datetime import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from measurements.models import (
    Meter,
    MeterReading,
    Sensor,
    SensorMeasurement,
    WaterMeasurement,
)
from standards.models import ObservedProperty
from tests.factories import WellFactory
from wells.models import WellMeter

pytestmark = pytest.mark.django_db

SECTION_HEADING = "Measurement history"
EMPTY_SENTENCE = "No meter reads or water-level readings recorded for this well."


def _login():
    from core.models import User

    user = User.objects.create(
        username="historian",
        email="historian@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _at(y, m, d, hour=14):
    """A field-visit timestamp in the project's own time zone."""
    return timezone.make_aware(datetime(y, m, d, hour, 0))


def _depth_property():
    return ObservedProperty.objects.get_or_create(
        key="groundwater_level_depth", defaults={"name": "Depth to groundwater"}
    )[0]


def _metered_well():
    well = WellFactory(name="Metered well")
    meter = Meter.objects.create(serial_number="MTR-TEST-1", unit="acre_feet")
    WellMeter.objects.create(well=well, meter=meter, is_current=True)
    reads = [
        (_at(2025, 9, 30), "1200.0000", "1234.5000", "34.5000", "approved"),
        (_at(2025, 10, 31), "1234.5000", "1300.0000", "65.5000", "approved"),
        (_at(2025, 11, 30), "1300.0000", "1412.2500", "112.2500", "estimated"),
    ]
    for when, prev, cur, vol, quality in reads:
        MeterReading.objects.create(
            meter=meter,
            reading_date=when,
            previous_value=Decimal(prev),
            current_value=Decimal(cur),
            calculated_volume=Decimal(vol),
            quality=quality,
        )
    return well


def _logged_well():
    well = WellFactory(name="Logged well")
    prop = _depth_property()
    sensor = Sensor.objects.create(
        name="test transducer", sensor_type="pressure_transducer", well=well,
        exclude_anomalies=True,
    )
    points = [
        (2025, 8, 30, "79.0000"), (2025, 8, 31, "79.5000"),
        (2025, 9, 28, "80.1000"), (2025, 9, 29, "80.2000"), (2025, 9, 30, "80.3500"),
        (2025, 10, 30, "81.0000"), (2025, 10, 31, "81.7500"),
        (2025, 11, 29, "82.0000"), (2025, 11, 30, "82.9000"),
    ]
    for y, m, d, v in points:
        SensorMeasurement.objects.create(
            sensor=sensor, observed_property=prop, measurement_date=_at(y, m, d, 6),
            value=Decimal(v), unit="ft",
        )
    # Logged after the day's real reading, flagged as the instrument out of the
    # water. It is the newest row in November and must not be November's close.
    SensorMeasurement.objects.create(
        sensor=sensor, observed_property=prop, measurement_date=_at(2025, 11, 30, 9),
        value=Decimal("2.1400"), unit="ft", is_anomalous=True,
    )
    return well


def _sounded_well():
    well = WellFactory(name="Sounded well")
    prop = _depth_property()
    for y, m, d, v in [(2025, 9, 10, "86.9398"), (2025, 10, 10, "87.5136")]:
        WaterMeasurement.objects.create(
            name="sounder", measurement_type="groundwater_level", observed_property=prop,
            value=Decimal(v), unit="ft", measurement_date=_at(y, m, d, 10), well=well,
        )
    return well


def _page(well):
    return _login().get(reverse("wells:detail", args=[well.pk])).content.decode()


def test_the_meter_reads_render_with_their_literal_values_and_deltas():
    html = _page(_metered_well())
    assert SECTION_HEADING in html
    for literal in ("1,234.50", "34.50", "1,300.00", "65.50", "1,412.25", "112.25"):
        assert literal in html, literal


def test_the_reads_are_grouped_by_water_year_and_listed_newest_first():
    html = _page(_metered_well())
    assert "WY 2025-2026" in html
    assert "WY 2024-2025" in html
    # Newest read first: November 2025, then October, then the September read
    # that closes the earlier water year.
    assert html.index("1,412.25") < html.index("1,300.00") < html.index("1,234.50")
    assert html.index("WY 2025-2026") < html.index("WY 2024-2025")


def test_a_read_that_was_not_approved_says_so():
    html = _page(_metered_well())
    section = html[html.index(SECTION_HEADING):]
    assert section.count("estimated") == 1


def test_the_monthly_water_level_closes_are_literal_for_two_months_in_each_water_year():
    html = _page(_logged_well())
    section = html[html.index(SECTION_HEADING):]
    # WY 2024-2025: August and September 2025.
    assert "79.50" in section
    assert "80.35" in section
    assert "0.85" in section
    # WY 2025-2026: October and November 2025.
    assert "81.75" in section
    assert "1.40" in section
    assert "82.90" in section
    assert "1.15" in section
    # The anomalous row is not the close, and does not print.
    assert "2.14" not in section
    assert "WY 2025-2026" in section and "WY 2024-2025" in section


def test_a_well_with_only_a_hand_entered_record_still_gets_a_digest():
    html = _page(_sounded_well())
    section = html[html.index(SECTION_HEADING):]
    assert "86.94" in section
    assert "87.51" in section
    assert "0.57" in section
    assert "hand-entered" in section


def test_the_logger_wins_where_a_well_has_both_records():
    well = _logged_well()
    prop = _depth_property()
    WaterMeasurement.objects.create(
        name="sounder", measurement_type="groundwater_level", observed_property=prop,
        value=Decimal("55.5500"), unit="ft", measurement_date=_at(2025, 9, 15, 10), well=well,
    )
    section = _page(well)
    section = section[section.index(SECTION_HEADING):]
    assert "80.35" in section
    assert "55.55" not in section


def test_a_well_with_nothing_recorded_renders_the_empty_sentence_and_no_table():
    html = _page(WellFactory(name="Bare well"))
    section = html[html.index(SECTION_HEADING):]
    section = section[: section.index("</div>")]
    assert EMPTY_SENTENCE in section
    assert "<table" not in section


def test_the_page_description_sentence_is_unchanged():
    """The promise at detail.html:23 is kept by rendering, never by rewording."""
    html = _page(_metered_well())
    assert "Well details, linked meters, and measurement history." in html
