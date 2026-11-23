/* map-core.js — OpenH2O shared cartographic toolkit (single source of truth)
   Loaded on every page that renders a MapLibre map, BEFORE map-engine.js or any
   inline detail-map script. Extends window.OH2O with:
     - colors            entity color palette
     - entities          per-entity symbology + zoom-dependent label specs
     - basemapStyle()    combined dark-vector + aerial-raster MapLibre style
     - switchBasemap()   toggle dark <-> aerial without rebuilding the map
     - addMarkLayer/addAreaLayers/makeLabelLayer  one kind of record drawn the same on every map
     - popupHtml        one popup style for every map
   Dark basemap is a recolored OpenFreeMap (OpenMapTiles schema) vector style,
   keyless and unlimited, fonts+sprites served by OpenFreeMap. Aerial is Esri.

   STREAMING BASEMAPS (operator note): the platform does NOT self-host a custom
   basemap style or tile server. Both basemaps STREAM their tiles live from
   external services every time a map loads:
     - Aerial (default): Esri World Imagery + reference labels from
       server.arcgisonline.com (see OH2O._AERIAL_SOURCES below).
     - Dark: OpenFreeMap vector tiles (tiles.openfreemap.org/planet) + a Natural
       Earth raster underlay, plus OpenFreeMap fonts/sprites (OH2O.GLYPHS /
       OH2O.SPRITE / OH2O._DARK_SOURCES below).
   Implication: the map's backdrop depends on those third-party services staying
   reachable. If Esri or OpenFreeMap is down or blocked, basemap tiles fail to
   load (the app's own GeoJSON layers still render). No tile-server install is
   part of deployment; there is nothing local to provision or back up for maps. */
