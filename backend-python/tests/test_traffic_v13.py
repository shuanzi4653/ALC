"""V1.3 contracts: declared airspace layers, resource calendar, delivery orders."""
import math

import pytest

from traffic import airspace, delivery, service, weather_control
from traffic.resources import ResourceCalendar, crossing_zones
from traffic.service import network, profiles, simulate

SETTINGS = profiles()['operations']['delivery']


def test_declared_layers_never_stack_and_ceilings_are_enforced():
    profile = profiles()['DELIVERY']
    assert airspace.layers(profile) == [80, 160]
    layer, strategy = airspace.allocate(profile, 0, 0)
    assert layer in profile['cruiseLayersAglM'] and strategy == airspace.PRIMARY
    opposite, _ = airspace.allocate(profile, 1, 0)
    assert opposite != layer, '对向班次必须分到不同声明层'
    busy = airspace.layers(profile)
    assert airspace.allocate(profile, 0, 0, occupied=busy) == (None, airspace.UNAVAILABLE)
    with pytest.raises(ValueError):
        airspace.layers({**profile, 'cruiseLayersAglM': [80, 900]})
    info = airspace.validate([[0, 0, 80, 0], [10, 0, 160, 1], [20, 0, 0, 2]], profile)
    assert info['withinCeiling'] and info['maxAglM'] == 160
    assert info['cruiseLayersUsedAglM'] == [80, 160]


def test_every_published_flight_holds_one_of_its_own_declared_layers():
    value = simulate(42, 'clear')
    for flight in value['flights']:
        if flight['status'] != 'SCHEDULED':
            continue
        profile = profiles()[flight['mode']]
        assert flight['assignedLayerAglM'] in profile['cruiseLayersAglM']
        assert flight['maxAltitudeM'] <= profile['maxCruiseAglM']
        assert flight['layerStrategy'] in (airspace.PRIMARY, airspace.ALTERNATE)
        assert flight['groundWaitMinutes'] == flight['delayMinutes']
        # 0.11.26（T-1）：同上 —— 60 不是规则，`maxExtraMinutes` 才是（唯一来源）。
    assert flight['delayMinutes'] <= profiles()['separation']['maxExtraMinutes'] + 0.001
    assert flight['detourMinutes'] >= -0.001


def test_resource_calendar_enforces_capacity_and_window():
    calendar = ResourceCalendar({'PAD-A': 1})
    assert calendar.available('PAD-A', 10, 2)
    calendar.reserve('PAD-A', 10)
    assert not calendar.available('PAD-A', 11, 2)
    assert calendar.available('PAD-A', 13, 2)
    calendar.register('PAD-B', 2)
    calendar.reserve('PAD-B', 5)
    calendar.reserve('PAD-B', 5.5)
    assert not calendar.available('PAD-B', 5.2, 1.5)
    assert calendar.available('PAD-B', 9, 1.5)
    assert not calendar.window_available((('PAD-A', 10),), 2)
    assert calendar.window_available((('PAD-A', 30),), 2)
    assert calendar.utilization()['PAD-A']['reservations'] == 1
    assert calendar.busiest(1)[0]['resource'] == 'PAD-B'


def test_crossing_zones_resolve_to_a_grid_cell_and_flight_minute():
    path = [[0, 0], [1000, 0], [2000, 0]]
    points = [[0, 0, 90, 0], [1000, 0, 90, 2], [2000, 0, 90, 4]]
    zones = crossing_zones(path, [1100], points, 15000)
    assert len(zones) == 1
    assert zones[0]['zoneId'] == 'XZ:0,0'
    assert abs(zones[0]['xy'][0] - 1100) < 1e-6
    assert zones[0]['minute'] == 2
    assert crossing_zones(path, [], points, 15000) == []
    assert crossing_zones(path, [1100], points, 0) == []


