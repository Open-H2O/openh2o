# SPDX-License-Identifier: AGPL-3.0-or-later
import io
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from accounting.models import AllocationCarryover
from parcels.models import ParcelLedger
from accounting.services import (
    BASIN_RECHARGE_POOL,
    _balance_dict,
    account_balance,
    create_diversion_ledger_entry,
    create_diversion_ledger_entries,
    create_recharge_ledger_entries,
    et_mm_to_acre_feet,
    parcel_balance,
    parse_ledger_csv,
    zone_balance,
)
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    ParcelZoneFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    RechargeEventFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    WaterAccountFactory,
    WaterAccountParcelFactory,
    WaterRightFactory,
    WaterRightParcelFactory,
    WaterTypeFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
    ZoneFactory,
)


# ---------------------------------------------------------------------------
# Balance functions
# ---------------------------------------------------------------------------


class TestParcelBalance:
    def test_empty(self):
        parcel = ParcelFactory()
        assert parcel_balance(parcel) == Decimal("0")

    def test_single_entry(self):
        parcel = ParcelFactory()
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("15.5000"))
        assert parcel_balance(parcel) == Decimal("15.5000")

    def test_mixed_entries(self):
        parcel = ParcelFactory()
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("100.0000"))
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("-40.0000"))
        assert parcel_balance(parcel) == Decimal("60.0000")

    def test_filtered_by_period(self):
        parcel = ParcelFactory()
        period_a = ReportingPeriodFactory(
            start_date=date(2023, 10, 1), end_date=date(2024, 9, 30)
        )
        period_b = ReportingPeriodFactory(
            start_date=date(2024, 10, 1), end_date=date(2025, 9, 30)
        )
        ParcelLedgerFactory(
            parcel=parcel,
            amount_acre_feet=Decimal("50.0000"),
            reporting_period=period_a,
        )
        ParcelLedgerFactory(
            parcel=parcel,
            amount_acre_feet=Decimal("30.0000"),
            reporting_period=period_b,
        )
        assert parcel_balance(parcel, reporting_period=period_a) == Decimal("50.0000")


class TestAccountBalance:
    def test_aggregates_parcels(self):
        account = WaterAccountFactory()
        p1 = ParcelFactory()
        p2 = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=p1)
        WaterAccountParcelFactory(water_account=account, parcel=p2)
        ParcelLedgerFactory(parcel=p1, amount_acre_feet=Decimal("20.0000"))
        ParcelLedgerFactory(parcel=p2, amount_acre_feet=Decimal("30.0000"))

        result = account_balance(account)
        assert result["supply"] == Decimal("50.0000")
        assert result["usage"] == Decimal("0")
        assert result["net"] == Decimal("50.0000")

    def test_excludes_removed_parcels(self):
        account = WaterAccountFactory()
        active_parcel = ParcelFactory()
        removed_parcel = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=active_parcel)
        WaterAccountParcelFactory(
            water_account=account,
            parcel=removed_parcel,
            removed_date=date(2024, 6, 1),
        )
        ParcelLedgerFactory(
            parcel=active_parcel, amount_acre_feet=Decimal("20.0000")
        )
        ParcelLedgerFactory(
            parcel=removed_parcel, amount_acre_feet=Decimal("99.0000")
        )

        result = account_balance(account)
        assert result["supply"] == Decimal("20.0000")


