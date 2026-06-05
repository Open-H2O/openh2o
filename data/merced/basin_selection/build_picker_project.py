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
  - candidate_basins on top: the full DWR crop-field canvas, colored by crop,
    semi-transparent over satellite, click-to-tag. Tag the fields that become
    recharge basins with:
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

# Same crop palette as the parcel picker, so the candidate canvas reads the way
# the crop pick did. Untagged fields show their crop color; tagged ones glow gold.
CLASS_COLORS = {
    "Deciduous fruits & nuts": "#c8902f", "Field crops": "#e8c63a",
    "Truck/nursery/berry": "#7fb069", "Grain & hay": "#d4b483",
    "Pasture": "#5f8d4e", "Vineyard": "#b048c8", "Rice": "#3a9cc5",
    "Citrus & subtropical": "#e07a1f", "Idle": "#9aa0a6",
    "Fallow/unclassified": "#c98b6b", "Other": "#8899aa",
}
FILL_ALPHA = 150  # opaque enough to read crop color over satellite imagery


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
    canals = vlayer("canals", "Canals (feed option — read the name)")
    rivers = vlayer("rivers", "Rivers (feed option — read the name)")
    diversions = vlayer("diversions", "Diversion headgates (where surface water is pulled)")
    existing = vlayer("existing_basins", "Existing v1.9 basins (reference — being replaced)")
    cand = vlayer("candidate_basins", "Candidate basins — CLICK TO TAG")

    # --- styling ---
    sub_sym = QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ffd400", "outline_width": "0.8"})
    subbasin.setRenderer(QgsSingleSymbolRenderer(sub_sym))

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

    # Candidate footprints, rule-based so each field draws once: a TAGGED field
    # (feeds_via set) glows gold with a bold white edge; every other field shows
    # its crop color (semi-transparent over satellite) so the whole pickable
    # canvas is visible — exactly the quilt the crop pick presented.
    Rule = QgsRuleBasedRenderer.Rule
    root = Rule(None)
    tagged = QgsFillSymbol.createSimple(
        {"color": _rgba("#ffd400", 200), "outline_color": "#ffffff",
         "outline_width": "0.8"})
    root.appendChild(Rule(tagged, 0, 0, "\"feeds_via\" IS NOT NULL AND \"feeds_via\" <> ''",
                          "▣ Tagged as recharge basin"))
    for cls, hexcol in CLASS_COLORS.items():
        sym = QgsFillSymbol.createSimple(
            {"color": _rgba(hexcol, FILL_ALPHA), "outline_color": "#1a1d21",
             "outline_width": "0.1"})
        root.appendChild(Rule(
            sym, 0, 0,
            f"(\"feeds_via\" IS NULL OR \"feeds_via\" = '') AND \"crop_class\" = '{cls}'",
            cls))
    # Catch-all so a field with an unmapped crop_class still draws (never invisible).
    other = QgsFillSymbol.createSimple(
        {"color": _rgba("#8899aa", FILL_ALPHA), "outline_color": "#1a1d21",
         "outline_width": "0.1"})
    root.appendChild(Rule(other, 0, 0, "ELSE", "Other crop"))
    cand.setRenderer(QgsRuleBasedRenderer(root))

    # --- add bottom-up; candidate_basins last so it sits on top & is clickable ---
    for lyr in (sat, subbasin, canals, rivers, diversions, existing, cand):
        proj.addMapLayer(lyr)

    proj.write(OUT)
    print(f"wrote {OUT}")
    print(f"layers: {[l.name() for l in proj.mapLayers().values()]}")
    app.exitQgis()


if __name__ == "__main__":
    main()