def test_delivery_orders_expose_energy_return_leg_and_state_flow():
    flight = dict(id='F1', fromPad='CITY-1-01', scheduledMinute=0, departureMinute=5, arrivalMinute=15,
                  distanceKm=4.0, maxAltitudeM=160, mode='DELIVERY', status='SCHEDULED', points=[[0, 0, 0, 0]])
    record = delivery.evaluate(flight, SETTINGS)
    flight.update(record)
    assert record['vehicleId'].startswith('UAV-')
    assert 0 < record['energyPercentRemainingAtHandover'] < 100
    assert record['returnLegEnergyPercent'] > 0
    assert record['energyReservePercent'] == SETTINGS['energyReservePercent']
    assert record['orderOutcome'] == '已送达'
    assert delivery.order_state(flight, 'PENDING', 'PENDING', 0) == '待备货'
    assert delivery.order_state(flight, 'HOLD', 'HOLD', 3) == '待分配'
    assert delivery.order_state(flight, 'AIRBORNE', 'CLIMB', 6) == '待起飞'
    assert delivery.order_state(flight, 'AIRBORNE', 'CRUISE', 8) == '配送中'
    assert delivery.order_state(flight, 'ARRIVED', 'ARRIVED', 16) == '已送达'
    assert delivery.order_state(flight, 'CLOSED', 'CLOSED', 8) == '取消'
    assert delivery.vehicle_state(flight, 'HOLD', 3, SETTINGS) == '装载'
    assert delivery.vehicle_state(flight, 'AIRBORNE', 8, SETTINGS) == '飞行'
    assert delivery.vehicle_state(flight, 'ARRIVED', 15, SETTINGS) == '返航'
    assert delivery.vehicle_state(flight, 'ARRIVED', 15 + record['returnLegMinutes'] + 1, SETTINGS) == '充电'
    assert delivery.vehicle_state(flight, 'ARRIVED', 999, SETTINGS) == '可用'
    assert delivery.vehicle_state(flight, 'CLOSED', 999, SETTINGS) == '停用'


def test_insufficient_energy_cancels_the_order_instead_of_flying():
    flight = dict(id='F2', fromPad='CITY-1-01', scheduledMinute=0, departureMinute=5, arrivalMinute=15,
                  distanceKm=40.0, maxAltitudeM=200, mode='DELIVERY', status='SCHEDULED', points=[[0, 0, 0, 0]])
    record = delivery.evaluate(flight, SETTINGS)
    assert record['orderOutcome'] == '取消'
    assert record['orderOutcomeReason'] == 'ENERGY_INSUFFICIENT_FOR_RETURN'


def test_published_plan_publishes_layers_hubs_and_delivery_summary():
    value = simulate(42, 'clear')
    assert value['stats']['noAltitudeStacking'] is True
    assert value['stats']['alternateLayers'] == sum(f['layerStrategy'] == airspace.ALTERNATE for f in value['flights'])
    assert value['layerUsage']
    for key in value['layerUsage']:
        mode, _, _layer = key.partition(':')
        assert mode in ('CAR', 'DELIVERY')
    assert value['hubs']['padCount'] == len(network()['pads'])
    assert len(value['hubs']['pads']) == len(network()['pads'])
    assert value['hubs']['crossingZones']['capacityPerZone'] >= 1
    summary = value['deliveryPlan']
    orders = [f for f in value['flights'] if f['mode'] == 'DELIVERY']
    assert summary['orders'] == len(orders)
    assert 0 <= summary['deliveryRate'] <= 1
    assert summary['settings']['nodesPerCity'] == SETTINGS['nodesPerCity']
    assert summary['note'].startswith('订单与载具为模拟数据')
    for flight in orders:
        assert flight['orderId'].startswith('ORD-')
        assert flight['vehicleId'].startswith('UAV-')


