import heapq
import math
from shapely.geometry import LineString, Point
from shapely.prepared import prep

SEARCH_MARGIN_MIN_M = 12000.0
SEARCH_MARGIN_MAX_M = 70000.0
SEARCH_MARGIN_FRACTION = 0.4
SEARCH_STEP_MIN_M = 800.0
SEARCH_STEP_MAX_M = 6000.0
SEARCH_STEP_DIVISOR = 25.0
SEARCH_MAX_CHECKS = 12000
DEFAULT_PENETRATION_M = 0.0

def penetration_limit(geometry, depth):
    if geometry is None or geometry.is_empty or depth <= 0.0:
        return geometry
    shrunk = geometry.buffer(-depth)
    if shrunk.is_empty:
        return None
    return shrunk

def penalty_geometry_for(geometry, start, end, exempt_radius_m, exempt_geometry=None):
    """起降段豁免：先挖掉起降点所在的本场净空，再挖半径缓冲区。"""
    if geometry is None or geometry.is_empty:
        return None
    if exempt_geometry is not None and not exempt_geometry.is_empty:
        geometry = geometry.difference(exempt_geometry)
    if exempt_radius_m and exempt_radius_m > 0:
        hole = Point(tuple(start)).buffer(float(exempt_radius_m)).union(
            Point(tuple(end)).buffer(float(exempt_radius_m)))
        geometry = geometry.difference(hole)
    return None if geometry.is_empty else geometry

def _perpendicular(a, b, distance):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    return (-dy / length * distance, dx / length * distance)

SHIFT_STEPS_M = (2000.0, 4000.0, 6000.0, 9000.0, 12000.0, 16000.0)

def minimal_detour(points, avoid, *, exempt=None, allowed=None, keep_clear=None,
                   max_shift_m=16000.0, min_gain_km=0.1):
    """「能绕就小绕一下」：把走廊顶点沿法线挪一小段，压低净空内航段长度。

    不做全局 A*（在 16 km 净空环组成的条带里，网格搜索会因缝隙太窄而搜不到），
    只做有界的单顶点/双顶点侧移，候选全部落在 `allowed` 内、不碰 `keep_clear`、
    起终点不动、总航程增幅不超过 5%，才算数。
    返回 `(points, info)`；没找到改进时返回原顶点与 `shifted=False`。
    """
    base = [tuple(point) for point in points]
    if len(base) < 3 or avoid is None or avoid.is_empty:
        return base, {'shifted': False, 'beforeKm': 0.0, 'afterKm': 0.0, 'shiftM': 0.0}
    steps = [value for value in SHIFT_STEPS_M if value <= max_shift_m]

    def inside_km(candidate):
        line = LineString(candidate)
        clipped = line.intersection(avoid)
        if exempt is not None and not exempt.is_empty:
            clipped = clipped.difference(exempt)
        return clipped.length / 1000.0, line.length / 1000.0

    def feasible(candidate, base_km):
        line = LineString(candidate)
        if allowed is not None and not allowed.covers(line):
            return False
        if keep_clear is not None and not keep_clear.is_empty and line.intersects(keep_clear):
            return False
        return line.length / 1000.0 <= base_km * 1.05 + 1.0

    before, base_km = inside_km(base)
    if before <= min_gain_km:
        return base, {'shifted': False, 'beforeKm': round(before, 1),
                      'afterKm': round(before, 1), 'shiftM': 0.0}
    best = list(base)
    best_inside = before
    best_shift = 0.0
    best_index = None
    for index in range(1, len(base) - 1):
        for distance in steps:
            for sign in (1.0, -1.0):
                dx, dy = _perpendicular(base[index - 1], base[index + 1], distance * sign)
                candidate = list(base)
                candidate[index] = (base[index][0] + dx, base[index][1] + dy)
                if not feasible(candidate, base_km):
                    continue
                inside, _ = inside_km(candidate)
                if inside < best_inside - 0.05:
                    best, best_inside, best_shift, best_index = candidate, inside, distance * sign, index
    if best_index is None:
        return base, {'shifted': False, 'beforeKm': round(before, 1),
                      'afterKm': round(before, 1), 'shiftM': 0.0}
    # 第二处顶点：在第一处定好之后再挪一个，两道弯折才好贴住相邻净空。
    for index in range(1, len(base) - 1):
        if index == best_index:
            continue
        for distance in steps:
            for sign in (1.0, -1.0):
                dx, dy = _perpendicular(base[index - 1], base[index + 1], distance * sign)
                candidate = list(best)
                candidate[index] = (base[index][0] + dx, base[index][1] + dy)
                if not feasible(candidate, base_km):
                    continue
                inside, _ = inside_km(candidate)
                if inside < best_inside - 0.05:
                    best, best_inside = candidate, inside
    return best, {'shifted': True, 'beforeKm': round(before, 1),
                  'afterKm': round(best_inside, 1), 'shiftM': abs(best_shift)}

