/* map-engine.js — Interactive map engine for Open Water Accounting Platform.
   Reads a global MAP_CONFIG and auto-generates the layer panel, legend,
   MapLibre data layers, zoom-dependent labels, and popups.

   Requires (in load order): map-core.js (window.OH2O), maplibre-gl, MAP_CONFIG. */

(function() {
'use strict';

document.title = MAP_CONFIG.title;
var OH2O = window.OH2O || { switchBasemap: function(){}, basemapStyle: function(){ return { version:8, sources:{}, layers:[] }; } };

// ── Build layer panel (header + body) from MAP_CONFIG.layers ──
(function buildLayerPanel() {
    var panel = document.getElementById('controls');
    var groupsSeen = {};

    // Panel header: title + show/hide-all
    var head = document.createElement('div');
    head.className = 'panel-head';
    var h3 = document.createElement('h3'); h3.textContent = 'Layers';
    var allBtn = document.createElement('button');
    allBtn.className = 'panel-toggle-all'; allBtn.type = 'button'; allBtn.textContent = 'Hide all';
    head.appendChild(h3); head.appendChild(allBtn);
    panel.appendChild(head);

    var body = document.createElement('div');
    body.className = 'panel-body';
    panel.appendChild(body);

    allBtn.addEventListener('click', function() {
        var boxes = body.querySelectorAll('input[type="checkbox"]');
        var anyOn = Array.prototype.some.call(boxes, function(b) { return b.checked; });
        var target = !anyOn;
        boxes.forEach(function(b) { if (b.checked !== target) { b.checked = target; b.dispatchEvent(new Event('change')); } });
        allBtn.textContent = target ? 'Hide all' : 'Show all';
    });

    // Build one layer-toggle row
    function buildToggle(layer, layerIds) {
        var label = document.createElement('label');
        label.className = 'layer-toggle';

        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = layer.visible !== false;
        cb.dataset.layers = layerIds.join(',');

        var swatch = document.createElement('span');
        var st = layer.swatch || 'dot';
        if (st === 'line') {
            swatch.className = 'swatch-line';
            if (layer.swatchStyle) swatch.style.cssText = layer.swatchStyle;
            else swatch.style.borderColor = layer.swatchColor || '#888';
        } else if (st === 'line-dash') {
            swatch.className = 'swatch-line swatch-line-dash';
            swatch.style.borderColor = layer.swatchColor || '#888';
        } else if (st === 'dot') {
            swatch.className = 'swatch-dot';
            swatch.style.background = layer.swatchColor || '#888';
            swatch.style.color = layer.swatchColor || '#888'; // drives glow via currentColor
        } else if (st === 'square') {
            swatch.className = 'swatch-square';
            if (layer.swatchStyle) swatch.style.cssText = layer.swatchStyle;
            else swatch.style.background = layer.swatchColor || '#888';
        } else if (st === 'fill') {
            swatch.className = 'swatch-fill';
            if (layer.swatchStyle) swatch.style.cssText = layer.swatchStyle;
            else swatch.style.background = layer.swatchColor || '#888';
        } else if (st === 'letter') {
            swatch.className = 'swatch-letter';
            swatch.textContent = layer.swatchText || 'A';
        } else if (st === 'triangle') {
            swatch.className = 'swatch-triangle';
            swatch.style.color = layer.swatchColor || '#ff6b4a';
            swatch.textContent = layer.swatchText || '▲';
        } else if (st === 'diamond') {
            swatch.className = 'swatch-diamond';
            swatch.style.color = layer.swatchColor || '#44aaff';
            swatch.textContent = layer.swatchText || '◆';
        } else if (st === 'custom') {
            if (layer.swatchStyle) swatch.style.cssText = layer.swatchStyle;
        }

        var name = document.createElement('span');
        name.className = 'layer-name';
        name.textContent = layer.label || layer.id;

        label.appendChild(cb);
        label.appendChild(swatch);
        label.appendChild(name);

        // Feature-count badge (filled after geojson loads). Only for layers with a source.
        var srcId = layer.source || MAP_CONFIG.sourceId;
        if (srcId) {
            var count = document.createElement('span');
            count.className = 'layer-count';
            count.dataset.countSource = srcId;
            if (layer.countFilter) count.dataset.countFilter = JSON.stringify(layer.countFilter);
            count.textContent = '·';
            label.appendChild(count);
        }
        return label;
    }

    var hasSections = MAP_CONFIG.layers.some(function(l) { return l.section; });

    if (!hasSections) {
        MAP_CONFIG.layers.forEach(function(layer) {
            if (layer.groupHidden || layer.panelHidden) return;
            var layerIds = [layer.id];
            if (layer.glow) layerIds.unshift(layer.id + '-glow');
            if (layer.label_id) layerIds.push(layer.label_id);
            if (layer.group) {
                if (groupsSeen[layer.group]) return;
                groupsSeen[layer.group] = true;
                layerIds = [];
                MAP_CONFIG.layers.forEach(function(l) {
                    if (l.group === layer.group) {
                        if (l.glow) layerIds.push(l.id + '-glow');
                        layerIds.push(l.id);
                        if (l.label_id) layerIds.push(l.label_id);
                    }
                });
            }
            body.appendChild(buildToggle(layer, layerIds));
        });
        return;
    }

    // Grouped mode
    var sectionOrder = [], sectionMap = {};
    MAP_CONFIG.layers.forEach(function(layer) {
        if (layer.groupHidden || layer.panelHidden) return;
        var sectionName = layer.section || 'Other';
        if (!sectionMap[sectionName]) { sectionMap[sectionName] = []; sectionOrder.push(sectionName); }
        if (layer.group) {
            if (groupsSeen[layer.group]) return;
            groupsSeen[layer.group] = true;
        }
        sectionMap[sectionName].push(layer);
    });

    sectionOrder.forEach(function(sectionName) {
        var layers = sectionMap[sectionName];
        var section = document.createElement('div');
        section.className = 'layer-section';
        var header = document.createElement('div');
        header.className = 'layer-section-header';
        header.innerHTML = '<span class="section-chevron">&#9662;</span> ' + sectionName;
        header.addEventListener('click', function() { section.classList.toggle('collapsed'); });
        section.appendChild(header);

        layers.forEach(function(layer) {
            var layerIds = [layer.id];
            if (layer.glow) layerIds.unshift(layer.id + '-glow');
            if (layer.label_id) layerIds.push(layer.label_id);
            if (layer.group) {
                layerIds = [];
                MAP_CONFIG.layers.forEach(function(l) {
                    if (l.group === layer.group) {
                        if (l.glow) layerIds.push(l.id + '-glow');
                        layerIds.push(l.id);
                        if (l.label_id) layerIds.push(l.label_id);
                    }
                });
            }
            section.appendChild(buildToggle(layer, layerIds));
        });
        body.appendChild(section);
    });
})();

// ── Build legend from MAP_CONFIG.legend ──
(function buildLegend() {
    var legendEl = document.getElementById('legend');
    if (!legendEl) return;
    if (!MAP_CONFIG.legend || MAP_CONFIG.legend.length === 0) { legendEl.style.display = 'none'; return; }
    MAP_CONFIG.legend.forEach(function(section, i) {
        var h4 = document.createElement('h4');
        if (i > 0) h4.style.marginTop = '12px';
        h4.textContent = section.title;
        legendEl.appendChild(h4);
        section.items.forEach(function(item) {
            var row = document.createElement('div');
            row.className = 'legend-row';
            var sw = document.createElement('span');
            var st = item.swatch || 'dot';
            if (st === 'dot') { sw.className = 'swatch-dot'; sw.style.background = item.color; sw.style.color = item.color; }
            else if (st === 'square' || st === 'fill') { sw.className = 'swatch-fill'; if (item.swatchStyle) sw.style.cssText = item.swatchStyle; else sw.style.background = item.color; }
            else if (st === 'line') { sw.className = 'swatch-line'; sw.style.borderColor = item.color; }
            else if (st === 'line-dash') { sw.className = 'swatch-line swatch-line-dash'; sw.style.borderColor = item.color; }
            row.appendChild(sw);
            row.appendChild(document.createTextNode(item.label));
            legendEl.appendChild(row);
        });
    });
})();

var currentBase = MAP_CONFIG.basemap || 'aerial';

var map = new maplibregl.Map({
    container: 'map',
    style: OH2O.basemapStyle(currentBase),
    center: MAP_CONFIG.center,
    zoom: MAP_CONFIG.zoom,
    maxZoom: MAP_CONFIG.maxZoom || 18,
    attributionControl: true
});

if (MAP_CONFIG.fitBounds) {
    map.fitBounds(MAP_CONFIG.fitBounds, { padding: MAP_CONFIG.fitBoundsPadding || 40, duration: 0 });
}

map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ maxWidth: 160, unit: 'imperial' }), 'bottom-left');

