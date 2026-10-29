import datetime as dt
import math

from . import cma_tiles

DEFAULT_GRID = cma_tiles.DEFAULT_GRID
TILE_SIZE = cma_tiles.TILE_SIZE
ZOOM = 3

FIELD_LON_MIN = 115.0
FIELD_LON_MAX = 135.0
FIELD_LAT_MIN = 38.0
FIELD_LAT_MAX = 54.0
FIELD_INSET_DEG = 1.8

CELL_COUNT = 48
CLUSTER_COUNT = 7
CLUSTER_SPREAD_TILES = 0.115
LINE_AXIS_JITTER_DEG = 22.0

BAND_AXIS_SHARE = 0.62
BAND_SEGMENT_OFFSET_TILES = 0.055
BAND_LENGTH_TILES = 0.24
BAND_CENTRE_JITTER_TILES = 0.006
BAND_AXIS_JITTER_DEG = 14.0

PEAK_DBZ_MIN = 38.0
PEAK_DBZ_MAX = 66.0
EDGE_DBZ = 8.0
SHIELD_PEAK_RATIO = 0.46
SHIELD_FRACTION = 0.62

CORE_RADIUS_CELLS_MIN = 8.0
CORE_RADIUS_CELLS_MAX = 13.0
ELLIPTICITY_MIN = 0.42
ELLIPTICITY_MAX = 0.86

LIFE_SLOTS = 46
GROWTH_SLOTS = 11

COHORT_SIZE = 8
COHORT_SPAN_SLOTS = 14.0

DRIFT_EXCURSION_TILES = 0.11
DRIFT_PERIOD_MINUTES = 960.0
DRIFT_PERIOD_SLOTS = DRIFT_PERIOD_MINUTES / cma_tiles.CADENCE_MINUTES

DRIFT_AGE_TILES_PER_SLOT = 0.00006
DRIFT_BEARING_DEG = 68.0

DRIFT_REFERENCE_TIME = dt.datetime(2026, 9, 14, 10, 0, tzinfo=dt.timezone.utc)
_REFERENCE_SLOT = None

def set_drift_reference(when):
    global DRIFT_REFERENCE_TIME, _REFERENCE_SLOT
    DRIFT_REFERENCE_TIME = when
    _REFERENCE_SLOT = None

TEXTURE_OCTAVES = ((13.0, 0.055), (29.0, 0.030), (7.0, 0.022))

MISSING_BELOW_DBZ = 0.5

def _hash_unit(*parts):
    value = 2166136261
    for part in parts:
        if isinstance(part, str):
            for char in part:
                value = ((value ^ ord(char)) * 16777619) & 0xFFFFFFFF
        else:
            number = int(part) & 0xFFFFFFFF
            value = ((value ^ number) * 16777619) & 0xFFFFFFFF
            value ^= (value >> 13)
    return ((value >> 8) & 0xFFFFFF) / float(0x1000000)

def _slot_index(slot):
    if isinstance(slot, str):
        slot = dt.datetime.fromisoformat(slot.replace('Z', '+00:00'))
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=dt.timezone.utc)
    return int(slot.timestamp()) // (cma_tiles.CADENCE_MINUTES * 60)

_SQUALL_AXIS = None
_SQUALL_CENTRE = None
_SQUALL_RESOLVED = False
UNRESOLVED = object()