def test_plan_hubs_and_delivery_projections_share_one_plan_revision():
    value = simulate(42, 'clear')
    key = service.identity(42, 'clear', None)
    value['sessionId'] = key
    with service.LOCK:
        saved = dict(service.JOBS)
        service.JOBS.clear()
        service.JOBS[key] = value
    try:
        meta = service.plan_meta(42, 'clear')
        assert meta['status'] == 'READY'
        # 0.11.16：0.11.14（H-2③）把 `planRevision` 从"算法版本串"改成了**进程内递增序号**
        # —— 目的是让"切通道/重建"在界面上可判（原来它恒等于算法串，重建与命中长得一样）。
        # 算法串搬到了 `planVersion`。这条期望没跟着改，于是从 0.11.14 起一直红着。
        assert meta['planRevision'].isdigit(), meta['planRevision']
        assert meta['planVersion'] == service.PLAN_REVISION
        assert meta['stats']['accepted'] == value['stats']['accepted']
        # 'clear' claims no weather at all: the snapshot has to say so rather than
        # presenting synthesised data as if it were a source.
        assert meta['weatherSnapshot']['dataType'] == 'NO_WEATHER_CLAIMED'
        assert meta['weatherSnapshot']['provider'] == 'NONE'
        assert 'NO_WEATHER_SOURCE_FOR_THIS_SCENARIO' in meta['weatherSnapshot']['qualityFlags']
        assert meta['coverage']['terrain']['status'] == 'UNAVAILABLE'
        assert meta['coverage']['buildings']['status'] == 'UNAVAILABLE'
        assert meta['riskRules']['ceilingAglM'] >= profiles()['CAR']['maxCruiseAglM']
        assert service.hubs(42, 'clear')['planRevision'] == meta['planRevision']
        plan = service.delivery_plan(42, 'clear')
        assert len(plan['orders']) == sum(f['mode'] == 'DELIVERY' for f in value['flights'])
        assert plan['vehicles']
        assert all(v['assignedFlights'] >= 1 for v in plan['vehicles'])
    finally:
        with service.LOCK:
            service.JOBS.clear()
            service.JOBS.update(saved)


def test_the_plan_publishes_the_weather_channel_it_was_built_against():
    """The one disagreement an operator cannot see, and so the one that must be printed.

    The map draws the channel that is current *now*; a plan is fixed when it is
    built. When the two differ, every missing detour looks like a routing failure
    while the router is behaving correctly -- reported 2026-09-30 as 「有飞机在禁飞区，
    怎么没有实现绕行？全局的绕飞似乎都不可控」, where the plan had been built against
    the measured echo (empty ban tier, no echo that far north) and the map was
    painting the virtual one over 吉林. The channel therefore has to be *published*,
    not inferred from the picture.

    The ambient mode is deliberately set to the opposite value, because "read the
    controller at the end of the build" would pass a naive version of this test.
    """
    weather_control.reset()
    try:
        weather_control.set_mode(weather_control.MODE_VIRTUAL)
        value = simulate(42, 'clear', weather_mode=weather_control.MODE_MEASURED)
        assert value['weatherMode'] == weather_control.MODE_MEASURED, \
            '载荷报告的通道不是本次构建使用的通道'
    finally:
        weather_control.reset()


def test_v13_endpoints_validate_query_parameters():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    for path in ('/traffic/plan?scenario=typo', '/traffic/plan?seed=-1', '/traffic/hubs?seed=100000',
                 '/traffic/delivery?scenario=nope', '/traffic/delivery?seed=abc'):
        assert client.get(path).status_code == 422, path


def _polygon_components(geometry):
    """Every polygon inside a Polygon/MultiPolygon/GeometryCollection.

    Needed because the rain band is a MultiPolygon of cluster discs: reading
    ``.exterior`` directly raises AttributeError, and quietly keeping only the
    largest component would skip the clusters that sit in the corridors.
    """
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return [part for part in getattr(geometry, 'geoms', [])
            if part.geom_type == 'Polygon' and not part.is_empty]