(function () {
'use strict';
var OH2O = window.OH2O = window.OH2O || {};

/* ── Entity color palette ─────────────────────────────────────────────── */
OH2O.colors = {
    // Water is one blue: rivers by stream order, canals thinner and greyer.
    river: '#4FA3E0', canal: '#6F9FC4',
    // OpenET's field outlines: a dashed line in the primary text colour, so it reads over the
    // aerial and the dark basemap and never as one of the site's own entities.
    openet: '#E7EEF2',
    // The palette by role (tokens.css names each one). Every map reads these.
    frame: '#E7EEF2', frameCasing: '#0B121B', managementArea: '#D8C7A6', serviceArea: '#46B3C4',
    useArea: '#1B7FAF', useAreaLine: '#3DB4E0',
    well: '#E0A446', pod: '#46B3C4', drinking: '#A9DCFF', recharge: '#9B87F5', station: '#C3CDD6',
    selection: '#F4F7F9',
    cropEt1: '#F3E6B3', cropEt2: '#B9DCA0', cropEt3: '#6FC3B1', cropEt4: '#2F97C1', cropEt5: '#1B5AA6',
    noFigure: '#8FA3AE'
};

/* ── Marks: one shape per kind of record ──────────────────────────────────
   Each kind of point record has its own hue AND its own shape, so a mark reads
   on the aerial, on the dark map and to a reader who cannot tell the hues apart:
   a well is a gold circle (as USGS draws a well), a point of diversion a teal
   square, a monitoring station a grey triangle, a recharge site a purple diamond,
   a drinking-water facility a light-blue ring (it shares a place with its well,
   so the ring sits around the well's circle). Every filled mark carries a light
   ring over a dark casing. Drawn once onto a canvas at twice the size and
   registered as the map image `mark-<kind>`. */
OH2O.marks = {
    well:     { shape: 'circle',   color: OH2O.colors.well,     size: 13 },
    pod:      { shape: 'square',   color: OH2O.colors.pod,      size: 13 },
    station:  { shape: 'triangle', color: OH2O.colors.station,  size: 14 },
    recharge: { shape: 'diamond',  color: OH2O.colors.recharge, size: 15 },
    drinking: { shape: 'ring',     color: OH2O.colors.drinking, size: 21 }
};
/* Draw one mark onto a canvas and register it as the map image `name`. */
OH2O.drawMark = function (map, name, m) {
    if (map.hasImage(name)) return;
    var R = 2, s = m.size * R, pad = 3 * R, W = s + pad * 2;
    var c = document.createElement('canvas'); c.width = W; c.height = W;
    var g = c.getContext('2d'), cx = W / 2, r = s / 2;
    g.beginPath();
    if (m.shape === 'circle' || m.shape === 'ring') g.arc(cx, cx, r, 0, Math.PI * 2);
    else if (m.shape === 'square') g.rect(cx - r * 0.86, cx - r * 0.86, r * 1.72, r * 1.72);
    else if (m.shape === 'diamond') { g.moveTo(cx, cx - r); g.lineTo(cx + r, cx); g.lineTo(cx, cx + r); g.lineTo(cx - r, cx); g.closePath(); }
    else if (m.shape === 'triangle') { g.moveTo(cx, cx - r); g.lineTo(cx + r * 0.95, cx + r * 0.75); g.lineTo(cx - r * 0.95, cx + r * 0.75); g.closePath(); }
    g.lineJoin = 'round';
    if (m.shape === 'ring') {
        g.lineWidth = 6 * R; g.strokeStyle = OH2O.colors.frameCasing; g.stroke();
        g.lineWidth = 3 * R; g.strokeStyle = m.color; g.stroke();
    } else {
        g.lineWidth = 4.5 * R; g.strokeStyle = OH2O.colors.frameCasing; g.stroke();
        g.lineWidth = 2 * R; g.strokeStyle = OH2O.colors.selection; g.stroke();
        g.fillStyle = m.color; g.fill();
    }
    map.addImage(name, g.getImageData(0, 0, W, W), { pixelRatio: R });
};
OH2O.registerMarks = function (map) {
    Object.keys(OH2O.marks).forEach(function (k) { OH2O.drawMark(map, 'mark-' + k, OH2O.marks[k]); });
};
/* A symbol layer's layout for one kind of mark: always drawn, sized by zoom. */
OH2O.markLayout = function (k, over) {
    return Object.assign({
        'icon-image': 'mark-' + k, 'icon-allow-overlap': true, 'icon-ignore-placement': false,
        'icon-size': ['interpolate', ['linear'], ['zoom'], 9, 0.75, 13, 1, 16, 1.25]
    }, over || {});
};

/* One kind of record's marks as a symbol layer, on any map: the overview maps
   above a list, a record's own detail map and the Map page draw a well, a point
   of diversion, a station, a recharge point and a drinking-water facility the
   same way. Registers the marks once per map. opts:
     size      a fixed icon-size (a detail map's one mark is sized for its band)
     colorBy   { prop, values: { value: colour }, other: colour }: the kind's
               shape in a colour per value of `prop` (a station's triangle by
               freshness on the Monitoring page)
     filter, beforeId, layout   as MapLibre takes them
   Returns the layer id. */
OH2O.addMarkLayer = function (map, id, source, kind, opts) {
    opts = opts || {};
    OH2O.registerMarks(map);
    var layout = OH2O.markLayout(kind);
    if (opts.colorBy) {
        var by = opts.colorBy, image = ['match', ['get', by.prop]];
        Object.keys(by.values).forEach(function (v) {
            OH2O.drawMark(map, 'mark-' + kind + '-' + v, Object.assign({}, OH2O.marks[kind], { color: by.values[v] }));
            image.push(v, 'mark-' + kind + '-' + v);
        });
        OH2O.drawMark(map, 'mark-' + kind + '-other', Object.assign({}, OH2O.marks[kind], { color: by.other }));
        image.push('mark-' + kind + '-other');
        layout['icon-image'] = image;
    }
    if (opts.size != null) layout['icon-size'] = opts.size;
    Object.assign(layout, opts.layout || {});
    var def = { id: id, type: 'symbol', source: source, layout: layout };
    if (opts.filter) def.filter = opts.filter;
    map.addLayer(def, opts.beforeId);
    return id;
};

/* An area record's fill and outline by role, on every map: a use area is the
   use-area blue with its brighter outline, a recharge basin the recharge purple,
   a zone a line only (a management area the sand dashed line, any other zone the
   teal dotted line), its fill left clear so the area can still be clicked. */
OH2O.areas = {
    parcel:   { fill: 'useArea', fillOpacity: 0.35, line: 'useAreaLine', width: 2 },
    recharge: { fill: 'recharge', fillOpacity: 0.3, line: 'recharge', width: 2 },
    zone:     { fill: 'managementArea', fillOpacity: 0, line: 'managementArea', width: 2, dash: [4, 3],
                other: { line: 'serviceArea', width: 1.5, dash: [1, 2] } }
};
/* Adds `<prefix>-fill` and `<prefix>-outline` (a zone also `<prefix>-outline-other`)
   and returns their ids. opts: filter (fill and outline alike), fillPaint and
   linePaint (merged over the role's paint), beforeId. */
OH2O.addAreaLayers = function (map, prefix, source, key, opts) {
    opts = opts || {};
    var a = OH2O.areas[key] || OH2O.areas.parcel, C = OH2O.colors, ids = [];
    function add(def, extraFilter) {
        var f = opts.filter && extraFilter ? ['all', opts.filter, extraFilter] : (extraFilter || opts.filter);
        if (f) def.filter = f;
        map.addLayer(def, opts.beforeId);
        ids.push(def.id);
    }
    function line(spec) {
        var p = { 'line-color': C[spec.line], 'line-width': spec.width, 'line-opacity': 0.9 };
        if (spec.dash) p['line-dasharray'] = spec.dash;
        return Object.assign(p, opts.linePaint || {});
    }
    add({ id: prefix + '-fill', type: 'fill', source: source,
          paint: Object.assign({ 'fill-color': C[a.fill], 'fill-opacity': a.fillOpacity }, opts.fillPaint || {}) });
    if (a.other) {
        var isMA = ['==', ['get', 'zone_type'], 'management_area'];
        add({ id: prefix + '-outline', type: 'line', source: source, paint: line(a) }, isMA);
        add({ id: prefix + '-outline-other', type: 'line', source: source, paint: line(a.other) }, ['!', isMA]);
    } else {
        add({ id: prefix + '-outline', type: 'line', source: source, paint: line(a) });
    }
    return ids;
};

/* ── One popup for every map ──────────────────────────────────────────────
   The record's name as the popup's title, then its lines, then its links,
   styled by map-engine.css (.maplibregl-popup-content and .popup-line), never
   inline. A line is plain text, or { text, muted } for a quieter line, or
   { html } for markup the caller built from escaped parts. */
OH2O.escapeHtml = function (t) {
    return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
};
OH2O.popupHtml = function (o) {
    o = o || {};
    var esc = OH2O.escapeHtml, html = '<strong>' + esc(o.title) + '</strong>';
    (o.lines || []).forEach(function (l) {
        if (l == null || l === '') return;
        var obj = typeof l === 'object';
        html += '<div class="popup-line' + (obj && l.muted ? ' popup-line-muted' : '') + '">' +
            (obj ? (l.html != null ? l.html : esc(l.text)) : esc(l)) + '</div>';
    });
    (o.links || (o.link ? [o.link] : [])).forEach(function (k) {
        if (k && k.href) html += '<a href="' + esc(k.href) + '">' + esc(k.text) + '</a>';
    });
    return html;
};

/* ── Crop ET: the one shaded fill ─────────────────────────────────────────
   Five classes from pale straw (least) to deep blue (most): darker is more water
   used, as OpenET's own maps draw it. The breaks are fixed so a colour means the
   same depth every month: inches, 0 to 10 by 2 for a month and 0 to 50 by 10 for
   a water year. A field with no figure is a neutral grey with its own legend
   entry, never a ramp stop. */
OH2O.cropET = {
    RAMP: [OH2O.colors.cropEt1, OH2O.colors.cropEt2, OH2O.colors.cropEt3, OH2O.colors.cropEt4, OH2O.colors.cropEt5],
    BREAKS: { month: [0, 2, 4, 6, 8, 10], wy: [0, 10, 20, 30, 40, 50] },
    NO_FIGURE: OH2O.colors.noFigure
};

OH2O.FONT = ['Noto Sans Regular'];
OH2O.GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
OH2O.SPRITE = 'https://tiles.openfreemap.org/sprites/ofm_f384/ofm';

/* ── Per-entity symbology + label rules ───────────────────────────────────
   color  : marker / accent color
   rampLo/rampHi : circle radius at zoom 9 and zoom 16 (interpolated)
   labelField : MapLibre expression for the label text
   labelMin   : zoom at which the label fades in (zoom-dependent labels)

   Five of these (pod, recharge, zone, drinking, station — every entity the
   overview maps draw) lead with ['get','label']: the geojson endpoint's map_label()-stripped name, with the code
   prefix a stored name like "MER-POD-004-DEMO Atwater Canal Headgate" carries
   dropped. `coalesce` falls through to the old expression when a feature has
   no `label` property at all (an older cached response, or an endpoint that
   does not send one), so nothing regresses; a facility's `label` is `null`
   rather than `""` when it has no name, for exactly that reason. `well` is
   untouched — its geojson endpoint does not carry `label` yet. */
OH2O.entities = {
    well:    { color: OH2O.colors.well,   rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','name'], ['get','well_registration_id'], 'Well'] },
    pod:     { color: OH2O.colors.pod,   rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','label'], ['get','name'], 'POD'] },
    station: { color: OH2O.colors.station,    rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','label'], ['get','station_name'], ['get','external_station_id'], 'Station'] },
    recharge:{ color: OH2O.colors.recharge, rampLo: 4.5, rampHi: 10,  labelMin: 10.5,
               labelField: ['coalesce', ['get','label'], ['get','name'], ['get','site_type'], 'Recharge'] },
    // Drinking-water facilities: a light-blue ring, because on the district map
    // a facility lands on the SAME coordinates as its well (one physical
    // feature seen from two sides), so the ring sits around the well's circle.
    drinking:{ color: OH2O.colors.drinking, rampLo: 3.5, rampHi: 8.5, labelMin: 10.5,
               labelField: ['coalesce', ['get','label'], ['get','name'], ['get','facility_id'], 'Facility'] },
    parcel:  { color: OH2O.colors.useArea,   labelMin: 10.5,
               labelField: ['get','parcel_number'] },
    zone:    { color: OH2O.colors.managementArea,  labelMin: 9,
               labelField: ['coalesce', ['get','label'], ['get','name']] },
    boundary:{ color: OH2O.colors.frame,   labelMin: 8,
               labelField: ['get','name'] },
    hydrography:{ color: OH2O.colors.river, labelMin: 11,
               labelField: ['coalesce', ['get','name'], ['get','feature_type'], 'Waterway'] }
};

OH2O.labelPaint = function () {
    return {
        'text-color': OH2O.colors.frame,
        'text-halo-color': OH2O.colors.frameCasing,
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

/* ── A source's use areas, shown when it is picked ────────────────────────
   The links from each well and point of diversion to the use areas it serves are
   not drawn all the time (88 of them crossed the demonstration's map). A click on
   a well or a point of diversion outlines its use areas, draws a line to each
   with its share beside the line's end, and its popup lists the shares: all of
   them up to six, otherwise the first SHARES_SHOWN and a line for the rest. The
   lines come from geography:tie_lines_geojson, which ends each one at a point
   inside its use area. A click anywhere else clears the pick. */
OH2O.SHARES_SHOWN = 5;
OH2O._shares = { map: null, words: null };
OH2O._sharesOf = function (type, pk) {
    var map = OH2O._shares.map, src = map && map.getSource('tie-lines');
    var d = src && src.serialize && src.serialize().data;
    return ((d && d.features) || []).filter(function (f) {
        return pk != null && f.properties.source_type === type && String(f.properties.source_id) === String(pk);
    }).sort(function (a, b) { return b.properties.fraction - a.properties.fraction; });
};
/* The popup's shares block for a well ('gw') or a point of diversion ('sw'). */
OH2O.shareRows = function (type, pk) {
    var w = OH2O._shares.words, rows = OH2O._sharesOf(type, pk);
    if (!w || !rows.length) return '';
    var cut = rows.length > OH2O.SHARES_SHOWN + 1;
    var shown = cut ? rows.slice(0, OH2O.SHARES_SHOWN) : rows;
    var esc = function (t) { var e = document.createElement('span'); e.textContent = t; return e.innerHTML; };
    return '<div class="popup-shares"><div class="popup-shares-head">' + esc(type === 'gw' ? w.wellHead : w.podHead) + '</div>' +
        shown.map(function (f) {
            return '<div class="popup-share"><span>' + esc(f.properties.parcel_number) + '</span><span>' +
                Math.round(f.properties.fraction * 100) + '%</span></div>';
        }).join('') +
        (cut ? '<div class="popup-shares-more">' + esc(w.more.replace('N', String(rows.length - OH2O.SHARES_SHOWN))) + '</div>' : '') +
        '</div>';
};
/* Where a picked source's popup goes: beside the box that holds the well or point of
   diversion and every use area it serves, never over them. The sides are tried in
   turn (left, right, below, above); the first where the whole popup fits on the map,
   clear of the toolbar and the Layers panel, wins, with the popup's tip on that edge
   of the box. When no side fits (a group that fills the screen), the map jumps to
   frame the group with the popup's width kept free on the left, the side away from
   the panel. No animation: the camera only moves when it has to, and then at once. */
OH2O._groupBox = function (map, type, pk, coords) {
    var rows = OH2O._sharesOf(type, pk);
    if (!rows.length) return null;
    var ids = {}; rows.forEach(function (f) { ids[f.properties.parcel_id] = true; });
    var src = map.getSource('parcels'), d = src && src.serialize && src.serialize().data;
    var pts = [coords];
    ((d && d.features) || []).forEach(function (f) {
        if (!ids[f.properties.pk] || !f.geometry) return;
        (function walk(c) { if (typeof c[0] === 'number') pts.push(c); else c.forEach(walk); })(f.geometry.coordinates);
    });
    var west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
    pts.forEach(function (c) { west = Math.min(west, c[0]); east = Math.max(east, c[0]); south = Math.min(south, c[1]); north = Math.max(north, c[1]); });
    var box = [[west, south], [east, north]];
    box.source = coords;
    return box;
};
OH2O._freeArea = function (map) {
    var c = map.getContainer().getBoundingClientRect();
    var area = { left: 10, top: 10, right: c.width - 10, bottom: c.height - 10 };
    var tb = document.getElementById('toolbar'), panel = document.getElementById('controls');
    if (tb) { var t = tb.getBoundingClientRect(); area.top = Math.max(area.top, t.bottom - c.top + 8); }
    if (panel && panel.offsetParent) { var p = panel.getBoundingClientRect(); area.right = Math.min(area.right, p.left - c.left - 10); }
    return area;
};
OH2O._placeBeside = function (map, popup, box, w, h) {
    var a = map.project(box[0]), b = map.project(box[1]);
    var minX = Math.min(a.x, b.x), maxX = Math.max(a.x, b.x), minY = Math.min(a.y, b.y), maxY = Math.max(a.y, b.y);
    var f = OH2O._freeArea(map), gap = 12;
    var clamp = function (v, lo, hi) { return Math.max(lo, Math.min(hi, v)); };
    var src = map.project(box.source), midY = clamp(src.y, f.top + h / 2, f.bottom - h / 2);
    var midX = clamp((minX + maxX) / 2, f.left + w / 2, f.right - w / 2);
    var sides = [
        { anchor: 'right',  at: [minX - gap, midY], fits: minX - gap - w >= f.left && f.bottom - f.top >= h },
        { anchor: 'left',   at: [maxX + gap, midY], fits: maxX + gap + w <= f.right && f.bottom - f.top >= h },
        { anchor: 'top',    at: [midX, maxY + gap], fits: maxY + gap + h <= f.bottom && f.right - f.left >= w },
        { anchor: 'bottom', at: [midX, minY - gap], fits: minY - gap - h >= f.top && f.right - f.left >= w }
    ];
    for (var i = 0; i < sides.length; i++) {
        if (sides[i].fits) {
            OH2O._setAnchor(popup, sides[i].anchor); popup.setLngLat(map.unproject(sides[i].at));
            // Beside the group its tip would point at open ground, not at the source: no tip.
            popup.addClassName('popup-beside');
            return true;
        }
    }
    return false;
};
OH2O._setAnchor = function (popup, anchor) {
    // MapLibre keeps the anchor in its options; setting it and re-placing the popup is the public way round.
    popup.options.anchor = anchor;
};
OH2O.placePopup = function (map, popup, layerId, props, coords) {
    var type = layerId === 'wells-points' ? 'gw' : layerId === 'pods-points' ? 'sw' : null;
    if (!type) return;
    var box = OH2O._groupBox(map, type, props.pk, coords);
    if (!box) return;
    var el = popup.getElement(), w = el.offsetWidth, h = el.offsetHeight;
    if (OH2O._placeBeside(map, popup, box, w, h)) return;
    var c = map.getContainer().getBoundingClientRect(), f = OH2O._freeArea(map);
    map.fitBounds(box, { duration: 0, maxZoom: Math.max(map.getZoom(), 13),
        padding: { left: f.left + w + 40, right: (c.width - f.right) + 30, top: f.top + 20, bottom: 30 } });
    if (!OH2O._placeBeside(map, popup, box, w, h)) {
        OH2O._setAnchor(popup, 'right'); popup.addClassName('popup-beside');
        popup.setLngLat(map.unproject([map.project(box[0]).x - 12, c.height / 2]));
    }
};

/* Mount the pick on the Map page. `words`: { podHead, wellHead, more } (more carries N). */
OH2O.mountSourceShares = function (map, words) {
    OH2O._shares = { map: map, words: words };
    var EMPTY = { type: 'FeatureCollection', features: [] };
    var C = OH2O.colors;
    function ready() {
        if (!map.getSource('tie-lines') || !map.getLayer('parcels-outline')) return window.setTimeout(ready, 100);
        map.addSource('sel-lines', { type: 'geojson', data: EMPTY });
        map.addSource('sel-ends', { type: 'geojson', data: EMPTY });
        var below = map.getLayer('parcels-label') ? 'parcels-label' : undefined;
        map.addLayer({ id: 'sel-use-areas', type: 'line', source: 'parcels',
            filter: ['in', ['get', 'pk'], ['literal', []]],
            paint: { 'line-color': C.selection, 'line-width': 3 } }, below);
        map.addLayer({ id: 'sel-lines-casing', type: 'line', source: 'sel-lines',
            paint: { 'line-color': C.frameCasing, 'line-width': 4, 'line-opacity': 0.6 } }, below);
        map.addLayer({ id: 'sel-lines', type: 'line', source: 'sel-lines',
            paint: { 'line-color': ['match', ['get', 'source_type'], 'gw', C.well, C.pod], 'line-width': 1.75 } }, below);
        map.addLayer({ id: 'sel-ends-label', type: 'symbol', source: 'sel-ends',
            layout: { 'text-field': ['concat', ['to-string', ['round', ['*', ['get', 'fraction'], 100]]], '%'],
                      'text-font': OH2O.FONT, 'text-size': 13, 'text-allow-overlap': true, 'text-offset': [0, -1.1] },
            paint: { 'text-color': C.selection, 'text-halo-color': C.frameCasing, 'text-halo-width': 2 } });
        function select(type, pk) {
            var feats = OH2O._sharesOf(type, pk);
            map.getSource('sel-lines').setData({ type: 'FeatureCollection', features: feats });
            map.getSource('sel-ends').setData({ type: 'FeatureCollection', features: feats.map(function (f) {
                var c = f.geometry.coordinates;
                return { type: 'Feature', properties: f.properties, geometry: { type: 'Point', coordinates: c[c.length - 1] } };
            }) });
            map.setFilter('sel-use-areas', ['in', ['get', 'pk'], ['literal', feats.map(function (f) { return f.properties.parcel_id; })]]);
            // While a source is picked, only its own name and its use areas' names stay on the map,
            // so the lines and shares are not read through other wells' and fields' labels.
            var picked = feats.length ? String(pk) : null;
            var only = function (id, expr) {
                if (!map.getLayer(id)) return;
                if (!(id in base)) base[id] = map.getFilter(id) || null;
                map.setFilter(id, picked ? (base[id] ? ['all', base[id], expr] : expr) : base[id]);
            };
            var ids = feats.map(function (f) { return f.properties.parcel_id; });
            only('parcels-label', ['in', ['get', 'pk'], ['literal', ids]]);
            only('wells-label', type === 'gw' ? ['==', ['to-string', ['get', 'pk']], picked || ''] : ['==', ['get', 'pk'], -1]);
            only('pods-label', type === 'sw' ? ['==', ['to-string', ['get', 'pk']], picked || ''] : ['==', ['get', 'pk'], -1]);
        }
        var base = {};
        OH2O.selectSource = select;
        map.on('click', function (e) {
            var layers = ['pods-points', 'wells-points'].filter(function (l) { return map.getLayer(l); });
            var hit = layers.length ? map.queryRenderedFeatures(e.point, { layers: layers }) : [];
            if (!hit.length) { select(null, null); return; }
            select(hit[0].layer.id === 'wells-points' ? 'gw' : 'sw', hit[0].properties.pk);
        });
    }
    ready();
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

/* ── The overview map follows its list ───────────────────────────────────
   An overview page's results partial emits the WHOLE filtered queryset's pks
   (before pagination) as <script id="results-map-pks" type="application/json">.
   The map keeps ONE unfiltered source (one fetch per page load; the geojson
   endpoints take no parameter) and this helper filters the named layers to
   those pks and re-frames on them: once now, and again after every htmx swap
   of #results. The count line comes from the server (the card head, swapped
   out of band by the same response); this touches only the map. opts:
     layers      layer ids to filter (glow, dots, label; or fill, outline, label)
     source      the geojson source id, read back for the re-frame when `data`
                 is not given
     data        the FeatureCollection the source was built from (optional)
     pksEl       id of the json_script element (default 'results-map-pks')
     resultsEl   id of the htmx target whose swaps re-run this (default 'results')
     padding     fitBounds padding (default 40)
     maxZoom     fitBounds maxZoom (default 13)
     singleZoom  zoom for a lone point (default 11)
   Every feature must carry `pk` in its properties. No pks element on the page
   (a list not yet wired): the layers stay unfiltered and the frame takes every
   feature. An empty list filters everything out and keeps the frame. */
OH2O.followResults = function (map, opts) {
    opts = opts || {};
    var pksEl = opts.pksEl || 'results-map-pks';
    var resultsEl = opts.resultsEl || 'results';
    var padding = opts.padding != null ? opts.padding : 40;
    var maxZoom = opts.maxZoom != null ? opts.maxZoom : 13;
    var singleZoom = opts.singleZoom != null ? opts.singleZoom : 11;

    function readPks() {
        var el = document.getElementById(pksEl);
        if (!el) return null;
        try {
            var v = JSON.parse(el.textContent);
            return Array.isArray(v) ? v : null;
        } catch (e) { return null; }
    }
    function features() {
        if (opts.data && opts.data.features) return opts.data.features;
        var src = map.getSource(opts.source);
        var s = src && src.serialize && src.serialize();
        return (s && s.data && s.data.features) || [];
    }
    function frame(feats) {
        var bounds = OH2O._geojsonBounds({ features: feats });
        if (!bounds) return;                                   // nothing left: keep the frame
        var spanLon = bounds[1][0] - bounds[0][0];
        var spanLat = bounds[1][1] - bounds[0][1];
        if (spanLon < 1e-6 && spanLat < 1e-6) {
            map.easeTo({ center: bounds[0], zoom: singleZoom });
        } else {
            map.fitBounds(bounds, { padding: padding, maxZoom: maxZoom });
        }
    }
    // Each layer's OWN filter (the recharge dots layer keeps only Point
    // geometry, for one) is read once and ANDed with the pk filter. Replacing
    // it wholesale put a circle on every polygon vertex of every basin.
    // A legacy filter (['==', '$type', 'Point']) cannot sit inside an
    // expression ['all', ...]: MapLibre rejects the pair and keeps the old
    // filter, silently. Translate the one legacy shape this codebase uses.
    function asExpression(f) {
        if (!f) return null;
        if (f.length === 3 && f[1] === '$type') return [f[0], ['geometry-type'], f[2]];
        if (f.length === 3 && typeof f[1] === 'string' && f[1].charAt(0) !== '$' && !Array.isArray(f[2])) {
            return [f[0], ['get', f[1]], f[2]];
        }
        return f;
    }
    var ownFilters = {};
    (opts.layers || []).forEach(function (id) {
        if (map.getLayer(id)) ownFilters[id] = asExpression(map.getFilter(id));
    });
    function apply() {
        var pks = readPks();
        var pkFilter = pks === null ? null : ['in', ['get', 'pk'], ['literal', pks]];
        (opts.layers || []).forEach(function (id) {
            if (!map.getLayer(id)) return;
            var own = ownFilters[id];
            var filter = pkFilter === null ? own : (own ? ['all', own, pkFilter] : pkFilter);
            map.setFilter(id, filter);
        });
        var feats = features();
        if (pks !== null) {
            var keep = {};
            pks.forEach(function (pk) { keep[String(pk)] = true; });
            feats = feats.filter(function (f) { return f.properties && keep[String(f.properties.pk)]; });
        }
        frame(feats);
    }
    apply();
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (e.detail && e.detail.target && e.detail.target.id === resultsEl) apply();
    });
    return apply;
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
    // A flex row, so a second group (OH2O.mountOpenETFieldsToggle) sits beside this one.
    bar.style.cssText = 'position:absolute;top:10px;left:10px;z-index:5;display:flex;gap:8px;';
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

/* ── OpenET's fields on a detail map, off until a person ticks the box ──
   The outlines show only when asked for, and OpenET is named on the map
   whenever they show. Adds a second group to the map's Dark/Aerial bar holding one
   checkbox ("OpenET fields", with a dashed swatch), a dashed line layer, and a credit
   chip at the map's bottom-left. The box is unticked on every call: nothing is
   remembered between pages or panes. Called again on the same map (a pane swapped in
   place), it takes the new outlines, or hides the group when there are none. No fill
   (it would hide the use area's own fill and label) and no label per field. */
OH2O.mountOpenETFieldsToggle = function (map, fc) {
    var has = !!(fc && fc.features && fc.features.length);
    var state = map.__openetFields;
    if (!state) {
        if (!has) return null;
        var host = map.getContainer();
        var first = host.querySelector('.tb-group');
        if (!first) return null;
        var bar = first.parentElement;
        var group = document.createElement('div');
        group.className = 'tb-group';
        var label = document.createElement('label');
        label.className = 'tb-btn layer-toggle';
        var box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = false;
        var swatch = document.createElement('span');
        swatch.className = 'layer-swatch-dashed';
        swatch.style.borderTopColor = OH2O.colors.openet;
        var name = document.createElement('span');
        name.textContent = 'OpenET fields';
        label.appendChild(box); label.appendChild(swatch); label.appendChild(name);
        group.appendChild(label);
        bar.appendChild(group);
        var credit = document.createElement('div');
        credit.className = 'map-credit-chip';
        credit.textContent = 'OpenET field outlines';
        host.appendChild(credit);
        map.addSource('openet-fields', { type: 'geojson', data: fc });
        map.addLayer({
            id: 'openet-fields-outline', type: 'line', source: 'openet-fields',
            layout: { visibility: 'none' },
            paint: { 'line-color': OH2O.colors.openet, 'line-width': 2, 'line-dasharray': [2, 1.5] }
        }, map.getLayer('parcel-label') ? 'parcel-label' : undefined);
        state = map.__openetFields = {
            group: group,
            set: function (on) {
                box.checked = on;
                map.setLayoutProperty('openet-fields-outline', 'visibility', on ? 'visible' : 'none');
                credit.hidden = !on;
            }
        };
        box.addEventListener('change', function () { state.set(box.checked); });
    } else if (has) {
        map.getSource('openet-fields').setData(fc);
    }
    state.group.hidden = !has;
    state.set(false);
    return state.group;
};

/* ── Frame a map on the agency boundary ───────────────────────────
   The two draw-your-boundary maps (zone_create, infrastructure add) used to
   open on a fixed point in the mountains with no sense of where the agency
   actually is. Fetches `geography:boundaries_geojson`; with features, draws
   an outline + an always-on centered label and fits the map to it; with none
   (a deployment that has not drawn its boundary yet) leaves the map's own
   center/zoom alone — there is nothing to frame on.

   Returns the fetch promise (never rejects) so a caller adds its OWN layers
   inside `.then()`, which guarantees they are added to the map AFTER this
   helper's, whichever way the fetch resolves — layer order is add order, not
   call order, and the fetch is async, so calling this first in the source
   only draws the caller's layers on top if the caller also waits on it. */
OH2O.frameOnBoundary = function (map, url) {
    return fetch(url)
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (fc) {
            if (!fc || !fc.features || !fc.features.length) return;
            map.addSource('boundary', { type: 'geojson', data: fc });
            // The frame, as the Map page draws it: a light line over a dark casing.
            map.addLayer({
                id: 'boundary-casing', type: 'line', source: 'boundary',
                paint: { 'line-color': OH2O.colors.frameCasing, 'line-width': 5, 'line-opacity': 0.55 }
            });
            map.addLayer({
                id: 'boundary-outline', type: 'line', source: 'boundary',
                paint: { 'line-color': OH2O.colors.frame, 'line-width': 2, 'line-opacity': 0.95 }
            });
            // One label per boundary, not one per polygon part: a two-part
            // MultiPolygon labelled from the polygon source paints its name
            // twice (seen on the add page). Label a point
            // source built from each feature's bbox centre instead.
            var pts = { type: 'FeatureCollection', features: fc.features.map(function (f) {
                var b = OH2O._geojsonBounds({ type: 'FeatureCollection', features: [f] });
                return { type: 'Feature', properties: f.properties || {},
                         geometry: { type: 'Point', coordinates: b ? [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2] : [0, 0] } };
            }) };
            map.addSource('boundary-label-points', { type: 'geojson', data: pts });
            OH2O.addDetailLabel(map, 'boundary-label-points', 'boundary', { id: 'boundary-label', anchor: 'center' });
            var bounds = OH2O._geojsonBounds(fc);
            if (bounds) map.fitBounds(bounds, { padding: 40 });
        })
        .catch(function () { /* keep the map's initial center/zoom */ });
};

/* ── Persistent detail-pane map (master-detail workspace engine) ────────────
   The shared spine of the v2.0 master-detail screens. The map element lives in
   the pane SHELL (the workspace layout / the standalone detail page); each
   swapped-in detail body calls OH2O.detailPaneMap() to re-point that ONE map at
   the newly selected feature. The map is built once per host and thereafter only
   setData + reframed — never torn down and rebuilt — which is what kills the
   tile-load flash on row-to-row switching. Handles both point geometries (wells,
   diversions, stations: glow + marker) and polygon geometries (parcels, zones,
   recharge: fill + outline), auto-detected from the GeoJSON. */

OH2O._detailMaps = OH2O._detailMaps || {};

/* Walk arbitrarily-nested GeoJSON coordinates down to [lon,lat] pairs. */
OH2O._walkCoords = function (geo, cb) {
    if (!geo) return;
    if (typeof geo[0] === 'number' && typeof geo[1] === 'number') { cb(geo); return; }
    for (var i = 0; i < geo.length; i++) OH2O._walkCoords(geo[i], cb);
};

/* Bounding box [[minLon,minLat],[maxLon,maxLat]] of a FeatureCollection, or null. */
OH2O._geojsonBounds = function (gj) {
    var pts = [];
    (gj.features || []).forEach(function (f) {
        if (f.geometry && f.geometry.coordinates) {
            OH2O._walkCoords(f.geometry.coordinates, function (pt) { pts.push(pt); });
        }
    });
    if (!pts.length) return null;
    var lons = pts.map(function (c) { return c[0]; });
    var lats = pts.map(function (c) { return c[1]; });
    return [[Math.min.apply(null, lons), Math.min.apply(null, lats)],
            [Math.max.apply(null, lons), Math.max.apply(null, lats)]];
};

OH2O._geojsonIsPoint = function (gj) {
    var f = (gj.features || [])[0];
    return !!(f && f.geometry && /Point/.test(f.geometry.type || ''));
};

/* Frame a map on a bounding box. A single point gives a degenerate box, so fall
   back to center + fixed zoom; anything with real extent uses fitBounds. */
OH2O._frameBounds = function (map, bounds) {
    var spanLon = bounds[1][0] - bounds[0][0];
    var spanLat = bounds[1][1] - bounds[0][1];
    if (spanLon < 1e-6 && spanLat < 1e-6) {
        map.easeTo({ center: [bounds[0][0], bounds[0][1]], zoom: 14, duration: 0 });
    } else {
        map.fitBounds(bounds, { padding: 40, maxZoom: 16, duration: 0 });
    }
};

/* Add this feature's layers (point or polygon) to a freshly-loaded map. opts:
     labelAt   'point_on_surface' reads a server-supplied `label_point`
               ([lng, lat]) off each feature's properties and labels a
               separate one-point-per-feature source instead of the polygon
               source itself: a MultiPolygon with many disjoint parts
               (a GSA union of scattered parcels, or a zone) otherwise stamps
               a symbol layer placed ON the polygon source once PER PART —
               the same fault `zone_labels_geojson` already fixed for the
               full map. Falls back to labeling the polygon source directly
               (today's behavior) when no feature carries `label_point` (an
               older cached response, or a caller that never asked for this).
     geojson   the FeatureCollection just loaded into `src`, read for the
               `label_point` properties above; ignored when isPoint. */
/* A detail map's one mark is sized for its band, not the overview's zoom ramp:
   the detail map frames a single point at zoom 14, and a mark drawn at the
   ramp's size sat as "a tiny dot" in a 1,430 x 380 band. Here the mark is
   2 x DETAIL_POINT_RADIUS (18 px) across at every zoom, whatever its kind. */
OH2O.DETAIL_POINT_RADIUS = 9;

OH2O._addDetailLayers = function (map, src, key, isPoint, popup, opts) {
    opts = opts || {};
    if (isPoint) {
        var mark = OH2O.marks[key] ? key : 'well';
        OH2O.addMarkLayer(map, src + '-point', src, mark,
            { size: (2 * OH2O.DETAIL_POINT_RADIUS) / OH2O.marks[mark].size });
        OH2O.addDetailLabel(map, src, key, { id: src + '-label', offset: [0, 1.3] });
        if (popup) OH2O.attachPopup(map, src + '-point', popup);
    } else {
        OH2O.addAreaLayers(map, src, src, key);
        var labelSrc = src;
        if (opts.labelAt === 'point_on_surface' && opts.geojson) {
            var pts = (opts.geojson.features || [])
                .filter(function (f) { return f.properties && f.properties.label_point; })
                .map(function (f) {
                    return { type: 'Feature',
                        geometry: { type: 'Point', coordinates: f.properties.label_point },
                        properties: f.properties };
                });
            if (pts.length) {
                labelSrc = src + '-label-point';
                map.addSource(labelSrc, { type: 'geojson', data: { type: 'FeatureCollection', features: pts } });
            }
        }
        OH2O.addDetailLabel(map, labelSrc, key, { id: src + '-label', anchor: 'center', offset: [0, 0] });
        if (popup) OH2O.attachPopup(map, src + '-fill', popup);
    }
};

/* Public entry point. opts:
     card   id of the wrapping card element (shown/hidden by geometry presence)
     host   id of the map container element
     dataEl id of the json_script element carrying this feature's GeoJSON
     source MapLibre source name + layer-id prefix (e.g. 'well', 'parcel')
     key    OH2O.entities key for color/label rules (defaults to source)
     popup  optional fn(properties) -> popup HTML
     onMapLoad optional fn(map) -> run ONCE, after the feature's own layers are
            added on first build, for a per-screen substrate (e.g. the POD pane
            drops the river/canal flowlines beneath the diversion point). Does
            NOT re-run on row-to-row swaps — the substrate is built once with the
            map, same as the basemap.
     labelAt   optional, forwarded to OH2O._addDetailLayers: pass
            'point_on_surface' for a polygon feature whose geojson carries a
            `label_point` per feature, so a multi-part MultiPolygon gets one
            label instead of one per part.
   Defensive: polls until maplibre + the toolkit are ready, no-ops when the page
   has no map host, hides the card when the feature has no geometry. */
OH2O.detailPaneMap = function (opts) {
    var src = opts.source;
    var key = opts.key || opts.source;
    function boot() {
        if (typeof maplibregl === 'undefined' || !window.OH2O || !OH2O.basemapStyle) {
            return window.setTimeout(boot, 50);
        }
        var card = document.getElementById(opts.card);
        var host = document.getElementById(opts.host);
        var dataEl = document.getElementById(opts.dataEl);
        if (!host) return;                                   // page has no map host
        if (!dataEl) { if (card) card.style.display = 'none'; return; }  // no geometry
        if (card) card.style.display = '';

        var geojson = JSON.parse(dataEl.textContent);
        var bounds = OH2O._geojsonBounds(geojson);
        var isPoint = OH2O._geojsonIsPoint(geojson);
        var center = bounds
            ? [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2]
            : [-120.5, 37.3];

        var reg = OH2O._detailMaps[opts.host];
        var map = reg && reg.map;
        if (map && map.__oh2oReady) {
            // UPDATE in place — no rebuild, no flash.
            map.getSource(src).setData(geojson);
            map.resize();                        // card may have been display:none
            if (bounds) OH2O._frameBounds(map, bounds);
            return;
        }
        if (map) return;                         // a map is mid-build; its load handler honours latest data

        // CREATE once.
        map = new maplibregl.Map({
            cooperativeGestures: true,  // plain scroll passes to the page; Cmd/Ctrl+scroll zooms
            container: opts.host, style: OH2O.basemapStyle('aerial'),
            center: center, zoom: 13, fadeDuration: 0
        });
        OH2O._detailMaps[opts.host] = { map: map };
        map.on('load', function () {
            map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
            OH2O.mountBasemapToggle(map, 'aerial');
            map.addSource(src, { type: 'geojson', data: geojson });
            OH2O._addDetailLayers(map, src, key, isPoint, opts.popup,
                { labelAt: opts.labelAt, geojson: geojson });
            // Per-screen substrate (e.g. POD flowlines), added once beneath the
            // feature's own layers. Guarded so a screen's substrate fetch can't
            // abort the map build.
            if (opts.onMapLoad) { try { opts.onMapLoad(map); } catch (e) { /* substrate optional */ } }
            // Honour the CURRENT selection — the user may have switched while the
            // tiles were still loading.
            var latest = document.getElementById(opts.dataEl);
            if (latest) {
                try {
                    var gj = JSON.parse(latest.textContent);
                    map.getSource(src).setData(gj);
                    var b = OH2O._geojsonBounds(gj);
                    if (b) OH2O._frameBounds(map, b);
                } catch (e) { /* keep initial frame */ }
            } else if (bounds) {
                OH2O._frameBounds(map, bounds);
            }
            map.__oh2oReady = true;
        });
    }
    boot();
};

})();
