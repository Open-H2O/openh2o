"""The literary sentence, pinned: Phase 143.1 plan 01, ruled by Brent 2026-09-17.

Brent, 2026-09-13, at the 143-10 checkpoint: "We have the strange AI language
issue going on. It's something we have to correct periodically. Instead of
speaking clearly, using short phrases that have a lot of meaning, the phrasing
becomes literary and conversational." His fix, the well page's Measurement
history subtitle, is the standard every row here was judged against:

    before  What came through the meter, and what the water table did beneath it
    after   Meter reads and depth to water, by water year.

DESIGN.md copy rule 15 states the rule. This module is its guard: 126 rulings
(accept-all, 2026-09-17 06:57 PDT, `.planning/phases/143.1-literary-sentence/
143.1-01-RULINGS.md`) as a table of (path, struck, settled). Three tests,
parametrised by row so a failure names the sentence:

1. the settled sentence is in its file;
2. the struck sentence is gone from the product (templates and product Python);
3. the settled sentence scans clean under copy rule 11
   (`tests.test_domain_vocabulary.scan`).

RULE 8 OF THE HOUSE (ISS-129): this table mandates WORDS Brent ruled, never a
domain description. A row is added only with a ruling and its date; a row is
changed only the same way. Four rows carry words that differ from the
candidates file he ruled on, each recorded in 143.1-01-SUMMARY.md: S-1154 and
S-1058 (the droppability gate forbids the noun "recharge" on a page a
recharge-less deployment still serves; "deep percolation" / "goes to the
aquifer" carry the fact), S-0669 (the candidates row misquoted the sentence;
the settled first sentence stands and the second stays), S-0639 (its address
was `onboard.html`, not `overview.html`).

Comparison is on collapsed text: whitespace collapsed, HTML entities
unescaped, curly quotes straightened, Django tags and `{{ }}` figures removed
(a `<x>` in a settled sentence stands for a figure; the fragments around it are
what is checked). A Python row's implicit string concatenation is joined first.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.test_domain_vocabulary import scan

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "templates"


class Row(NamedTuple):
    id: str
    path: str
    struck: str
    settled: str | None  # None: the sentence was struck outright
    #: Words of the struck sentence to test for, when the automatic window
    #: (see ``struck_probe``) would collide with a different, live sentence
    #: that shares its tail.
    probe: str | None = None


SETTLED = [
    Row('S-1223 + S-1224',
        'templates/parcels/partials/_detail_pane.html',
        "More water is recorded arriving here than this parcel's uses account for — by more than a quarter of estimated consumptive use, so it is flagged rather than treated as ordinary on-farm loss. A residual this size is a gap in the books, not spare water: conveyance loss is not yet a term in this platform, so ditch seepage and evaporation have nowhere to be recorded and land here.",
        'Recorded supplies exceed estimated consumptive use by more than a quarter. The platform has no conveyance-loss entry, so ditch seepage and evaporation are counted in this residual.'),
    Row('S-1221',
        'templates/parcels/partials/_detail_pane.html',
        'Supplies slightly exceed estimated consumptive use — the difference is on-farm loss or return flow, not unaccounted water.',
        'Supplies exceed estimated consumptive use by a small margin: on-farm loss or return flow.'),
    Row('S-1222',
        'templates/parcels/partials/_detail_pane.html',
        "Estimated consumptive use slightly exceeds recorded supplies — a minor supplement (deficit irrigation, or shallow-groundwater / stream-adjacent rootzone water the meters don't capture).",
        'Estimated consumptive use exceeds recorded supplies by a small margin: deficit irrigation, or water the meters do not capture.'),
    Row('S-0002 (+ S-0009 tail)',
        'accounting/ledger_words.py',
        'split by the fixed share on file <x> no estimated use on record for the month',
        'the fixed share on file <x> because no use area it serves has an estimated use for the month'),
    Row('S-0379',
        'templates/accounting/dashboard.html',
        "This is your water-data overview. It summarizes the water data you've recorded — deliveries, measurements, and usage — by account and zone. To get started:",
        'Deliveries, measurements and usage by account and zone. To get started:'),
    Row('S-0383',
        'templates/accounting/dashboard.html',
        '4 The overview summarizes your recorded water data — supplies, usage, and how they compare by account and zone',
        None),
    Row('S-0373',
        'templates/accounting/dashboard.html',
        "Summary of your district's water data for the selected period — recorded supplies and uses by account and zone, with satellite-estimated crop water use (evapotranspiration, or ET) shown as one estimated input.",
        'Recorded supplies and uses by account and zone for the period, with satellite-estimated crop water use (ET) as one estimated input.'),
    Row('S-1315',
        'templates/reporting/partials/_handoff.html',
        "The worksheet lays them out in transcription order, with each water right's CalWATRS PIN beside it, so you are reading down one page instead of hunting through the platform.",
        "The worksheet lists them in transcription order, each water right's CalWATRS PIN beside it, on one page."),
    Row('S-0596',
        'templates/drinking/facility_detail.html',
        "Positions come from the state's Groundwater Ambient Monitoring and Assessment Program (GAMA), which publishes them for groundwater sources and not for distribution-system or treatment-plant facilities — and not for every source either.",
        "Positions come from the state's Groundwater Ambient Monitoring and Assessment Program (GAMA), which publishes them for groundwater sources only, and not for every one."),
    Row('S-0597',
        'templates/drinking/facility_detail.html',
        'A system onboarded from the federal record arrives with no coordinates.',
        "EPA's record, which onboarding reads, carries no coordinates."),
    Row('S-0831',
        'templates/drinking/sampling_point_detail.html',
        "A sampling point is placed at its facility's position, and positions come from the state's Groundwater Ambient Monitoring and Assessment Program (GAMA), which publishes them for groundwater sources and not for distribution-system or treatment-plant facilities — and not for every source either.",
        "A sampling point takes its facility's position. Positions come from the state's Groundwater Ambient Monitoring and Assessment Program (GAMA), which publishes them for groundwater sources only, and not for every one."),
    Row('S-0827',
        'templates/drinking/sampling_point_detail.html',
        'Where this sample is physically drawn, and what has been measured there.',
        "The sampling point's location and the measurements taken there."),
    Row('S-0692 = S-0803',
        'templates/drinking/partials/_facility_results.html',
        "Coordinates are published by the state's Groundwater Ambient Monitoring and Assessment Program (GAMA) for groundwater sources only — EPA's Envirofacts record, which onboarding builds a system from, carries none — so a newly onboarded system starts unmapped and gains coordinates as its sources are located.",
        "The state's Groundwater Ambient Monitoring and Assessment Program (GAMA) publishes coordinates for groundwater sources only; EPA's Envirofacts record, which onboarding reads, carries none. A new system has no map until its sources are located."),
    Row('S-0692 = S-0803',
        'templates/drinking/partials/_sampling_point_results.html',
        "Coordinates are published by the state's Groundwater Ambient Monitoring and Assessment Program (GAMA) for groundwater sources only — EPA's Envirofacts record, which onboarding builds a system from, carries none — so a newly onboarded system starts unmapped and gains coordinates as its sources are located.",
        "The state's Groundwater Ambient Monitoring and Assessment Program (GAMA) publishes coordinates for groundwater sources only; EPA's Envirofacts record, which onboarding reads, carries none. A new system has no map until its sources are located."),
    Row('S-0659',
        'templates/drinking/overview.html',
        'Where the rest of the platform accounts for how much water there is, this domain records what is in it.',
        None),
    Row('S-0738',
        'templates/drinking/partials/_onboard_result.html',
        'This page no longer knows which system you were reviewing — the tab has been open a while, or the sign-in session rolled over.',
        'The review has expired: the tab was open too long, or the sign-in session ended.'),
    Row('S-0740',
        'templates/drinking/partials/_onboard_result.html',
        'Look the PWSID up again and the review will come back as it was.',
        'Look the PWSID up again to restore the review.'),
    Row('S-0754',
        'templates/drinking/partials/_onboard_result.html',
        'Walk the facilities and add the points your lab file names.',
        'Add, under each facility, the points your lab file names.'),
    Row('S-0722',
        'templates/drinking/partials/_import_result.html',
        'Fix these rows in your file and import it again — the rows that already landed will be recognized and skipped.',
        'Fix these rows in your file and import it again; rows already imported are skipped.'),
    Row('S-0074',
        'config/views.py',
        'One record per POD, holding its location, the right it draws under, the stream or flowline it sits on, its maximum rate in CFS, and the parcels it serves. Monthly records of what came through it hang off it.',
        'One record per POD: its location, the right it draws under, its stream or flowline, its maximum rate in CFS, and the parcels it serves, with its monthly diversion records.'),
    Row('S-0082',
        'config/views.py',
        'One record per well, holding its state well number, WCR number and local ID, the meters attached to it, and the parcels it irrigates. Depth, casing and screen intervals sit here too.',
        'One record per well, holding its state well number, WCR number and local ID, its meters, the parcels it irrigates, and its depth, casing and screen intervals.'),
    Row('S-1424',
        'templates/setup/run.html',
        'Re-running a step is safe: it notices what is already here and skips it, so nothing is duplicated.',
        'Re-running a step is safe: records already present are skipped.'),
    Row('S-0264',
        'templates/about_demonstration_data.html',
        'The two sit side by side, so the tables below say which is which.',
        'The tables below say which is which.'),
    Row('S-0266',
        'templates/about_demonstration_data.html',
        'The drinking-water screens say this for themselves as well: each section carries a small label naming who published its values, so the question can be answered in front of the data instead of by coming back here.',
        'Each drinking-water section carries a label naming who published its values.'),
    Row('S-0295',
        'templates/about_demonstration_data.html',
        "Generated by this deployment so the accounting has land use to read — each record sits at its parcel's center point, which is derived from the parcel shape and is not a surveyed location",
        "Generated by this deployment so the accounting has land use to read; each record is placed at its parcel's center point, derived from the parcel shape, not surveyed"),
    Row('S-0166',
        'health/checks.py',
        'No metered parcels with applied water — satellite ET has nothing independent to check against here',
        'No metered parcels with applied water to check satellite ET against'),
    Row('S-0453',
        'templates/accounting/partials/_dashboard_content.html',
        'This is a missing step, not a finding — it does not mean nothing was consumed.',
        'A missing step, not a finding: water may still have been consumed.'),
    Row('S-0758',
        'templates/drinking/partials/_onboard_review.html',
        "Check the ID against the regulator's own listing and try again — this is an answer from a working service, not a sign that EPA is down.",
        "Check the ID against the regulator's listing and try again. EPA answered; the ID was not found."),
    Row('S-1377',
        'templates/reporting/shared_supply_check.html',
        "This page compares each hand-entered share against the share that estimated satellite crop-water use (ET) would imply, and flags any field where the two are far apart — a likely typo worth a look on the source's own page.",
        "Each hand-entered share beside the share satellite crop-water use (ET) implies; a field where the two are far apart is flagged for a check on the source's page."),
    Row('S-1323',
        'templates/reporting/partials/_openet_prefill.html',
        'ET is the water your crops consumed, which is not the same as the water you pumped or diverted — rain and surface deliveries also feed a crop, so consumptive use and metered extraction rarely match.',
        'ET is estimated crop water use, not metered pumping or diversion.'),
    Row('S-1344',
        'templates/reporting/partials/_report_detail_pane.html',
        'ET is the water your crops consumed — not what you pumped or diverted — so each value is an editable estimate you review before certifying in the state portal.',
        'ET is estimated crop water use, not metered pumping or diversion; each value is an estimate to review before certifying in the state portal.'),
    Row('S-0426',
        'templates/accounting/partials/_account_detail_pane.html',
        'conjunctive growers fall back on groundwater to make up the shortfall.',
        None),
    Row('S-0376',
        'templates/accounting/dashboard.html',
        'Set one up to import parcels, wells, groundwater basins, and the monitoring stations near your district — everything the dashboard needs to start tracking water.',
        'Set one up to import parcels, wells, groundwater basins, and the monitoring stations near your district.'),
    Row('S-0615',
        'templates/drinking/import.html',
        "Analytes the file names but this system has never seen are added to the vocabulary, because the analyte list belongs to the regulator and the state's own file is the authority on it — the preview lists every one before you commit.",
        "Analytes the file names that this system has not seen are added to the vocabulary; the state's file is the authority. The preview lists each one before you commit."),
    Row('S-0727',
        'templates/drinking/partials/_onboard_points_form.html',
        'Letters are fine — LCR and 900 are both real.',
        'Letters are allowed: LCR and 900 are both published codes.'),
    Row('S-0730',
        'templates/drinking/partials/_onboard_points_listed.html',
        'Coming back to a system you had partly finished is ordinary;',
        'A partly finished system can be resumed;'),
    Row('S-0761',
        'templates/drinking/partials/_onboard_review.html',
        'Your PWSID may be perfectly good;',
        'Your PWSID may be correct;'),
    Row('S-0789 = S-0639',
        'templates/drinking/partials/_onboard_review.html',
        'so those fields stay empty until a source that genuinely breaks them down is imported.',
        'so those fields stay empty until a source that breaks them down is imported.'),
    Row('S-0789 = S-0639',
        'templates/drinking/onboard.html',
        'so those fields stay empty until a source that genuinely breaks them down is imported.',
        'so those fields stay empty until a source that breaks them down is imported.'),
    Row('S-0632',
        'templates/drinking/onboard.html',
        'That is the whole of it.',
        None),
    Row('S-0685',
        'templates/drinking/partials/_empty_drinking.html',
        "Onboard one from EPA's federal record first — the builder opens on the system that creates, and on its facilities.",
        "Onboard one from EPA's federal record first; the builder then opens on that system and its facilities."),
    Row('S-0753',
        'templates/drinking/partials/_onboard_result.html',
        'This system now has its facilities, but no sampling points — and lab results cannot be imported until it has them, because every result row is matched to a monitoring location by its PS Code.',
        'This system has its facilities but no sampling points. Lab results cannot be imported until it has them: every result row is matched to a point by its PS Code.'),
    Row('S-0669',
        'templates/drinking/overview.html',
        'Envirofacts carries the facilities but not the points beneath them, so onboarding deliberately creates none — inventing them would let one federal record decide the structure a lab file is matched against.',
        'Envirofacts carries the facilities but not their sampling points, so onboarding creates none.'),
    Row('S-0146',
        'drinking/views.py',
        '<x> is carried here but has no facilities, so there is nothing to hang a sampling point on. Re-run the lookup to refresh its facilities from EPA.',
        '<x> has no facilities, so no sampling point can be added. Re-run the lookup to refresh its facilities from EPA.'),
    Row('S-0050',
        'config/views.py',
        'so the total always reconciles back to what the source actually produced.',
        'so the total reconciles to what the source produced.'),
    Row('S-0056',
        'config/views.py',
        'A small leftover residual is normal — real books rarely close to exactly zero.',
        'A small residual is normal.'),
    Row('S-0059 · S-0062 [1]',
        'config/views.py',
        'how much of a delivery the crop actually uses',
        'how much of a delivery the crop uses'),
    Row('S-0059 · S-0062 [2]',
        'config/views.py',
        'The portion of rainfall that crops actually use',
        'Rainfall the crops use, rather than running off or percolating away.'),
    Row('S-0085',
        'core/forms.py',
        'The rest soaks back into the aquifer. Typical: 75%.',
        'Typical: 75%.'),
    Row('S-0087',
        'core/models.py',
        'Share of delivered water the crop actually consumes; the rest returns to the aquifer as recharge.',
        'Share of delivered water the crop consumes.'),
    Row('S-0131',
        'drinking/models.py',
        'Published location of the facility. From GAMA, which publishes coordinates for source wells only — most facilities have none, and NULL is the honest value.',
        'Published location of the facility, from GAMA, which publishes coordinates for source wells only; most facilities have none.'),
    Row('S-0129',
        'drinking/models.py',
        "EPA's own facility ID. Provenance only — never a PS Code segment. See .planning/phases/79-envirofacts-adapter/79-RESEARCH.md.",
        "EPA's own facility ID. Provenance only; never a PS Code segment."),
    Row('S-0030',
        'accounting/models.py',
        'Month at/after which the carried surplus is dead, as YYYY-MM. Null = never expires.',
        'Month at or after which the carried surplus expires, as YYYY-MM. Blank = never expires.'),
    Row('S-1410',
        'templates/setup/partials/_progress.html',
        'Review imported parcels — confirm the use areas brought in for your watershed',
        'Review imported parcels — confirm the use areas for your watershed'),
    Row('S-0585',
        'templates/datasync/station_list.html',
        'The map follows the list, each station colored by how recently it reported;',
        'The map shows the list, each station colored by how recently it reported;'),
    Row('S-0557',
        'templates/datasync/partials/_station_detail_pane.html',
        'Whether this station is wired up for scheduled data pulls. Switch it off and syncs skip it. Nothing to do with how recently it published — that is the freshness dot.',
        'Whether scheduled syncs include this station. Off, and syncs skip it. Freshness (how recently it reported) is the dot.'),
    Row('S-0191 = S-0193 · S-0192 = S-0194 [1]',
        'setup/views.py',
        'Setup starts here. Choose or upload a boundary, then confirm it; this session had none.',
        'No boundary is confirmed for this session. Choose or upload one, then confirm it.'),
    Row('S-0191 = S-0193 · S-0192 = S-0194 [2]',
        'setup/views.py',
        'the boundary this session had chosen no longer exists.',
        'The boundary this session chose no longer exists. Choose or upload one, then confirm it.'),
    Row('S-1432',
        'templates/setup/wizard.html',
        "A GIS consultant, or whoever handles the district's mapping, can export one — and if a file is rejected here, they are the people to send it back to.",
        "A GIS consultant, or whoever handles the district's mapping, can export one, and can fix a file rejected here."),
    Row('S-1174 · S-1176 [1]',
        'templates/home.html',
        'Work out your figures',
        "Your figures for the state's layouts"),
    Row('S-1174 · S-1176 [2]',
        'templates/home.html',
        'Boundaries, zones, and bringing your data in',
        'Boundaries, zones and data import'),
    Row('S-0408',
        'templates/accounting/methodology_settings.html',
        'Each step below is one operation in that chain — reorder it, enable or disable it, and tune its knobs, then preview a sample parcel to see the effect.',
        'Each step below is one operation in that chain: reorder, enable or disable, and set its parameters; then preview a sample parcel.',
        probe='enable or disable it, and tune its knobs'),
    Row('S-0225',
        'templates/about.html',
        'OpenH2O exists because the Groundwater Accounting Platform (GAP) proved something that was far from obvious when it started: that a partnership across public agencies, a nonprofit, and private firms could build and sustain shared, open-source infrastructure for water management — and hold it to a standard that raised the bar for every tool in the field.',
        'OpenH2O exists because the Groundwater Accounting Platform (GAP) proved that public agencies, a nonprofit and private firms could build and sustain shared, open-source infrastructure for water management, to a high standard.'),
    Row('S-0227',
        'templates/about.html',
        'Years of that work are the example OpenH2O learned from.',
        'OpenH2O is built on that work.'),
    Row('S-0228 + S-0229 + S-0230',
        'templates/about.html',
        'GAP also made the hard part clear. Standing up the software is the easy half; the decisive work is everything around it — training, outreach, and the patient support that turns a tool into a system an agency actually trusts.',
        'GAP also showed where the work is: not in standing up the software, but in training, outreach and support until an agency relies on it.'),
    Row('S-0231',
        'templates/about.html',
        'OpenH2O treats that human and institutional work as the real work, not an afterthought.',
        'OpenH2O treats that work as the work.'),
    Row('S-0233',
        'templates/about.html',
        "OpenH2O is an independent reimplementation on an open stack, indebted to GAP's example and glad to keep learning from the people who built it.",
        "OpenH2O is an independent reimplementation on an open stack, built on GAP's example."),
    Row('S-0242',
        'templates/about.html',
        'What the platform is actually computing, in plain language',
        'What the platform is computing, in plain language'),
    Row('S-0285',
        'templates/about_demonstration_data.html',
        'and are not what it actually pumps, owns or owes.',
        'and are not what it pumps, owns or owes.'),
    Row('S-0297',
        'templates/about_demonstration_data.html',
        "The accounting story the platform exists to show, with no real agency's numbers in it",
        "The accounting the platform exists to show, with no real agency's numbers in it"),
    Row('S-0301',
        'templates/about_demonstration_data.html',
        'One thing worth being clear about',
        'One clarification'),
    Row('S-0846',
        'templates/geography/partials/_zone_detail_pane.html',
        'Surface deliveries to the curtailed parcels stop after the curtailment date — the current-year surface allocation below is reduced to match, and conjunctive growers substitute groundwater.',
        'Surface deliveries to the curtailed parcels stop after the curtailment date; the current-year surface allocation below is reduced to match.',
        probe='reduced to match, and conjunctive growers'),
    Row('S-1435',
        'templates/surface/partials/_detail_pane.html',
        'This traces the journey one hop at a time.',
        'One hop per row below.'),
    Row('S-1449',
        'templates/surface/partials/_detail_pane.html',
        'This diversion point operates without a formal water right permit.',
        None),
    Row('S-0210',
        'surface/models.py',
        'The real NHD/canal waterway this diversion sits on (provenance). stream_name stays the human-readable eWRIMS label.',
        'Waterway (NHD or canal) this diversion is on, for provenance. stream_name stays the human-readable eWRIMS label.'),
    Row('S-1123',
        'templates/help/water_balances.html',
        'A water balance answers a deceptively hard question: who used what?',
        'A water balance answers one question: who used what?'),
    Row('S-1125',
        'templates/help/water_balances.html',
        'Out of everything a field involves, there is exactly one quantity we can estimate for every field, from space, whether its water came from a canal, a well, or rain: the water the crops actually drank.',
        'One quantity can be estimated for every field, from satellite, whatever its water source: the water the crops consumed.'),
    Row('S-1127',
        'templates/help/water_balances.html',
        '— is the anchor.',
        'is the reference figure.'),
    Row('S-1128',
        'templates/help/water_balances.html',
        'Everything else is a supply we line up against it to see whether the books add up.',
        'Everything else is a supply, compared against it.'),
    Row('S-1132',
        'templates/help/water_balances.html',
        'a perfect zero would be the surprise.',
        'an exact zero would be unusual.'),
    Row('S-1141',
        'templates/help/water_balances.html',
        'A balance lays the supplies alongside the use and asks whether they line up.',
        'A balance compares the supplies with the use.'),
    Row('S-1142',
        'templates/help/water_balances.html',
        'Because ET is the floor, the supplies delivered usually run a little higher than the estimated ET — and that difference is itself information.',
        'Because ET is the floor, supplies usually run a little above estimated ET; the difference is itself information.'),
    Row('S-1143',
        'templates/help/water_balances.html',
        'Reading it honestly is the next section.',
        'Reading that difference is the next section.'),
    Row('S-1145',
        'templates/help/water_balances.html',
        'Reconciling is just supplies minus use.',
        'Reconciling is supplies minus use.'),
    Row('S-1146',
        'templates/help/water_balances.html',
        "Start with the estimated use, subtract the supplies we already know about — surface deliveries first, then rain — and look at what's left unexplained.",
        'Start with the estimated use, subtract the known supplies (surface deliveries first, then rain), and read what is left.'),
    Row('S-1148',
        'templates/help/water_balances.html',
        'The rule that keeps it honest',
        'Where the leftover goes'),
    Row('S-1149',
        'templates/help/water_balances.html',
        'An unexplained leftover is booked as groundwater only where a well actually exists.',
        'Only where a well exists is an unexplained leftover booked as groundwater.'),
    Row('S-1150',
        'templates/help/water_balances.html',
        "On a field with no well, that same leftover is unmet demand — the crop wanted more than it got — or a surface number that's off.",
        'On a field with no well, the leftover is unmet demand, or a surface figure that is wrong.'),
    Row('S-1151 + S-1152',
        'templates/help/water_balances.html',
        'It is never phantom pumping. The platform refuses to invent groundwater out of a missing meter.',
        'It is never written as pumping; a missing meter yields no groundwater figure.'),
    Row('S-1154',
        'templates/help/water_balances.html',
        'ET is the floor, so the water delivered will usually exceed the water consumed — some seeps from canals on the way (conveyance loss), some runs off, some sinks past the roots back into the aquifer.',
        'ET is the floor, so delivered water usually exceeds consumed water: conveyance loss, runoff and deep percolation take the rest.'),
    Row('S-1156 + S-1157',
        'templates/help/water_balances.html',
        "it's how irrigation actually behaves. The job isn't to force the balance to zero — it's to make the remaining gap small enough to explain.",
        'that is normal. The aim is not a zero balance but a gap small enough to explain.'),
    Row('S-1158 + S-1159',
        'templates/help/water_balances.html',
        'All of this exists to solve one stubborn problem: most water diversions in California are not metered. Reporting is sparse, self-reported, and exempt below certain thresholds — so for the vast majority of fields, nobody knows how much water actually moved.',
        'Most water diversions in California are not metered, and reporting is sparse, self-reported and exempt below thresholds; for most fields the volume moved is unknown.'),
    Row('S-1160 + S-1162',
        'templates/help/water_balances.html',
        'Evapotranspiration estimated from space is the answer to that missing-meter problem. … That is what makes a credible balance possible where one was never possible before.',
        'Evapotranspiration estimated from satellite covers the fields no meter does.'),
    Row('S-1166',
        'templates/help/water_balances.html',
        'Now that the idea is clear, here is where to watch it work and where to dig deeper.',
        'Where to see it applied, and where to read more.'),
    Row('S-0992 + S-0993',
        'templates/help/methods.html',
        'Turning a satellite measurement into a number you can stand behind is a chain of subtractions. Start from what the crops actually used — the one thing we can measure for every field, from space.',
        'Turning a satellite measurement into a defensible number is a chain of subtractions. Start from what the crops used, the one figure available for every field.'),
    Row('S-0996',
        'templates/help/methods.html',
        'No single clever formula — just honest bookkeeping, one supply at a time.',
        'One subtraction per supply, in order.'),
    Row('S-0998',
        'templates/help/methods.html',
        'this page picks up where that one leaves off and walks the actual arithmetic.',
        'this page gives the arithmetic.'),
    Row('S-1000',
        'templates/help/methods.html',
        'Each step removes one supply we can account for — and the order matters: you subtract the free water (rain) and the delivered water (canals) before asking what groundwater had to make up the difference.',
        'Each step removes one supply, in order: rain, then canal deliveries, then groundwater as the remainder.'),
    Row('S-1003',
        'templates/help/methods.html',
        'Rain that actually soaked in and was available to the crop — not every drop that fell, just the share the plants could use.',
        'Rainfall available to the crop, not the total that fell.'),
    Row('S-1006',
        'templates/help/methods.html',
        'What the crop drank from that delivery comes off the demand next.',
        'The consumed share of that delivery comes off the demand next.'),
    Row('S-1011 + S-1012',
        'templates/help/methods.html',
        "The platform writes that leftover as a groundwater figure where a well exists, and as unmet demand (the crop wanted more than it got) where one doesn't. It never invents pumping out of a missing meter.",
        'Where a well exists the leftover is written as groundwater; where none does, as unmet demand. A missing meter yields no pumping figure.'),
    Row('S-1018 + S-1019',
        'templates/help/methods.html',
        "A water district holds one water right and delivers canal water to dozens of farms — but the canal isn't metered field by field. All the district knows is the total it sent down the ditch.",
        'Districts hold one water right and deliver canal water to many farms; the canal is not metered per field, so only the total delivered is known.'),
    Row('S-1023',
        'templates/help/methods.html',
        'A fallow field is credited the same as a thirsty vineyard — so water lands on fields that never used it, and the fields that did go short.',
        'A fallow field is credited the same as a vineyard: fields that used no water are credited, and fields that did are short.'),
    Row('S-1025 + S-1026 + S-1027',
        'templates/help/methods.html',
        "Each field's share tracks what its crop actually drank that month. The thirsty summer crop draws the larger share; the fallow field draws almost none.",
        "Each field's share follows its crop's ET that month: the summer crop takes the larger share, the fallow field almost none."),
    Row('S-1030',
        'templates/help/methods.html',
        'The same logic settles a smaller, thornier case: when two or more fields share a single well or a single headgate, and only the combined pumping or diversion is known.',
        'The same method covers the smaller case: two or more fields on one well or one headgate, with only the combined pumping or diversion known.'),
    Row('S-1032',
        'templates/help/methods.html',
        "That's the same mistake as the canal — it ignores what was actually growing.",
        "That is the canal's mistake again: it ignores what was growing."),
    Row('S-1036',
        'templates/help/methods.html',
        'The total always reconciles back to what the well or headgate actually produced — the demand weights only decide how that known total is divided.',
        'The total always reconciles to what the well or headgate produced; the demand weights only divide it.'),
    Row('S-0887 + S-0888 + S-0889',
        'templates/help/budgets_allocations.html',
        "An allocation ceiling and an allocation are the same number seen from two directions. The ceiling is the whole pie — the total volume of water assigned to a management zone for a reporting period. The allocation is one account's slice of that pie, worked out from how much land the account holds in the zone.",
        "An allocation ceiling is the total volume assigned to a management zone for a reporting period. An allocation is one account's share of it, by the land the account holds in the zone."),
    Row('S-0893',
        'templates/help/budgets_allocations.html',
        'The whole pie — the total volume assigned to a zone for a period.',
        'The total volume assigned to a zone for a period.'),
    Row('S-0895',
        'templates/help/budgets_allocations.html',
        "One account's slice — the platform pro-rates the ceiling by how many use areas the account holds in the zone.",
        "One account's share: the ceiling pro-rated by the use areas the account holds in the zone."),
    Row('S-0900 + S-0901',
        'templates/help/budgets_allocations.html',
        'An acre-foot is the volume of water covering one acre to a depth of one foot — roughly a year of household use. It is the standard unit California water managers count in.',
        None),
    Row('S-0903',
        'templates/help/budgets_allocations.html',
        "A single landowner does not care about the zone's full 12,000 acre-feet — they care about their limit.",
        "A landowner's figure is the account's allocation, not the zone's 12,000 acre-feet."),
    Row('S-0907',
        'templates/help/budgets_allocations.html',
        'It trades a little precision for not breaking when data is missing.',
        None),
    Row('S-0914',
        'templates/help/budgets_allocations.html',
        'When an account pumps past its allocation, remaining goes negative — that is an overdraft, and the only thing the platform colors red.',
        'When an account pumps past its allocation, remaining goes negative: an overdraft, the one figure the platform colors red.'),
    Row('S-0916',
        'templates/help/budgets_allocations.html',
        '"No ceiling defined" and "a ceiling of zero" are deliberately different: the platform will not imply a limit nobody actually set.',
        '"No ceiling defined" and "a ceiling of zero" are different: a blank is not a limit.'),
    Row('S-1086 + S-1087',
        'templates/help/surface_deliveries.html',
        "First: of the water that reaches a field, how much does the crop actually drink, and how much soaks back down into the aquifer? Second: if a district doesn't use all the surface water it was entitled to in a year, does the leftover carry into next year or disappear?",
        "First, what share of a delivery the crop consumes. Second, whether a district's unused surface water carries into the next year or expires."),
    Row('S-1090 + S-1091 + S-1092',
        'templates/help/surface_deliveries.html',
        'Not every drop delivered to a field is "used up." A crop drinks part of the water; the rest sinks past the roots and recharges the aquifer underneath. This setting is that share — the percentage of delivered water the crop actually consumes.',
        'This setting is the share of a delivery the crop consumes; the rest is counted as recharge.'),
    Row('S-1094 + S-1095',
        'templates/help/surface_deliveries.html',
        "Why it matters: the platform splits a district's total monthly delivery across its farms by how thirsty each crop is that month. A field growing a thirsty summer crop pulls a larger share than a fallow or low-water field next door.",
        "Why it matters: the platform splits a district's monthly delivery across its fields by each field's ET that month, so a summer crop takes a larger share than a fallow field."),
    Row('S-1100',
        'templates/help/surface_deliveries.html',
        'The unused amount opens next year as a credit the district can draw on — a surplus banks instead of vanishing.',
        'The unused amount carries into next year as a credit.'),
    Row('S-1101 + S-1102',
        'templates/help/surface_deliveries.html',
        'The leftover simply disappears at year-end; next year starts fresh with no bonus.',
        'The leftover expires at year-end; next year starts at zero.'),
    Row('S-1110',
        'templates/help/surface_deliveries.html',
        'Because they steer every future delivery calculation, change them deliberately, the same way you would the methodology.',
        'They enter every future delivery calculation; change them the way you would the methodology.'),
    Row('S-1050',
        'templates/help/settings_explained.html',
        'the deeper detail sits under its "Advanced" toggle.',
        'the detail is under its "Advanced" toggle.'),
    Row('S-1056',
        'templates/help/settings_explained.html',
        'Rarely, and deliberately — every calculation flows through this chain, so a change re-shapes past and future numbers alike.',
        'Rarely: every calculation runs through this chain, so a change alters past and future numbers.'),
    Row('S-1058',
        'templates/help/settings_explained.html',
        "Two agency-wide settings govern how canal deliveries are counted: how much of a delivery the crop actually consumes (the rest sinks past the roots and recharges the aquifer — typically around 75%), and what happens to a district's unused water at year-end (carry it forward as a credit, or let it expire).",
        "Two agency-wide settings govern how canal deliveries are counted: the share of a delivery the crop consumes (typically 75%; the rest goes to the aquifer), and what happens to a district's unused water at year-end (carried forward as a credit, or expired)."),
    Row('S-1072 + S-1073 + S-1074',
        'templates/help/settings_explained.html',
        'One system-level switch decides whether the platform\'s front door is open or locked. For this demonstration it is deliberately off — the front door is open so anyone can look around. Flipping it on is the "go-live" step a real agency takes when it\'s ready to restrict the platform to its own staff, and it\'s intentionally deferred until the demo has been evaluated.',
        "One system-level switch decides whether the platform requires sign-in. On this demonstration it is off. Turning it on restricts the platform to the agency's own staff; it stays off until the demonstration has been evaluated."),
    Row('S-0924 + S-0925 + S-0926',
        'templates/help/getting_started.html',
        'Before the steps below, it helps to know what the platform is actually computing. It measures the water your crops consumed — from satellites — and reconciles that against the water that supplied them: surface deliveries, groundwater, and rain. A few minutes on the concept makes every step that follows click into place.',
        'The platform estimates the water your crops consumed, from satellite, and reconciles it against the supplies: surface deliveries, groundwater and rain.'),
    Row('S-0931',
        'templates/help/getting_started.html',
        'The Setup Wizard draws your district boundary — the map outline every other page is built on — so start there before working the steps below.',
        'The Setup Wizard draws your district boundary, which every other page uses; start there.'),
    Row('S-0934',
        'templates/help/getting_started.html',
        "Read this page as the manual route, or as a map of what the wizard already did and what's left.",
        'This page is the manual route, and a list of what the wizard did and what is left.'),
    Row('S-0936',
        'templates/help/getting_started.html',
        'Nothing is written until you review what came back and confirm.',
        'Nothing is written until you review the results and confirm.'),
    Row('S-0953',
        'templates/help/getting_started.html',
        'An allocation ceiling is the total volume assigned to a zone for a reporting period — the policy ceiling for the whole area.',
        'An allocation ceiling is the total volume assigned to a zone for a reporting period.'),
    Row('S-0978',
        'templates/help/getting_started.html',
        "If the difference between a zone's allocation ceiling and an account's allocation is unclear, this short guide walks through how the platform turns one into the other, with a worked example.",
        "How the platform turns a zone's allocation ceiling into an account's allocation, with a worked example."),
    Row("S-0412 (S-0408's ruling)",
        'templates/accounting/methodology_settings.html',
        "reorder, enable/disable, and edit each step's knobs",
        "reorder, enable or disable, and set each step's parameters"),
    # Twin sites found by this guard's own first run against HEAD (the same
    # sentence, or the same rule-7 word, at a second address the sweep did not
    # list). Applied under the same ruling, 2026-09-17, by the main session.
    Row('S-0059 [1] twin',
        'templates/help/getting_started.html',
        'how much of a delivery the crop actually uses',
        'how much of a delivery the crop uses'),
    Row('S-0030 twin (the credit)',
        'accounting/models.py',
        'Month at/after which the credit is dead, as YYYY-MM. Null = never expires.',
        'Month at or after which the credit expires, as YYYY-MM. Blank = never expires.'),
    Row('S-0087 twin (the form label)',
        'core/forms.py',
        'Share of delivered water the crop actually consumes',
        'Share of delivered water the crop consumes'),
    Row('S-0557 twin (the list header)',
        'templates/datasync/partials/_station_list_results.html',
        'Whether this station is wired up for scheduled data pulls.',
        'Whether scheduled syncs include this station.'),
    Row('S-0557 twin (the filter)',
        'templates/datasync/station_list.html',
        'Whether this station is wired up for scheduled data pulls. Nothing to do with how recently it published.',
        'Whether scheduled syncs include this station. Freshness (how recently it reported) is the dot.'),
    Row('S-0936 twin',
        'templates/drinking/onboard.html',
        'Nothing is written until you review what came back and confirm.',
        'Nothing is written until you review the results and confirm.'),
]

PLACEHOLDER = re.compile(r"<x>|\[(?:if|elif|else|endif|for|endfor|empty)\]|…")
_PY_JOIN = re.compile(r'"\s*\n\s*f?"')


_VISIBLE_ATTR = re.compile(r"""\b(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)\"""")


def collapse(text: str, python: bool = False) -> str:
    """Whitespace collapsed, entities unescaped, quotes straightened, Django
    tags and figures dropped, HTML tags dropped (a `title=` or `placeholder=`
    a reader sees is kept as text), no space before punctuation."""
    if python:
        text = _PY_JOIN.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", " ", text, flags=re.S)
    if not python:
        text = _VISIBLE_ATTR.sub(lambda m: "> " + m.group(1) + " <", text)
        text = re.sub(r"<[^>]+>", " ", text)
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(a, b)
    text = " ".join(text.split())
    return re.sub(r"\s+([,.;:)])", r"\1", text)


def fragments(sentence: str) -> list:
    """The checkable pieces of a sentence: the text between figures."""
    return [f.strip(" ,;:.\"") for f in PLACEHOLDER.split(sentence)
            if len(f.strip(" ,;:.\"")) >= 12]


def _file_text(path: str) -> str:
    p = REPO_ROOT / path
    return collapse(p.read_text(), python=path.endswith(".py"))


def product_files() -> list:
    files = list(TEMPLATES.rglob("*.html"))
    for p in REPO_ROOT.rglob("*.py"):
        rel = p.relative_to(REPO_ROOT)
        if rel.parts[0] in {"tests", ".venv", "audit", "scripts", "docs", "staticfiles",
                            "static", "media", "logs", ".planning"}:
            continue
        if "migrations" in rel.parts:
            continue
        files.append(p)
    return files


def struck_probe(row: Row) -> str:
    """A 40-character window of the struck sentence that the settled one does
    not contain, so a row whose two sentences share an opening still tests the
    words that went. Fragments (the text between figures) that survive whole
    in the settled sentence are skipped; the window then slides from the
    fragment's start, and falls back to its tail."""
    if row.probe:
        return collapse(row.probe)
    settled = collapse(row.settled or "")
    for fragment in fragments(row.struck) or [row.struck]:
        struck = collapse(fragment)
        if struck in settled or len(struck) < 25:
            continue
        tail = struck[-40:]
        if tail not in settled:
            return tail  # the words that went are usually the sentence's end
        for start in range(0, len(struck) - 40 + 1, 4):
            window = struck[start:start + 40]
            if window not in settled:
                return window
    return collapse(row.struck)[:40]


