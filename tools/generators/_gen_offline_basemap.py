"""Build the bundled offline basemap from the province geometry we already ship.

Why this exists
---------------
The basemap in ``frontend/src/map/city-map-style.json`` has two sources and both
are remote (``tiles.openfreemap.org``): a vector ``openmaptiles`` planet tile set
and a raster Natural Earth shaded relief. With no network, MapLibre renders the
``background`` layer only, so the operator sees a flat dark rectangle with our
own overlays floating on it -- the province outlines, the zones and the aircraft
are still there, but nothing says *where* in the world they are.

The user asked for exactly this: "把地图下到本地，这样如果没有联网先显示本地的地图，
精度可以低一点的" -- a local map first, lower precision acceptable.

Design
------
* Source geometry is ``frontend/src/assets/china.json`` (DataV GeoJSON, already a
  project dependency used by ``echarts.js`` for the ECharts province map). We only
  keep 辽宁/吉林/黑龙江, because that is the whole operating area.
* The output is a plain GeoJSON FeatureCollection, read as a GeoJSON source. That
  means no tile server, no sprite atlas and no glyph PBFs -- the three remote
  dependencies collapse into one bundled file.
* Precision is deliberately reduced with Douglas-Peucker (~0.01 deg). This is not
  a shortcut: the file is a *fallback* for the no-network case, it is labelled as
  such in the UI, and carrying survey-grade vertices would triple the bundle for a
  picture that is only ever shown when nothing better can be fetched.
* Labels are NOT rendered offline. Text needs a glyph PBF from the network, and
  the three province names are drawn from a static HTML overlay instead, which
  keeps zero remote dependencies in the offline path.

Determinism
-----------
Output is byte-stable for a given input: features are emitted in a fixed order and
numbers are rounded to 4 decimals. Re-running the generator must not produce a
diff, so the file can be committed and reviewed.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
ROOT = Path(ROOT)

SOURCE = ROOT / 'frontend' / 'src' / 'assets' / 'china.json'
# .json, not .geojson: Vite imports *.json as a module without extra config, and
# adding a geojson loader for one file would be a build-system change to serve a
# file that is already valid JSON. The `.name` field records that it is GeoJSON.
TARGET = ROOT / 'frontend' / 'src' / 'assets' / 'northeast-offline.json'

# 产品范围即东北三省；范围外的几何不进入离线底图。
PROVINCES = ['辽宁省', '吉林省', '黑龙江省']
PROVINCE_LABELS = {
    '辽宁省': [122.6, 41.3],
    '吉林省': [126.2, 43.6],
    '黑龙江省': [127.9, 47.6],
}

# ~0.01 deg is about 1 km on the ground. At the 3-6 zoom a fallback is used at,
# one screen pixel is several km, so nothing visible is lost.
TOLERANCE_DEG = 0.01
DECIMALS = 4


def _perpendicular_distance(point, start, end):
    (x, y), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(points, tolerance):
    """Iterative Douglas-Peucker.

    Recursion depth is a real hazard here: a province ring is 1300 points and a
    pathological split can nest ~log2(n) deep, which is fine, but a naive
    implementation on unsorted input can degenerate to O(n) frames. The explicit
    stack keeps the worst case bounded and the peak memory is one marker pair per
    pending segment.
    """
    if len(points) <= 2:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, worst_at = 0.0, None
        for index in range(first + 1, last):
            distance = _perpendicular_distance(points[index], points[first], points[last])
            if distance > worst:
                worst, worst_at = distance, index
        if worst_at is not None and worst > tolerance:
            keep[worst_at] = True
            stack.append((first, worst_at))
            stack.append((worst_at, last))
    return [point for point, flag in zip(points, keep) if flag]


def _closed(ring):
    """A valid GeoJSON linear ring repeats its first position as its last."""
    if len(ring) >= 2 and ring[0] == ring[-1]:
        return ring
    return ring + [ring[0]]


def _round(point):
    return [round(float(point[0]), DECIMALS), round(float(point[1]), DECIMALS)]


def simplify_ring(ring, tolerance):
    """Simplify an open ring and restore closure.

    The closing vertex is dropped before simplification: it is a duplicate of the
    first point, and leaving it in gives Douglas-Peucker a zero-length baseline
    (start == end), which makes every perpendicular distance degenerate to a
    radius test and flattens the ring into two points.
    """
    body = list(ring)
    if len(body) >= 2 and body[0] == body[-1]:
        body = body[:-1]
    if len(body) < 3:
        return None
    reduced = simplify(body + [body[0]], tolerance)
    reduced = reduced[:-1]
    if len(reduced) < 3:
        return None
    return _closed([_round(p) for p in reduced])


def simplify_polygon(rings, tolerance):
    simplified = []
    for index, ring in enumerate(rings):
        # Only the exterior ring is allowed to disappear. An interior ring that
        # collapses is a hole too small to render anyway, so it is dropped; an
        # exterior that collapses means the whole part is below the tolerance and
        # the part is dropped entirely.
        result = simplify_ring(ring, tolerance)
        if result is None:
            if index == 0:
                return None
            continue
        simplified.append(result)
    return simplified or None


def convert(feature, tolerance):
    geometry = feature.get('geometry') or {}
    kind = geometry.get('type')
    coordinates = geometry.get('coordinates')
    if kind == 'Polygon':
        polygon = simplify_polygon(coordinates, tolerance)
        if polygon is None:
            return None
        return {'type': 'Polygon', 'coordinates': polygon}
    if kind == 'MultiPolygon':
        parts = []
        for rings in coordinates:
            polygon = simplify_polygon(rings, tolerance)
            if polygon is not None:
                parts.append(polygon)
        return {'type': 'MultiPolygon', 'coordinates': parts} if parts else None
    raise ValueError('unexpected geometry type: %r' % kind)


def main():
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    features = []
    stats = []
    for name in PROVINCES:
        match = next((f for f in source['features']
                      if f.get('properties', {}).get('name') == name), None)
        if match is None:
            raise SystemExit('province missing from %s: %s' % (SOURCE.name, name))
        before = json.dumps(match['geometry'], separators=(',', ':'))
        geometry = convert(match, TOLERANCE_DEG)
        if geometry is None:
            raise SystemExit('province simplified away entirely: %s' % name)
        feature = {
            'type': 'Feature',
            'properties': {
                'name': name,
                # Named so the style can treat this as a fallback surface rather
                # than a survey product, and so a screenshot is self-describing.
                'role': 'offline-basemap',
                'precisionDeg': TOLERANCE_DEG,
                'labelAnchor': PROVINCE_LABELS[name],
            },
            'geometry': geometry,
        }
        after = json.dumps(geometry, separators=(',', ':'))
        features.append(feature)
        stats.append((name, len(before), len(after)))

    collection = {
        'type': 'FeatureCollection',
        'name': 'northeast-offline-basemap',
        'properties': {
            'purpose': 'offline fallback basemap for 天窗智巡',
            'source': 'frontend/src/assets/china.json (DataV GeoJSON)',
            'toleranceDeg': TOLERANCE_DEG,
            'licence': 'see docs/model-and-data-v1.md',
        },
        'features': features,
    }
    text = json.dumps(collection, ensure_ascii=False, separators=(',', ':'))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding='utf-8')

    print('wrote', TARGET.relative_to(ROOT))
    for name, before, after in stats:
        print('  %-12s %7d -> %6d bytes  (%d%%)' % (name, before, after, 100 * after // before))
    print('  total %d bytes' % len(text.encode('utf-8')))


if __name__ == '__main__':
    main()