// ── Basemap switching (delegates to the shared toolkit) ──
window.switchBase = function(mode) {
    currentBase = OH2O.switchBasemap(map, mode);
    document.querySelectorAll('#toolbar .tb-group:first-child .tb-btn').forEach(function(b) { b.classList.remove('active'); });
    var btn = document.getElementById(mode === 'dark' ? 'btn-dark' : 'btn-aerial');
    if (btn) btn.classList.add('active');
};

window.resetView = function() {
    map.flyTo({ center: MAP_CONFIG.center, zoom: MAP_CONFIG.zoom, pitch: 0, bearing: 0, duration: 1200 });
};
window.planimetricView = function() { map.easeTo({ pitch: 0, bearing: 0, duration: 800 }); };

// ── Measure tool ──
var _measureActive = false, _mPts = [], _mMarkers = [], _mPopup = null;
window.toggleMeasure = function() {
    _measureActive = !_measureActive;
    document.getElementById('btn-measure').classList.toggle('active', _measureActive);
    map.getCanvas().style.cursor = _measureActive ? 'crosshair' : '';
    if (!_measureActive) clearMeasure();
};
function clearMeasure() {
    _mMarkers.forEach(function(m) { m.remove(); });
    _mMarkers = []; _mPts = [];
    if (map.getSource('measure-line')) {
        try { map.removeLayer('measure-line-layer'); } catch(e) {}
        try { map.removeSource('measure-line'); } catch(e) {}
    }
    if (_mPopup) { _mPopup.remove(); _mPopup = null; }
}
function haversine(a, b) {
    var R = 6371000, toR = function(d) { return d * Math.PI / 180; };
    var dLat = toR(b[1]-a[1]), dLon = toR(b[0]-a[0]);
    var s = Math.sin(dLat/2)*Math.sin(dLat/2) + Math.cos(toR(a[1]))*Math.cos(toR(b[1]))*Math.sin(dLon/2)*Math.sin(dLon/2);
    return R * 2 * Math.atan2(Math.sqrt(s), Math.sqrt(1-s));
}
function fmtDist(m) {
    var km = m/1000, mi = km*0.621371;
    return km < 1 ? m.toFixed(0)+' m' : km.toFixed(2)+' km ('+mi.toFixed(2)+' mi)';
}
var GOLD = (OH2O.colors && OH2O.colors.gold) || '#E4A317';
map.on('click', function(e) {
    if (!_measureActive) return;
    var pt = [e.lngLat.lng, e.lngLat.lat];
    _mPts.push(pt);
    var el = document.createElement('div');
    el.style.cssText = 'width:10px;height:10px;background:' + GOLD + ';border:2px solid #fff;border-radius:50%;';
    _mMarkers.push(new maplibregl.Marker({ element: el }).setLngLat(pt).addTo(map));
    if (_mPts.length > 1) {
        var gj = { type:'Feature', geometry:{ type:'LineString', coordinates:_mPts } };
        if (map.getSource('measure-line')) { map.getSource('measure-line').setData(gj); }
        else {
            map.addSource('measure-line', { type:'geojson', data:gj });
            map.addLayer({ id:'measure-line-layer', type:'line', source:'measure-line',
                paint:{'line-color': GOLD,'line-width':2.5,'line-dasharray':[4,3]} });
        }
        var total = 0;
        for (var i=1; i<_mPts.length; i++) total += haversine(_mPts[i-1], _mPts[i]);
        if (_mPopup) _mPopup.remove();
        _mPopup = new maplibregl.Popup({ closeButton:false, closeOnClick:false, className:'measure-popup', anchor:'bottom' })
            .setLngLat(pt).setHTML('<strong>'+fmtDist(total)+'</strong>').addTo(map);
    }
});
map.on('dblclick', function(e) { if (_measureActive) { e.preventDefault(); window.toggleMeasure(); } });
document.addEventListener('keydown', function(e) { if (e.key === 'Escape' && _measureActive) window.toggleMeasure(); });

