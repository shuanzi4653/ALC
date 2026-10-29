import math

HORIZONTAL_M = 250.0
VERTICAL_M = 60.0

def position(points, minute):
    if not points:
        return None
    if minute <= points[0][3]:
        return points[0][:3]
    for a, b in zip(points, points[1:]):
        if minute <= b[3]:
            fraction = (minute - a[3]) / (b[3] - a[3])
            return [a[key] + fraction * (b[key] - a[key]) for key in range(3)]
    return points[-1][:3]

def bbox_2d(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))

def bbox_apart(box_a, box_b, horizontal=HORIZONTAL_M):
    return (box_b[0] - horizontal > box_a[2] or box_a[0] - horizontal > box_b[2]
            or box_b[1] - horizontal > box_a[3] or box_a[1] - horizontal > box_b[3])

def conflict(a, b, horizontal=HORIZONTAL_M, vertical=VERTICAL_M, box_a=None, box_b=None):
    if box_a is None:
        box_a = bbox_2d(a)
    if box_b is None:
        box_b = bbox_2d(b)
    if bbox_apart(box_a, box_b, horizontal):
        return False
    for p, q in zip(a, a[1:]):
        for r, s in zip(b, b[1:]):
            lo, hi = max(p[3], r[3]), min(q[3], s[3])
            if hi < lo:
                continue
            if _segments_apart(p, q, r, s, horizontal):
                continue
            va = [(q[key] - p[key]) / (q[3] - p[3]) for key in range(3)]
            vb = [(s[key] - r[key]) / (s[3] - r[3]) for key in range(3)]
            delta = [p[key] + va[key] * (lo - p[3]) - r[key] - vb[key] * (lo - r[3]) for key in range(3)]
            velocity = [va[key] - vb[key] for key in range(3)]
            left, right = 0.0, hi - lo
            if abs(velocity[2]) < 1e-10:
                if abs(delta[2]) > vertical:
                    continue
            else:
                interval = sorted(((-vertical - delta[2]) / velocity[2], (vertical - delta[2]) / velocity[2]))
                left, right = max(left, interval[0]), min(right, interval[1])
            if left > right:
                continue
            velocity_squared = velocity[0] ** 2 + velocity[1] ** 2
            moment = left if velocity_squared < 1e-10 else max(
                left, min(right, -(delta[0] * velocity[0] + delta[1] * velocity[1]) / velocity_squared)
            )
            if (delta[0] + velocity[0] * moment) ** 2 + (delta[1] + velocity[1] * moment) ** 2 <= horizontal ** 2:
                return True
    return False

def _segments_apart(p, q, r, s, horizontal):
    if min(p[0], q[0]) > max(r[0], s[0]) + horizontal:
        return True
    if min(r[0], s[0]) > max(p[0], q[0]) + horizontal:
        return True
    if min(p[1], q[1]) > max(r[1], s[1]) + horizontal:
        return True
    if min(r[1], s[1]) > max(p[1], q[1]) + horizontal:
        return True
    return False

def rounded_path(path, min_turn_radius_m):
    if len(path) < 3:
        return [list(point) for point in path]
    result = [list(path[0])]
    for previous, corner, following in zip(path, path[1:], path[2:]):
        incoming = math.dist(previous, corner)
        outgoing = math.dist(corner, following)
        if incoming < 1 or outgoing < 1:
            return None
        ux, uy = ((corner[0] - previous[0]) / incoming, (corner[1] - previous[1]) / incoming)
        vx, vy = ((following[0] - corner[0]) / outgoing, (following[1] - corner[1]) / outgoing)
        dot = max(-1.0, min(1.0, ux * vx + uy * vy))
        angle = math.acos(dot)
        if angle < 0.03:
            result.append(list(corner))
            continue
        trim = min_turn_radius_m * math.tan(angle / 2)
        if trim > incoming * .42 or trim > outgoing * .42:
            return None
        start = [corner[0] - ux * trim, corner[1] - uy * trim]
        end = [corner[0] + vx * trim, corner[1] + vy * trim]
        result.append(start)
        for fraction in (.25, .5, .75):
            one_minus = 1 - fraction
            result.append([
                one_minus * one_minus * start[0] + 2 * one_minus * fraction * corner[0] + fraction * fraction * end[0],
                one_minus * one_minus * start[1] + 2 * one_minus * fraction * corner[1] + fraction * fraction * end[1],
            ])
        result.append(end)
    result.append(list(path[-1]))
    return result

def trajectory(path, departure, speed_kmh, altitude, crossings=None,
               max_altitude=None, climb_mps=3.0):
    if len(path) < 2 or altitude <= 0 or speed_kmh <= 0 or climb_mps <= 0:
        return None
    if max_altitude is not None and altitude > max_altitude + 1e-8:
        return None
    distances = [0.0]
    for first, second in zip(path, path[1:]):
        distances.append(distances[-1] + math.dist(first, second))
    total = distances[-1]
    if total <= 0:
        return None
    result = [[path[0][0], path[0][1], 0.0, departure]]
    current_time = departure + altitude / (climb_mps * 60)
    result.append([path[0][0], path[0][1], float(altitude), current_time])
    horizontal_speed_mpm = speed_kmh * 1000 / 60
    for distance in sorted(set(distances))[1:]:
        index = next(index for index in range(1, len(distances)) if distances[index] >= distance - 1e-6)
        fraction = (distance - distances[index - 1]) / (distances[index] - distances[index - 1])
        xy = [path[index - 1][key] + fraction * (path[index][key] - path[index - 1][key]) for key in range(2)]
        z = float(altitude)
        previous = result[-1]
        current_time += max(math.dist(previous[:2], xy) / horizontal_speed_mpm, abs(z - previous[2]) / (climb_mps * 60))
        result.append([*xy, z, current_time])
    result.append([*path[-1], 0.0, current_time + result[-1][2] / (climb_mps * 60)])
    return result

def within_profile(points, profile):
    if not points or points[0][2] != 0 or points[-1][2] != 0:
        return False
    maximum = profile['maxCruiseAglM']
    for first, second in zip(points, points[1:]):
        minutes = second[3] - first[3]
        if minutes <= 0 or max(first[2], second[2]) > maximum + 1e-8:
            return False
        if abs(second[2] - first[2]) / (minutes * 60) > profile['maxClimbMps'] + 1e-8:
            return False
        if math.dist(first[:2], second[:2]) / (minutes * 60) > profile['speedKmh'] * 1000 / 3600 + 1e-8:
            return False
    return True
