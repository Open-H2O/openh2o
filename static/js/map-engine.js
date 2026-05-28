/* map-engine.js — Interactive map engine for Open Water Accounting Platform
   Reads from a global MAP_CONFIG object and auto-generates:
   layer panel, legend, MapLibre layers, popup handlers.

   Adapted from VanderDev shared map engine.

   Required globals before this script loads:
     - MAP_CONFIG (object)
     - maplibregl (from MapLibre GL JS CDN)
*/

(function() {
'use strict';

// ── Set page title ──
document.title = MAP_CONFIG.title;

// ── Build layer panel from MAP_CONFIG.layers ──
(function buildLayerPanel() {
    var panel = document.getElementById('controls');
    var groupsSeen = {};

    // Helper: build a single layer-toggle label
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

        label.appendChild(cb);
        label.appendChild(swatch);
        label.appendChild(document.createTextNode(layer.label || layer.id));
        return label;
    }

    // Determine if any layer has a section property (grouped mode)
    var hasSections = MAP_CONFIG.layers.some(function(l) { return l.section; });

    if (!hasSections) {
        // Flat mode: backward compatible with detail page mini-maps
        MAP_CONFIG.layers.forEach(function(layer) {
            if (layer.groupHidden) return;

            var layerIds = [layer.id];
            if (layer.glow) layerIds.unshift(layer.id + '-glow');
            if (layer.group) {
                if (groupsSeen[layer.group]) return;
                groupsSeen[layer.group] = true;
                layerIds = [];
                MAP_CONFIG.layers.forEach(function(l) {
                    if (l.group === layer.group) {
                        if (l.glow) layerIds.push(l.id + '-glow');
                        layerIds.push(l.id);
                    }
                });
            }
            panel.appendChild(buildToggle(layer, layerIds));
        });
        return;
    }

    // Grouped mode: collect sections in order of first appearance
    var sectionOrder = [];
    var sectionMap = {};

    MAP_CONFIG.layers.forEach(function(layer) {
        if (layer.groupHidden) return;
        var sectionName = layer.section || 'Other';
        if (!sectionMap[sectionName]) {
            sectionMap[sectionName] = [];
            sectionOrder.push(sectionName);
        }
        // Dedup groups within sections
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
        header.addEventListener('click', function() {
            section.classList.toggle('collapsed');
        });
        section.appendChild(header);

        layers.forEach(function(layer) {
            var layerIds = [layer.id];
            if (layer.glow) layerIds.unshift(layer.id + '-glow');
            if (layer.group) {
                layerIds = [];
                MAP_CONFIG.layers.forEach(function(l) {
                    if (l.group === layer.group) {
                        if (l.glow) layerIds.push(l.id + '-glow');
                        layerIds.push(l.id);
                    }
                });
            }
            section.appendChild(buildToggle(layer, layerIds));
        });

        panel.appendChild(section);
    });
})();

// ── Build legend from MAP_CONFIG.legend ──
(function buildLegend() {
    var legendEl = document.getElementById('legend');
    if (!MAP_CONFIG.legend || MAP_CONFIG.legend.length === 0) {
        legendEl.style.display = 'none';
        return;
    }
    MAP_CONFIG.legend.forEach(function(section, i) {
        var h4 = document.createElement('h4');
        if (i > 0) h4.style.marginTop = '10px';
        h4.textContent = section.title;
        legendEl.appendChild(h4);
        section.items.forEach(function(item) {
            var row = document.createElement('div');
            row.className = 'legend-row';
            var sw = document.createElement('span');
            var st = item.swatch || 'dot';
            if (st === 'dot') {
                sw.className = 'swatch-dot';
                sw.style.background = item.color;
            } else if (st === 'square' || st === 'fill') {
                sw.className = 'swatch-fill';
                if (item.swatchStyle) sw.style.cssText = item.swatchStyle;
                else sw.style.background = item.color;
            } else if (st === 'line') {
                sw.className = 'swatch-line';
                sw.style.borderColor = item.color;
            } else if (st === 'line-dash') {
                sw.className = 'swatch-line swatch-line-dash';
                sw.style.borderColor = item.color;
            }
            row.appendChild(sw);
            row.appendChild(document.createTextNode(item.label));
            legendEl.appendChild(row);
        });
    });
})();

var currentBase = 'aerial';

var map = new maplibregl.Map({
    container: 'map',
    style: {
        version: 8,
        name: MAP_CONFIG.title,
        sources: {
            'carto-dark': {
                type: 'raster',
                tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
                tileSize: 256,
                maxzoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
            },
            'esri-aerial': {
                type: 'raster',
                tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
                tileSize: 256,
                maxzoom: 19,
                attribution: '&copy; Esri, Maxar, Earthstar Geographics'
            },
            'esri-labels': {
                type: 'raster',
                tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],
                tileSize: 256,
                maxzoom: 19
            }
        },
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
        layers: [
            { id: 'background', type: 'background', paint: { 'background-color': '#1a3040' } },
            { id: 'dark-tiles', type: 'raster', source: 'carto-dark', layout: { visibility: 'none' }, paint: { 'raster-opacity': 1.0 } },
            { id: 'aerial-tiles', type: 'raster', source: 'esri-aerial', paint: { 'raster-opacity': 1.0 } },
            { id: 'aerial-labels', type: 'raster', source: 'esri-labels', paint: { 'raster-opacity': 0.7 } }
        ]
    },
    center: MAP_CONFIG.center,
    zoom: MAP_CONFIG.zoom,
    maxZoom: MAP_CONFIG.maxZoom || 18,
    attributionControl: true
});

