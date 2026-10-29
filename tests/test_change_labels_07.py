# SPDX-License-Identifier: AGPL-3.0-or-later
"""Change history prints each field by a label a reader recognises.

A field with no ``verbose_name`` prints the name Django makes from its column
("Gross et af"). A tracked field either carries a written ``verbose_name`` or is
on the list below of labels that already read as plain words; a new tracked
field is neither until someone puts it on one or the other.
"""

import re
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from core.changes import changes_for, field_name

from accounting.models import CalculationRun

from .factories import ParcelFactory

pytestmark = pytest.mark.django_db

ABBREVIATIONS = re.compile(
    r"\b(af|ft|gpm|id|pk|srid|dwr|usgs|wcr|wqx|oauth|cimis|cdec|url|mg|ug|pct"
    r"|cfs|gsa|apn|pwsid|et|epa|nwis|json|csv|sgma|gears|ms|mm)\b"
)

# The pages write a unit in brackets in lower case where the unit is lower case
# there ("Depth (ft)"), so a bracketed unit is not read as a raw abbreviation.
UNITS_IN_BRACKETS = re.compile(r"\([^)]*\)")

# Tracked fields with no written verbose_name whose Django-made label reads as
# plain words. Keyed "app.Model.field".
PLAIN_WORDS = frozenset(
    {
        "accounting.AccountCredit.water_account",
        "accounting.AccountCredit.water_type",
        "accounting.AccountCredit.water_year",
        "accounting.AccountCredit.origin",
        "accounting.AccountCredit.source_key",
        "accounting.AccountCredit.description",
        "accounting.AccountCredit.created_at",
        "accounting.AllocationCarryover.zone",
        "accounting.AllocationCarryover.water_type",
        "accounting.AllocationCarryover.water_year",
        "accounting.AllocationCarryover.source_water_year",
        "accounting.AllocationCarryover.depreciation_rate",
        "accounting.AllocationCarryover.expires_period",
        "accounting.AllocationCarryover.origin",
        "accounting.AllocationCarryover.created_at",
        "accounting.AllocationPlan.name",
        "accounting.AllocationPlan.zone",
        "accounting.AllocationPlan.water_type",
        "accounting.AllocationPlan.reporting_period",
        "accounting.AllocationPlan.notes",
        "accounting.AllocationPlan.created_at",
        "accounting.CalculationPlan.name",
        "accounting.CalculationPlan.water_type",
        "accounting.CalculationPlan.is_active",
        "accounting.CalculationPlan.created_at",
        "accounting.CalculationRun.parcel",
        "accounting.CalculationRun.period",
        "accounting.CalculationRun.period_start",
        "accounting.CalculationRun.surface_efficiency",
        "accounting.CalculationRun.over_delivery_treatment",
        "accounting.CalculationRun.over_delivery_leave_behind",
        "accounting.CalculationRun.over_delivery_credit_pooled",
        "accounting.CalculationRun.residual_disposition",
        "accounting.CalculationRun.groundwater_application_efficiency",
        "accounting.CalculationRun.groundwater_efficiency_source",
        "accounting.CalculationRun.breakdown",
        "accounting.CalculationRun.methodology_plan_name",
        "accounting.CalculationRun.config_hash",
        "accounting.CalculationRun.created_at",
        "accounting.CalculationStep.plan",
        "accounting.CalculationStep.order",
        "accounting.CalculationStep.step_type",
        "accounting.CalculationStep.config",
        "accounting.CalculationStep.enabled",
        "accounting.CalculationStep.label",
        "accounting.ReportingPeriod.name",
        "accounting.ReportingPeriod.start_date",
        "accounting.ReportingPeriod.end_date",
        "accounting.ReportingPeriod.is_finalized",
        "accounting.ReportingPeriod.finalized_at",
        "accounting.ReportingPeriod.finalized_by",
        "accounting.ReportingPeriod.notes",
        "accounting.ReportingPeriod.created_at",
        "accounting.WaterAccount.name",
        "accounting.WaterAccount.account_number",
        "accounting.WaterAccount.status",
        "accounting.WaterAccount.contact_name",
        "accounting.WaterAccount.contact_email",
        "accounting.WaterAccount.unit_kind",
        "accounting.WaterAccount.delivery_well",
        "accounting.WaterAccount.notes",
        "accounting.WaterAccount.created_at",
        "accounting.WaterAccountParcel.water_account",
        "accounting.WaterAccountParcel.parcel",
        "accounting.WaterAccountParcel.reporting_period",
        "accounting.WaterAccountParcel.added_date",
        "accounting.WaterAccountParcel.removed_date",
        "accounting.WaterCredit.parcel",
        "accounting.WaterCredit.origin_period",
        "accounting.WaterCredit.origin",
        "accounting.WaterCredit.depreciation_rate",
        "accounting.WaterCredit.expires_period",
        "accounting.WaterCredit.created_at",
        "accounting.WaterCreditDraw.credit",
        "accounting.WaterCreditDraw.draw_period",
        "accounting.WaterCreditDraw.created_at",
        "core.SiteConfig.agency_name",
        "core.SiteConfig.timezone",
        "core.SiteConfig.contact_email",
        "core.SiteConfig.contact_phone",
        "core.SiteConfig.logo",
        "core.SiteConfig.demonstration_mode",
        "core.SiteConfig.default_irrigation_efficiency",
        "core.SiteConfig.over_delivery_treatment",
        "core.SiteConfig.over_delivery_leave_behind",
        "core.SiteConfig.canal_seepage_credit",
        "core.SiteConfig.default_recovery_horizon",
        "core.SiteConfig.diversion_use_type_rule",
        "core.SiteConfig.diversion_report_year_rule",
        "core.SiteConfig.season_start_month",
        "core.SiteConfig.water_year_start_month",
        "core.SiteConfig.identifier_host",
        "core.User.username",
        "core.User.first_name",
        "core.User.last_name",
        "core.User.agency_admin",
        "drinking.SampleResult.event",
        "drinking.SampleResult.analyte",
        "drinking.SampleResult.result_kind",
        "drinking.SampleResult.result_value",
        "drinking.SampleResult.presence",
        "drinking.SampleResult.unit",
        "drinking.SampleResult.reporting_level",
        "drinking.SampleResult.counting_error",
        "drinking.SampleResult.analysis_date",
        "drinking.SampleResult.method",
        "drinking.SampleResult.lab_name",
        "drinking.SampleResult.limits_source_file",
        "drinking.SampleResult.limits_file_date",
        "drinking.SamplingSchedule.system",
        "drinking.SamplingSchedule.sampling_point",
        "drinking.SamplingSchedule.analyte",
        "drinking.SamplingSchedule.group_label",
        "drinking.SamplingSchedule.frequency",
        "drinking.SamplingSchedule.last_done",
        "drinking.SamplingSchedule.next_due",
        "drinking.SamplingSchedule.notes",
        "drinking.SamplingSchedule.created_at",
        "drinking.SystemFacility.system",
        "drinking.SystemFacility.name",
        "drinking.SystemFacility.local_name",
        "drinking.SystemFacility.added_by_hand",
        "drinking.SystemFacility.facility_type",
        "drinking.SystemFacility.activity_status",
        "drinking.SystemFacility.is_source",
        "drinking.SystemFacility.water_type",
        "drinking.SystemFacility.availability",
        "drinking.SystemFacility.well",
        "drinking.SystemProduction.system",
        "drinking.SystemProduction.year",
        "drinking.SystemProduction.month",
        "drinking.SystemProduction.type_code",
        "drinking.SystemProduction.facility",
        "drinking.SystemProduction.volume_as_reported",
        "drinking.SystemProduction.unit_as_reported",
        "drinking.SystemProduction.volume_gallons",
        "drinking.SystemProduction.volume_acre_feet",
        "drinking.SystemProduction.provenance",
        "drinking.SystemProduction.notes",
        "drinking.SystemProduction.created_at",
        "drinking.WaterSystem.name",
        "drinking.WaterSystem.activity_status",
        "drinking.WaterSystem.state_classification",
        "drinking.WaterSystem.owner_type",
        "drinking.WaterSystem.primary_source_code",
        "drinking.WaterSystem.is_wholesaler",
        "drinking.WaterSystem.is_school_or_daycare",
        "drinking.WaterSystem.population_served_total",
        "drinking.WaterSystem.service_connections_total",
        "drinking.WaterSystem.population_residential",
        "drinking.WaterSystem.population_non_transient",
        "drinking.WaterSystem.population_transient",
        "drinking.WaterSystem.connections_agricultural",
        "drinking.WaterSystem.connections_combined",
        "drinking.WaterSystem.connections_commercial",
        "drinking.WaterSystem.connections_industrial",
        "drinking.WaterSystem.connections_residential",
        "drinking.WaterSystem.mailing_city",
        "drinking.WaterSystem.mailing_state",
        "drinking.WaterSystem.regulating_agency",
        "geography.ParcelZone.parcel",
        "geography.ParcelZone.zone",
        "geography.ParcelZone.start_date",
        "geography.ParcelZone.end_date",
        "geography.Zone.name",
        "geography.Zone.boundary",
        "geography.Zone.description",
        "geography.Zone.zone_type",
        "geography.Zone.basin_code",
        "geography.Zone.recovery_horizon",
        "geography.Zone.created_at",
        "measurements.MeterReading.meter",
        "measurements.MeterReading.observed_property",
        "measurements.MeterReading.reading_date",
        "measurements.MeterReading.previous_value",
        "measurements.MeterReading.current_value",
        "measurements.MeterReading.calculated_volume",
        "measurements.MeterReading.quality",
        "measurements.MeterReading.read_by",
        "measurements.MeterReading.notes",
        "measurements.MeterReading.created_at",
        "measurements.WaterMeasurement.name",
        "measurements.WaterMeasurement.measurement_type",
        "measurements.WaterMeasurement.observed_property",
        "measurements.WaterMeasurement.value",
        "measurements.WaterMeasurement.unit",
        "measurements.WaterMeasurement.measurement_date",
        "measurements.WaterMeasurement.parcel",
        "measurements.WaterMeasurement.well",
        "measurements.WaterMeasurement.source",
        "measurements.WaterMeasurement.recorded_by",
        "measurements.WaterMeasurement.notes",
        "measurements.WaterMeasurement.created_at",
        "parcels.FallowPeriod.parcel",
        "parcels.FallowPeriod.start_month",
        "parcels.FallowPeriod.end_month",
        "parcels.FallowPeriod.created_by",
        "parcels.FallowPeriod.created_at",
        "parcels.IrrigationMethod.name",
        "parcels.IrrigationMethod.assigned_efficiency",
        "parcels.IrrigationMethod.range_low",
        "parcels.IrrigationMethod.range_high",
        "parcels.IrrigationMethod.source",
        "parcels.IrrigationMethod.sort_order",
        "parcels.Parcel.parcel_number",
        "parcels.Parcel.owner_name",
        "parcels.Parcel.area_acres",
        "parcels.Parcel.area_override",
        "parcels.Parcel.status",
        "parcels.Parcel.address",
        "parcels.Parcel.notes",
        "parcels.Parcel.created_at",
        "parcels.ParcelIrrigationMethod.parcel",
        "parcels.ParcelIrrigationMethod.method",
        "parcels.ParcelLedger.parcel",
        "parcels.ParcelLedger.transaction_date",
        "parcels.ParcelLedger.effective_date",
        "parcels.ParcelLedger.amount_acre_feet",
        "parcels.ParcelLedger.water_type",
        "parcels.ParcelLedger.source_type",
        "parcels.ParcelLedger.description",
        "parcels.ParcelLedger.reporting_period",
        "parcels.ParcelLedger.created_by",
        "parcels.ParcelLedger.created_at",
        "parcels.ParcelLedger.divided_from_headgate",
        "recharge.RechargeEvent.recharge_site",
        "recharge.RechargeEvent.start_date",
        "recharge.RechargeEvent.end_date",
        "recharge.RechargeEvent.volume_acre_feet",
        "recharge.RechargeEvent.water_type",
        "recharge.RechargeEvent.source_description",
        "recharge.RechargeEvent.notes",
        "recharge.RechargeEvent.created_at",
        "recharge.RechargeMeasurement.recharge_site",
        "recharge.RechargeMeasurement.measurement_date",
        "recharge.RechargeMeasurement.measurement_type",
        "recharge.RechargeMeasurement.value",
        "recharge.RechargeMeasurement.unit",
        "recharge.RechargeMeasurement.notes",
        "recharge.RechargeMeasurement.created_at",
        "reporting.ReportSubmission.report_template",
        "reporting.ReportSubmission.reporting_period",
        "reporting.ReportSubmission.status",
        "reporting.ReportSubmission.generated_file",
        "reporting.ReportSubmission.generated_at",
        "reporting.ReportSubmission.filed_at",
        "reporting.ReportSubmission.certified_by",
        "reporting.ReportSubmission.state_confirmation_number",
        "reporting.ReportSubmission.internal_notes",
        "reporting.ReportSubmission.prefill_overrides",
        "reporting.ReportSubmission.validation_warnings",
        "reporting.ReportSubmission.created_at",
        "surface.CanalMonthLoss.point_of_diversion",
        "surface.CanalMonthLoss.month",
        "surface.CanalMonthLoss.seepage_zone",
        "surface.CanalMonthLoss.seepage_water_year",
        "surface.CanalMonthLoss.created_at",
        "surface.DiversionRecord.point_of_diversion",
        "surface.DiversionRecord.reporting_period",
        "surface.DiversionRecord.month",
        "surface.DiversionRecord.volume_acre_feet",
        "surface.DiversionRecord.diversion_type",
        "surface.DiversionRecord.method",
        "surface.DiversionRecord.device",
        "surface.DiversionRecord.data_state",
        "surface.DiversionRecord.notes",
        "surface.DiversionRecord.created_at",
        "surface.MeasuringDevice.nickname",
        "surface.MeasuringDevice.device_type",
        "surface.MeasuringDevice.make",
        "surface.MeasuringDevice.model_number",
        "surface.MeasuringDevice.recording_make",
        "surface.MeasuringDevice.recording_model",
        "surface.MeasuringDevice.recording_type",
        "surface.MeasuringDevice.measured_parameter",
        "surface.MeasuringDevice.raw_units",
        "surface.MeasuringDevice.accuracy_percent",
        "surface.MeasuringDevice.installed_on",
        "surface.MeasuringDevice.installer_contact",
        "surface.MeasuringDevice.last_evidence_on",
        "surface.MeasuringDevice.status",
        "surface.MeasuringDevice.notes",
        "surface.MeasuringDevice.created_at",
        "surface.PointOfDiversion.water_right",
        "surface.PointOfDiversion.name",
        "surface.PointOfDiversion.rediverted_from",
        "surface.PointOfDiversion.stream_name",
        "surface.PointOfDiversion.source_flowline",
        "surface.PointOfDiversion.status",
        "surface.PointOfDiversion.notes",
        "surface.PointOfDiversion.evaporation_fraction",
        "surface.PointOfDiversion.seepage_fraction",
        "surface.PointOfDiversion.spill_fraction",
        "surface.PointOfDiversion.evaporation_band_percent",
        "surface.PointOfDiversion.seepage_band_percent",
        "surface.PointOfDiversion.spill_band_percent",
        "surface.PointOfDiversion.loss_basis",
        "surface.PointOfDiversion.lining",
        "surface.PointOfDiversion.spill_device",
        "surface.PointOfDiversion.owner_account",
        "surface.PointOfDiversion.division_method",
        "surface.PointOfDiversion.local_name",
        "surface.PointOfDiversionDevice.point_of_diversion",
        "surface.PointOfDiversionDevice.device",
        "surface.PointOfDiversionDevice.installed_on",
        "surface.PointOfDiversionDevice.removed_on",
        "surface.PointOfDiversionDevice.is_current",
        "surface.PointOfDiversionParcel.point_of_diversion",
        "surface.PointOfDiversionParcel.parcel",
        "surface.PointOfDiversionParcel.fraction",
        "surface.PointOfDiversionParcel.notes",
        "surface.UnallocatedDelivery.point_of_diversion",
        "surface.UnallocatedDelivery.reporting_period",
        "surface.UnallocatedDelivery.month",
        "surface.UnallocatedDelivery.amount_acre_feet",
        "surface.UnallocatedDelivery.delivery_acre_feet",
        "surface.UnallocatedDelivery.created_at",
        "surface.WaterAccountDeliveryPoint.account",
        "surface.WaterAccountDeliveryPoint.point_of_diversion",
        "surface.WaterRight.right_type",
        "surface.WaterRight.holder_name",
        "surface.WaterRight.priority_date",
        "surface.WaterRight.face_value_acre_feet",
        "surface.WaterRight.status",
        "surface.WaterRight.source_name",
        "surface.WaterRight.state_status",
        "surface.WaterRight.permit_number",
        "surface.WaterRight.license_number",
        "surface.WaterRight.purpose_of_use",
        "surface.WaterRight.net_acreage",
        "surface.WaterRight.direct_season_start_month",
        "surface.WaterRight.direct_season_start_day",
        "surface.WaterRight.direct_season_end_month",
        "surface.WaterRight.direct_season_end_day",
        "surface.WaterRight.storage_season_start_month",
        "surface.WaterRight.storage_season_start_day",
        "surface.WaterRight.storage_season_end_month",
        "surface.WaterRight.storage_season_end_day",
        "surface.WaterRight.watershed",
        "surface.WaterRight.notes",
        "surface.WaterRight.created_at",
        "surface.WaterRightParcel.water_right",
        "surface.WaterRightParcel.parcel",
        "surface.WaterRightParcel.notes",
        "wells.Well.name",
        "wells.Well.well_type",
        "wells.Well.status",
        "wells.Well.owner_name",
        "wells.Well.year_pumping_began",
        "wells.Well.measurement_method",
        "wells.Well.accuracy_band",
        "wells.Well.state_well_number",
        "wells.Well.vertical_datum",
        "wells.Well.casing_material",
        "wells.Well.pump_type",
        "wells.Well.notes",
        "wells.Well.created_at",
        "wells.WellIrrigatedParcel.well",
        "wells.WellIrrigatedParcel.parcel",
        "wells.WellIrrigatedParcel.fraction",
        "wells.WellIrrigatedParcel.notes",
        "wells.WellMeter.well",
        "wells.WellMeter.meter",
        "wells.WellMeter.installed_date",
        "wells.WellMeter.removed_date",
        "wells.WellMeter.calibration_date",
        "wells.WellMeter.is_current",
    }
)