// ── Fetch GeoJSON sources and load data layers ──
map.on('load', function() {
    var fetches = (MAP_CONFIG.geojsonSources || []).map(function(src) {
        return fetch(src.url)
            .then(function(r) { return r.json(); })
            .then(function(data) { return { id: src.id, data: data }; })
            .catch(function(err) {
                console.warn('Failed to fetch GeoJSON source "' + src.id + '":', err);
                return { id: src.id, data: { type: 'FeatureCollection', features: [] } };
            });
    });

    Promise.all(fetches).then(function(results) {
        var sourceCounts = {};
        results.forEach(function(result) {
            map.addSource(result.id, { type: 'geojson', data: result.data });
            sourceCounts[result.id] = (result.data && result.data.features) ? result.data.features : [];
        });

        if (MAP_CONFIG.inlineSources) {
            Object.keys(MAP_CONFIG.inlineSources).forEach(function(srcId) {
                map.addSource(srcId, MAP_CONFIG.inlineSources[srcId]);
            });
        }

        MAP_CONFIG.layers.forEach(function(layer) {
            var sourceId = layer.source || MAP_CONFIG.sourceId;

            if (layer.glow) {
                var glowDef = { id: layer.id + '-glow', type: layer.type, source: sourceId, paint: {} };
                if (layer.filter) glowDef.filter = layer.filter;
                if (layer.minzoom) glowDef.minzoom = layer.minzoom;
                if (layer.type === 'line') {
                    glowDef.paint = { 'line-color': layer.paint['line-color'] || '#fff',
                        'line-width': layer.glow.width || 10, 'line-opacity': layer.glow.opacity || 0.12, 'line-blur': layer.glow.blur || 6 };
                } else if (layer.type === 'circle') {
                    glowDef.paint = layer.glow.paint || { 'circle-radius': layer.glow.width || 14,
                        'circle-color': layer.paint['circle-color'] || '#fff', 'circle-opacity': layer.glow.opacity || 0.15, 'circle-blur': layer.glow.blur || 1 };
                }
                if (layer.visible === false) glowDef.layout = { visibility: 'none' };
                map.addLayer(glowDef);
            }

            var layerDef = { id: layer.id, type: layer.type, source: sourceId, paint: layer.paint || {} };
            if (layer.layout) layerDef.layout = Object.assign({}, layer.layout);
            if (layer.filter) layerDef.filter = layer.filter;
            if (layer.minzoom) layerDef.minzoom = layer.minzoom;
            if (layer.maxzoom) layerDef.maxzoom = layer.maxzoom;
            if (layer.visible === false || layer.groupHidden) {
                layerDef.layout = layerDef.layout || {};
                layerDef.layout.visibility = 'none';
            }
            map.addLayer(layerDef);
        });

        // Populate feature-count badges
        document.querySelectorAll('.layer-count').forEach(function(badge) {
            var feats = sourceCounts[badge.dataset.countSource];
            if (!feats) { badge.textContent = ''; return; }
            var n = feats.length;
            if (badge.dataset.countFilter) {
                try {
                    var f = JSON.parse(badge.dataset.countFilter);
                    n = feats.filter(function(ft) { return ft.properties && ft.properties[f.prop] === f.val; }).length;
                } catch(e) {}
            }
            badge.textContent = n;
        });

        // ── Popups (single instance) ──
        var _activePopup = null;
        Object.keys(MAP_CONFIG.popups || {}).forEach(function(layerId) {
            map.on('click', layerId, function(e) {
                if (_measureActive) return;
                if (_activePopup) _activePopup.remove();
                var props = e.features[0].properties;
                var coords = e.features[0].geometry.type === 'Point'
                    ? e.features[0].geometry.coordinates.slice() : [e.lngLat.lng, e.lngLat.lat];
                _activePopup = new maplibregl.Popup({ maxWidth: '280px' })
                    .setLngLat(coords).setHTML(MAP_CONFIG.popups[layerId](props, coords)).addTo(map);
            });
            map.on('mouseenter', layerId, function() { if (!_measureActive) map.getCanvas().style.cursor = 'pointer'; });
            map.on('mouseleave', layerId, function() { if (!_measureActive) map.getCanvas().style.cursor = ''; });
        });

        // ── Fit bounds ──
        if (MAP_CONFIG.fitBounds) {
            map.fitBounds(MAP_CONFIG.fitBounds, { padding: MAP_CONFIG.fitBoundsPadding || 60, maxZoom: 14, duration: 1000 });
        } else if (MAP_CONFIG.fitToData) {
            var bounds = null;
            results.forEach(function(result) {
                if (!result.data || !result.data.features) return;
                result.data.features.forEach(function(f) {
                    if (!f.geometry || !f.geometry.coordinates) return;
                    flattenCoords(f.geometry).forEach(function(c) {
                        if (!bounds) bounds = new maplibregl.LngLatBounds(c, c); else bounds.extend(c);
                    });
                });
            });
            if (bounds) map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 1000 });
        }
    });
});

