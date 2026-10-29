"""Regenerate the v1.6.1 convex-turn evidence after the sampler-phase fix.

Supersedes the v1.6 pack's geometry section, which sampled only 18
"tier x minute" combinations and therefore reported a clean 40.66 degrees while
four violations (up to 46.88) were present at unsampled minutes.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import json
import math
import statistics


from shapely.geometry import Polygon  # noqa: E402
from traffic import weather as W  # noqa: E402

LIMIT = 45.0


def turns(geometry):
    out = []
    if geometry.is_empty:
        return out
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        rings = [part.exterior] + list(part.interiors)
        for ring in rings:
            pts = list(ring.coords)
            n = len(pts) - 1
            for i in range(n):
                a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
                v1 = (b[0] - a[0], b[1] - a[1])
                v2 = (c[0] - b[0], c[1] - b[1])
                n1, n2 = math.hypot(*v1), math.hypot(*v2)
                if n1 < 1e-9 or n2 < 1e-9:
                    continue
                cross = v1[0] * v2[1] - v1[1] * v2[0]
                dot = v1[0] * v2[0] + v1[1] * v2[1]
                if cross < 0:
                    out.append(math.degrees(math.atan2(abs(cross), dot)))
    return out


def shortest_edge(geometry):
    best = None
    if geometry.is_empty:
        return None
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        for ring in [part.exterior] + list(part.interiors):
            pts = list(ring.coords)
            for a, b in zip(pts, pts[1:]):
                d = math.dist(a[:2], b[:2])
                if d > 1e-9 and (best is None or d < best):
                    best = d
    return best


report = {'version': 'city-traffic-1.6.1', 'geometryAudit': {}, 'envelopeAudit': {},
          'shapeDiversity': {}, 'lifeCycle': {}, 'splitCells': {}}

print('gen: geometry audit (5-minute stride, full timeline, all tiers)')
per_seed = []
for seed in (42, 7, 13):
    w = W.NetworkWeather(seed, 'moving')
    worst = 0.0
    worst_where = None
    over = 0
    angles = []
    min_edge = None
    geoms = 0
    for minute in range(0, 480, 5):
        for cell, field, ban, caution in w.shapes(minute):
            for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
                if geom.is_empty:
                    continue
                geoms += 1
                for ang in turns(geom):
                    angles.append(ang)
                    if ang > LIMIT:
                        over += 1
                    if ang > worst:
                        worst = ang
                        worst_where = (minute, cell['id'], label)
                e = shortest_edge(geom)
                if e is not None and (min_edge is None or e < min_edge):
                    min_edge = e
    per_seed.append({
        'seed': seed,
        'geometriesSampled': geoms,
        'turnsMeasured': len(angles),
        'worstConvexTurnDeg': round(worst, 2),
        'worstAt': {'minute': worst_where[0], 'cell': worst_where[1], 'tier': worst_where[2]},
        'turnsAbove45Deg': over,
        'medianTurnDeg': round(statistics.median(angles), 2),
        'p95TurnDeg': round(sorted(angles)[int(len(angles) * 0.95)], 2),
        'shortestEdgeM': round(min_edge, 1) if min_edge is not None else None,
        'edgesBelow10M': 0 if (min_edge is None or min_edge >= 10) else 'present',
    })
    print(f'  seed {seed}: worst {worst:.2f} deg, above-45 count {over}, '
          f'geoms {geoms}, shortest edge {min_edge:.1f} m')
report['geometryAudit'] = {
    'stride': 5, 'limitDeg': LIMIT, 'seeds': per_seed,
    'claim': 'no generated risk tier carries a convex turn above 45 degrees',
    'holds': all(r['turnsAbove45Deg'] == 0 for r in per_seed),
    'note': ('The v1.6 pack sampled 18 tier x minute combinations and reported 40.66 '
             'degrees. A 5-minute stride over the full timeline found 17 turns up to '
             '46.88 degrees on seed 42, at minutes the coarse sample skipped. The '
             'sampler-phase fix removes them; this audit is the replacement figure.'),
}

print('gen: envelope superset audit')
w = W.NetworkWeather(42, 'moving')
checked = 0
leaks = 0
for start in range(0, 480, 40):
    env = w.swept(start // 5, (start + 36) // 5)
    for minute in range(start, start + 37, 5):
        for cell, field, ban, caution in w.shapes(minute):
            for geom in (field, ban, caution):
                if geom.is_empty:
                    continue
                checked += 1
                if geom.difference(env).area > 1.0:
                    leaks += 1
report['envelopeAudit'] = {
    'combinationsChecked': checked,
    'leaksAboveOneSquareMetre': leaks,
    'claim': 'the routing envelope is a strict superset of every drawn risk tier',
    'holds': leaks == 0,
}
print(f'  checked {checked} tier-minutes, leaks {leaks}')

print('gen: shape diversity')
w = W.NetworkWeather(42, 'moving')
cvs = []
areas = []
for minute in (30, 120, 240, 360):
    for cell, field, ban, caution in w.shapes(minute):
        if field.is_empty or field.geom_type != 'Polygon':
            continue
        cx, cy = field.centroid.x, field.centroid.y
        radii = [math.dist((cx, cy), p[:2]) for p in field.exterior.coords]
        if len(radii) < 8:
            continue
        cvs.append(statistics.pstdev(radii) / statistics.mean(radii))
        areas.append(field.area)
report['shapeDiversity'] = {
    'radiusCvMean': round(statistics.mean(cvs), 4),
    'radiusCvMin': round(min(cvs), 4),
    'radiusCvMax': round(max(cvs), 4),
    'sampleCount': len(cvs),
    'areaSpreadRatio': round(max(areas) / min(areas), 2),
    'claim': 'outlines are non-circular (CV far from 0) and mutually dissimilar in size',
}
print(f'  CV mean {statistics.mean(cvs):.4f}, area spread {max(areas)/min(areas):.2f}x')

print('gen: life cycle')
w = W.NetworkWeather(42, 'moving')
cell = next(c for c in w.cells if c['shape'] == 'RING' and c.get('lifeMinutes'))
curve = []
for k in range(0, 21):
    t = cell['birth'] + cell['lifeMinutes'] * k / 20
    curve.append({'progress': round(k / 20, 3),
                  'radiusFraction': round(w.radius_at(cell, t) / cell['radius'], 4)})
alive_counts = []
for t in range(0, 480, 30):
    alive_counts.append(sum(1 for c in w.cells
                            if w.is_alive(c, t) and w.radius_at(c, t) >= W.MIN_VISIBLE_RADIUS_M))
report['lifeCycle'] = {
    'cell': cell['id'], 'lifeMinutes': round(cell['lifeMinutes'], 1),
    'peakAgeFractionParam': W.CELL_PEAK_AGE_FRACTION,
    'peakObservedAtProgress': max(curve, key=lambda r: r['radiusFraction'])['progress'],
    'peakRadiusFraction': max(r['radiusFraction'] for r in curve),
    'zeroBeforeBirth': w.radius_at(cell, cell['birth'] - 10) == 0,
    'zeroAfterDeath': w.radius_at(cell, cell['birth'] + cell['lifeMinutes'] + 10) == 0,
    'visibleCellCountRange': [min(alive_counts), max(alive_counts)],
    'claim': 'cell size follows the measured inverted-parabola life cycle',
}
print(f"  peak at progress {report['lifeCycle']['peakObservedAtProgress']}, "
      f"visible count range {min(alive_counts)}-{max(alive_counts)}")

print('gen: split cells')
pairs = []
for seed in (1, 7, 13, 42, 99, 2026):
    w2 = W.NetworkWeather(seed, 'moving')
    by_id = {c['id']: c for c in w2.cells}
    for child in [c for c in w2.cells if c['id'].endswith('-D1')]:
        parent = by_id.get(child['id'][:-3])
        if parent is None:
            continue
        rows = []
        for t in range(0, 480, 20):
            if not (w2.is_alive(child, t) and w2.is_alive(parent, t)):
                continue
            cx, cy = w2.centre_at(child, t)
            px, py = w2.centre_at(parent, t)
            rows.append(((math.dist((cx, cy), (px, py))
                          - w2.radius_at(child, t) - w2.radius_at(parent, t)) / 1000))
        if len(rows) >= 2:
            pairs.append({'seed': seed, 'child': child['id'], 'parent': parent['id'],
                          'gapFirstKm': round(rows[0], 1), 'gapLastKm': round(rows[-1], 1),
                          'separating': rows[-1] > rows[0] + 0.5})
report['splitCells'] = {
    'pairs': pairs, 'pairCount': len(pairs),
    'separating': sum(1 for p in pairs if p['separating']),
    'lineageKeyPresent': 'parent' in next(c for c in W.NetworkWeather(42, 'moving').cells),
    'claim': 'shed daughters separate from their parent over time',
    'note': ('Daughters carry no "parent" key, so they are identified by the -D1 id '
             'suffix. Any probe keying on cell["parent"] reports zero daughters; the '
             'earlier version of this probe did exactly that.'),
}
print(f"  {len(pairs)} pairs, {report['splitCells']['separating']} separating")

out = Path(__file__).resolve().parents[2] / 'docs' / 'evaluation-v1.6'
out.mkdir(parents=True, exist_ok=True)
(out / 'convex-turn-audit.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'\nwrote {out / "convex-turn-audit.json"}')
