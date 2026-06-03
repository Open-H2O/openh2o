/* map-core.js — OpenH2O shared cartographic toolkit (single source of truth)
   Loaded on every page that renders a MapLibre map, BEFORE map-engine.js or any
   inline detail-map script. Extends window.OH2O with:
     - colors            entity color palette
     - entities          per-entity symbology + zoom-dependent label specs
     - basemapStyle()    combined dark-vector + aerial-raster MapLibre style
     - switchBasemap()   toggle dark <-> aerial without rebuilding the map
     - pointPaint/glowPaint/makeLabelLayer  reusable layer generators
   Dark basemap is a recolored OpenFreeMap (OpenMapTiles schema) vector style,
   keyless and unlimited, fonts+sprites served by OpenFreeMap. Aerial is Esri. */
(function () {
'use strict';
var OH2O = window.OH2O = window.OH2O || {};

/* ── Entity color palette ─────────────────────────────────────────────── */
OH2O.colors = {
    gold: '#E4A317', teal: '#4ECDC4', purple: '#7B68EE', red: '#FF6B6B',
    blue: '#1B7FAF', blueBright: '#3DB4E0', green: '#52b788', boundary: '#E4A317',
    // Hydrography strokes — the GIS hydrology house style (Pit River ACP / NHD
    // maps): cyan natural channels, mint-green man-made canals, both solid, width
    // carrying stream order. Bright solid lines read over the aerial basemap and
    // against the muted translucent green GSA zone fills.
    river: '#45d0e8', canal: '#7ee8a0',
    // Dark casing drawn beneath the mint canal so it lifts off green farm fields.
    hydroCasing: '#06140e'
};

OH2O.FONT = ['Noto Sans Regular'];
OH2O.GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
OH2O.SPRITE = 'https://tiles.openfreemap.org/sprites/ofm_f384/ofm';

/* ── Per-entity symbology + label rules ───────────────────────────────────
   color  : marker / accent color
   rampLo/rampHi : circle radius at zoom 9 and zoom 16 (interpolated)
   labelField : MapLibre expression for the label text
   labelMin   : zoom at which the label fades in (zoom-dependent labels) */
OH2O.entities = {
    well:    { color: OH2O.colors.gold,   rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','name'], ['get','well_registration_id'], 'Well'] },
    pod:     { color: OH2O.colors.teal,   rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','name'], 'POD'] },
    station: { color: OH2O.colors.red,    rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','station_name'], ['get','external_station_id'], 'Station'] },
    recharge:{ color: OH2O.colors.purple, rampLo: 4.5, rampHi: 10,  labelMin: 10.5,
               labelField: ['coalesce', ['get','name'], ['get','site_type'], 'Recharge'] },
    parcel:  { color: OH2O.colors.blue,   labelMin: 10.5,
               labelField: ['get','parcel_number'] },
    zone:    { color: OH2O.colors.green,  labelMin: 9,
               labelField: ['get','name'] },
    boundary:{ color: OH2O.colors.gold,   labelMin: 8,
               labelField: ['get','name'] },
    hydrography:{ color: OH2O.colors.river, labelMin: 11,
               labelField: ['coalesce', ['get','name'], ['get','feature_type'], 'Waterway'] }
};

/* zoom-interpolated radius for point markers */
function ramp(lo, hi) {
    return ['interpolate', ['linear'], ['zoom'], 9, lo, 13, (lo+hi)/2, 16, hi];
}

/* solid marker paint: filled circle + crisp ring that reads on dark AND aerial */
OH2O.pointPaint = function (key, over) {
    var e = OH2O.entities[key] || { color: '#fff', rampLo: 4, rampHi: 8 };
    return Object.assign({
        'circle-radius': ramp(e.rampLo || 4, e.rampHi || 8),
        'circle-color': e.color,
        'circle-stroke-width': 1.6,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-opacity': 0.92,
        'circle-pitch-alignment': 'map'
    }, over || {});
};

/* soft glow halo placed UNDER the marker — gives depth, separates from busy imagery */
OH2O.glowPaint = function (key) {
    var e = OH2O.entities[key] || { color: '#fff', rampHi: 8 };
    return {
        'circle-radius': ramp((e.rampLo||4)*2, (e.rampHi||8)*2.1),
        'circle-color': e.color,
        'circle-opacity': 0.18,
        'circle-blur': 0.9
    };
};

OH2O.labelPaint = function () {
    return {
        'text-color': '#e8edf4',
        'text-halo-color': '#040608',
        'text-halo-width': 1.5,
        'text-halo-blur': 0.4
    };
};

/* full symbol layer for a zoom-dependent point label */
OH2O.makeLabelLayer = function (id, source, key, opts) {
    opts = opts || {};
    var e = OH2O.entities[key] || {};
    var def = {
        id: id, type: 'symbol', source: source,
        minzoom: opts.minzoom != null ? opts.minzoom : (e.labelMin || 13),
        layout: Object.assign({
            'text-field': opts.field || e.labelField || ['get', 'name'],
            'text-font': OH2O.FONT,
            'text-size': ['interpolate', ['linear'], ['zoom'], 12, 10, 16, 13],
            'text-offset': opts.offset || [0, 1.1],
            'text-anchor': opts.anchor || 'top',
            'text-optional': true,
            'text-allow-overlap': false,
            'text-padding': 4,
            'symbol-sort-key': opts.sortKey || 1
        }, opts.layout || {}),
        paint: OH2O.labelPaint()
    };
    if (opts.filter) def.filter = opts.filter;
    return def;
};

/* ── Detail mini-map decorators ────────────────────────────────────────────
   The seven entity detail pages each mount their own MapLibre map zoomed to a
   single feature (or a handful). These two helpers give those maps the same
   always-on label + click popup the full map has, without repeating the layer
   boilerplate in every template. Call both inside the map's 'load' handler,
   after the source + circle/fill layers are added. */

/* Always-on symbol label for a detail map. Reuses makeLabelLayer + labelPaint
   so text/halo match the full map; minzoom 0 because the map is already framed
   on the feature. Collision detection (text-allow-overlap:false) declutters a
   multi-feature map (e.g. a water right's several PODs). */
OH2O.addDetailLabel = function (map, source, key, opts) {
    opts = opts || {};
    var layer = OH2O.makeLabelLayer(
        opts.id || (source + '-label'), source, key,
        Object.assign({ minzoom: 0 }, opts)
    );
    map.addLayer(layer);
    return layer.id;
};

/* Bind a click popup (+ pointer cursor) to one or more layers. htmlFn receives
   the clicked feature's properties and returns the popup HTML. Anchors the
   popup at the click point, which reads correctly for points and polygons. */
OH2O.attachPopup = function (map, layerIds, htmlFn) {
    if (!Array.isArray(layerIds)) layerIds = [layerIds];
    layerIds.forEach(function (id) {
        map.on('click', id, function (e) {
            var f = e.features && e.features[0];
            if (!f) return;
            new maplibregl.Popup({ closeButton: true, maxWidth: '260px' })
                .setLngLat(e.lngLat)
                .setHTML(htmlFn(f.properties || {}))
                .addTo(map);
        });
        map.on('mouseenter', id, function () { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', id, function () { map.getCanvas().style.cursor = ''; });
    });
};

/* ── Dark vector basemap (recolored OpenFreeMap) ─────────────────────────── */
OH2O._DARK_SOURCES = {"ne2_shaded": {"maxzoom": 6, "tileSize": 256, "tiles": ["https://tiles.openfreemap.org/natural_earth/ne2sr/{z}/{x}/{y}.png"], "type": "raster"}, "openmaptiles": {"type": "vector", "url": "https://tiles.openfreemap.org/planet"}};
OH2O._DARK_LAYERS  = [{"id": "background", "type": "background", "paint": {"background-color": "#040608"}}, {"id": "water", "type": "fill", "source": "openmaptiles", "source-layer": "water", "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["!=", ["get", "brunnel"], "tunnel"]], "paint": {"fill-antialias": false, "fill-color": "#0e2a3e"}}, {"id": "landcover_ice_shelf", "type": "fill", "source": "openmaptiles", "source-layer": "landcover", "maxzoom": 8, "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["==", ["get", "subclass"], "ice_shelf"]], "paint": {"fill-color": "rgb(12,12,12)", "fill-opacity": 0.7}}, {"id": "landcover_glacier", "type": "fill", "source": "openmaptiles", "source-layer": "landcover", "maxzoom": 8, "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["==", ["get", "subclass"], "glacier"]], "paint": {"fill-color": "hsl(0,1%,2%)", "fill-opacity": ["interpolate", ["linear"], ["zoom"], 0, 1, 8, 0.5]}}, {"id": "landuse_residential", "type": "fill", "source": "openmaptiles", "source-layer": "landuse", "maxzoom": 9, "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["==", ["get", "class"], "residential"]], "paint": {"fill-color": "#080b10", "fill-opacity": 0.4}}, {"id": "landcover_wood", "type": "fill", "source": "openmaptiles", "source-layer": "landcover", "minzoom": 10, "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["==", ["get", "class"], "wood"]], "paint": {"fill-color": "#0a130e", "fill-opacity": ["interpolate", ["exponential", 0.3], ["zoom"], 8, 0, 10, 0.8, 13, 0.4], "fill-pattern": "wood-pattern", "fill-translate": [0, 0]}}, {"id": "landuse_park", "type": "fill", "source": "openmaptiles", "source-layer": "landuse", "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["==", ["get", "class"], "park"]], "paint": {"fill-color": "#0b150e"}}, {"id": "waterway", "type": "line", "source": "openmaptiles", "source-layer": "waterway", "filter": ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], "paint": {"line-color": "#2f6f99"}}, {"id": "water_name", "type": "symbol", "source": "openmaptiles", "source-layer": "water_name", "filter": ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], "layout": {"symbol-placement": "line", "symbol-spacing": 500, "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-rotation-alignment": "map", "text-size": 12}, "paint": {"text-color": "#7fb0d0", "text-halo-color": "#040608", "text-halo-width": 1.2}}, {"id": "building", "type": "fill", "source": "openmaptiles", "source-layer": "building", "minzoom": 12, "filter": ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], "paint": {"fill-antialias": true, "fill-color": "#0b0e14", "fill-outline-color": "rgb(27 ,27 ,29)"}}, {"id": "aeroway-taxiway", "type": "line", "source": "openmaptiles", "source-layer": "aeroway", "minzoom": 12, "filter": ["match", ["get", "class"], ["taxiway"], true, false], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#181818", "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.55], ["zoom"], 13, 1.8, 20, 20]}}, {"id": "aeroway-runway-casing", "type": "line", "source": "openmaptiles", "source-layer": "aeroway", "minzoom": 11, "filter": ["match", ["get", "class"], ["runway"], true, false], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "rgba(60,60,60,0.8)", "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.5], ["zoom"], 11, 5, 17, 55]}}, {"id": "aeroway-area", "type": "fill", "source": "openmaptiles", "source-layer": "aeroway", "minzoom": 4, "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["match", ["get", "class"], ["runway", "taxiway"], true, false]], "paint": {"fill-color": "#000", "fill-opacity": 1}}, {"id": "aeroway-runway", "type": "line", "source": "openmaptiles", "source-layer": "aeroway", "minzoom": 11, "filter": ["all", ["match", ["get", "class"], ["runway"], true, false], ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#000", "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.5], ["zoom"], 11, 4, 17, 50]}}, {"id": "road_area_pier", "type": "fill", "source": "openmaptiles", "source-layer": "transportation", "filter": ["all", ["match", ["geometry-type"], ["MultiPolygon", "Polygon"], true, false], ["==", ["get", "class"], "pier"]], "paint": {"fill-antialias": true, "fill-color": "rgb(12,12,12)"}}, {"id": "road_pier", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["match", ["get", "class"], ["pier"], true, false]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "rgb(12,12,12)", "line-width": ["interpolate", ["exponential", 1.2], ["zoom"], 15, 1, 17, 4]}}, {"id": "highway_path", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "path"]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#161b22", "line-dasharray": [1.5, 1.5], "line-opacity": 0.9, "line-width": ["interpolate", ["exponential", 1.2], ["zoom"], 13, 1, 20, 10]}}, {"id": "highway_minor", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 8, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["match", ["get", "class"], ["minor", "service", "track"], true, false]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#1c222b", "line-opacity": 0.9, "line-width": ["interpolate", ["exponential", 1.55], ["zoom"], 13, 1.8, 20, 20]}}, {"id": "highway_major_casing", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 11, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["match", ["get", "class"], ["primary", "secondary", "tertiary", "trunk"], true, false]], "layout": {"line-cap": "butt", "line-join": "miter"}, "paint": {"line-color": "#11151b", "line-dasharray": [12, 0], "line-width": ["interpolate", ["exponential", 1.3], ["zoom"], 10, 3, 20, 23]}}, {"id": "highway_major_inner", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 11, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["match", ["get", "class"], ["primary", "secondary", "tertiary", "trunk"], true, false]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#2a323d", "line-width": ["interpolate", ["exponential", 1.3], ["zoom"], 10, 2, 20, 20]}}, {"id": "highway_major_subtle", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 6, "maxzoom": 11, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["match", ["get", "class"], ["primary", "secondary", "tertiary", "trunk"], true, false]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#222a33", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0, 8, 2]}}, {"id": "highway_motorway_casing", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 6, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "motorway"]], "layout": {"line-cap": "butt", "line-join": "miter"}, "paint": {"line-color": "#11151b", "line-dasharray": [2, 0], "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 5.8, 0, 6, 3, 20, 40]}}, {"id": "highway_motorway_inner", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 6, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "motorway"]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#33414e", "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 4, 2, 6, 1.3, 20, 30]}}, {"id": "road_oneway", "type": "symbol", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 15, "filter": ["==", ["get", "oneway"], 1], "layout": {"icon-image": "oneway", "icon-padding": 2, "icon-rotate": 0, "icon-rotation-alignment": "map", "icon-size": ["interpolate", ["linear"], ["zoom"], 15, 0.5, 19, 1], "symbol-placement": "line", "symbol-spacing": 200}, "paint": {"icon-opacity": 0.5}}, {"id": "road_oneway_opposite", "type": "symbol", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 15, "filter": ["==", ["get", "oneway"], -1], "layout": {"icon-image": "oneway", "icon-padding": 2, "icon-rotate": 180, "icon-rotation-alignment": "map", "icon-size": ["interpolate", ["linear"], ["zoom"], 15, 0.5, 19, 1], "symbol-placement": "line", "symbol-spacing": 200}, "paint": {"icon-opacity": 0.5}}, {"id": "highway_motorway_subtle", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "maxzoom": 6, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "motorway"]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#2a3743", "line-width": ["interpolate", ["exponential", 1.4], ["zoom"], 4, 2, 6, 1.3]}}, {"id": "railway_transit", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 16, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["all", ["==", ["get", "class"], "transit"], ["match", ["get", "brunnel"], ["tunnel"], false, true]]], "layout": {"line-join": "round"}, "paint": {"line-color": "#1b212a", "line-width": 3}}, {"id": "railway_transit_dashline", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 16, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["all", ["==", ["get", "class"], "transit"], ["match", ["get", "brunnel"], ["tunnel"], false, true]]], "layout": {"line-join": "round"}, "paint": {"line-color": "rgb(12,12,12)", "line-dasharray": [3, 3], "line-width": 2}}, {"id": "railway_minor", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 16, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["all", ["==", ["get", "class"], "rail"], ["has", "service"]]], "layout": {"line-join": "round"}, "paint": {"line-color": "#1b212a", "line-width": 3}}, {"id": "railway_minor_dashline", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 16, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["all", ["==", ["get", "class"], "rail"], ["has", "service"]]], "layout": {"line-join": "round"}, "paint": {"line-color": "rgb(12,12,12)", "line-dasharray": [3, 3], "line-width": 2}}, {"id": "railway", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 13, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "rail"], ["!", ["has", "service"]]], "layout": {"line-join": "round"}, "paint": {"line-color": "#222831", "line-width": ["interpolate", ["exponential", 1.3], ["zoom"], 16, 3, 20, 7]}}, {"id": "railway_dashline", "type": "line", "source": "openmaptiles", "source-layer": "transportation", "minzoom": 13, "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "rail"], ["!", ["has", "service"]]], "layout": {"line-join": "round"}, "paint": {"line-color": "rgb(12,12,12)", "line-dasharray": [3, 3], "line-width": ["interpolate", ["exponential", 1.3], ["zoom"], 16, 2, 20, 6]}}, {"id": "highway_name_other", "type": "symbol", "source": "openmaptiles", "source-layer": "transportation_name", "filter": ["all", ["!=", ["get", "class"], "motorway"], ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false]], "layout": {"symbol-placement": "line", "symbol-spacing": 350, "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], " ", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-max-angle": 30, "text-pitch-alignment": "viewport", "text-rotation-alignment": "map", "text-size": 10, "text-transform": "uppercase"}, "paint": {"text-color": "#6b7f94", "text-halo-blur": 0, "text-halo-color": "#040608", "text-halo-width": 1.0, "text-translate": [0, 0]}}, {"id": "highway_name_motorway", "type": "symbol", "source": "openmaptiles", "source-layer": "transportation_name", "filter": ["all", ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false], ["==", ["get", "class"], "motorway"]], "layout": {"symbol-placement": "line", "symbol-spacing": 350, "text-field": ["to-string", ["get", "ref"]], "text-font": ["Noto Sans Regular"], "text-pitch-alignment": "viewport", "text-rotation-alignment": "viewport", "text-size": 10}, "paint": {"text-color": "#7d91a6", "text-translate": [0, 2], "text-halo-color": "#040608", "text-halo-width": 1.0}}, {"id": "boundary_state", "type": "line", "source": "openmaptiles", "source-layer": "boundary", "filter": ["==", ["get", "admin_level"], 4], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-blur": 0.4, "line-color": "#3a4654", "line-dasharray": [2, 2], "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.3], ["zoom"], 3, 1, 22, 15]}}, {"id": "boundary_country_z0-4", "type": "line", "source": "openmaptiles", "source-layer": "boundary", "maxzoom": 5, "filter": ["all", ["==", ["get", "admin_level"], 2], ["!", ["has", "claimed_by"]]], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-blur": ["interpolate", ["linear"], ["zoom"], 0, 0.4, 22, 4], "line-color": "#4a586a", "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.1], ["zoom"], 3, 1, 22, 20]}}, {"id": "boundary_country_z5-", "type": "line", "source": "openmaptiles", "source-layer": "boundary", "minzoom": 5, "filter": ["==", ["get", "admin_level"], 2], "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-blur": ["interpolate", ["linear"], ["zoom"], 0, 0.4, 22, 4], "line-color": "#4a586a", "line-opacity": 1, "line-width": ["interpolate", ["exponential", 1.1], ["zoom"], 3, 1, 22, 20]}}, {"id": "place_other", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 14, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["match", ["get", "class"], ["hamlet", "isolated_dwelling", "neighbourhood"], true, false]], "layout": {"text-anchor": "center", "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-justify": "center", "text-offset": [0.5, 0], "text-size": 10, "text-transform": "uppercase"}, "paint": {"text-color": "#8899aa", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_suburb", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 15, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "suburb"]], "layout": {"text-anchor": "center", "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-justify": "center", "text-offset": [0.5, 0], "text-size": 10, "text-transform": "uppercase"}, "paint": {"text-color": "#8899aa", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_village", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 14, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "village"]], "layout": {"icon-size": 0.4, "text-anchor": "left", "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-justify": "left", "text-offset": [0.5, 0.2], "text-size": 10, "text-transform": "uppercase"}, "paint": {"icon-opacity": 0.7, "text-color": "#8899aa", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_town", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 15, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "town"]], "layout": {"icon-image": ["step", ["zoom"], "circle-11", 9, ""], "icon-size": 0.4, "text-anchor": ["step", ["zoom"], "left", 8, "center"], "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-justify": "left", "text-offset": [0.5, 0.2], "text-size": 10, "text-transform": "uppercase"}, "paint": {"icon-opacity": 0.7, "text-color": "#8899aa", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_city", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 14, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "city"], [">", ["get", "rank"], 3]], "layout": {"icon-image": ["step", ["zoom"], "circle-11", 9, ""], "icon-size": 0.4, "text-anchor": ["step", ["zoom"], "left", 8, "center"], "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-justify": "left", "text-offset": [0.5, 0.2], "text-size": 10, "text-transform": "uppercase"}, "paint": {"icon-opacity": 0.7, "text-color": "#8899aa", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_city_large", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 12, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["<=", ["get", "rank"], 3], ["==", ["get", "class"], "city"]], "layout": {"icon-image": ["step", ["zoom"], "circle-11", 9, ""], "icon-size": 0.4, "text-anchor": ["step", ["zoom"], "left", 8, "center"], "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-justify": "left", "text-offset": [0.5, 0.2], "text-size": 14, "text-transform": "uppercase"}, "paint": {"icon-opacity": 0.7, "text-color": "#aab6c4", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_state", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 12, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "state"]], "layout": {"text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-size": 10, "text-transform": "uppercase"}, "paint": {"text-color": "#aab6c4", "text-halo-blur": 0.5, "text-halo-color": "#040608", "text-halo-width": 1.3}}, {"id": "place_country_other", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 8, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "country"], ["!", ["has", "iso_a2"]]], "layout": {"text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-size": ["interpolate", ["linear"], ["zoom"], 0, 9, 1, 11], "text-transform": "uppercase"}, "paint": {"text-color": "#8899aa", "text-halo-color": "#040608", "text-halo-width": 1.3, "text-halo-blur": 0.5}}, {"id": "place_country_minor", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 8, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["==", ["get", "class"], "country"], [">=", ["get", "rank"], 2], ["has", "iso_a2"]], "layout": {"text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-size": ["interpolate", ["linear"], ["zoom"], 0, 10, 6, 12], "text-transform": "uppercase"}, "paint": {"text-color": "#aab6c4", "text-halo-color": "#040608", "text-halo-width": 1.3, "text-halo-blur": 0.5}}, {"id": "place_country_major", "type": "symbol", "source": "openmaptiles", "source-layer": "place", "maxzoom": 6, "filter": ["all", ["match", ["geometry-type"], ["MultiPoint", "Point"], true, false], ["<=", ["get", "rank"], 1], ["==", ["get", "class"], "country"], ["has", "iso_a2"]], "layout": {"text-anchor": "center", "text-field": ["case", ["has", "name:nonlatin"], ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]], ["coalesce", ["get", "name_en"], ["get", "name"]]], "text-font": ["Noto Sans Regular"], "text-size": ["interpolate", ["exponential", 1.4], ["zoom"], 0, 10, 3, 12, 4, 14], "text-transform": "uppercase"}, "paint": {"text-color": "#aab6c4", "text-halo-color": "#040608", "text-halo-width": 1.3, "text-halo-blur": 0.5}}];
OH2O._DARK_LAYER_IDS = ["water", "landcover_ice_shelf", "landcover_glacier", "landuse_residential", "landcover_wood", "landuse_park", "waterway", "water_name", "building", "aeroway-taxiway", "aeroway-runway-casing", "aeroway-area", "aeroway-runway", "road_area_pier", "road_pier", "highway_path", "highway_minor", "highway_major_casing", "highway_major_inner", "highway_major_subtle", "highway_motorway_casing", "highway_motorway_inner", "road_oneway", "road_oneway_opposite", "highway_motorway_subtle", "railway_transit", "railway_transit_dashline", "railway_minor", "railway_minor_dashline", "railway", "railway_dashline", "highway_name_other", "highway_name_motorway", "boundary_state", "boundary_country_z0-4", "boundary_country_z5-", "place_other", "place_suburb", "place_village", "place_town", "place_city", "place_city_large", "place_state", "place_country_other", "place_country_minor", "place_country_major"];

OH2O._AERIAL_SOURCES = {
    'esri-aerial': {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256, maxzoom: 19,
        attribution: '&copy; Esri, Maxar, Earthstar Geographics'
    },
    'esri-labels': {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256, maxzoom: 19
    }
};

/* Build a complete MapLibre style with BOTH basemaps baked in; the inactive one
   is just hidden, so switching is a visibility flip (no restyle, no reload). */
OH2O.basemapStyle = function (mode) {
    mode = mode || 'aerial';
    var darkVisible = (mode === 'dark');
    var sources = {};
    Object.keys(OH2O._DARK_SOURCES).forEach(function (k) { sources[k] = OH2O._DARK_SOURCES[k]; });
    Object.keys(OH2O._AERIAL_SOURCES).forEach(function (k) { sources[k] = OH2O._AERIAL_SOURCES[k]; });

    var layers = [];
    OH2O._DARK_LAYERS.forEach(function (L) {
        var c = JSON.parse(JSON.stringify(L));
        if (c.id !== 'background') {
            c.layout = c.layout || {};
            c.layout.visibility = darkVisible ? 'visible' : 'none';
        } else {
            c.paint = c.paint || {};
            c.paint['background-color'] = '#040608';
        }
        layers.push(c);
    });
    layers.push({ id: 'aerial-tiles', type: 'raster', source: 'esri-aerial',
        layout: { visibility: darkVisible ? 'none' : 'visible' } });
    layers.push({ id: 'aerial-labels', type: 'raster', source: 'esri-labels',
        layout: { visibility: darkVisible ? 'none' : 'visible' }, paint: { 'raster-opacity': 0.7 } });

    return {
        version: 8, name: 'OpenH2O',
        glyphs: OH2O.GLYPHS, sprite: OH2O.SPRITE,
        sources: sources, layers: layers
    };
};

/* Flip basemap by toggling layer visibility. Returns the new mode. */
OH2O.switchBasemap = function (map, mode) {
    var darkVisible = (mode === 'dark');
    OH2O._DARK_LAYER_IDS.forEach(function (id) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', darkVisible ? 'visible' : 'none');
    });
    ['aerial-tiles', 'aerial-labels'].forEach(function (id) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', darkVisible ? 'none' : 'visible');
    });
    return mode;
};

/* Inject a compact Dark/Aerial basemap toggle into a map's own container.
   Used by detail mini-maps so every map shares one toggle implementation. */
var _ICON_DARK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/></svg>';
var _ICON_AERIAL = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>';

OH2O.mountBasemapToggle = function (map, mode) {
    mode = mode || 'aerial';
    var host = map.getContainer();
    if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
    var bar = document.createElement('div');
    bar.style.cssText = 'position:absolute;top:10px;left:10px;z-index:5;';
    var group = document.createElement('div');
    group.className = 'tb-group';
    var bDark = document.createElement('button');
    bDark.className = 'tb-btn' + (mode === 'dark' ? ' active' : '');
    bDark.type = 'button'; bDark.innerHTML = _ICON_DARK + ' Dark';
    var bAerial = document.createElement('button');
    bAerial.className = 'tb-btn' + (mode === 'aerial' ? ' active' : '');
    bAerial.type = 'button'; bAerial.innerHTML = _ICON_AERIAL + ' Aerial';
    group.appendChild(bDark); group.appendChild(bAerial);
    bar.appendChild(group); host.appendChild(bar);
    bDark.addEventListener('click', function () {
        OH2O.switchBasemap(map, 'dark'); bDark.classList.add('active'); bAerial.classList.remove('active');
    });
    bAerial.addEventListener('click', function () {
        OH2O.switchBasemap(map, 'aerial'); bAerial.classList.add('active'); bDark.classList.remove('active');
    });
    return bar;
};

})();