def _exterior_turns(geometry, signed=False):
    """Exterior turn angle in degrees at every vertex of every ring.

    With ``signed=True`` each entry becomes ``(angle, convex)`` where ``convex``
    is True for a turn that points *outward* of the polygon. The distinction is
    what the smoothness guard actually needs: an outward spike is the sawtooth
    defect, while an inward notch is just the concave corner where two cloud
    masses merged -- a real feature of a real radar echo, and the band is
    explicitly built as a chain of clusters that merge.
    """
    parts = [geometry] if geometry.geom_type == 'Polygon' else list(getattr(geometry, 'geoms', []))
    turns = []
    for polygon in parts:
        if polygon.geom_type != 'Polygon':
            continue
        points = list(polygon.exterior.coords)[:-1]
        count = len(points)
        if count < 3:
            continue
        for index in range(count):
            before, here, after = points[index - 1], points[index], points[(index + 1) % count]
            first = (here[0] - before[0], here[1] - before[1])
            second = (after[0] - here[0], after[1] - here[1])
            length_first = math.hypot(*first) or 1e-9
            length_second = math.hypot(*second) or 1e-9
            cosine = (first[0] * second[0] + first[1] * second[1]) / (length_first * length_second)
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
            # Shoelace sign of the turn: negative cross product means the edge
            # bent away from the interior, i.e. outward.
            cross = first[0] * second[1] - first[1] * second[0]
            turns.append((angle, cross < 0) if signed else angle)
    return turns


def _band_world():
    """The retained band generator, used here as a *geometry* regression fixture.

    The project no longer serves synthesised weather: ``moving`` is rejected by
    every endpoint and no scenario reaches :class:`NetworkWeather`. The class is
    kept — and still drives these four tests — because the band outline is the
    most demanding geometry the renderer and the swept envelope ever had to
    handle (a 20-cluster chain with staggered life cycles), and these guards pin
    properties of the *shared* outline/buffer/hull code that the real point
    observations also flow through. Deleting the tests with the scenario would
    have dropped the only coverage of a sawtooth outline, a collapsed core, a
    merged wall and a dropped cluster.
    """
    from traffic.weather import NetworkWeather
    return NetworkWeather(42, 'moving')