def _squall_frame():
    global _SQUALL_AXIS, _SQUALL_CENTRE, _SQUALL_RESOLVED
    if _SQUALL_RESOLVED:
        if _SQUALL_AXIS is None or _SQUALL_CENTRE is None:
            return None
        return _SQUALL_AXIS, _SQUALL_CENTRE
    try:
        from .catalog import cities, connections

        catalog_cities = cities()
        by_id = {city['id']: city for city in catalog_cities}
        sum_x = sum_y = 0.0
        counted = 0
        for origin, destination in connections():
            a, b = by_id.get(origin), by_id.get(destination)
            if not a or not b:
                continue
            dx = b['xy'][0] - a['xy'][0]
            dy = b['xy'][1] - a['xy'][1]
            if not dx and not dy:
                continue
            theta = 2.0 * math.atan2(dy, dx)
            sum_x += math.cos(theta)
            sum_y += math.sin(theta)
            counted += 1
        if not counted or not (sum_x or sum_y) or not catalog_cities:
            _SQUALL_AXIS, _SQUALL_CENTRE, _SQUALL_RESOLVED = None, None, True
            return None
        axis_deg = (math.degrees(math.atan2(sum_y, sum_x)) / 2.0) % 180.0

        mean_x = sum(city['xy'][0] for city in catalog_cities) / len(catalog_cities)
        mean_y = sum(city['xy'][1] for city in catalog_cities) / len(catalog_cities)
        from weather.geometry import unproject

        centre_lon, centre_lat = unproject((mean_x, mean_y))
        centre_x, centre_y = lonlat_to_tile(centre_lon, centre_lat)
        _SQUALL_AXIS, _SQUALL_CENTRE = axis_deg, (centre_x, centre_y)
    except Exception:
        _SQUALL_AXIS, _SQUALL_CENTRE = None, None
    _SQUALL_RESOLVED = True
    if _SQUALL_AXIS is None or _SQUALL_CENTRE is None:
        return None
    return _SQUALL_AXIS, _SQUALL_CENTRE

def reset_squall_frame():
    global _SQUALL_AXIS, _SQUALL_CENTRE, _SQUALL_RESOLVED
    _SQUALL_AXIS = _SQUALL_CENTRE = None
    _SQUALL_RESOLVED = False

def force_squall_frame(axis_deg, centre=None):
    global _SQUALL_AXIS, _SQUALL_CENTRE, _SQUALL_RESOLVED
    _SQUALL_AXIS = axis_deg
    _SQUALL_CENTRE = centre
    _SQUALL_RESOLVED = True

def squall_axis():
    frame = _squall_frame()
    return frame[0] if frame else None