class TestZoneBalance:
    def test_aggregates_parcels(self):
        zone = ZoneFactory()
        p1 = ParcelFactory()
        p2 = ParcelFactory()
        ParcelZoneFactory(parcel=p1, zone=zone)
        ParcelZoneFactory(parcel=p2, zone=zone)
        ParcelLedgerFactory(parcel=p1, amount_acre_feet=Decimal("10.0000"))
        ParcelLedgerFactory(parcel=p2, amount_acre_feet=Decimal("-5.0000"))

        result = zone_balance(zone)
        assert result["supply"] == Decimal("10.0000")
        assert result["usage"] == Decimal("5.0000")
        assert result["net"] == Decimal("5.0000")

    def test_empty_zone(self):
        zone = ZoneFactory()
        result = zone_balance(zone)
        assert result["supply"] == Decimal("0")
        assert result["usage"] == Decimal("0")
        assert result["net"] == Decimal("0")

    @pytest.mark.django_db
    def test_gw_recharge_credit_raises_supply_and_lowers_net_depletion(self):
        """ISS-052 regression: a groundwater recharge credit (managed OR
        incidental) reaches the groundwater budget — it raises a zone's supply
        and reduces net depletion by its full magnitude, rather than hiding in a
        separate bucket. Guards the reconciliation that closed Phase 52.5."""
        gw = WaterTypeFactory(code="GW", name="Groundwater")
        zone = ZoneFactory()
        parcel = ParcelFactory(area_acres=Decimal("100"))
        ParcelZoneFactory(parcel=parcel, zone=zone)
        # The parcel pumps 30 AF of groundwater (negative = usage).
        ParcelLedgerFactory(
            parcel=parcel,
            amount_acre_feet=Decimal("-30.0000"),
            source_type="calculated",
        )
        before = zone_balance(zone)

        # Credit 20 AF of GW recharge (positive, water_type GW).
        ParcelLedgerFactory(
            parcel=parcel,
            amount_acre_feet=Decimal("20.0000"),
            source_type="recharge",
            water_type=gw,
        )
        after = zone_balance(zone)

        assert after["supply"] == before["supply"] + Decimal("20.0000")
        # Net depletion is reduced by the recharge (net moves toward zero).
        assert after["net"] == before["net"] + Decimal("20.0000")
        assert after["usage"] == before["usage"]  # recharge is supply, not usage


# ---------------------------------------------------------------------------
# Diversion / recharge ledger integration
# ---------------------------------------------------------------------------


class TestCreateDiversionLedgerEntry:
    def test_explicit_parcel(self):
        """Explicit parcel param creates a single entry (backward compat)."""
        parcel = ParcelFactory()
        record = DiversionRecordFactory(volume_acre_feet=Decimal("25.0000"))
        entries = create_diversion_ledger_entries(record, parcel=parcel)

        assert len(entries) == 1
        assert entries[0].parcel == parcel
        assert entries[0].amount_acre_feet == Decimal("-25.0000")
        assert entries[0].source_type == "surface_diversion"

    def test_single_parcel_backward_compat(self):
        """The old create_diversion_ledger_entry alias still works."""
        parcel = ParcelFactory()
        record = DiversionRecordFactory(volume_acre_feet=Decimal("25.0000"))
        entry = create_diversion_ledger_entry(record, parcel=parcel)
        assert entry.parcel == parcel
        assert entry.amount_acre_feet == Decimal("-25.0000")

    def test_from_fk(self):
        """Falls back to WaterRightParcel when no POD-parcel links exist."""
        wr = WaterRightFactory()
        parcel = ParcelFactory()
        WaterRightParcelFactory(water_right=wr, parcel=parcel)
        pod = PointOfDiversionFactory(water_right=wr)
        record = DiversionRecordFactory(
            point_of_diversion=pod, volume_acre_feet=Decimal("10.0000")
        )

        entries = create_diversion_ledger_entries(record)
        assert len(entries) == 1
        assert entries[0].parcel == parcel
        assert entries[0].amount_acre_feet == Decimal("-10.0000")

    def test_no_parcel_raises(self):
        record = DiversionRecordFactory()
        with pytest.raises(ValueError, match="No parcel supplied"):
            create_diversion_ledger_entries(record)

    def test_multi_parcel_pod(self):
        """POD linked to 3 parcels with fractions 0.5, 0.3, 0.2."""
        wr = WaterRightFactory()
        pod = PointOfDiversionFactory(water_right=wr)
        p1 = ParcelFactory()
        p2 = ParcelFactory()
        p3 = ParcelFactory()
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p1, fraction=Decimal("0.5000")
        )
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p2, fraction=Decimal("0.3000")
        )
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p3, fraction=Decimal("0.2000")
        )
        record = DiversionRecordFactory(
            point_of_diversion=pod, volume_acre_feet=Decimal("100.0000")
        )

        entries = create_diversion_ledger_entries(record)
        assert len(entries) == 3
        amounts = sorted(abs(e.amount_acre_feet) for e in entries)
        assert amounts == [Decimal("20.0000"), Decimal("30.0000"), Decimal("50.0000")]
        assert all(e.amount_acre_feet < 0 for e in entries)

    def test_multi_parcel_residual(self):
        """Entries sum exactly to diversion volume (no rounding loss)."""
        wr = WaterRightFactory()
        pod = PointOfDiversionFactory(water_right=wr)
        p1 = ParcelFactory()
        p2 = ParcelFactory()
        p3 = ParcelFactory()
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p1, fraction=Decimal("0.3333")
        )
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p2, fraction=Decimal("0.3333")
        )
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=p3, fraction=Decimal("0.3334")
        )
        record = DiversionRecordFactory(
            point_of_diversion=pod, volume_acre_feet=Decimal("100.0000")
        )

        entries = create_diversion_ledger_entries(record)
        total = sum(abs(e.amount_acre_feet) for e in entries)
        assert total == Decimal("100.0000")


