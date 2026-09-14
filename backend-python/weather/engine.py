"""Deterministic births, continuous advection, lifetimes and risk derivation.

No real station or calibrated probability is implied by synthetic scenarios.
Time is relative to a persisted origin, never modulo a wall-clock period.
"""
import math
import random
import hashlib
import json
from pathlib import Path
from functools import lru_cache

from shapely.geometry import Point, Polygon, mapping
from shapely.ops import unary_union

from .geometry import boundary, project, unproject, geojson, BOUNDARY_VERSION

RULE_BYTES = (Path(__file__).resolve().parents[2] / 'config' / 'rules-v1.json').read_bytes()
RULE_SPEC = json.loads(RULE_BYTES)
RULE_VERSION = RULE_SPEC['version'] + ':' + hashlib.sha256(RULE_BYTES).hexdigest()[:12]
FACTOR_RULES = {f['key']: f for f in RULE_SPEC['factors']}
MODEL_VERSION = 'continuous-weather-2:' + RULE_VERSION
REGIONS = {
    'liaoning': {'name': '辽宁省', 'center': [123.25, 42.02], 'from': [122.90, 42.02], 'to': [123.60, 42.02]},
    'jilin': {'name': '吉林省', 'center': [125.20, 44.05], 'from': [124.85, 44.05], 'to': [125.55, 44.05]},
    'heilongjiang': {'name': '黑龙江省', 'center': [126.40, 46.10], 'from': [126.05, 46.10], 'to': [126.75, 46.10]},
}
SCENARIOS = ('clear', 'wind', 'rain', 'storm', 'crossing', 'multi', 'unknown', 'calm')


