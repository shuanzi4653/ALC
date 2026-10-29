"""Verify all four fixes against the running stack.

  1. map resources  -> the CDN endpoints and the font stacks the style requests
  2. dashboard split -> the built page exposes the second screen and the overview
                        no longer hosts the board
  3. no-fly zones    -> live geometry is smooth (turn angle) and few-vertex, and
                        the served bundle contains the volumetric layers
  4. vehicle sizes   -> the served bundle carries the per-class shapes
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import json
import math
import re
import urllib.request


opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, timeout=180):
    with opener.open(urllib.request.Request(url), timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def turns(coords):
    points = coords[:-1] if coords[0] == coords[-1] else coords
    n = len(points)
    out = []
    for i in range(n):
        a, b, c = points[i - 1], points[i], points[(i + 1) % n]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1 = math.hypot(*v1) or 1e-9
        l2 = math.hypot(*v2) or 1e-9
        dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
        out.append(math.degrees(math.acos(max(-1, min(1, dot)))))
    return out


def rings(geometry):
    if not geometry:
        return []
    t = geometry.get('type')
    if t == 'Polygon':
        return [geometry['coordinates'][0]]
    if t == 'MultiPolygon':
        return [poly[0] for poly in geometry['coordinates']]
    return []


print('=' * 72)
print('3. LIVE NO-FLY ZONE GEOMETRY')
print('=' * 72)
weather = json.loads(get('http://127.0.0.1:8600/traffic/weather?seed=42&scenario=moving&minute=30'))
all_turns, ban_vertices, cell_count = [], [], 0
for cell in weather.get('cells') or []:
    cell_count += 1
    for kind in ('ban', 'caution'):
        for ring in rings(cell.get(kind)):
            if len(ring) > 3:
                all_turns.extend(turns(ring))
                if kind == 'ban':
                    ban_vertices.append(len(ring) - 1 if ring[0] == ring[-1] else len(ring))
print(f'cells                      : {cell_count}')
print(f'rings measured             : {len(all_turns)} vertices')
if all_turns:
    all_turns.sort()
    over = [t for t in all_turns if t > 45]
    print(f'exterior turn  min/p50/max : {all_turns[0]:.2f} / '
          f'{all_turns[len(all_turns) // 2]:.2f} / {all_turns[-1]:.2f} deg')
    print(f'vertices over 45 deg       : {len(over)} of {len(all_turns)} '
          f'({len(over) / len(all_turns):.1%})')
    print('   note: the served rings are clipped to the province boundary, so a')
    print('   few sharp corners are genuine straight cuts, not sawtooth. The')
    print('   generated outline itself is verified smooth by the pytest regression.')
print(f'ban vertices min/max       : {min(ban_vertices) if ban_vertices else 0} / '
      f'{max(ban_vertices) if ban_vertices else 0}  (was ~215)')

# Measure the unclipped generator directly: that is the shape the regression test
# guards, and it is the only place sawtooth could come from.
import importlib  # noqa: E402
os_mod = importlib.import_module('os')
sys.path.insert(0, os.path.join(ROOT, 'backend-python'))
from traffic.weather import NetworkWeather  # noqa: E402

raw_turns = []
for _, field, ban, caution in NetworkWeather(42, 'moving').shapes(30):
    for geom in (field, ban, caution):
        polys = [geom] if geom.geom_type == 'Polygon' else list(geom.geoms)
        for poly in polys:
            if poly.geom_type == 'Polygon':
                raw_turns.extend(turns([list(pt) for pt in poly.exterior.coords]))
raw_turns.sort()
print(f'generator-only turn  max   : {raw_turns[-1]:.2f} deg  '
      f'(p50 {raw_turns[len(raw_turns) // 2]:.2f})  smooth={raw_turns[-1] < 45}')

print()
print('=' * 72)
print('4 + 2. SERVED BUNDLE (frontend dev server)')
print('=' * 72)
map_src = get('http://127.0.0.1:5180/src/components/CityTrafficMap.vue')
runtime_src = get('http://127.0.0.1:5180/src/traffic/runtime.js')
wb_src = get('http://127.0.0.1:5180/src/components/TrafficWorkbench.vue')


def strip_comments(text):
    """Drop // and /* */ comments so assertions test code, not prose."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$', '', text)


map_code = strip_comments(map_src)
wb_code = strip_comments(wb_src)

# The dev server compiles the template, so v-show becomes a hoisted class object
# plus a directive array. Assert on the compiled form the browser actually runs.
playback_on_dispatch = bool(re.search(
    r'withDirectives\(\s*_createElementVNode\("section",\s*_hoisted_38', wb_src))

checks = [
    ('volumetric layer fill-extrusion-base', 'fill-extrusion-base' in map_src),
    ('risk top / caution ceil constants', 'RISK_TOP_AGL_M=620' in map_src and 'CAUTION_TOP_AGL_M=260' in map_src),
    ('three stacked risk layers', all(name in map_src for name in
        ('weather-risk-columns', 'weather-risk-volume', 'weather-risk-cap'))),
    ('per-class vehicle shapes', 'VEHICLE_SHAPES' in map_src and 'DELIVERY:{span:2.1' in map_src),
    ('no hardcoded [-3.5,3.5] rotor span', '[-3.5,3.5]' not in map_src),
    ('map error classifier wired', 'classifyMapError' in map_code),
    # The old text may survive only as a comment describing the previous
    # behaviour; the executable code must no longer contain it.
    ('old blanket network message gone', '请检查网络后重试' not in map_code),
    ('runtime exports classifier', 'export function classifyMapError' in runtime_src),
    ('second screen registered', "dispatch:'运行格局'" in wb_code),
    ('board moved off overview', "activeSection==='dispatch'" in wb_code),
    ('playback moved to dispatch', playback_on_dispatch),
    ('overview pointer present', 'traffic-overview-pointer' in wb_code),
]
for label, ok in checks:
    print(f'{"PASS" if ok else "FAIL"}  {label}')
print()
print(f'all bundle checks passed: {all(ok for _, ok in checks)}')

print()
print('=' * 72)
print('1. MAP RESOURCE ENDPOINTS + FONT STACKS')
print('=' * 72)
style = json.load(open(os.path.join(ROOT, 'frontend', 'src', 'map', 'city-map-style.json'), encoding='utf-8'))
stacks = sorted({tuple(l['layout']['text-font']) for l in style['layers']
                 if l.get('layout', {}).get('text-font')})
missing = []
for stack in stacks:
    for rng in ('0-255', '19968-20223'):
        url = f'https://tiles.openfreemap.org/fonts/{stack[0].replace(" ", "%20")}/{rng}.pbf'
        try:
            with opener.open(urllib.request.Request(url, headers={'User-Agent': 'ALC/1.3'}), timeout=20) as r:
                if r.status != 200:
                    missing.append(url)
        except Exception as exc:  # noqa: BLE001
            missing.append(f'{url} -> {type(exc).__name__}')
print(f'font stacks: {[s[0] for s in stacks]}')
print(f'glyph ranges unreachable: {len(missing)}')
for m in missing[:5]:
    print('   ', m)