class TestCreateRechargeLedgerEntries:
    """52.6-02 (ISS-053): managed recharge pools at the GSA level instead of being
    smeared area-weighted across every parcel (which invented recoverable credits
    on surface-only, no-well parcels). The area-weighted distribution is gone."""

    def _pool_total(self, zone):
        return sum(
            (
                r.amount_af
                for r in AllocationCarryover.objects.filter(
                    zone=zone, origin=BASIN_RECHARGE_POOL
                )
            ),
            Decimal("0"),
        )

    def test_pools_full_volume_to_basin_pool_not_per_parcel(self):
        """The whole event volume lands in ONE basin-pool row; the parcels in the
        zone get NO recharge ledger rows."""
        zone = ZoneFactory(zone_type="management_area")
        p1 = ParcelFactory(area_acres=Decimal("100.00"))
        p2 = ParcelFactory(area_acres=Decimal("300.00"))
        ParcelZoneFactory(parcel=p1, zone=zone)
        ParcelZoneFactory(parcel=p2, zone=zone)

        event = RechargeEventFactory(volume_acre_feet=Decimal("100.0000"))
        entries = create_recharge_ledger_entries(event, zone=zone)

        assert entries == []  # no per-parcel smear
        assert self._pool_total(zone) == Decimal("100.0000")
        assert ParcelLedger.objects.filter(source_type="recharge").count() == 0

    def test_multiple_events_accumulate_in_one_pool_row(self):
        """Two events to the same zone/year sum into a single basin-pool row."""
        zone = ZoneFactory(zone_type="management_area")
        ParcelZoneFactory(parcel=ParcelFactory(), zone=zone)

        create_recharge_ledger_entries(
            RechargeEventFactory(volume_acre_feet=Decimal("60.0000")), zone=zone
        )
        create_recharge_ledger_entries(
            RechargeEventFactory(volume_acre_feet=Decimal("40.0000")), zone=zone
        )

        rows = AllocationCarryover.objects.filter(
            zone=zone, origin=BASIN_RECHARGE_POOL
        )
        assert rows.count() == 1
        assert rows.first().amount_af == Decimal("100.0000")

    def test_personal_path_for_a_has_well_parcel(self):
        """When tied to a conjunctive (has-well) parcel, the event writes ONE
        personal recharge row and pools nothing."""
        zone = ZoneFactory(zone_type="management_area")
        parcel = ParcelFactory(area_acres=Decimal("40.00"))
        ParcelZoneFactory(parcel=parcel, zone=zone)
        WellIrrigatedParcelFactory(parcel=parcel)  # has well -> CONJUNCTIVE

        event = RechargeEventFactory(volume_acre_feet=Decimal("80.0000"))
        entries = create_recharge_ledger_entries(event, zone=zone, parcel=parcel)

        assert len(entries) == 1
        assert entries[0].amount_acre_feet == Decimal("80.0000")
        assert entries[0].source_type == "recharge"
        assert self._pool_total(zone) == Decimal("0")

    def test_no_well_parcel_arg_still_pools(self):
        """A no-well parcel passed explicitly does NOT get a personal credit — it
        has no well to recover it, so the volume still pools (the ISS-053 guard)."""
        zone = ZoneFactory(zone_type="management_area")
        parcel = ParcelFactory()  # no well
        ParcelZoneFactory(parcel=parcel, zone=zone)

        event = RechargeEventFactory(volume_acre_feet=Decimal("50.0000"))
        entries = create_recharge_ledger_entries(event, zone=zone, parcel=parcel)

        assert entries == []
        assert self._pool_total(zone) == Decimal("50.0000")
        assert not ParcelLedger.objects.filter(
            parcel=parcel, source_type="recharge"
        ).exists()

    def test_from_fk_pools_to_site_zone(self):
        """No zone arg falls back to the site's zone, and pools there."""
        zone = ZoneFactory(zone_type="management_area")
        site = RechargeSiteFactory(zone=zone)
        event = RechargeEventFactory(
            recharge_site=site, volume_acre_feet=Decimal("80.0000")
        )

        entries = create_recharge_ledger_entries(event)
        assert entries == []
        assert self._pool_total(zone) == Decimal("80.0000")

    def test_no_zone_raises(self):
        site = RechargeSiteFactory(zone=None)
        event = RechargeEventFactory(recharge_site=site)
        with pytest.raises(ValueError, match="No zone supplied"):
            create_recharge_ledger_entries(event)

    def test_empty_zone(self):
        zone = ZoneFactory()
        event = RechargeEventFactory(volume_acre_feet=Decimal("50.0000"))
        entries = create_recharge_ledger_entries(event, zone=zone)
        assert entries == []


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