IDS = [f"{r.id} · {Path(r.path).name}" for r in SETTLED]


@pytest.mark.parametrize("row", SETTLED, ids=IDS)
def test_the_settled_sentence_is_in_its_file(row):
    if row.settled is None:
        pytest.skip("struck outright; test 2 covers it")
    text = _file_text(row.path)
    missing = [collapse(f) for f in fragments(row.settled) if collapse(f) not in text]
    assert not missing, (
        f"{row.id}: {row.path} no longer carries the settled words {missing!r}. "
        f"Brent ruled these words on 2026-09-17; change them only with a new ruling "
        f"and its date in this table."
    )


@pytest.fixture(scope="module")
def product_text():
    return {str(p.relative_to(REPO_ROOT)): collapse(p.read_text(), python=p.suffix == ".py")
            for p in product_files()}


@pytest.mark.parametrize("row", SETTLED, ids=IDS)
def test_the_struck_sentence_is_gone_from_the_product(row, product_text):
    probe = struck_probe(row)
    where = [p for p, t in product_text.items() if probe in t]
    assert not where, (
        f"{row.id}: the struck words {probe!r} are back in {where}. They were "
        f"ruled out on 2026-09-17 (143.1-01)."
    )


@pytest.mark.parametrize("row", SETTLED, ids=IDS)
def test_every_settled_sentence_scans_clean(row):
    if row.settled is None:
        pytest.skip("struck outright")
    offences = scan(row.settled.replace("<x>", "X"))
    assert not offences, (
        f"{row.id}: the settled sentence explains the water (copy rule 11): "
        f"{[str(o) for o in offences]}"
    )