if (MAP_CONFIG.fitBounds) {
    map.fitBounds(MAP_CONFIG.fitBounds, {
        padding: MAP_CONFIG.fitBoundsPadding || 40,
        duration: 0
    });
}

map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ maxWidth: 160, unit: 'imperial' }), 'bottom-left');

// ── Basemap switching ──
window.switchBase = function(mode) {
    currentBase = mode;
    document.querySelectorAll('#toolbar .tb-group:first-child .tb-btn').forEach(function(b) { b.classList.remove('active'); });
    if (mode === 'aerial') {
        document.getElementById('btn-aerial').classList.add('active');
        map.setLayoutProperty('dark-tiles', 'visibility', 'none');
        map.setLayoutProperty('aerial-tiles', 'visibility', 'visible');
        map.setLayoutProperty('aerial-labels', 'visibility', 'visible');
        map.setPaintProperty('background', 'background-color', '#1a3040');
    } else {
        document.getElementById('btn-dark').classList.add('active');
        map.setLayoutProperty('dark-tiles', 'visibility', 'visible');
        map.setLayoutProperty('aerial-tiles', 'visibility', 'none');
        map.setLayoutProperty('aerial-labels', 'visibility', 'none');
        map.setPaintProperty('background', 'background-color', '#040608');
    }
};

// ── Reset view ──
window.resetView = function() {
    map.flyTo({ center: MAP_CONFIG.center, zoom: MAP_CONFIG.zoom, pitch: 0, bearing: 0, duration: 1200 });
};

// ── Planimetric (top-down, north-up) ──
window.planimetricView = function() {
    map.easeTo({ pitch: 0, bearing: 0, duration: 800 });
};

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