class TestSurfaceWaterCountsAsSupply:
    """surface_diversion is stored NEGATIVE (production convention — the calc
    engine and CSV importer expect it), but it is a SUPPLY to the parcel: a
    delivery that offsets groundwater need, NOT consumption. The balance summary
    must count its magnitude as supply, never as usage."""

    @pytest.mark.django_db
    def test_negative_surface_diversion_is_supply_not_usage(self):
        account = WaterAccountFactory()
        parcel = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
        ParcelLedgerFactory(
            parcel=parcel, amount_acre_feet=Decimal("-12.0000"),
            source_type="surface_diversion")
        result = account_balance(account)
        assert result["supply"] == Decimal("12.0000")
        assert result["usage"] == Decimal("0")
        assert result["net"] == Decimal("12.0000")

    @pytest.mark.django_db
    def test_surface_supply_alongside_groundwater_usage(self):
        account = WaterAccountFactory()
        parcel = ParcelFactory()
        WaterAccountParcelFactory(water_account=account, parcel=parcel)
        ParcelLedgerFactory(
            parcel=parcel, amount_acre_feet=Decimal("100.0000"),
            source_type="allocation")              # budget → supply
        ParcelLedgerFactory(
            parcel=parcel, amount_acre_feet=Decimal("-30.0000"),
            source_type="surface_diversion")       # delivery → supply
        ParcelLedgerFactory(
            parcel=parcel, amount_acre_feet=Decimal("-20.0000"),
            source_type="meter_reading")           # pumping → usage
        result = account_balance(account)
        assert result["supply"] == Decimal("130.0000")  # allocation + |surface|
        assert result["usage"] == Decimal("20.0000")    # groundwater only
        assert result["net"] == Decimal("110.0000")


class TestParseLedgerCsv:
    def _csv_file(self, text):
        return io.BytesIO(text.encode("utf-8"))

    def test_valid(self):
        parcel = ParcelFactory(parcel_number="P-001")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-001,2024-01-15,10.5,manual_entry\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["created_count"] == 1
        assert result["error_count"] == 0

    def test_dry_run(self):
        parcel = ParcelFactory(parcel_number="P-002")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-002,2024-01-15,10.5,manual_entry\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text), dry_run=True)
        assert result["created_count"] == 1
        assert result["error_count"] == 0
        from parcels.models import ParcelLedger

        assert ParcelLedger.objects.filter(parcel=parcel).count() == 0

    def test_missing_columns(self):
        csv_text = "parcel_number,amount_acre_feet\nP-001,10\n"
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["error_count"] == 1
        assert "Missing required columns" in result["errors"][0]["messages"][0]

    def test_invalid_parcel(self):
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "NONEXISTENT,2024-01-15,10.5,manual_entry\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["error_count"] == 1
        assert "parcel not found" in result["errors"][0]["messages"][0]

    def test_invalid_amount(self):
        ParcelFactory(parcel_number="P-003")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-003,2024-01-15,NOT_A_NUMBER,manual_entry\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["error_count"] == 1
        assert "invalid amount" in result["errors"][0]["messages"][0]

    def test_csv_positive_meter_reading_rejected(self):
        """Positive amount for a usage source_type (meter_reading) is rejected."""
        ParcelFactory(parcel_number="P-SIGN-1")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-SIGN-1,2024-01-15,10.0,meter_reading\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["error_count"] == 1
        assert "positive amount" in result["errors"][0]["messages"][0]
        assert "usage" in result["errors"][0]["messages"][0]

    def test_csv_negative_meter_reading_accepted(self):
        """Negative amount for meter_reading is accepted."""
        ParcelFactory(parcel_number="P-SIGN-2")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-SIGN-2,2024-01-15,-10.0,meter_reading\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["created_count"] == 1
        assert result["error_count"] == 0

    def test_csv_negative_surface_diversion_accepted(self):
        """Exported demo surface deliveries (stored negative) re-import cleanly —
        this is the CSV round-trip the demo's old positive sign broke."""
        ParcelFactory(parcel_number="P-SURF-1")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-SURF-1,2025-05-15,-2.5,surface_diversion\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["created_count"] == 1
        assert result["error_count"] == 0

    def test_csv_positive_surface_diversion_rejected(self):
        """A positive surface_diversion violates the stored-negative convention."""
        ParcelFactory(parcel_number="P-SURF-2")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-SURF-2,2025-05-15,2.5,surface_diversion\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["error_count"] == 1
        assert "positive amount" in result["errors"][0]["messages"][0]

    def test_csv_positive_recharge_accepted(self):
        """Positive amount for a supply source_type (recharge) is accepted."""
        ParcelFactory(parcel_number="P-SIGN-3")
        csv_text = (
            "parcel_number,effective_date,amount_acre_feet,source_type\n"
            "P-SIGN-3,2024-01-15,10.0,recharge\n"
        )
        result = parse_ledger_csv(self._csv_file(csv_text))
        assert result["created_count"] == 1
        assert result["error_count"] == 0