def _band_placement(seed, index):
    frame = _squall_frame()
    if frame is None:
        return None
    axis_deg, (centre_x, centre_y) = frame
    axis = math.radians(axis_deg)
    cos_a, sin_a = math.cos(axis), math.sin(axis)

    jitter_deg = (_hash_unit(seed, 'bandaxis') - 0.5) * BAND_AXIS_JITTER_DEG
    angle = math.radians(axis_deg + jitter_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    centre_x += (_hash_unit(seed, 'bandcx') - 0.5) * BAND_CENTRE_JITTER_TILES * 2.0
    centre_y += (_hash_unit(seed, 'bandcy') - 0.5) * BAND_CENTRE_JITTER_TILES * 2.0

    main_cells = int(round(CELL_COUNT * BAND_AXIS_SHARE))
    if index < main_cells:
        along = (_hash_unit(seed, index, 'along') - 0.5) * BAND_LENGTH_TILES
        across = (_hash_unit(seed, index, 'across') - 0.5) * CLUSTER_SPREAD_TILES * 0.6
    else:
        tail = index - main_cells
        segment = 1 + (tail % max(1, CLUSTER_COUNT - 1))
        side = 1.0 if segment % 2 else -1.0
        magnitude = BAND_SEGMENT_OFFSET_TILES * (0.6 + 0.4 * _hash_unit(seed, segment, 'mag'))
        along = (_hash_unit(seed, index, 'along') - 0.5) * BAND_LENGTH_TILES * 0.45
        across = side * magnitude + (_hash_unit(seed, index, 'across') - 0.5) * CLUSTER_SPREAD_TILES * 0.5

    x = centre_x + cos_a * along - sin_a * across
    y = centre_y + sin_a * along + cos_a * across
    return x, y

def lonlat_to_tile(lon, lat, zoom=ZOOM):
    scale = float(2 ** zoom)
    world_x = (lon + 180.0) / 360.0 * scale
    n = math.radians(lat)
    mercator_y = math.log(math.tan(math.pi / 4.0 + n / 2.0))
    world_y = (math.pi - mercator_y) / (2.0 * math.pi) * scale
    return world_x, world_y

def _position(seed, index):
    band = _band_placement(seed, index)
    if band is not None:
        return band
    cluster = int(_hash_unit(seed, index, 'cluster') * CLUSTER_COUNT)
    lon = (FIELD_LON_MIN + FIELD_INSET_DEG
           + _hash_unit(seed, cluster, 'alon') * (FIELD_LON_MAX - FIELD_LON_MIN - 2 * FIELD_INSET_DEG))
    lat = (FIELD_LAT_MIN + FIELD_INSET_DEG
           + _hash_unit(seed, cluster, 'alat') * (FIELD_LAT_MAX - FIELD_LAT_MIN - 2 * FIELD_INSET_DEG))
    anchor_x, anchor_y = lonlat_to_tile(lon, lat)
    axis = _hash_unit(seed, cluster, 'axis') * 180.0
    along = (_hash_unit(seed, index, 'along') - 0.5) * CLUSTER_SPREAD_TILES * 2.0
    across = (_hash_unit(seed, index, 'across') - 0.5) * CLUSTER_SPREAD_TILES * 0.5
    jitter = math.radians(LINE_AXIS_JITTER_DEG)
    angle = math.radians(axis) + (_hash_unit(seed, index, 'jit') - 0.5) * jitter
    x = anchor_x + math.cos(angle) * along - math.sin(angle) * across
    y = anchor_y + math.sin(angle) * along + math.cos(angle) * across
    return x, y

def _reference_slot():
    global _REFERENCE_SLOT
    if _REFERENCE_SLOT is None:
        _REFERENCE_SLOT = _slot_index(DRIFT_REFERENCE_TIME)
    return _REFERENCE_SLOT

def _advection(age, since=None, vigour=0.0):
    span = (since - _reference_slot()) if since is not None else age
    phase = 2.0 * math.pi * span / DRIFT_PERIOD_SLOTS
    travelled = DRIFT_EXCURSION_TILES * 0.5 * (1.0 - math.cos(phase))
    total = travelled + DRIFT_AGE_TILES_PER_SLOT * LIFE_SLOTS * max(0.0, min(1.0, vigour))
    bearing = math.radians(DRIFT_BEARING_DEG)
    return math.cos(bearing) * total, -math.sin(bearing) * total

def _cohort_phase(seed, index):
    cohort = index // COHORT_SIZE
    member = index % COHORT_SIZE
    centre = _hash_unit(seed, cohort, 'cohort') * LIFE_SLOTS
    spread = (_hash_unit(seed, index, 'member') - 0.5) * COHORT_SPAN_SLOTS
    return int((centre + spread) % LIFE_SLOTS)

def _cell_state(seed, index, slot_index):
    phase = _cohort_phase(seed, index)
    age = (slot_index + phase) % LIFE_SLOTS
    cycle = (slot_index + phase) // LIFE_SLOTS
    factor = _life_curve(age)
    if factor <= 0.0:
        return None
    peak_base = PEAK_DBZ_MIN + _hash_unit(seed, index, 'peak') * (PEAK_DBZ_MAX - PEAK_DBZ_MIN)
    peak = peak_base * (0.35 + 0.65 * factor)
    if peak <= EDGE_DBZ:
        return None
    radius = (CORE_RADIUS_CELLS_MIN + _hash_unit(seed, index, 'radius')
              * (CORE_RADIUS_CELLS_MAX - CORE_RADIUS_CELLS_MIN)) * (0.45 + 0.55 * factor)
    if radius <= 0.0:
        return None
    base_x, base_y = _position(seed, index * 100003 + cycle % 100003)
    dx_tile, dy_tile = _advection(age, since=slot_index, vigour=factor)
    return {
        'index': index,
        'field_x': base_x + dx_tile,
        'field_y': base_y + dy_tile,
        'peak': peak,
        'radius_tiles': radius / float(TILE_SIZE),
        'radius': radius,
        'ellipticity': ELLIPTICITY_MIN + _hash_unit(seed, index, 'ell')
        * (ELLIPTICITY_MAX - ELLIPTICITY_MIN),
        'angle': math.radians(DRIFT_BEARING_DEG + 90.0
                             + (_hash_unit(seed, index, 'orient') - 0.5) * 50.0),
        'has_shield': _hash_unit(seed, index, 'shield') < SHIELD_FRACTION,
    }

def _life_curve(age):
    if age < 0 or age > LIFE_SLOTS:
        return 0.0
    if age <= GROWTH_SLOTS:
        fraction = age / float(GROWTH_SLOTS)
        return fraction ** 0.72
    decay_span = LIFE_SLOTS - GROWTH_SLOTS
    fraction = (age - GROWTH_SLOTS) / float(decay_span)
    return (1.0 - fraction) ** 0.85

def _texture(angle, seed, index):
    value = 1.0
    for order, (harmonic, amplitude) in enumerate(TEXTURE_OCTAVES):
        phase = _hash_unit(seed, index, 'phase', order) * 2.0 * math.pi
        value += amplitude * math.sin(harmonic * angle + phase)
    return value

def _cell_sample(seed, index, dx, dy, peak, radius, ellipticity, angle):
    if radius <= 0.0 or peak <= EDGE_DBZ:
        return 0.0
    cos_a, sin_a = math.cos(-angle), math.sin(-angle)
    rx = dx * cos_a - dy * sin_a
    ry = dx * sin_a + dy * cos_a
    minor = max(0.12, ellipticity)
    scaled = math.hypot(rx, ry / minor)
    azimuth = math.atan2(dy, dx)
    effective = radius * _texture(azimuth, seed, index)
    if scaled >= effective:
        return 0.0
    t = scaled / effective
    shaped = t ** 1.9
    value = peak - (peak - EDGE_DBZ) * shaped
    return max(0.0, value)

def _shield_sample(seed, index, dx, dy, peak, radius, angle):
    shield_peak = peak * SHIELD_PEAK_RATIO
    if shield_peak <= EDGE_DBZ:
        return 0.0
    offset = radius * 0.72
    sx = dx - math.cos(angle) * offset
    sy = dy - math.sin(angle) * offset
    major = radius * 1.35
    minor = radius * 0.85
    cos_a, sin_a = math.cos(-angle), math.sin(-angle)
    rx = sx * cos_a - sy * sin_a
    ry = sx * sin_a + sy * cos_a
    t = math.hypot(rx / major, ry / minor)
    if t >= 1.0:
        return 0.0
    return max(0.0, shield_peak - (shield_peak - EDGE_DBZ) * (t ** 2.2))

_TEXTURE_REACH = max(amplitude for _harmonic, amplitude in TEXTURE_OCTAVES)
_SHIELD_REACH = 1.35 + 0.72

def _raster(seed, slot_index, tile_x, tile_y):
    best = [[0.0] * TILE_SIZE for _ in range(TILE_SIZE)]

    for index in range(CELL_COUNT):
        state = _cell_state(seed, index, slot_index)
        if state is None:
            continue
        radius = state['radius']
        reach = radius * (1.0 + _TEXTURE_REACH)
        if state['has_shield']:
            reach = max(reach, radius * _SHIELD_REACH)

        local_x = (state['field_x'] - tile_x) * TILE_SIZE
        local_y = (state['field_y'] - tile_y) * TILE_SIZE
        col_lo = max(0, int(math.floor(local_x - reach)))
        col_hi = min(TILE_SIZE - 1, int(math.ceil(local_x + reach)))
        row_lo = max(0, int(math.floor(local_y - reach)))
        row_hi = min(TILE_SIZE - 1, int(math.ceil(local_y + reach)))
        if col_lo > col_hi or row_lo > row_hi:
            continue

        for row in range(row_lo, row_hi + 1):
            dy = local_y - (row + 0.5)
            target = best[row]
            for column in range(col_lo, col_hi + 1):
                dx = (column + 0.5) - local_x
                value = _cell_sample(seed, index, dx, dy, state['peak'], radius,
                                     state['ellipticity'], state['angle'])
                if state['has_shield']:
                    value = max(value, _shield_sample(seed, index, dx, dy,
                                                      state['peak'], radius, state['angle']))
                if value > target[column]:
                    target[column] = value

    return [[None if value < MISSING_BELOW_DBZ else round(value, 1) for value in row]
            for row in best]

def frame(seed=42, slot=None, grid=None, zoom=ZOOM):
    grid = tuple(grid) if grid else DEFAULT_GRID
    if isinstance(slot, str):
        slot_dt = dt.datetime.fromisoformat(slot.replace('Z', '+00:00'))
    else:
        slot_dt = slot
    if slot_dt is None:
        slot_dt = dt.datetime.now(dt.timezone.utc)
    if slot_dt.tzinfo is None:
        slot_dt = slot_dt.replace(tzinfo=dt.timezone.utc)
    slot_dt = slot_dt.astimezone(dt.timezone.utc).replace(second=0, microsecond=0)
    slot_index = _slot_index(slot_dt)

    cells = [(tile_x, tile_y, _raster(seed, slot_index, tile_x, tile_y))
             for tile_x, tile_y in grid]

    span = float(TILE_SIZE * TILE_SIZE * len(cells))
    present = [value for _x, _y, rows in cells for row in rows for value in row
               if value is not None]
    echo = [value for value in present if value >= cma_tiles.ECHO_FLOOR_DBZ]
    provenance = {
        'provider': 'SYNTHETIC_RADAR',
        'synthetic': True,
        'dataset': 'SYNTHETIC_CONVECTIVE_MOSAIC',
        'transport': 'IN_PROCESS',
        'credentialed': False,
        'cadenceMinutes': cma_tiles.CADENCE_MINUTES,
        'zoom': zoom,
        'tileFormat': f'{TILE_SIZE}x{TILE_SIZE} synthetic dBZ raster, same layout as the real mosaic',
        'retrievedAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'generator': {'seed': seed, 'slotIndex': slot_index, 'cells': CELL_COUNT,
                      'clusters': CLUSTER_COUNT, 'lifeSlots': LIFE_SLOTS,
                      'driftExcursionTiles': DRIFT_EXCURSION_TILES,
                      'driftPeriodMinutes': DRIFT_PERIOD_MINUTES,
                      'driftAnchor': DRIFT_REFERENCE_TIME.isoformat().replace('+00:00', 'Z'),
                      'driftBearingDeg': DRIFT_BEARING_DEG,
                      'fieldBox': {'lon': [FIELD_LON_MIN, FIELD_LON_MAX],
                                   'lat': [FIELD_LAT_MIN, FIELD_LAT_MAX]}},
        'note': '本帧为程序生成的模拟对流回波，用于在实测源不可用或需要重现时使用；'
                '几何形态与强度分档仿照主流气象雷达产品，不是观测结果。',
    }
    return {
        'available': True, 'provenance': provenance, 'error': None,
        'slot': slot_dt.isoformat().replace('+00:00', 'Z'),
        'slotAgeMinutes': 0.0,
        'cells': cells, 'degreesPerCell': cma_tiles.tile_degrees_per_cell(zoom),
        'gridTiles': sorted((x, y) for x, y, _ in cells),
        'stats': {
            'cells': int(span),
            'present': len(present),
            'echoFraction': round(len(echo) / span, 6),
            'convectiveFraction': round(sum(1 for v in echo if v >= cma_tiles.CONVECTIVE_DBZ) / span, 6),
            'strongFraction': round(sum(1 for v in echo if v >= cma_tiles.STRONG_DBZ) / span, 6),
            'minDbz': min(present) if present else None,
            'maxDbz': max(present) if present else None,
        },
        'lookbackStepsUsed': 0,
        'cache': 'MISS',
    }

def status():
    return {
        'provider': 'SYNTHETIC_RADAR',
        'synthetic': True,
        'dataset': 'SYNTHETIC_CONVECTIVE_MOSAIC',
        'cells': CELL_COUNT, 'clusters': CLUSTER_COUNT,
        'thresholdsDbz': {'echo': cma_tiles.ECHO_FLOOR_DBZ,
                          'convective': cma_tiles.CONVECTIVE_DBZ,
                          'strong': cma_tiles.STRONG_DBZ,
                          'severe': cma_tiles.SEVERE_DBZ},
        'note': '程序生成的模拟对流回波，仅在显式切换到虚拟数据时使用；'
                '不参与实测通道，也不会在实测源失败时自动顶替。',
    }
