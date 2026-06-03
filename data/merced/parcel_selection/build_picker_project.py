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
    {"— none / not served —": ""},
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
# Distinct fill per readable crop class.
CLASS_COLORS = {
    "Deciduous fruits & nuts": "#8c6d31", "Field crops": "#c9a227",
    "Truck/nursery/berry": "#7fb069", "Grain & hay": "#d4b483",
    "Pasture": "#5f8d4e", "Vineyard": "#7b2d8e", "Rice": "#3a7ca5",
    "Citrus & subtropical": "#e07a1f", "Idle": "#777777",
    "Fallow/unclassified": "#555555",
}


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
    xyz = (
        "type=xyz&zmin=0&zmax=19&url=https://server.arcgisonline.com/"
        "ArcGIS/rest/services/World_Imagery/MapServer/tile/"
        "%7Bz%7D/%7By%7D/%7Bx%7D"
    )
    sat = QgsRasterLayer(xyz, "Satellite (Esri World Imagery)", "wms")
    # XYZ tile layers often report invalid in offscreen/headless QGIS because
    # no validation tile can be fetched without the GUI network stack. The
    # layer renders fine once opened with network, so add it regardless.
    if not sat.isValid():
        print("note: satellite reports invalid headless (expected) — adding anyway")

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

    cats = []
    for cls, hexcol in CLASS_COLORS.items():
        sym = QgsFillSymbol.createSimple(
            {"color": _rgba(hexcol, 90), "outline_color": "#e8edf4",
             "outline_width": "0.18"})
        cats.append(QgsRendererCategory(cls, sym, cls))
    # fallback for any unmapped class
    fallback = QgsFillSymbol.createSimple(
        {"color": _rgba("#999999", 90), "outline_color": "#e8edf4",
         "outline_width": "0.18"})
    cats.append(QgsRendererCategory("", fallback, "other"))
    fields.setRenderer(QgsCategorizedSymbolRenderer("crop_class", cats))

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