# ---------------------------------------------------------------------------
# PostGIS auto-calc of area_acres
# ---------------------------------------------------------------------------


class TestParcelAreaAutoCalc:
    def test_auto_computes_area_from_geometry(self):
        """Parcel with geometry but no area_acres gets area auto-computed on save."""
        from parcels.models import Parcel

        parcel = ParcelFactory(area_acres=None)
        # Refresh from DB to get the value set by the signal via queryset.update()
        parcel.refresh_from_db()
        assert parcel.area_acres is not None
        # Default factory box is ~0.01 deg at lat 36.5 => ~244 acres
        # Allow 1% tolerance for PostGIS geodetic calculation differences
        assert Decimal("241") < parcel.area_acres < Decimal("248")

    def test_preserves_manual_area(self):
        """Parcel with explicit area_acres is NOT overwritten by signal."""
        parcel = ParcelFactory(area_acres=Decimal("500.00"))
        parcel.refresh_from_db()
        assert parcel.area_acres == Decimal("500.00")


# ---------------------------------------------------------------------------
# _balance_dict edge cases
# ---------------------------------------------------------------------------


class TestBalanceDict:
    def test_empty_queryset(self):
        """Empty queryset returns all zeros."""
        from parcels.models import ParcelLedger

        qs = ParcelLedger.objects.none()
        result = _balance_dict(qs)
        assert result["supply"] == Decimal("0")
        assert result["usage"] == Decimal("0")
        assert result["net"] == Decimal("0")
        assert result["total"] == Decimal("0")

    def test_all_positive(self):
        """All-positive entries: usage is 0, supply is the sum."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("10.0000"))
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("20.0000"))

        from parcels.models import ParcelLedger

        qs = ParcelLedger.objects.filter(parcel=parcel)
        result = _balance_dict(qs)
        assert result["supply"] == Decimal("30.0000")
        assert result["usage"] == Decimal("0")
        assert result["net"] == Decimal("30.0000")

    def test_all_negative(self):
        """All-negative entries: supply is 0, usage is the absolute sum."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("-15.0000"))
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("-25.0000"))

        from parcels.models import ParcelLedger

        qs = ParcelLedger.objects.filter(parcel=parcel)
        result = _balance_dict(qs)
        assert result["supply"] == Decimal("0")
        assert result["usage"] == Decimal("40.0000")
        assert result["net"] == Decimal("-40.0000")

    def test_zero_entries_excluded(self):
        """Zero-amount entries are excluded from both supply and usage."""
        parcel = ParcelFactory()
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("0.0000"))
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("50.0000"))
        ParcelLedgerFactory(parcel=parcel, amount_acre_feet=Decimal("-20.0000"))

        from parcels.models import ParcelLedger

        qs = ParcelLedger.objects.filter(parcel=parcel)
        result = _balance_dict(qs)
        assert result["supply"] == Decimal("50.0000")
        assert result["usage"] == Decimal("20.0000")
        assert result["net"] == Decimal("30.0000")


