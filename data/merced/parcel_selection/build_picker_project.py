# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Assemble the Merced parcel-picker QGIS project (.qgz).

Run via the bundle-python launcher (build_picker_project.sh), which supplies
the QGIS environment. Produces merced_parcel_picker.qgz pointing at the
sibling merced_parcel_picker.gpkg, with:
  - Esri World Imagery satellite basemap (bottom)
  - subbasin outline, named canals (labelled), diversion headgates (labelled)
  - crop_fields on top: categorized by crop class, semi-transparent so the
    satellite shows through, with two click-to-fill dropdowns:
      served_by    -> which diversion headgate feeds this field
      water_source -> surface / groundwater / conjunctive
"""
import os
import sys

from qgis.core import (
    QgsApplication, QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsCoordinateReferenceSystem, QgsEditorWidgetSetup,
    QgsSymbol, QgsRendererCategory, QgsCategorizedSymbolRenderer,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer, QgsPalLayerSettings, QgsTextFormat,
    QgsVectorLayerSimpleLabeling, QgsTextBufferSettings, QgsMarkerSymbol,
    QgsLineSymbol, QgsFillSymbol,
)
from qgis.PyQt.QtGui import QColor, QFont

HERE = os.path.dirname(os.path.abspath(__file__))
GPKG = os.path.join(HERE, "merced_parcel_picker.gpkg")
OUT = os.path.join(HERE, "merced_parcel_picker.qgz")

# served_by dropdown: friendly label -> stored POD code (what the ingest reads).
SERVED_BY = [
    {"— none (groundwater-only / unserved) —": ""},
    {"Atwater Canal (MID)": "MER-POD-004"},
    {"Le Grand Canal": "MER-POD-005"},
    {"Stevinson — Diversion Canal": "MER-POD-006"},
    {"Plainsburg — El Nido Canal": "MER-POD-007"},
    {"Crocker-Huffman (Merced River)": "MER-POD-008"},
    {"Bottomlands riparian (Merced River)": "MER-POD-009"},
]
WATER_SOURCE = [
    {"— none —": ""},
    {"Surface (canal only)": "surface"},
    {"Groundwater (well only)": "groundwater"},
    {"Conjunctive (canal + well)": "conjunctive"},
]
# Distinct fill per readable crop class. "Other" catches anything unmapped
# so the categorized renderer never leaves a field invisible.
CLASS_COLORS = {
    "Deciduous fruits & nuts": "#c8902f", "Field crops": "#e8c63a",
    "Truck/nursery/berry": "#7fb069", "Grain & hay": "#d4b483",
    "Pasture": "#5f8d4e", "Vineyard": "#b048c8", "Rice": "#3a9cc5",
    "Citrus & subtropical": "#e07a1f", "Idle": "#9aa0a6",
    "Fallow/unclassified": "#c98b6b", "Other": "#8899aa",
}
FILL_ALPHA = 155  # opaque enough to read crop color over satellite imagery

# Progress symbology: tagged fields light up by the headgate they serve, so
# Brent can see what's done and where the gaps are. (code, color, label)
HEADGATE_STYLE = [
    ("MER-POD-004", "#ff4d4d", "▣ Atwater Canal (MID)"),
    ("MER-POD-005", "#ff9e1b", "▣ Le Grand Canal"),
    ("MER-POD-006", "#ffe14d", "▣ Stevinson — Diversion Canal"),
    ("MER-POD-007", "#7CFC00", "▣ Plainsburg — El Nido Canal"),
    ("MER-POD-008", "#23d5e0", "▣ Crocker-Huffman (Merced R.)"),
    ("MER-POD-009", "#e879f9", "▣ Bottomlands (Merced R.)"),
]


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


def main():
    QgsApplication.setPrefixPath(
        "/Applications/QGIS-final-4_0_1.app/Contents/MacOS", True)
    app = QgsApplication([], False)
    app.initQgis()

    proj = QgsProject.instance()
    proj.clear()
    proj.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    proj.setTitle("Merced Parcel Picker — select fields each diversion serves")

    # --- basemap (bottom) ---
    # Use a GDAL TMS service description, NOT the 'wms'/xyz provider: the wms
    # provider plugin isn't loaded in the headless build env, so an xyz layer
    # would be invalid at save time and get dropped on reload (the white-map
    # bug). The GDAL provider IS available, validates cleanly, and renders the
    # same Esri World Imagery tiles in the GUI.
    sat_xml = os.path.join(HERE, "esri_world_imagery.xml")
    sat = QgsRasterLayer(sat_xml, "Satellite (Esri World Imagery)", "gdal")
    if not sat.isValid():
        sys.exit("FATAL: satellite (gdal TMS) invalid: "
                 + sat.error().summary())

    subbasin = vlayer("subbasin", "Merced Subbasin (boundary)")
    canals = vlayer("canals", "Canals & rivers")
    diversions = vlayer("diversions", "Diversion headgates")
    fields = vlayer("crop_fields", "Crop fields — CLICK TO SELECT")

    # --- styling ---
    sub_sym = QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ffd400", "outline_width": "0.8"})
    subbasin.setRenderer(QgsSingleSymbolRenderer(sub_sym))

    canal_sym = QgsLineSymbol.createSimple({"color": "#23b5d3", "width": "0.9"})
    canals.setRenderer(QgsSingleSymbolRenderer(canal_sym))
    label_with(canals, "name", 9, "#9fe7f5")

    div_sym = QgsMarkerSymbol.createSimple(
        {"name": "star", "color": "#ffd400", "outline_color": "#000000",
         "size": "5"})
    diversions.setRenderer(QgsSingleSymbolRenderer(div_sym))
    label_with(diversions, "name", 10, "#ffe98a")

    # Rule-based "progress" symbology. Rules are mutually exclusive so each
    # field draws once: assigned fields glow in their headgate color with a
    # bold white edge; groundwater-only fields get their own bucket; untouched
    # fields fade to faint gray (satellite still shows the crop underneath).
    Rule = QgsRuleBasedRenderer.Rule
    root = Rule(None)

    def add_rule(symbol, expr, label):
        root.appendChild(Rule(symbol, 0, 0, expr, label))

    for code, hexcol, label in HEADGATE_STYLE:
        s = QgsFillSymbol.createSimple(
            {"color": _rgba(hexcol, 185), "outline_color": "#ffffff",
             "outline_width": "0.5"})
        add_rule(s, f"\"served_by\" = '{code}'", label)

    gw = QgsFillSymbol.createSimple(
        {"color": _rgba("#39c0ff", 185), "outline_color": "#ffffff",
         "outline_width": "0.5"})
    add_rule(
        gw,
        "(\"served_by\" IS NULL OR \"served_by\" = '') "
        "AND \"water_source\" IS NOT NULL AND \"water_source\" <> ''",
        "▣ Groundwater-only (well)",
    )

    untouched = QgsFillSymbol.createSimple(
        {"color": _rgba("#9aa6b2", 38), "outline_color": "#6b7785",
         "outline_width": "0.1"})
    add_rule(
        untouched,
        "(\"served_by\" IS NULL OR \"served_by\" = '') "
        "AND (\"water_source\" IS NULL OR \"water_source\" = '')",
        "· Unassigned field (pick from these)",
    )
    fields.setRenderer(QgsRuleBasedRenderer(root))

    # --- editor dropdowns on the crop layer ---
    f = fields.fields()
    fields.setEditorWidgetSetup(
        f.indexOf("served_by"),
        QgsEditorWidgetSetup("ValueMap", {"map": SERVED_BY}))
    fields.setEditorWidgetSetup(
        f.indexOf("water_source"),
        QgsEditorWidgetSetup("ValueMap", {"map": WATER_SOURCE}))

    # --- add bottom-up; crop fields last so they sit on top & are clickable ---
    for lyr in (sat, subbasin, canals, diversions, fields):
        proj.addMapLayer(lyr)

    proj.write(OUT)
    print(f"wrote {OUT}")
    print(f"layers: {[l.name() for l in proj.mapLayers().values()]}")
    app.exitQgis()


def _rgba(hexcol, alpha):
    c = QColor(hexcol)
    return f"{c.red()},{c.green()},{c.blue()},{alpha}"


if __name__ == "__main__":
    main()
