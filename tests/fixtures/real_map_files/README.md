# Real map files

Small files cut from real public exports, so the map-file readers are tested against what agencies and
GIS tools actually write, not only hand-drawn squares. Each was downloaded on 2026-11-02. Where a file
was changed, only `ogr2ogr` column selection, a filter, a reprojection, a simplification or the removal
of one member of a zip was used, as named below. No file carries a person's name or an address.

| File | From | Terms | What was changed | What it tests |
|---|---|---|---|---|
| `central_sj_wcd_gsa.zip` | California Department of Water Resources, i03 Groundwater Sustainability Agencies (gis.data.cnra.ca.gov item `51688234e6104427894328acee4983e8`) | CC BY; "No restrictions on public use" | One agency (GSA_ID 189, Central San Joaquin Water Conservation District GSA); columns GSA_ID, GSA_Name, Basin_Subb | A district boundary in Web Mercator (EPSG 3857) |
| `central_sj_wcd_gsa_no_prj.zip` | As above | As above | The same zip without its `.prj` | A shapefile zip missing its projection |
| `central_sj_wcd_gsa_esri_prj.zip` | As above | As above | Reprojected to California zone 3 (US feet); its `.prj` is written in Esri's form with no EPSG code, as Esri tools write it | A `.prj` GDAL cannot match to an EPSG code |
| `sj_valley_subbasins_2227.zip` | DWR, i08 B118 CA Groundwater Basins (item `49807a1fbc584631bdf88d9ca71dd083`) | CC BY; "No restrictions on public use" | Five San Joaquin Valley subbasins (5-022.01 to .04, .16); reprojected to EPSG 2227 (California zone 3, US feet); simplified at 150 ft; columns Basin_Subb, Basin_Su_1 | A State Plane shapefile; one outline with a hole; one in two parts |
| `sj_valley_subbasins_names.kml` | As above | As above | The same five subbasins as KML with only a Name; simplified at 45 m | A KML whose outlines carry only names |
| `wbd_20_several_shapefiles.zip` | USGS Watershed Boundary Dataset, region 20 (`WBD_20_HU2_Shape.zip`) | USGS, public domain | Seven of its thirteen shapefiles kept, unchanged, in their `Shape/` folder (six are empty) | A zip holding several shapefiles, the first empty |
| `wbd_20_hu8.zip` | As above | As above | `WBDHU8` only, unchanged | Outlines in Hawaii, in NAD83 (EPSG 4269) |
| `us_watersheds_two_layers.kml.gz` | USGS EDNA, Major US Watersheds (`USWatersheds.kml`) | USGS, public domain | Unchanged, gzipped (a test unzips it to a temporary `.kml`) | A KML with two layers, points and lines, no outlines |