# ---------------------------------------------------------------------------
# GEARS by-well fraction normalization (Task 1)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGearsWellFractionNormalization:
    def test_gears_well_fraction_normalization(self):
        """A well irrigating 3 parcels (all fraction=1.0) reports 1x extraction, not 3x."""
        from reporting.generators import generate_gears_csv

        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )
        well = WellFactory()
        p1 = ParcelFactory()
        p2 = ParcelFactory()
        p3 = ParcelFactory()

        # Each parcel linked to the same well with default fraction=1.0
        WellIrrigatedParcelFactory(well=well, parcel=p1, fraction=Decimal("1.0000"))
        WellIrrigatedParcelFactory(well=well, parcel=p2, fraction=Decimal("1.0000"))
        WellIrrigatedParcelFactory(well=well, parcel=p3, fraction=Decimal("1.0000"))

        # One ledger entry of -30 AF on parcel p1
        ParcelLedgerFactory(
            parcel=p1,
            source_type="meter_reading",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-30.0000"),
        )

        output = generate_gears_csv(period, method="by_well")
        content = output.read()
        lines = [l for l in content.strip().split("\n") if well.name in l or (well.well_registration_id or "") in l]

        # Parse all volume values from matching rows
        # CSV: reg_id, name, lat, lon, month, volume, method
        total_reported = Decimal("0")
        reader = __import__("csv").reader(content.splitlines())
        next(reader)  # skip header
        for row in reader:
            if len(row) >= 7:
                try:
                    total_reported += Decimal(row[5])
                except Exception:
                    pass

        # With 3 parcels each fraction=1.0, normalized fraction = 1/3 each.
        # Total reported = 30 * (1/3) = 10 AF (1 ledger entry on p1 only).
        # Without normalization it would be 30 * 1.0 = 30 AF — the triple-count bug.
        assert total_reported == Decimal("30") * (Decimal("1") / Decimal("3"))

    def test_gears_well_single_parcel_fraction_unchanged(self):
        """A well irrigating 1 parcel (fraction=1.0) reports the full extraction volume."""
        from reporting.generators import generate_gears_csv

        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )
        well = WellFactory()
        parcel = ParcelFactory()
        WellIrrigatedParcelFactory(well=well, parcel=parcel, fraction=Decimal("1.0000"))

        ParcelLedgerFactory(
            parcel=parcel,
            source_type="meter_reading",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-50.0000"),
        )

        output = generate_gears_csv(period, method="by_well")
        content = output.read()

        total_reported = Decimal("0")
        reader = __import__("csv").reader(content.splitlines())
        next(reader)  # skip header
        for row in reader:
            if len(row) >= 7:
                try:
                    total_reported += Decimal(row[5])
                except Exception:
                    pass

        # Single parcel: normalized fraction = 1.0/1.0 = 1.0 → full 50 AF reported
        assert total_reported == Decimal("50")


# ---------------------------------------------------------------------------
# CalWATRS null water_right guards (Task 2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNullWaterRightGuards:
    def test_calwatrs_null_water_right(self):
        """CalWATRS CSV generates without crashing when a POD has no water right,
        and (ISS-031b) WITHHOLDS the blank Water Right ID row — a blank key is
        rejected/orphaned by the portal. The volume is surfaced as a
        validate_report warning instead (see tests/test_state_exports.py)."""
        from reporting.generators import generate_calwatrs_csv

        period = ReportingPeriodFactory(
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        )
        # POD with no water_right
        pod = PointOfDiversionFactory(water_right=None)
        DiversionRecordFactory(
            point_of_diversion=pod,
            reporting_period=period,
            month=date(2024, 3, 1),
            volume_acre_feet=Decimal("25.0000"),
            diversion_type="direct_use",
        )

        # Must not raise, and must emit header only — no blank-key data row.
        output = generate_calwatrs_csv(period, template_type="a1")
        content = output.read()
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 1  # header only; the blank-key row is withheld


# ---------------------------------------------------------------------------
# OpenET-to-ledger pipeline (Task 4)
# ---------------------------------------------------------------------------


