import math

class ResourceCalendar:

    def __init__(self, capacities):
        self._capacities = {str(key): int(value) for key, value in capacities.items()}
        self._entries = {}

    def register(self, resource, capacity=1):
        resource = str(resource)
        self._capacities.setdefault(resource, int(capacity))
        self._entries.setdefault(resource, [])
        return resource

    def capacities(self):
        return dict(self._capacities)

    def reservations(self, resource):
        return tuple(self._entries.get(str(resource), ()))

    def _occupied(self, resource, moment, window):
        return sum(1 for used in self._entries.get(resource, ()) if abs(used - moment) < window - 1e-8)

    def available(self, resource, moment, window):
        resource = str(resource)
        return self._occupied(resource, moment, window) < self._capacities.get(resource, 1)

    def reserve(self, resource, moment):
        resource = str(resource)
        self._capacities.setdefault(resource, 1)
        self._entries.setdefault(resource, []).append(float(moment))

    def window_available(self, entries, window):
        return all(self.available(resource, moment, window) for resource, moment in entries)

    def reserve_all(self, entries):
        for resource, moment in entries:
            self.reserve(resource, moment)

    def utilization(self):
        result = {}
        for resource, capacity in sorted(self._capacities.items()):
            used = self._entries.get(resource, ())
            result[resource] = {
                'capacity': capacity,
                'reservations': len(used),
                'firstMinute': round(min(used), 2) if used else None,
                'lastMinute': round(max(used), 2) if used else None,
            }
        return result

    def busiest(self, limit=12):
        rows = sorted(self.utilization().items(), key=lambda item: (-item[1]['reservations'], item[0]))
        return [{'resource': resource, **detail} for resource, detail in rows[:limit]]

    def snapshot(self):
        return {'capacities': self.capacities(), 'utilization': self.utilization(), 'busiest': self.busiest()}

def _cumulative(path):
    distances = [0.0]
    for first, second in zip(path, path[1:]):
        distances.append(distances[-1] + math.dist(first[:2], second[:2]))
    return distances

def _point_at(path, distances, target):
    if not path or not distances:
        return None
    if target <= 0:
        return list(path[0][:2])
    if target >= distances[-1]:
        return list(path[-1][:2])
    for index in range(1, len(distances)):
        if distances[index] >= target:
            span = distances[index] - distances[index - 1]
            fraction = 0.0 if span <= 0 else (target - distances[index - 1]) / span
            return [
                path[index - 1][0] + (path[index][0] - path[index - 1][0]) * fraction,
                path[index - 1][1] + (path[index][1] - path[index - 1][1]) * fraction,
            ]
    return list(path[-1][:2])

def crossing_zones(path, crossings, points, cell_m):
    if not crossings or cell_m <= 0 or not path:
        return []
    distances = _cumulative(path)
    result = []
    for target in crossings:
        if target <= 0:
            continue
        xy = _point_at(path, distances, target)
        if xy is None:
            continue
        minute = None
        if points:
            nearest = min(points, key=lambda point: math.dist(point[:2], xy))
            minute = round(nearest[3], 3)
        result.append({
            'zoneId': f"XZ:{int(xy[0] // cell_m)},{int(xy[1] // cell_m)}",
            'xy': [round(xy[0], 2), round(xy[1], 2)],
            'distanceM': round(target, 2),
            'minute': minute,
        })
    return result
