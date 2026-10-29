import math
from functools import lru_cache

from shapely import affinity, make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

from weather.geometry import boundary, project
from . import cma_tiles

BAND_EDGES = (
    ('STRATIFORM', cma_tiles.ECHO_FLOOR_DBZ, cma_tiles.CONVECTIVE_DBZ),
    ('CONVECTIVE', cma_tiles.CONVECTIVE_DBZ, cma_tiles.STRONG_DBZ),
    ('STRONG', cma_tiles.STRONG_DBZ, math.inf),
)
BAND_ORDER = tuple(name for name, _low, _high in BAND_EDGES)
CORE_BAND = 'STRONG'
RING_BANDS = ('CONVECTIVE',)

SIMPLIFY_TOLERANCE_M = 2500.0
MIN_COMPONENT_CELLS = 1
MAX_COMPONENTS = 40

def band_of(value):
    if value is None:
        return None
    for name, low, high in BAND_EDGES:
        if low <= value < high:
            return name
    return None

def cell_quad(x, y, column, row, zoom):
    ring = []
    for cx, cy in ((column, row), (column + 1, row),
                   (column + 1, row + 1), (column, row + 1)):
        ring.append(cma_tiles.cell_centre_lonlat(x, y, cx, cy, zoom))
    ring.append(ring[0])
    return ring

def _quad_metres(ring):
    projected = [project(point) for point in ring]
    polygon = Polygon(projected)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon

@lru_cache(maxsize=65536)
def _grid_quad(key):
    x, y, column, row, zoom = key
    return _quad_metres(cell_quad(x, y, column, row, zoom))

def clear_grid_cache():
    _grid_quad.cache_clear()

def _components(cells):
    remaining = {}
    for cell in cells:
        remaining[(cell[0], cell[1], cell[2])] = cell
    found = []
    while remaining:
        seed = next(iter(remaining))
        del remaining[seed]
        band = seed[0]
        stack = [seed]
        group = [seed]
        while stack:
            _band, row, column = stack.pop()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbour = (band, row + dr, column + dc)
                if neighbour in remaining:
                    del remaining[neighbour]
                    stack.append(neighbour)
                    group.append(neighbour)
        found.append((band, group))
    return found

def _tier_geometry(component_rows, cell_lookup, zoom, clip, min_cells):
    if len(component_rows) < min_cells:
        return GeometryCollection()
    quads = []
    for key in component_rows:
        _band, row, column = key
        x, y = cell_lookup[key][3]
        quads.append(_grid_quad((x, y, column, row, zoom)))
    if not quads:
        return GeometryCollection()
    clipped = unary_union(quads).intersection(clip)
    if clipped.is_empty or clipped.area <= 0.0:
        return GeometryCollection()
    simplified = clipped.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    return simplified if not simplified.is_empty else clipped

