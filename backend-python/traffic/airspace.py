PRIMARY = 'DIRECTION_LAYER'
ALTERNATE = 'ALTERNATE_DECLARED_LAYER'
UNAVAILABLE = 'NO_DECLARED_LAYER_AVAILABLE'

def layers(profile):
    declared = [float(layer) for layer in profile['cruiseLayersAglM']]
    if not declared:
        raise ValueError('机型未声明巡航高度层')
    ceiling = float(profile['maxCruiseAglM'])
    if any(layer > ceiling for layer in declared):
        raise ValueError('巡航高度层超过机型上限')
    if any(layer <= 0 for layer in declared):
        raise ValueError('巡航高度层必须为正值')
    return sorted(declared)

def preferences(profile, direction, corridor_index):
    declared = layers(profile)
    if len(declared) == 1:
        return declared
    ascending = int(direction) % 2 == int(corridor_index) % 2
    ordered = declared if ascending else list(reversed(declared))
    return ordered

def allocate(profile, direction, corridor_index, occupied=()):
    occupied = {float(layer) for layer in occupied}
    ordered = preferences(profile, direction, corridor_index)
    for position, layer in enumerate(ordered):
        if layer not in occupied:
            return layer, PRIMARY if position == 0 else ALTERNATE
    return None, UNAVAILABLE

def validate(points, profile):
    ceiling = float(profile['maxCruiseAglM'])
    floor = float(profile.get('minCruiseAglM') or 0)
    if not points:
        return {'withinCeiling': False, 'maxAglM': None, 'cruiseLayersUsedAglM': [], 'ceilingAglM': ceiling, 'floorAglM': floor}
    declared = set(layers(profile))
    cruise = sorted({round(point[2], 3) for point in points if point[2] in declared})
    maximum = max(point[2] for point in points)
    return {
        'withinCeiling': maximum <= ceiling + 1e-8,
        'maxAglM': round(maximum, 2),
        'ceilingAglM': ceiling,
        'floorAglM': floor,
        'cruiseLayersUsedAglM': cruise,
        'declaredLayersAglM': sorted(declared),
    }