map.on('click', function(e) {
    if (!_measureActive) return;
    var pt = [e.lngLat.lng, e.lngLat.lat];
    _mPts.push(pt);
    var el = document.createElement('div');
    el.style.cssText = 'width:10px;height:10px;background:' + (window.OH2O ? OH2O.colors.gold : '#E4A317') + ';border:2px solid #fff;border-radius:50%;';
    _mMarkers.push(new maplibregl.Marker({ element: el }).setLngLat(pt).addTo(map));
    if (_mPts.length > 1) {
        var gj = { type:'Feature', geometry:{ type:'LineString', coordinates:_mPts } };
        if (map.getSource('measure-line')) { map.getSource('measure-line').setData(gj); }
        else {
            map.addSource('measure-line', { type:'geojson', data:gj });
            map.addLayer({ id:'measure-line-layer', type:'line', source:'measure-line',
                paint:{'line-color': (window.OH2O ? OH2O.colors.gold : '#E4A317'),'line-width':2.5,'line-dasharray':[4,3]} });
        }
        var total = 0;
        for (var i=1; i<_mPts.length; i++) total += haversine(_mPts[i-1], _mPts[i]);
        if (_mPopup) _mPopup.remove();
        _mPopup = new maplibregl.Popup({ closeButton:false, closeOnClick:false, className:'measure-popup', anchor:'bottom' })
            .setLngLat(pt).setHTML(fmtDist(total)).addTo(map);
    }
});
map.on('dblclick', function(e) { if (_measureActive) { e.preventDefault(); window.toggleMeasure(); } });
document.addEventListener('keydown', function(e) { if (e.key === 'Escape' && _measureActive) window.toggleMeasure(); });

// ── Fetch GeoJSON sources and load data layers ──
map.on('load', function() {

    // Fetch all GeoJSON sources defined in MAP_CONFIG
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

        // Add each GeoJSON source to the map
        results.forEach(function(result) {
            map.addSource(result.id, {
                type: 'geojson',
                data: result.data
            });
        });

        // Add inline GeoJSON sources if provided
        if (MAP_CONFIG.inlineSources) {
            Object.keys(MAP_CONFIG.inlineSources).forEach(function(srcId) {
                map.addSource(srcId, MAP_CONFIG.inlineSources[srcId]);
            });
        }

        // Add configured layers
        MAP_CONFIG.layers.forEach(function(layer) {
            var sourceId = layer.source || MAP_CONFIG.sourceId;

            // Auto-generate glow layer if specified
            if (layer.glow) {
                var glowDef = {
                    id: layer.id + '-glow',
                    type: layer.type,
                    source: sourceId,
                    paint: {}
                };
                if (layer.filter) glowDef.filter = layer.filter;
                if (layer.minzoom) glowDef.minzoom = layer.minzoom;

                if (layer.type === 'line') {
                    var lineColor = layer.paint['line-color'] || '#fff';
                    glowDef.paint = {
                        'line-color': lineColor,
                        'line-width': layer.glow.width || 10,
                        'line-opacity': layer.glow.opacity || 0.12,
                        'line-blur': layer.glow.blur || 6
                    };
                } else if (layer.type === 'circle') {
                    var circleColor = layer.paint['circle-color'] || '#fff';
                    glowDef.paint = {
                        'circle-radius': layer.glow.width || 14,
                        'circle-color': circleColor,
                        'circle-opacity': layer.glow.opacity || 0.15,
                        'circle-blur': layer.glow.blur || 1
                    };
                }
                if (layer.visible === false) {
                    glowDef.layout = { visibility: 'none' };
                }
                map.addLayer(glowDef);
            }

            var layerDef = {
                id: layer.id,
                type: layer.type,
                source: sourceId,
                paint: layer.paint || {}
            };
            if (layer.layout) layerDef.layout = Object.assign({}, layer.layout);
            if (layer.filter) layerDef.filter = layer.filter;
            if (layer.minzoom) layerDef.minzoom = layer.minzoom;
            if (layer.visible === false || layer.groupHidden) {
                layerDef.layout = layerDef.layout || {};
                layerDef.layout.visibility = 'none';
            }

            map.addLayer(layerDef);
        });

        // ── Popups (single instance to prevent stacking) ──
        var _activePopup = null;
        var popupLayerIds = Object.keys(MAP_CONFIG.popups || {});
        popupLayerIds.forEach(function(layerId) {
            map.on('click', layerId, function(e) {
                if (_measureActive) return;
                if (_activePopup) _activePopup.remove();
                var props = e.features[0].properties;
                var coords = e.features[0].geometry.type === 'Point'
                    ? e.features[0].geometry.coordinates.slice()
                    : [e.lngLat.lng, e.lngLat.lat];
                var html = MAP_CONFIG.popups[layerId](props, coords);
                _activePopup = new maplibregl.Popup()
                    .setLngLat(coords)
                    .setHTML(html)
                    .addTo(map);
            });

            map.on('mouseenter', layerId, function() {
                if (!_measureActive) map.getCanvas().style.cursor = 'pointer';
            });
            map.on('mouseleave', layerId, function() {
                if (!_measureActive) map.getCanvas().style.cursor = '';
            });
        });

        // ── Fit to data bounds ──
        if (MAP_CONFIG.fitBounds) {
            map.fitBounds(MAP_CONFIG.fitBounds, {
                padding: MAP_CONFIG.fitBoundsPadding || 60,
                maxZoom: 14,
                duration: 1000
            });
        } else if (MAP_CONFIG.fitToData) {
            var bounds = null;
            results.forEach(function(result) {
                if (!result.data || !result.data.features || result.data.features.length === 0) return;
                result.data.features.forEach(function(f) {
                    if (!f.geometry || !f.geometry.coordinates) return;
                    var coords = flattenCoords(f.geometry);
                    coords.forEach(function(c) {
                        if (!bounds) {
                            bounds = new maplibregl.LngLatBounds(c, c);
                        } else {
                            bounds.extend(c);
                        }
                    });
                });
            });
            if (bounds) {
                map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 1000 });
            }
        }

    });
});