function flattenCoords(geometry) {
    var type = geometry.type, coords = geometry.coordinates, result = [];
    if (type === 'Point') result.push(coords);
    else if (type === 'MultiPoint' || type === 'LineString') result = coords;
    else if (type === 'MultiLineString' || type === 'Polygon') coords.forEach(function(ring) { result = result.concat(ring); });
    else if (type === 'MultiPolygon') coords.forEach(function(poly) { poly.forEach(function(ring) { result = result.concat(ring); }); });
    return result;
}

// ── Coordinate display ──
var coordText = document.getElementById('coord-text');
var coordLink = document.getElementById('coord-link');
function updateCoords() {
    var c = map.getCenter();
    var lat = c.lat.toFixed(4), lng = c.lng.toFixed(4);
    if (coordText) coordText.textContent = lat + ', ' + lng;
    if (coordLink) coordLink.href = 'https://www.google.com/maps/@' + lat + ',' + lng + ',14z';
}
window.copyCoords = function() {
    var text = coordText.textContent;
    try { navigator.clipboard.writeText(text); } catch(e) {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    }
    var toast = document.getElementById('coord-toast');
    toast.textContent = '✓ Copied to clipboard';
    toast.classList.add('copied'); toast.style.opacity = '1';
    setTimeout(function() { toast.classList.remove('copied'); }, 250);
    setTimeout(function() { toast.style.opacity = '0'; }, 1500);
};
map.on('move', updateCoords);
updateCoords();

// ── Layer toggle checkboxes ──
document.querySelectorAll('#controls input[type="checkbox"]').forEach(function(cb) {
    cb.addEventListener('change', function() {
        var vis = this.checked ? 'visible' : 'none';
        this.dataset.layers.split(',').forEach(function(id) {
            if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
        });
    });
});

window._mapEngine = { map: map };

})();
