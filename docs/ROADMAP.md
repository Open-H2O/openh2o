<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Roadmap

This page lists the parts of OpenH2O that are finished, the work that is planned, and
ideas that have not been started. The [README](../README.md) describes everything
OpenH2O does today.

OpenH2O keeps an organization's water records and calculates its water accounts. A
feature that writes figures in California's reporting format is under development
and switched off by default. OpenH2O does not submit reports to the state.

## Finished

These parts of OpenH2O are built and tested. Each one ends with a link to its code.

- **The monthly calculation.** For each field and month, OpenH2O starts from
  OpenET's satellite estimate of crop water use (0 in a month the field is marked fallow) and
  subtracts the rain and the canal water the crop could use. On a field with a well and no meter volume for the
  month, what is left is the groundwater consumed that month. Where a well's meter
  volume for the month is on the ledger, OpenH2O uses that volume. The code is in
  [`accounting/steps.py`](../accounting/steps.py),
  [`accounting/calculation.py`](../accounting/calculation.py) and
  [`accounting/services.py`](../accounting/services.py).
- **Carry-over between water years.** At the end of a water year, OpenH2O carries
  each zone's unused groundwater allocation, and each water account's own remainder,
  into the next water year as a credit, unless the
  Delivery Settings page, or the zone's own page, is set to let unused allocation
  expire. A zone's own choice overrides the Delivery Settings page. OpenH2O always
  carries an overdrawn allocation into the next water year as a debt, whichever
  choice is set. The code is in [`accounting/models.py`](../accounting/models.py)
  [`accounting/carryover_math.py`](../accounting/carryover_math.py) and
  [`accounting/management/commands/rollover_allocations.py`](../accounting/management/commands/rollover_allocations.py).
- **Dividing a canal delivery among fields.** OpenH2O keeps each headgate's delivery
  as one monthly total. It subtracts the canal's losses and any delivery recorded
  for an individual field, then divides the remainder among the other fields by the
  shares entered on the point of diversion, or by acreage where none is entered. A
  headgate set to divide by crop ET instead divides in proportion to each field's
  ETAW, caps each field at its ETAW divided by its irrigation efficiency,
  records any water left over against the headgate, and uses the shares in a month
  when no field has any ETAW. A point of diversion that does not serve a field
  does not divide its water: what is left after the canal's losses appears on its page as delivered to
  the recharge site it feeds, or to no field, and is credited to no one. The code is in
  [`accounting/allocation_math.py`](../accounting/allocation_math.py) and
  [`surface/services.py`](../surface/services.py).
- **A permanent web address for each record.** Each boundary, zone, use area, well,
  point of diversion, recharge site, monitoring station, water system, facility,
  sampling point and water right has a permanent web address on its OpenH2O
  site, such as `/id/well/12/`. A browser that opens the address shows the record's
  page. Another program that requests the same address receives the record's
  details as JSON-LD, a machine-readable format. Geoconnex, the Internet of Water's
  national index of water features, can list these addresses once an organization
  registers them, and [DATA-STANDARDS.md](DATA-STANDARDS.md) gives the steps. The
  code is in [`core/identifiers.py`](../core/identifiers.py).

## Planned: monthly volumes from meter readings

Meter readings arrive on irregular dates. OpenH2O stores each reading, and the code is
in [`measurements/models.py`](../measurements/models.py). Today a person enters each
meter's monthly volume on the ledger, by typing it or importing a file, or enters
readings on a well, and the month's calculation divides the volume of the readings
dated in that month among the well's fields. The
planned step would turn a meter's readings into monthly volumes by spreading the
water measured from one reading to the next over the days in between.

## Planned: publishing open data

OpenH2O maps every measurement it stores or receives to one shared vocabulary, which
[DATA-STANDARDS.md](DATA-STANDARDS.md) describes. The work still to do is publishing
the data in three open formats at web addresses where other systems can read it:

- **OGC SensorThings API**, the Open Geospatial Consortium's standard web interface
  for sensor data, which any compliant program can read.
- **Frictionless Data Package**, a set of data files together with a file that
  describes them.
- **WaDE 2.0**, the Western States Water Council's Water Data Exchange format.

## Ideas not yet started

- A form on which a landowner reports their own monthly water use.
- A statement for each account that shows its water use against its allocation.
- Project records for land fallowing and land repurposing.
- A warning when satellite imagery covers only part of a parcel.
