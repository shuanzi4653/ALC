import heapq
import math
import time

from shapely.geometry import LineString, Point

from weather.geometry import project, unproject, boundary
from weather.engine import REGIONS

ALGORITHM_VERSION = 'temporal-visibility-2'
OPEN = {'DIRECT', 'DETOUR', 'WAIT'}


def validate_task(task):
    if task.get('regionId') not in REGIONS:
        raise ValueError('请选择东北三省任务区域')
    for key in ('from', 'to'):
        p = task.get(key)
        if not isinstance(p, (list, tuple)) or len(p) != 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in p):
            raise ValueError('起终点必须是有效经纬度')
        if not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90):
            raise ValueError('经纬度越界')
    for key, low, high in [('speedKmh', 1, 300), ('enduranceMinutes', 1, 600),
                           ('latestArrivalMinute', 1, 1440), ('departureMinute', 0, 1260), ('bufferM', 0, 5000),
                           ('workMinutes', 0, 120)]:
        v = task.get(key)
        if not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{key}不在有效范围内')


def classify_extra(seconds):
    return 'CLOSED' if seconds > 3600 + 1e-7 else 'DETOUR'


def evaluate(world, task, deadline_seconds=2.0, mode='dynamic'):
    validate_task(task)
    rid = task['regionId']
    start, goal = project(task['from']), project(task['to'])
    allowed = boundary(REGIONS[rid]['name'])
    speed = task['speedKmh'] * 1000 / 60
    direct_minutes = math.dist(start, goal) / speed
    base = float(task['departureMinute'])
    horizon = min(base + 180, task['latestArrivalMinute'])
    deadline = time.perf_counter() + deadline_seconds
    def closed(reason, status='CLOSED', depart=base):
        return {'status': status, 'reason': reason, 'coords': [], 'departureMinute': depart,
                'directMinutes': direct_minutes, 'extraMinutes': None, 'distanceKm': None,
                'waitMinutes': depart - base}
    if world.scenario == 'unknown':
        return [closed('DATA_UNKNOWN', 'UNEVALUATED')]
    if not allowed.covers(Point(start)) or not allowed.covers(Point(goal)):
        return [closed('ENDPOINT_OUTSIDE_REGION')]
    if direct_minutes + task['workMinutes'] > task['enduranceMinutes']:
        return [closed('ENDURANCE_EXCEEDED')]
    if base + direct_minutes + task['workMinutes'] > horizon:
        return [closed('FORECAST_HORIZON' if task['latestArrivalMinute'] > base + 180 else 'DEADLINE_EXCEEDED')]
    # Candidate graph from multiple forecast times. Restricted to local task vicinity.
    nodes = [start, goal]
    minx, miny, maxx, maxy = LineString([start, goal]).buffer(28000).bounds
    for minute in ((base,) if mode == 'static' else (base, base + 20, base + 40, base + 60)):
        for a in world.risks(minute, rid, task['bufferM']):
            x1, y1, x2, y2 = a['geometry'].buffer(2500).bounds
            for p in [(x1, y1), (x1, y2), (x2, y1), (x2, y2)]:
                if minx <= p[0] <= maxx and miny <= p[1] <= maxy and allowed.covers(Point(p)):
                    if all(math.dist(p, old) > 1000 for old in nodes):
                        nodes.append(p)
    # Additional boundary-safe lateral alternatives for concave polygons.
    dx, dy = goal[0] - start[0], goal[1] - start[1]
    length = max(1, math.hypot(dx, dy))
    for side in (-1, 1):
        for offset in (10000, 22000):
            for fraction in (.25, .5, .75):
                p = (start[0] + fraction * dx - side * dy / length * offset,
                     start[1] + fraction * dy + side * dx / length * offset)
                if allowed.covers(Point(p)):
                    nodes.append(p)
    edge_geometry = {}
    for u in range(len(nodes)):
        for v in range(u + 1, len(nodes)):
            line = LineString([nodes[u], nodes[v]])
            if allowed.covers(line):
                edge_geometry[u, v] = line
                edge_geometry[v, u] = line
    checked = {}
    def edge_safe(u, v, begin, end):
        line = edge_geometry.get((u, v))
        if line is None:
            return False
        key = (u, v, math.floor(begin), math.ceil(end))
        if key not in checked:
            obstacle = world.swept(base, base, rid, task['bufferM']) if mode == 'static' else world.swept(begin, end, rid, task['bufferM'])
            checked[key] = not line.intersects(obstacle)
        return checked[key]

    def search(depart, side):
        if time.perf_counter() >= deadline:
            return closed('PLANNER_TIMEOUT', 'UNEVALUATED', depart)
        start_time = base if mode == 'static' else depart
        if Point(start).intersects(world.swept(start_time, start_time, rid, task['bufferM'])):
            return closed('START_RESTRICTED', depart=depart)
        # Time-expanded states: upward rounding makes any implicit delay explicit and checked.
        queue = [(depart + direct_minutes, depart, 0, [0], [depart])]
        visited = set()
        while queue:
            if time.perf_counter() >= deadline:
                return closed('PLANNER_TIMEOUT', 'UNEVALUATED', depart)
            _, arrival, u, path, times = heapq.heappop(queue)
            key = (u, round(arrival, 2))
            if key in visited:
                continue
            visited.add(key)
            if u == 1:
                duration = arrival - depart
                extra = max(0, duration - direct_minutes)
                if classify_extra(extra * 60) == 'CLOSED':
                    return closed('DETOUR_OVER_60_MIN', depart=depart)
                if duration + task['workMinutes'] > task['enduranceMinutes']:
                    return closed('ENDURANCE_EXCEEDED', depart=depart)
                if arrival + task['workMinutes'] > horizon:
                    return closed('DEADLINE_EXCEEDED', depart=depart)
                goal_start, goal_end = (base, base) if mode == 'static' else (arrival, arrival + task['workMinutes'])
                if Point(goal).intersects(world.swept(goal_start, goal_end, rid, task['bufferM'])):
                    continue
                coords = [unproject(nodes[i]) for i in path]
                coords[0], coords[-1] = task['from'], task['to']
                return {'status': 'WAIT' if depart > base else 'DIRECT' if len(path) == 2 else 'DETOUR',
                        'reason': 'VALIDATED', 'coords': coords, 'arrivalMinutes': times,
                        'departureMinute': depart, 'arrivalMinute': arrival + task['workMinutes'],
                        'flightMinutes': duration, 'directMinutes': direct_minutes, 'extraMinutes': extra,
                        'waitMinutes': depart - base, 'distanceKm': duration * task['speedKmh'] / 60,
                        'enduranceRemaining': task['enduranceMinutes'] - duration - task['workMinutes'],
                        'side': '左侧候选' if side > 0 else '右侧候选' if side < 0 else '延后出发'}
            for v, p in enumerate(nodes):
                if v in path:
                    continue
                cross = dx * (p[1] - start[1]) - dy * (p[0] - start[0])
                if v != 1 and side * cross < -1:
                    continue
                end = arrival + math.dist(nodes[u], p) / speed
                if end + math.dist(p, goal) / speed + task['workMinutes'] > horizon:
                    continue
                if end - depart + task['workMinutes'] > task['enduranceMinutes']:
                    continue
                if edge_safe(u, v, arrival, end):
                    heapq.heappush(queue, (end + math.dist(p, goal) / speed, end, v, path + [v], times + [end]))
        return closed('NO_FEASIBLE_ROUTE', depart=depart)

    candidates = [search(base, 1), search(base, -1)]
    waiting = search(base + 20, 0)
    candidates.append(waiting)
    return candidates


def verify_candidate(world, task, candidate):
    if candidate['status'] not in OPEN:
        return True
    allowed = boundary(REGIONS[task['regionId']]['name'])
    coords, times = candidate['coords'], candidate['arrivalMinutes']
    if coords[0] != task['from'] or coords[-1] != task['to']:
        return False
    for i in range(1, len(coords)):
        line = LineString([project(coords[i-1]), project(coords[i])])
        if not allowed.covers(line) or line.intersects(world.swept(times[i-1], times[i], task['regionId'], task['bufferM'])):
            return False
    return not Point(project(coords[-1])).intersects(world.swept(times[-1], candidate['arrivalMinute'], task['regionId'], task['bufferM']))