// ── Flatten geometry coordinates to an array of [lng, lat] pairs ──
function flattenCoords(geometry) {
    var type = geometry.type;
    var coords = geometry.coordinates;
    var result = [];

    if (type === 'Point') {
        result.push(coords);
    } else if (type === 'MultiPoint' || type === 'LineString') {
        result = coords;
    } else if (type === 'MultiLineString' || type === 'Polygon') {
        coords.forEach(function(ring) { result = result.concat(ring); });
    } else if (type === 'MultiPolygon') {
        coords.forEach(function(polygon) {
            polygon.forEach(function(ring) { result = result.concat(ring); });
        });
    }
    return result;
}

// ── Coordinate display ──
var coordText = document.getElementById('coord-text');
var coordLink = document.getElementById('coord-link');
function updateCoords() {
    var c = map.getCenter();
    var lat = c.lat.toFixed(4), lng = c.lng.toFixed(4);
    coordText.textContent = lat + ', ' + lng;
    if (coordLink) coordLink.href = 'https://www.google.com/maps/@' + lat + ',' + lng + ',14z';
}
window.copyCoords = function() {
    var text = coordText.textContent;
    try { navigator.clipboard.writeText(text); } catch(e) {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select(); document.execCommand('copy');
        document.body.removeChild(ta);
    }
    var toast = document.getElementById('coord-toast');
    toast.textContent = '✓ Copied to clipboard';
    toast.classList.add('copied');
    toast.style.opacity = '1';
    setTimeout(function() { toast.classList.remove('copied'); }, 250);
    setTimeout(function() { toast.style.opacity = '0'; }, 1500);
};
map.on('move', updateCoords);
updateCoords();

// ── Layer toggle checkboxes ──
document.querySelectorAll('#controls input[type="checkbox"]').forEach(function(cb) {
    cb.addEventListener('change', function() {
        var layers = this.dataset.layers.split(',');
        var vis = this.checked ? 'visible' : 'none';
        layers.forEach(function(id) {
            if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
        });
    });
});

// Expose map instance for external use
window._mapEngine = { map: map };

})();