class TestEtMmToAcreFeet:
    def test_100mm_10acres(self):
        """100mm over 10 acres = -(100/304.8)*10 = -3.2808... AF."""
        result = et_mm_to_acre_feet(100, Decimal("10"))
        # 100 / 304.8 * 10 = 3.28083...
        assert result < 0  # must be negative (consumption)
        assert abs(result - Decimal("-3.2808")) < Decimal("0.001")

    def test_zero_et(self):
        """0mm ET over any area = 0 AF."""
        result = et_mm_to_acre_feet(0, Decimal("80"))
        assert result == Decimal("0")

    def test_proportional_to_area(self):
        """ET in AF scales linearly with area."""
        result_10 = et_mm_to_acre_feet(100, Decimal("10"))
        result_20 = et_mm_to_acre_feet(100, Decimal("20"))
        assert abs(result_20 / result_10 - Decimal("2")) < Decimal("0.0001")


@pytest.mark.django_db
class TestSyncOpenETToLedger:
    def _make_cache(self, parcel, et_mm, month_str="2024-06"):
        """Create an OpenETCache entry for a parcel with the given ET value."""
        from django.contrib.gis.geos import MultiPolygon, Polygon
        from datetime import date
        from datasync.models import OpenETCache

        geom = parcel.geometry or MultiPolygon(
            Polygon.from_bbox((-119.3, 36.3, -119.2, 36.4)), srid=4326
        )
        return OpenETCache.objects.create(
            parcel=parcel,
            geometry=geom,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            variable="ET",
            model_name="Ensemble",
            et_data=[{"date": month_str, "et": et_mm, "unit": "mm"}],
        )

    def test_sync_openet_creates_ledger_entries(self):
        """Running the command creates ParcelLedger entries from OpenETCache data."""
        from django.core.management import call_command

        parcel = ParcelFactory(area_acres=Decimal("80.00"))
        self._make_cache(parcel, et_mm=150.0, month_str="2024-06")

        call_command(
            "sync_openet_to_ledger",
            "--start-date=2024-01-01",
            "--end-date=2024-12-31",
        )

        from parcels.models import ParcelLedger
        entries = ParcelLedger.objects.filter(parcel=parcel, source_type="et_estimate")
        assert entries.count() == 1
        entry = entries.first()
        assert entry.amount_acre_feet < 0  # consumption is negative
        # 150mm * 80 acres / 304.8 = 39.37... AF
        expected = -(Decimal("150") / Decimal("304.8")) * Decimal("80")
        assert abs(entry.amount_acre_feet - expected.quantize(Decimal("0.0001"))) < Decimal("0.001")

    def test_sync_openet_skips_duplicates(self):
        """Running the command twice does not create duplicate ledger entries."""
        from django.core.management import call_command

        parcel = ParcelFactory(area_acres=Decimal("80.00"))
        self._make_cache(parcel, et_mm=100.0, month_str="2024-06")

        call_command(
            "sync_openet_to_ledger",
            "--start-date=2024-01-01",
            "--end-date=2024-12-31",
        )
        call_command(
            "sync_openet_to_ledger",
            "--start-date=2024-01-01",
            "--end-date=2024-12-31",
        )

        from parcels.models import ParcelLedger
        count = ParcelLedger.objects.filter(parcel=parcel, source_type="et_estimate").count()
        assert count == 1  # second run skipped the duplicate

    def test_sync_openet_skips_parcel_without_area(self):
        """Parcels with no area_acres are skipped with no ledger entry created."""
        from django.core.management import call_command

        parcel = ParcelFactory(area_acres=None, geometry=None)
        self._make_cache(parcel, et_mm=100.0, month_str="2024-06")

        call_command(
            "sync_openet_to_ledger",
            "--start-date=2024-01-01",
            "--end-date=2024-12-31",
        )

        from parcels.models import ParcelLedger
        count = ParcelLedger.objects.filter(parcel=parcel, source_type="et_estimate").count()
        assert count == 0

    def test_sync_openet_dry_run_creates_nothing(self):
        """Dry run reports expected conversions but writes nothing to the database."""
        from django.core.management import call_command

        parcel = ParcelFactory(area_acres=Decimal("40.00"))
        self._make_cache(parcel, et_mm=200.0, month_str="2024-06")

        call_command(
            "sync_openet_to_ledger",
            "--start-date=2024-01-01",
            "--end-date=2024-12-31",
            "--dry-run",
        )

        from parcels.models import ParcelLedger
        count = ParcelLedger.objects.filter(parcel=parcel, source_type="et_estimate").count()
        assert count == 0  # nothing written in dry run