def route(start, end, allowed, obstacles=None, *,
          soft_obstacles=None, penetration_m=DEFAULT_PENETRATION_M,
          margin_m=None, step_m=None, max_checks=None,
          penalty_geometry=None, penalty_weight=0.0, exempt_radius_m=8000.0,
          penalty_exempt=None):
    start, end = tuple(start), tuple(end)
    checks_limit = SEARCH_MAX_CHECKS if max_checks is None else int(max_checks)
    prepared = prep(allowed)
    blocked = prep(obstacles) if obstacles is not None else None
    softened = penetration_limit(soft_obstacles, penetration_m)
    soft = prep(softened) if softened is not None else None
    # 净空软代价：默认 penalty_weight=0.0 → 下面两条分支都退化为原实现，路径逐字节不变。
    penalized = None
    if penalty_geometry is not None and float(penalty_weight) > 0.0:
        trimmed = penalty_geometry_for(penalty_geometry, start, end, exempt_radius_m, penalty_exempt)
        if trimmed is not None:
            penalized = trimmed
    penalty_w = float(penalty_weight) if penalized is not None else 0.0

    def penalised(a, b):
        if penalized is None:
            return 0.0
        return penalty_w * LineString([a, b]).intersection(penalized).length

    def valid(a, b):
        segment = LineString([a, b])
        if not prepared.covers(segment):
            return False
        if blocked is not None and blocked.intersects(segment):
            return False
        return not (soft is not None and soft.intersects(segment))

    def inside(candidate):
        point = Point(candidate)
        if obstacles is not None and obstacles.covers(point):
            return True
        return softened is not None and softened.covers(point)

    if not allowed.covers(Point(start)) or not allowed.covers(Point(end)):
        return None
    if inside(start) or inside(end):
        return None
    if valid(start, end) and penalised(start, end) == 0.0:
        return [list(start), list(end)]
    distance = math.dist(start, end)
    step = max(SEARCH_STEP_MIN_M, min(SEARCH_STEP_MAX_M, distance / SEARCH_STEP_DIVISOR))
    if step_m is not None:
        step = float(step_m)
    margin = max(SEARCH_MARGIN_MIN_M, min(SEARCH_MARGIN_MAX_M, distance * SEARCH_MARGIN_FRACTION))
    if margin_m is not None:
        margin = float(margin_m)
    minx = min(start[0], end[0]) - margin
    miny = min(start[1], end[1]) - margin
    nx = math.ceil((abs(start[0] - end[0]) + 2 * margin) / step)
    ny = math.ceil((abs(start[1] - end[1]) + 2 * margin) / step)

    def xy(node):
        return (minx + node[0] * step, miny + node[1] * step)

    source = (round((start[0] - minx) / step), round((start[1] - miny) / step))
    queue = []
    costs = {}
    previous = {}
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            node = (source[0] + dx, source[1] + dy)
            if valid(start, xy(node)):
                costs[node] = math.dist(start, xy(node)) + penalised(start, xy(node))
                previous[node] = None
                heapq.heappush(queue, (costs[node] + math.dist(xy(node), end), costs[node], node))
    checks = 0
    while queue and checks < checks_limit:
        _, cost, node = heapq.heappop(queue)
        if cost > costs[node] + 1e-8:
            continue
        checks += 1
        point = xy(node)
        if math.dist(point, end) < step * 3 and valid(point, end):
            path = [list(end)]
            while node is not None:
                path.append(list(xy(node)))
                node = previous[node]
            path.append(list(start))
            path.reverse()
            simplified = [path[0]]
            index = 0
            while index < len(path) - 1:
                following = len(path) - 1
                # 拉直只能拉直"不重新踩进净空"的那一段，否则绕开的航段会被简化回原线。
                while following > index + 1 and (not valid(path[index], path[following])
                                                 or penalised(path[index], path[following]) > 0.0):
                    following -= 1
                simplified.append(path[following])
                index = following
            return simplified
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            following = (node[0] + dx, node[1] + dy)
            if not (0 <= following[0] <= nx and 0 <= following[1] <= ny):
                continue
            new = cost + step * math.hypot(dx, dy) + penalised(point, xy(following))
            if new >= costs.get(following, float('inf')):
                continue
            if not valid(point, xy(following)):
                continue
            costs[following] = new
            previous[following] = node
            heapq.heappush(queue, (new + math.dist(xy(following), end), new, following))
    return None