class WeatherWorld:
    def __init__(self, seed=42, scenario='crossing', origin='2026-09-12T00:00:00+08:00', uncertainty=True):
        if scenario not in SCENARIOS:
            raise ValueError('Unknown scenario')
        self.seed, self.scenario, self.origin = int(seed), scenario, origin
        self.uncertainty = uncertainty

    def wind(self, x, y, minute):
        if self.scenario == 'calm':
            return 0.0, 0.0
        # Smooth vector field. Advection uses the integral of these periodic components.
        return (3.0 + math.sin(minute / 45 + y / 180000),
                1.5 + math.cos(minute / 60 + x / 180000))

    @lru_cache(maxsize=512)
    def cells(self, minute):
        if self.scenario in ('clear', 'calm', 'unknown'):
            return []
        result = []
        for region_index, (region_id, region) in enumerate(REGIONS.items()):
            cx, cy = project(region['center'])
            # Birth every 100 minutes, finite lifetime, positions vary by seed AND birth index.
            for birth in range(math.floor((minute - 150) / 100), math.floor(minute / 100) + 1):
                rng = random.Random(self.seed * 100003 + region_index * 1009 + birth * 97)
                born = birth * 100 - 30
                age = minute - born
                if not 0 <= age < 150:
                    continue
                count = 2 if self.scenario == 'multi' else 1
                for index in range(count):
                    kind = 'WIND' if self.scenario == 'wind' else 'PRECIPITATION' if self.scenario == 'rain' else 'THUNDER_PROBABILITY'
                    phase = rng.uniform(-math.pi, math.pi)
                    x0 = cx + rng.uniform(-5000, 5000) + index * 14000
                    y0 = cy - 12000 + rng.uniform(-3000, 3000)
                    # Integral in seconds of a bounded, changing velocity, rather than v(now)*age.
                    vx, vy = 0.5 + index, 5.0 + region_index * .4
                    x = x0 + vx * age * 60 + 1800 * (math.cos(phase) - math.cos(age / 30 + phase))
                    y = y0 + vy * age * 60 + 1200 * (math.sin(age / 40 + phase) - math.sin(phase))
                    growth = min(1.0, age / 15) * min(1.0, (150 - age) / 35)
                    intensity = growth * (1 + .12 * math.sin(age / 25 + phase))
                    peak = 15 if kind == 'WIND' else 9 if kind == 'PRECIPITATION' else .8
                    value = min(1, peak * intensity) if kind == 'THUNDER_PROBABILITY' else peak * intensity
                    radius = 4200 + 2200 * intensity
                    vertices = []
                    for k in range(20):
                        theta = k * math.tau / 20
                        irregular = 1 + .12 * math.sin(3 * theta + age / 60 + phase)
                        vertices.append((x + radius * irregular * math.cos(theta),
                                         y + radius * .75 * irregular * math.sin(theta)))
                    polygon = Polygon(vertices).intersection(boundary(region['name']))
                    if polygon.is_empty or value <= 0:
                        continue
                    result.append({'cellId': f'{region_id}:{birth}:{index}:{kind}', 'regionId': region_id,
                                   'kind': kind, 'bornMinute': born, 'expiresMinute': born + 150,
                                   'state': 'GROWING' if age < 15 else 'DISSIPATING' if age > 115 else 'ACTIVE',
                                   'value': value, 'center': [x, y], 'polygon': polygon,
                                   'velocityMps': [vx + math.sin(age / 30 + phase), vy + .5 * math.cos(age / 40 + phase)]})
        return result

    @lru_cache(maxsize=512)
    def risks(self, minute, region_id, buffer_m=500):
        areas = []
        for cell in self.cells(minute):
            if cell['regionId'] != region_id:
                continue
            factor = FACTOR_RULES[{'WIND': 'windSpeed', 'PRECIPITATION': 'precipMmh', 'THUNDER_PROBABILITY': 'thunderProb'}[cell['kind']]]
            warn, ban = factor['warnValue'], factor['banValue']
            if cell['value'] < warn:
                continue
            # The uncertain footprint is a scenario envelope, NOT a calibrated probability.
            uncertainty_m = 800 if self.uncertainty else 0
            influence = cell['polygon'].buffer(buffer_m + uncertainty_m).intersection(boundary(REGIONS[region_id]['name']))
            areas.append({'id': cell['cellId'], 'zoneType': 'BAN' if cell['value'] >= ban else 'CAUTION',
                          'reason': cell['kind'], 'value': round(cell['value'], 3), 'warnThreshold': warn,
                          'banThreshold': ban, 'bufferM': buffer_m, 'uncertaintyM': uncertainty_m,
                          'sourceCellId': cell['cellId'], 'geometry': influence})
        return areas

    def swept(self, start, end, region_id, buffer_m=500):
        # At most one-minute spacing plus a conservative envelope for movement and shape change.
        # Bound: <= 8 m/s translation + 10 m/s boundary growth, including birth/death.
        return self._swept_minutes(math.floor(start), math.ceil(end), region_id, buffer_m)

    @lru_cache(maxsize=2048)
    def _swept_minutes(self, lo, hi, region_id, buffer_m):
        shapes = [area['geometry'] for t in range(lo, hi + 1)
                  for area in self.risks(t, region_id, buffer_m)]
        if not shapes:
            return Polygon()
        return unary_union(shapes).buffer(18 * 60)

    def frame(self, minute, region_id=None, buffer_m=500):
        cells, areas = [], []
        for cell in self.cells(minute):
            if region_id and cell['regionId'] != region_id:
                continue
            cells.append({**{k: v for k, v in cell.items() if k not in ('polygon', 'center')},
                          'center': unproject(cell['center']), 'geometry': geojson(cell['polygon']),
                          'value': round(cell['value'], 3), 'source': 'SIMULATED_CELL'})
        for rid in ([region_id] if region_id else REGIONS):
            for area in self.risks(minute, rid, buffer_m):
                areas.append({**area, 'geometry': geojson(area['geometry']), 'regionId': rid})
        points = []
        # Actual spatial grid, clipped to province polygons, no station-cluster replication.
        selected = boundary(REGIONS[region_id]['name'] if region_id else None)
        xmin, ymin, xmax, ymax = selected.bounds
        spacing = 23000 if region_id else 55000
        x = xmin + spacing / 2
        while x < xmax:
            y = ymin + spacing / 2
            while y < ymax:
                if selected.contains(Point(x, y)):
                    u, v = self.wind(x, y, minute)
                    speed = math.hypot(u, v)
                    points.append({'coord': unproject([x, y]), 'u': u, 'v': v, 'speed': round(speed, 2),
                                   'direction': round((math.degrees(math.atan2(-u, -v)) + 360) % 360),
                                   'source': 'SIMULATED_GRID'})
                y += spacing
            x += spacing
        local_wind = {}
        for rid, region in REGIONS.items():
            cx, cy = project(region['center'])
            local_wind[rid] = []
            for ix in range(-9, 10):
                for iy in range(-9, 10):
                    x, y = cx + ix * 6500, cy + iy * 6500
                    if boundary(region['name']).contains(Point(x, y)):
                        u, v = self.wind(x, y, minute)
                        local_wind[rid].append({'coord': unproject([x, y]), 'u': u, 'v': v,
                                               'speed': round(math.hypot(u, v), 2),
                                               'direction': round((math.degrees(math.atan2(-u, -v)) + 360) % 360),
                                               'source': 'SIMULATED_GRID'})
        return {'minute': minute, 'cells': cells, 'areas': areas, 'wind': points, 'localWind': local_wind,
                'assessmentStatus': 'UNKNOWN' if self.scenario == 'unknown' else 'VALID',
                'source': 'SIMULATION', 'modelVersion': MODEL_VERSION, 'ruleVersion': RULE_VERSION, 'boundaryVersion': BOUNDARY_VERSION,
                'uncertaintyMeaning': '情景敏感性范围，非校准概率'}