def test_weather_risk_rings_are_smooth_and_not_index_driven():
    """The risk outline must not be a flower with sawtooth edges.

    Two defects produced that look: the radius harmonic was driven by the integer
    vertex index instead of the angle (so every lobe ended in a cusp, measured up
    to ~122 degrees of exterior turn), and only 24 vertices were sampled.

    The guard separates the two kinds of sharp turn, because only one of them is
    a defect:

    * An **outward** turn of more than 45 degrees is a spike -- the outline pokes
      out to a point. That is the sawtooth defect and it must stay at zero.
    * An **inward** turn is a concave corner. The rain band is a union of cluster
      outlines, so where two masses overlap the union legitimately creates a
      notch between them; the same is true of `field.difference(core)`. Such a
      corner is a feature of a merged echo, not roughness, and holding it to the
      same 45 degrees would force the band to be a single smooth blob -- which is
      the shape the corridor test below explicitly forbids.

    Inward corners are therefore bounded only by a much looser limit, and the
    real protection against degenerate geometry is the short-edge check: a notch
    that is one metre wide has no meaning as airspace and would render as a
    hairline.
    """
    from traffic.weather import NetworkWeather
    world = _band_world()
    shapes = world.shapes(60)
    assert shapes, '压力情景应生成气象单体'

    outward = []
    inward = []
    short_edges = []
    for _, field, ban, caution in shapes:
        for geometry in (field, ban, caution):
            assert geometry.geom_type in ('Polygon', 'MultiPolygon'), geometry.geom_type
            for angle, convex in _exterior_turns(geometry, signed=True):
                (outward if convex else inward).append(angle)
            for polygon in _polygon_components(geometry):
                points = list(polygon.exterior.coords)[:-1]
                for index, here in enumerate(points):
                    following = points[(index + 1) % len(points)]
                    length = math.hypot(following[0] - here[0], following[1] - here[1])
                    if 0 < length < 10:
                        short_edges.append(length)

    assert outward, '应至少有一个外环'
    assert max(outward) < 45.0, \
        f'外环出现向外尖刺：最大转角 {max(outward):.2f} 度'
    assert max(inward) < 90.0, \
        f'外环出现极端内凹：最大转角 {max(inward):.2f} 度'
    # A degenerate outline -- zero area, coincident vertices, a negative buffer
    # that collapsed -- shows up here and nowhere else.
    #
    # The floor is 10 m, not a percentage of the outline. This is deliberately
    # well below anything a resampled cloud edge produces (the band's normal
    # detail runs 60-100 m on a 30 km perimeter) and is aimed squarely at the
    # failure that motivated it: a core built at unit radius and scaled left a
    # 0.58 m shape whose `buffer(0)` collapsed to four vertices with edges of
    # 1.0-1.2 m. Anything in that range is arithmetic, not weather.
    assert not short_edges, f'外环存在碎边，几何退化：{len(short_edges)} 条，最短 {min(short_edges):.1f} m'

    max_ban_vertices = 0
    for _, _, ban, _ in shapes:
        polygons = [ban] if ban.geom_type == 'Polygon' else list(ban.geoms)
        for polygon in polygons:
            if polygon.geom_type == 'Polygon':
                max_ban_vertices = max(max_ban_vertices, len(polygon.exterior.coords) - 1)
    assert max_ban_vertices <= 120, f'禁飞区顶点过多，仍然锯齿：{max_ban_vertices}'

    # The outline must stay irregular on purpose: a perfect disc would mean the
    # harmonic term was dropped entirely rather than corrected. Radial spread is
    # measured per polygon component, because the band is a chain of clusters and
    # reading a single ``.exterior`` off it raises AttributeError; taking only the
    # largest component would silently skip every other cluster.
    radii = []
    for _, field, _, _ in shapes:
        for polygon in _polygon_components(field):
            centre = polygon.centroid
            radii.append(max(((x - centre.x) ** 2 + (y - centre.y) ** 2) ** .5
                             for x, y in list(polygon.exterior.coords)[:-1]))
    assert max(radii) > 0

    # A chain of clusters is only a chain if it has gaps a flight can use. The
    # width is load-bearing: a corridor too narrow to fly through might as well not
    # exist, and the continuous version of this geometry severed the network
    # east-west. Satellites hung off the large masses were rejected for closing
    # three of these gaps to under 1 km.
    band = [geometry for cell, geometry, _, _ in shapes if cell['shape'] == 'BAND']
    assert band, '压力情景应包含东北雨带'
    for geometry in band:
        parts = _polygon_components(geometry)
        assert len(parts) > 1, '雨带应是一串离散云团，不是连续条带'
        gaps = []
        for index, part in enumerate(parts):
            nearest = min((part.distance(other) for offset, other in enumerate(parts)
                           if offset != index), default=0.0)
            gaps.append(nearest)
        assert min(gaps) > 1000.0, f'云团间隙过窄，航路无法穿越：最小 {min(gaps):.0f} m'

def test_derived_risk_region_naming_stays_out_of_the_official_airspace_vocabulary():
    """The two map layers must not share a name.

    Weather-derived regions are this system's own derivation; fixed controlled
    airspace is statutory. If a derived region is labelled with the official
    vocabulary, an operator reads a system threshold as a published restriction.
    """
    rules = service.network()['riskRules']
    assert rules['layerName'] == '派生飞行风险区'
    assert rules['derivation']
    for label in rules['labels'].values():
        assert label.startswith('派生飞行风险区'), label
        for forbidden in ('管制空域', '禁飞区', '官方'):
            assert forbidden not in label, label
    # The official layer keeps its own vocabulary and its own source.
    zone_rules = service.network()['staticAirspace']['rules']
    assert zone_rules['legalFramework']['clause'] == '第十九条'
    assert '派生' not in str(zone_rules.get('legalFramework'))