def _all_event_models():
    """Every tracked model's event model, whichever modules are switched on."""
    found = {}
    for model in apps.get_models():
        tracked = getattr(model, "pgh_tracked_model", None)
        if tracked is None or model._meta.proxy or not model._meta.managed:
            continue
        found[tracked._meta.label] = model
    return found


def _tracked_fields():
    for label, event_model in sorted(_all_event_models().items()):
        tracked = event_model.pgh_tracked_model
        recorded = {f.name for f in event_model._meta.fields}
        for field in tracked._meta.concrete_fields:
            if field.name in recorded and not field.primary_key:
                yield label, field


def _is_made_by_django(field):
    return str(field.verbose_name) == field.name.replace("_", " ")


def test_every_tracked_field_is_labelled_or_listed_as_plain_words():
    unlabelled = sorted(
        f"{label}.{field.name}"
        for label, field in _tracked_fields()
        if _is_made_by_django(field) and f"{label}.{field.name}" not in PLAIN_WORDS
    )
    assert unlabelled == []


def test_the_plain_words_list_names_only_fields_that_exist_and_have_no_label():
    live = {
        f"{label}.{field.name}"
        for label, field in _tracked_fields()
        if _is_made_by_django(field)
    }
    assert sorted(PLAIN_WORDS - live) == []


def test_no_printed_label_carries_a_lower_case_abbreviation():
    bad = sorted(
        f"{label}.{field.name} -> {field_name(field)}"
        for label, field in _tracked_fields()
        if ABBREVIATIONS.search(UNITS_IN_BRACKETS.sub("", field_name(field)))
    )
    assert bad == []


def test_a_calculated_ledger_change_shows_the_pages_words():
    run = CalculationRun.objects.create(
        parcel=ParcelFactory(),
        period="2026-08",
        gross_et_af=Decimal("5.0000"),
        final_af=Decimal("4.0000"),
    )
    run.gross_et_af = Decimal("6.8069")
    run.save()
    names = [c.name for c in changes_for(run)[0].changes]
    assert "Crop ET (AF)" in names
    admin = get_user_model().objects.create_user(
        username="a", email="a@example.org", password="x", is_active=True, agency_admin=True
    )
    client = Client()
    client.force_login(admin)
    html = client.get(reverse("change_history")).content.decode()
    assert "Crop ET (AF)" in html
    assert "Gross et af" not in html
