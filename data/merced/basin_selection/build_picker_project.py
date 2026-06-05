# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Assemble the Merced basin-picker QGIS project (.qgz).

Run via the bundle-python launcher (build_picker_project.sh), which supplies
the QGIS environment. Produces merced_basin_picker.qgz pointing at the sibling
merced_basin_picker.gpkg (built first by build_basin_gpkg.py), with bottom→top:
  - Esri World Imagery satellite basemap
  - Merced Subbasin outline
  - canals (cyan, labelled) + named rivers (blue, labelled) — the feed options
  - existing v1.9 basins (magenta dashed outline, labelled) — reference only
  - agriculture: cropland as a faint red "avoid" wash (basins don't go on fields)
  - candidate_basins on top: the open non-ag parcels (teal), click-to-tag. Tag
    the parcels that become recharge basins with:
      name      -> basin name
      operator  -> operating district/GSA (optional)
      capacity_acre_feet -> design capacity hint (optional)
      feeds_via -> NAME of the canal/river that fills it (read it off the
                   labelled canal/river layers; the 62-02 seed resolves it to a
                   real Flowline) — REQUIRED for a parcel to count as a basin
"""
import os
import sys

from qgis.core import (
    QgsApplication, QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer, QgsPalLayerSettings, QgsTextFormat,
    QgsVectorLayerSimpleLabeling, QgsTextBufferSettings,
    QgsLineSymbol, QgsFillSymbol, QgsMarkerSymbol,
)
from qgis.PyQt.QtGui import QColor, QFont

HERE = os.path.dirname(os.path.abspath(__file__))
GPKG = os.path.join(HERE, "merced_basin_picker.gpkg")
OUT = os.path.join(HERE, "merced_basin_picker.qgz")


def vlayer(name, label):
    lyr = QgsVectorLayer(f"{GPKG}|layername={name}", label, "ogr")
    if not lyr.isValid():
        sys.exit(f"FATAL: layer {name} invalid")
    return lyr


def label_with(layer, field, size, color):
    s = QgsPalLayerSettings()
    s.fieldName = field
    s.enabled = True
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Helvetica", size))
    fmt.setSize(size)
    fmt.setColor(QColor(color))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor("#000000"))
    fmt.setBuffer(buf)
    s.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)


def _rgba(hexcol, alpha):
    c = QColor(hexcol)
    return f"{c.red()},{c.green()},{c.blue()},{alpha}"


def main():
    QgsApplication.setPrefixPath(
        "/Applications/QGIS-final-4_0_1.app/Contents/MacOS", True)
    app = QgsApplication([], False)
    app.initQgis()

    proj = QgsProject.instance()
    proj.clear()
    proj.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    proj.setTitle("Merced Basin Picker — tag the parcels that become recharge basins")

    # --- basemap (bottom). GDAL TMS service description, NOT the wms/xyz
    # provider: the wms plugin isn't loaded headless, so an xyz layer would be
    # invalid at save and dropped on reload (the white-map bug). ---
    sat_xml = os.path.join(HERE, "esri_world_imagery.xml")
    sat = QgsRasterLayer(sat_xml, "Satellite (Esri World Imagery)", "gdal")
    if not sat.isValid():
        sys.exit("FATAL: satellite (gdal TMS) invalid: " + sat.error().summary())

    subbasin = vlayer("subbasin", "Merced Subbasin (boundary)")
    agri = vlayer("agriculture", "Agriculture — basins do NOT go here")
    canals = vlayer("canals", "Canals (feed option — read the name)")
    rivers = vlayer("rivers", "Rivers (feed option — read the name)")
    diversions = vlayer("diversions", "Diversion headgates (where surface water is pulled)")
    existing = vlayer("existing_basins", "Existing v1.9 basins (reference — being replaced)")
    cand = vlayer("candidate_basins", "Open non-ag parcels — CLICK TO TAG")

    # --- styling ---
    sub_sym = QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ffd400", "outline_width": "0.8"})
    subbasin.setRenderer(QgsSingleSymbolRenderer(sub_sym))

    # Agriculture overlay — a faint red wash marking cropland (basins do NOT go
    # here). Translucent so the satellite + parcel edges still read underneath.
    ag_sym = QgsFillSymbol.createSimple(
        {"color": _rgba("#d2424a", 70), "outline_color": "#d2424a",
         "outline_width": "0.05"})
    agri.setRenderer(QgsSingleSymbolRenderer(ag_sym))

    canal_sym = QgsLineSymbol.createSimple({"color": "#23b5d3", "width": "0.7"})
    canals.setRenderer(QgsSingleSymbolRenderer(canal_sym))
    label_with(canals, "name", 8, "#9fe7f5")

    river_sym = QgsLineSymbol.createSimple({"color": "#5b8def", "width": "0.9"})
    rivers.setRenderer(QgsSingleSymbolRenderer(river_sym))
    label_with(rivers, "name", 8, "#bcd0ff")

    # Diversion headgates: gold stars marking where each surface right pulls
    # water off its canal/river. A basin plausibly sits where a labelled canal
    # or river (ideally near one of these takes) can flood it.
    div_sym = QgsMarkerSymbol.createSimple(
        {"name": "star", "color": "#ffd400", "outline_color": "#000000",
         "size": "5"})
    diversions.setRenderer(QgsSingleSymbolRenderer(div_sym))
    label_with(diversions, "stream_name", 9, "#ffe98a")

    # Existing basins: hollow magenta dashed outline so they read as "reference,
    # not a choice" against the candidate footprints.
    ex_sym = QgsFillSymbol.createSimple(
        {"color": _rgba("#e879f9", 30), "outline_color": "#e879f9",
         "outline_width": "0.6", "outline_style": "dash"})
    existing.setRenderer(QgsSingleSymbolRenderer(ex_sym))
    label_with(existing, "name", 9, "#f5c2ff")

    # Candidate parcels, rule-based so each draws once: a TAGGED parcel
    # (feeds_via set) glows gold with a bold white edge; every untagged open
    # parcel is a bright translucent teal so the pickable land is obvious over
    # satellite (and clearly distinct from the red cropland).
    Rule = QgsRuleBasedRenderer.Rule
    root = Rule(None)
    tagged = QgsFillSymbol.createSimple(
        {"color": _rgba("#ffd400", 205), "outline_color": "#ffffff",
         "outline_width": "0.8"})
    root.appendChild(Rule(tagged, 0, 0, "\"feeds_via\" IS NOT NULL AND \"feeds_via\" <> ''",
                          "▣ Tagged as recharge basin"))
    pick = QgsFillSymbol.createSimple(
        {"color": _rgba("#2bd4c4", 130), "outline_color": "#eafffb",
         "outline_width": "0.3"})
    root.appendChild(Rule(pick, 0, 0, "ELSE", "Open non-ag parcel (pick basins here)"))
    cand.setRenderer(QgsRuleBasedRenderer(root))

    # --- add bottom-up; candidate_basins last so it sits on top & is clickable ---
    for lyr in (sat, subbasin, agri, canals, rivers, diversions, existing, cand):
        proj.addMapLayer(lyr)

    proj.write(OUT)
    print(f"wrote {OUT}")
    print(f"layers: {[l.name() for l in proj.mapLayers().values()]}")
    app.exitQgis()


if __name__ == "__main__":
    main()