def test_swept_envelope_cache_is_keyed_on_the_binned_window():
    """The envelope must be cached on 5-minute tick bins, not raw float minutes.

    The planner calls envelope with departure + duration + maxExtra, which
    produced 13411 distinct float pairs over 13419 calls -- a cache keyed on the
    raw argument could never hit, so every window rebuilt the rain-band hull
    (measured: 0% hit rate, 11.25 s of a 13.3 s plan). Binning first collapses the
    key space to 1035 and reaches a 92.3% hit rate with an identical result.

    This asserts the *behaviour* (hits happen, geometry is unchanged), not the
    presence of a decorator, so an equivalent rewrite still passes.
    """
    from traffic.weather import NetworkWeather
    world = _band_world()
    NetworkWeather._swept_window.cache_clear()

    before = NetworkWeather._swept_window.cache_info()
    # 100.0 and 100.2 floor to the same start tick (20); 200.0 and 199.8 ceil to
    # the same end tick (40). Both pairs therefore denote one identical window and
    # must share a cache entry. (100.4 would ceil to tick 41 -- a different window,
    # correctly stored separately, which is why the probe uses sub-tick offsets.)
    first = world.envelope(100.0, 200.0)
    middle = NetworkWeather._swept_window.cache_info()
    world.envelope(100.2, 199.8)
    after = NetworkWeather._swept_window.cache_info()

    assert after.currsize == middle.currsize, '低于刻度的差异不应产生新缓存项'
    assert after.hits > before.hits, '同一刻度窗口的第二次调用必须命中缓存'
    assert first.equals(world.envelope(100.0, 200.0)), '缓存不得改变几何'