def _polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return 0
    if isinstance(geometry, Polygon):
        return 1
    if isinstance(geometry, MultiPolygon):
        return len(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return sum(_polygon_parts(part) for part in geometry.geoms)
    return 0

def derive(frame_result, minute=None, clip=None):
    clip = boundary() if clip is None else clip
    empty = {
        'available': False, 'bands': {}, 'provenance': None,
        'cells': 0, 'components': 0, 'echoFraction': None,
    }
    if not isinstance(frame_result, dict):
        empty['error'] = '雷达帧不是字典'
        return empty
    if not frame_result.get('available'):
        empty['error'] = frame_result.get('error') or '雷达帧不可用'
        empty['provenance'] = frame_result.get('provenance')
        return empty

    zoom = frame_result.get('provenance', {}).get('zoom')
    if zoom is None:
        empty['error'] = '雷达帧缺少 zoom，无法配准'
        return empty

    tiles = frame_result.get('cells') or []
    if not tiles:
        empty['error'] = '雷达帧没有任何瓦片'
        return empty

    by_band = {}
    sampled = 0
    echoed = 0
    for x, y, rows in tiles:
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                sampled += 1
                band = band_of(value)
                if band is None:
                    continue
                echoed += 1
                by_band.setdefault(band, []).append((band, row_index, column_index, (x, y)))

    provenance = {
        'provider': 'CMA_DATA_NET',
        'dataset': frame_result.get('provenance', {}).get('dataset'),
        'slot': frame_result.get('slot'),
        'slotAgeMinutes': frame_result.get('slotAgeMinutes'),
        'credentialed': False,
        'registration': 'TILE_MERCATOR_TO_AEQD',
        'connectivity': 'EDGE_4',
        'simplifyToleranceM': SIMPLIFY_TOLERANCE_M,
        'minComponentCells': MIN_COMPONENT_CELLS,
        'bands': [{'name': name, 'lowDbz': low,
                   'highDbz': None if math.isinf(high) else high}
                  for name, low, high in BAND_EDGES],
    }

    tiers = {}
    total_components = 0
    for band_name, cells in by_band.items():
        cell_lookup = {(cell[0], cell[1], cell[2]): cell for cell in cells}
        groups = _components(cells)
        kept = []
        for _band, group in groups:
            geometry = _tier_geometry(group, cell_lookup, zoom, clip, MIN_COMPONENT_CELLS)
            area = geometry.area
            if area <= 0.0 or _polygon_parts(geometry) == 0:
                continue
            kept.append((area, geometry, len(group)))
        kept.sort(key=lambda item: -item[0])
        kept = kept[:MAX_COMPONENTS]
        total_components += len(kept)
        if not kept:
            tiers[band_name] = {
                'geometry': GeometryCollection(), 'components': 0,
                'areaM2': 0.0, 'cells': len(cells),
            }
            continue
        tiers[band_name] = {
            'geometry': unary_union([item[1] for item in kept]),
            'components': len(kept),
            'areaM2': sum(item[0] for item in kept),
            'cells': len(cells),
            'largestComponentM2': kept[0][0],
        }

    for band_name in BAND_ORDER:
        tiers.setdefault(band_name, {
            'geometry': GeometryCollection(), 'components': 0,
            'areaM2': 0.0, 'cells': 0,
        })

    return {
        'available': True,
        'error': None,
        'minute': minute,
        'bands': tiers,
        'provenance': provenance,
        'cells': sampled,
        'echoCells': echoed,
        'echoFraction': round(echoed / sampled, 6) if sampled else 0.0,
        'components': total_components,
    }

CORE_INSET_M = 9000.0

def shield(derived, pad_m=1000.0, core_scale=0.58, core_inset_m=CORE_INSET_M):
    bands = derived.get('bands', {})
    convective = (bands.get('CONVECTIVE', {}) or {}).get('geometry')
    strong = (bands.get('STRONG', {}) or {}).get('geometry')
    watch = (bands.get('STRATIFORM', {}) or {}).get('geometry')
    convective = convective if convective is not None else GeometryCollection()
    strong = strong if strong is not None else GeometryCollection()
    watch = watch if watch is not None else GeometryCollection()
    if convective.is_empty and strong.is_empty:
        return GeometryCollection(), GeometryCollection(), GeometryCollection(), watch
    outer = unary_union([convective, strong])
    if not outer.is_valid:
        outer = make_valid(outer)
    core = _erode_to_core(outer, strong, core_inset_m)
    return outer, core, outer.difference(core), watch

def _erode_to_core(outer, strong, inset_m):
    if outer.is_empty:
        return GeometryCollection()
    speck_m2 = 2.19e8
    if not strong.is_empty and strong.area > speck_m2 and strong.area > 0.25 * outer.area:
        grown = strong.buffer(inset_m * 0.35, quad_segs=4)
        core = grown.intersection(outer)
        if not core.is_empty and core.area > speck_m2:
            return _clip_to(core, outer)
    eroded = outer.buffer(-inset_m, quad_segs=6, join_style=1)
    if not eroded.is_empty and eroded.area > speck_m2:
        return _clip_to(eroded, outer)
    scaled = affinity.scale(outer, xfact=0.58, yfact=0.58, origin='centroid')
    core = scaled.intersection(outer)
    return _clip_to(core, outer)

def _clip_to(core, outer):
    if core.is_empty:
        return GeometryCollection()
    smoothed = _smooth(core)
    if not smoothed.is_valid:
        smoothed = make_valid(smoothed)
    clipped = smoothed.intersection(outer)
    return clipped if not clipped.is_empty else GeometryCollection()

def _smooth(geometry, tolerance_m=1500.0):
    return geometry.simplify(tolerance_m, preserve_topology=True)

def summary(frame_result=None, derived=None, virtual=None):
    derived = derived if derived is not None else derive(frame_result)
    if virtual is None:
        provenance = derived.get('provenance') or {}
        virtual = bool(derived.get('syntheticEcho') or provenance.get('synthetic'))
    if not derived.get('available'):
        return {
            'channel': 'SYNTHETIC_RADAR_CREF' if virtual else 'CMA_RADAR_TILES',
            'drivesGeometry': False,
            'available': False, 'error': derived.get('error'),
            'note': '雷达帧不可用时风险几何只来自气象通道，本通道不产出任何几何。',
        }
    bands = derived.get('bands', {})
    provenance = derived.get('provenance') or {}
    slot = provenance.get('slot')
    if virtual:
        return {
            'channel': 'SYNTHETIC_RADAR_CREF', 'drivesGeometry': True, 'available': True,
            'slot': ('SYNTHETIC@%s' % slot) if slot else None,
            'slotAgeMinutes': None,
            'echoFraction': derived.get('echoFraction'),
            'components': derived.get('components'),
            'bands': {name: {'components': row.get('components'),
                             'areaKm2': round((row.get('areaM2') or 0.0) / 1e6, 1)}
                      for name, row in bands.items()},
            'note': '本通道几何为程序生成的模拟回波，用于演示与压力测试，不是观测数据，不参与任何实测结论。',
        }
    return {
        'channel': 'CMA_RADAR_TILES', 'drivesGeometry': True, 'available': True,
        'slot': slot,
        'slotAgeMinutes': provenance.get('slotAgeMinutes'),
        'echoFraction': derived.get('echoFraction'),
        'components': derived.get('components'),
        'bands': {name: {'components': row.get('components'),
                         'areaKm2': round((row.get('areaM2') or 0.0) / 1e6, 1)}
                  for name, row in bands.items()},
        'note': '本通道几何为实测雷达反射率经阈值分类与配准后生成，与合成气象场分开标注。',
    }