def test_swept_envelope_bins_outward_so_the_covered_interval_never_shrinks():
    """Binning must round the window *outward*, never inward.

    ``envelope`` rasterises to 5-minute ticks with floor/ceil, so the computed
    interval always contains the requested one. Rounding inward would shrink the
    swept area and let a flight depart into a cell that the envelope no longer
    covers. This pins the direction of the rounding by checking that a window
    whose request falls strictly inside another's produces a subset of it.
    """
    world = _band_world()
    for start, end in ((100.0, 200.0), (100.4, 200.6), (5.0, 45.0), (10.2, 30.8)):
        outer = world.envelope(start, end)
        # A strictly interior request: floor rises, ceil falls, so it lands on a
        # tick window contained in the outer one.
        inner_start = start + 0.2
        inner_end = end - 0.2
        if int(inner_end // 5) <= int(inner_start // 5):
            continue
        inner = world.envelope(inner_start, inner_end)
        outside = inner.difference(outer).area
        assert outside < 1.0, (
            f'内缩窗口 ({inner_start},{inner_end}) 超出 ({start},{end}) 的包络 '
            f'{outside:,.2f} m²，说明取整方向反了')


def test_swept_band_hull_drops_only_offsets_that_cannot_be_extremal():
    """The band hull must equal the per-vertex hull exactly, not approximately.

    _band_hull skips drift offsets that lie inside the drift path's own hull
    because a strictly interior offset cannot contribute an extremal point. That
    is an exact reduction, but the reasoning is subtle enough that it is worth
    pinning: an over-aggressive filter returns a hull that is too small, which is
    precisely how trajectories once threaded the rain band.

    Constructing the reference by translating the stored outline
    ------------------------------------------------------------
    This test used to build the reference from ``band['polygon']`` -- the t=0
    union stored on the cell -- and translate *that* across the window's drift
    offsets. That reference stopped being valid when the band became a chain of
    clusters with staggered life cycles, and it failed for a reason that has
    nothing to do with the envelope being too small:

    ``band['polygon']`` is a snapshot of whichever clusters were alive at t=0
    (6 of 20). Clusters that are *born later* are not in it, and clusters that
    die before the window are translated along anyway. So on window (56,70) the
    reference folded in a cluster that had already dissipated and, more
    importantly, the drifted t=0 snapshot swept a *different set of bodies*
    across the window than the window actually draws -- measured 1.98e10 m2 of
    apparent shortfall, on an envelope that contained every cluster actually
    alive there (0 m2 missing against the live outlines, and 0 m2 against the
    dissolved ``shapes()`` output).

    The exactness being pinned is about *drift only*: within a window, the hull
    of ``{cluster_outline + d_t}`` over the ticks. That is what the reference now
    reproduces, per live cluster, which is the property ``_band_hull`` claims.
    Whether the envelope covers the drawn shapes is a separate claim, and it is
    asserted independently at the end of this test.
    """
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union
    from traffic.weather import SWEPT_BAND_PAD_M, _band_cluster_outlines, _polygon_parts

    world = _band_world()
    index = next(i for i, c in enumerate(world.cells) if c['shape'] == 'BAND')
    band = world.cells[index]
    assert len(_polygon_parts(band['polygon'])) > 1, (
        '雨带应当是云团链；本用例逐云团构造参照，单一多边形说明形态已回退')

    for start_bin, end_bin in ((0, 18), (56, 70), (0, 96), (12, 107)):
        # Reference: every *live* cluster outline translated across the window's
        # own drift offsets, exactly as _band_hull sums outline hull + drift hull.
        #
        # Every ring of every part is collected. Reading ``outline.exterior`` would
        # raise on a MultiPolygon, and taking only the first part would silently
        # drop the smaller clusters -- the ones sitting in the corridors.
        points = []
        for cluster in band.get('clusters', ()):
            for tick in range(start_bin, end_bin + 1):
                outline, _core = _band_cluster_outlines(cluster, tick * 5)
                if outline is None:
                    continue
                dx, dy = world.drift(band, tick * 5)
                for part in _polygon_parts(outline):
                    points.extend((px + dx, py + dy)
                                  for px, py in part.exterior.coords)
        assert points, f'窗口 ({start_bin},{end_bin}) 内没有任何存活云团'
        reference = MultiPoint(points).convex_hull.buffer(SWEPT_BAND_PAD_M, quad_segs=4)
        got = world._swept_band(index, start_bin, end_bin)
        missing = reference.difference(got).area
        assert missing < 1.0, (
            f'窗口 ({start_bin},{end_bin}) 的包络比真实扫描区域小 {missing:,.2f} m²，'
            '会出现穿越风险区的航迹')

        # The separate claim: nothing the window actually draws may sit outside
        # the envelope. This is the property that keeps a trajectory out of the
        # band, and it is checked against `shapes()` rather than against the
        # drifted t=0 snapshot.
        drawn = [field for tick in range(start_bin, end_bin + 1)
                 for c, field, _b, _caution in world.shapes(tick * 5)
                 if c['shape'] == 'BAND']
        if drawn:
            leak = unary_union(drawn).difference(got).area
            assert leak < 1.0, (
                f'窗口 ({start_bin},{end_bin}) 有 {leak:,.2f} m² 已绘制云团落在包络之外')


def test_rain_clusters_never_merge_into_a_wall():
    """The rain system must stay a chain of clusters with usable gaps between them.

    The first version buffered the centreline by a single half-width and produced
    one unbroken ~190 km ribbon. Operationally that severs the east-west network:
    there is no gap anywhere along it, so every corridor that has to cross the
    front is closed or detoured past the budget and the eastern half of the map
    becomes unreachable. The user's report is exact -- 雨带不能连续，连在一起整个
    东西方向就断开了 -- so the gaps are a requirement, not a rendering detail.

    Two things are pinned here. First, no two adjacent clusters may touch. Second,
    the gap has to be wide enough to be a corridor rather than a pinhole: an early
    attempt hung a small satellite cell off each large mass, which looked right but
    parked a disc inside the gap and drove the minimum clearance from 8,131 m down
    to 449 m, restoring the wall.
    """
    from traffic.weather import _polygon_parts

    world = _band_world()
    band = next(c for c in world.cells if c['shape'] == 'BAND')
    parts = _polygon_parts(band['polygon'])

    assert len(parts) > 1, '雨带必须是由多个云团组成的链，而不是单一连续体'

    parts = sorted(parts, key=lambda p: p.centroid.x)
    gaps = [a.distance(b) for a, b in zip(parts, parts[1:])]
    assert min(gaps) > 1000, (
        f'相邻云团最小间隙仅 {min(gaps):,.0f} m，窄到无法通行，'
        '等于把云团链重新连成一道墙')

    # And the operational statement: a west-east line across the chain must never be
    # mostly inside the field. 35% is a generous ceiling; the continuous ribbon sat
    # at 100% for lines crossing it lengthwise.
    from shapely.geometry import LineString
    minx, miny, maxx, maxy = band['polygon'].bounds
    worst = 0.0
    for step in range(41):
        y = miny + (maxy - miny) * step / 40
        line = LineString([(minx - 300000, y), (maxx + 300000, y)])
        worst = max(worst, line.intersection(band['polygon']).length / line.length)
    assert worst < 0.35, (
        f'东西向直线最多有 {worst:.0%} 落在雨带内，云团链已接近连续墙')


def test_band_clusters_carry_every_component_into_the_swept_envelope():
    """Pruning the outline to one ring would silently drop the gap-filling cells.

    ``_band_hull`` reads the band's ring coordinates. When the outline became a
    MultiPolygon it raised AttributeError on ``.exterior``; the dangerous variant of
    that bug is quietly taking only the largest component, because the envelope
    would then cover the large masses but not the clusters between them -- and those
    are exactly the ones sitting in the corridors.

    The per-point/time-aligned avoidance property itself is already covered by
    ``test_traffic_network.py::test_no_trajectory_point_enters_the_drawn_risk_surface_at_its_own_minute``,
    which buckets points by their own minute and tests the dissolved ``frame()``.
    This test only pins the envelope-coverage half, which that one does not.
    """
    from shapely.geometry import Point
    from traffic.weather import _polygon_parts

    world = _band_world()
    index = next(i for i, c in enumerate(world.cells) if c['shape'] == 'BAND')
    band = world.cells[index]
    parts = _polygon_parts(band['polygon'])
    assert len(parts) > 1

    envelope = world._swept_band(index, 0, 96)
    for part in parts:
        # A centroid is inside its own component, so it must be inside the envelope.
        assert envelope.distance(Point(part.centroid)) < 1.0, (
            '某个云团组件没有进入扫描包络，其所在走廊会被误判为可通行')

def test_conflict_early_reject_never_drops_a_conflict():
    """`conflict` 的早退必须是**必要条件**，不能只是"看起来便宜"。

    2026-10-01 给 `conflict` 加早退时（它占计划时间 22.4%），第一版用的是
    "四个端点两两距离都超过间隔标准" —— 这个判据**是错的**。两条长线段可以在
    中点附近交叉，而四个端点都在几千米之外，于是端点距离给出的是距离的**上界**
    而不是下界，早退会漏掉真实冲突。`_probe_conflict_early_reject` 第 2 组用例
    正是这一族，它当场把这一版打回。

    现在用的是"膨胀间隔标准后的轴对齐包围盒不相交"，那是真必要条件。这条测试
    把那组反例固化下来 —— 否则下一个人会以为端点距离够用，因为它在 99% 的用例
    上确实够用。
    """
    from traffic.spatial import conflict

    # 两条 1700 m 长的线段，在原点附近交叉；四个端点两两距离都 > 1700 m。
    # 端点距离判据会认为"相距很远"，但它们实际相交 —— 必须判为冲突。
    a = [[-2000.0, 0.0, 500.0, 0.0], [2000.0, 0.0, 500.0, 40.0]]
    b = [[0.0, -1715.3, 500.0, 0.0], [0.0, 2284.7, 500.0, 40.0]]
    assert conflict(a, b) is True

    # 同一对，把 b 整体横移出间隔标准的包围盒之外 —— 这时才应当判为无冲突。
    far = [[5000.0, -1715.3, 500.0, 0.0], [5000.0, 2284.7, 500.0, 40.0]]
    assert conflict(a, far) is False


def test_conflict_early_reject_keeps_the_vertical_threshold():
    """早退不得顺带改变垂直间隔的判定边界。"""
    from traffic.spatial import conflict

    def pair(offset):
        a = [[0.0, 0.0, 500.0, 0.0], [1000.0, 0.0, 500.0, 20.0]]
        b = [[0.0, -100.0, 500.0 + offset, 0.0], [1000.0, 100.0, 500.0 + offset, 20.0]]
        return conflict(a, b)

    # VERTICAL_M == 60.0；正好等于阈值时按既有实现（<=）算冲突。
    assert pair(59.0) is True
    assert pair(60.0) is True
    assert pair(61.0) is False
