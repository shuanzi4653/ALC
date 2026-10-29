import math
from collections import Counter
import pytest
from shapely.geometry import LineString, Point, shape as to_shape
from shapely.prepared import prep
from shapely.strtree import STRtree
from traffic.catalog import cities, connections
from traffic import service
from traffic.service import network, profiles, simulate, weather_frame
from traffic.spatial import conflict, rounded_path, trajectory
from traffic.weather import LiveWeatherEnvelope, PublicWeather
from weather.geometry import boundary
from weather import geometry


# The old 'moving' scenario built a seeded synthetic field to route around, and a
# large block of tests here measured that field's geometry. That scenario is gone:
# weather is real-only now. What replaces it is a fixture over the two remaining
# cases that involve weather at all -- a real live snapshot, and 'clear' (no
# weather claimed). Tests that specifically exercised synthetic-cell geometry
# (rain band reachability, seeded field non-reproducibility, per-minute frame
# drift) are removed with it, because there is no longer a synthetic field to
# make those claims about.
@pytest.fixture(scope='module',params=['live','clear'])
def run(request):
    return simulate(42,request.param)


def test_city_coverage_and_capital_only_crossings():
    n=network(); lookup={c['id']:c for c in n['cities']}
    assert len(lookup)==36
    assert sorted(Counter(c['province'] for c in cities()).values())==[9,13,14]
    assert sum(r['interprovincial'] for r in n['routes'])==2
    assert len(n['administrativeBoundaries']['features'])==3
    assert n['assumptions']['cityCoordinates'].startswith('版本化')
    assert sum(r['mode']=='DELIVERY' for r in n['routes'])>108
    for r in n['routes']:
        assert r['path']
        assert r['path'][0]==r['fromXY'] and r['path'][-1]==r['toXY']
        assert boundary(r['province']).covers(LineString(r['path']))
        if r['interprovincial']: assert lookup[r['fromCity']]['capital'] and lookup[r['toCity']]['capital']
        if r['mode']=='CAR':
            assert r['fromXY']==lookup[r['fromCity']]['xy'] and r['toXY']==lookup[r['toCity']]['xy']
        if r['mode']=='DELIVERY':
            assert r['fromCity']==r['toCity']
            assert all(math.dist(p,lookup[r['fromCity']]['xy'])<=6000 for p in r['path'])
    for province in {c['province'] for c in cities()}:
        nodes={c['id'] for c in cities() if c['province']==province}; seen={min(nodes)}
        while True:
            expanded=seen|{b for a,b in connections() if a in seen and b in nodes}|{a for a,b in connections() if b in seen and a in nodes}
            if expanded==seen: break
            seen=expanded
        assert seen==nodes


def test_continuous_crossings_and_vertical_interval():
    a=[[-1000,0,100,0],[1000,0,100,1]]
    b=[[0,-1000,100,0],[0,1000,100,1]]
    assert conflict(a,b)
    assert not conflict(a,[[0,-1000,200,0],[0,1000,200,1]])
    assert not conflict(a,[[0,-1000,100,2],[0,1000,100,3]])
    assert conflict(a,[[0,-1000,300,0],[0,1000,-100,1]])
    assert conflict([[0,0,0,0],[0,0,200,1]],[[0,0,200,0],[0,0,0,1]])


def test_no_spatial_temporal_conflicts_independent_broadphase(run):
    accepted=[f for f in run['flights'] if f['points']]
    lines=[LineString([p[:2] for p in f['points']]) for f in accepted]
    tree=STRtree(lines)
    for i,f in enumerate(accepted):
        for j in tree.query(lines[i],predicate='dwithin',distance=250):
            if j<=i: continue
            other=accepted[j]
            if f['arrivalMinute']<other['departureMinute'] or other['arrivalMinute']<f['departureMinute']: continue
            assert not conflict(f['points'],other['points']),(f['id'],other['id'])


def test_flight_endpoints_rates_limits_and_geography(run):
    lookup={r['id']:r for r in network()['routes']}
    for f in run['flights']:
        if not f['points']: assert f['status']=='CLOSED'; continue
        r=lookup[f['routeId']]; points=f['points']
        assert points[0][:2]==(r['toXY'] if f['direction'] else r['fromXY'])
        assert points[-1][:2]==(r['fromXY'] if f['direction'] else r['toXY'])
        assert points[0][2]==points[-1][2]==0
        assert boundary(r['province']).covers(LineString([p[:2] for p in points]))
        if r['mode']=='DELIVERY':
            centre=next(c['xy'] for c in cities() if c['id']==r['fromCity'])
            assert Point(centre).buffer(6000).covers(LineString([p[:2] for p in points]))
        # 0.11.26（T-1）：原来写死 60，而**没有任何一条代码把 60 当规则** ——
        # 计划器的等待上限读的是 `aircraft-profiles.json::separation.maxExtraMinutes`（120）。
        # 60 之所以一直成立，是因为越界的班次先被"推演视界"闸门关掉了（于是它们
        # 根本不在这个循环里）。时间闸门撤掉后，长航线真的会等 100 分钟，这条判据
        # 才暴露出它守的是一个不存在的常量。
        # 现在改成读配置：判据仍然是"总延误不许超过声明上限"，但上限只有一处来源。
        assert f['delayMinutes'] <= _max_extra() + 0.001, '地面等待不许超过声明的上限'
        assert f['detourMinutes'] >= -0.001, '绕行增时不可能为负'
        # 0.11.26（T-1）：视界不再写死 480。撤掉时间闸门后，装不下 8 小时的班次
        # 不再被关闭，而是把**视界本身**撑大（`timelineMinutes`，由后端按实际最晚
        # 到达算）。判据仍然是"所有班次都落在计划声明的视界内"，只是那个 480
        # 改成读计划 —— 否则这一行会逼着实现把长航线重新关掉。
        assert points[-1][3] <= run['timelineMinutes'] + 0.001
        for a,b in zip(points,points[1:]):
            assert b[3]>a[3]
            assert abs(b[2]-a[2])/((b[3]-a[3])*60)<=3.000001
            assert math.dist(a[:2],b[:2])/((b[3]-a[3])*60)<= (50.000001 if f['mode']=='CAR' else 12.500001)
        profile=profiles()[f['mode']]
        assert f['maxAltitudeM']<=profile['maxCruiseAglM']
        assert f['clearanceStatus']=='SIMULATION_ASSUMPTION_UNVERIFIED'
        assert f['actualReleaseAt'] is None and f['actualArrivalAt'] is None
        assert f['requestedDepartureAt'] and f['plannedReleaseAt'] and f['estimatedArrivalAt']


def test_live_envelope_contains_every_drawn_contour():
    """The routing envelope must cover the contours the map draws.

    This replaces the old synthetic-field version of the same claim. The point is
    unchanged and is the one that matters: the geometry the planner avoids and the
    geometry the operator sees come from one place, so the envelope cannot be
    missing a region that is on screen.

    Note the empty-tier guard: a cautious-but-not-severe city legitimately has an
    empty ``ban`` (it is a ``GeometryCollection``), and ``envelope.covers(empty)``
    is ``False`` for *any* envelope -- an empty geometry is covered by nothing, not
    by everything. Asserting on it would test nothing but shapely's convention.
    """
    from traffic.service import weather_snapshot_entry
    snapshot=weather_snapshot_entry(cities())
    world=PublicWeather(snapshot,cities())
    envelope=LiveWeatherEnvelope(snapshot,cities()).envelope(0,480)
    checked=0
    for _,_,ban,caution in world.shapes(None):
        for tier in (ban,caution):
            if tier.is_empty:
                continue
            assert envelope.covers(tier)
            checked+=1
    if checked==0:
        pytest.skip('live snapshot produced no drawable tier in this environment')


def test_live_envelope_is_window_independent_and_never_synthtetic():
    """A point observation is one measurement, not a forecast trajectory.

    The retired synthetic field could be sampled at any minute, which is why the
    old test asserted ``frame(10) != frame(11)``. Real point data cannot honestly
    do that, so the property being protected is now the opposite: the envelope must
    NOT change with the window, and it must be empty when nothing was fetched.
    """
    from traffic.service import weather_snapshot_entry
    snapshot=weather_snapshot_entry(cities())
    provider=LiveWeatherEnvelope(snapshot,cities())
    assert provider.available
    assert provider.envelope(0,120).equals(provider.envelope(600,720))
    empty=LiveWeatherEnvelope(None,cities())
    assert not empty.available
    assert empty.envelope(0,480).is_empty


def test_unknown_fails_closed_and_no_wind():
    s=simulate(42,'unknown')
    assert s['stats']['accepted']==0
    assert all(f['reason']=='WEATHER_UNAVAILABLE' for f in s['flights'])
    frame=weather_frame(42,'unknown',30)
    assert not frame['available'] and frame['winds']==[] and frame['cells']==[]


def test_no_scenario_emits_synthetic_weather():
    """The whole point of this change: weather is never invented.

    Every scenario must either carry a real provider label or state plainly that
    no weather was claimed. A 'SYNTHETIC' marker anywhere in the snapshot is the
    exact thing that was removed, so it is asserted absent by name.
    """
    for scenario in ('live','clear','unknown'):
        run=simulate(42,scenario)
        blob=str(run['weatherSnapshot'])
        assert 'SYNTHETIC' not in blob, scenario
        assert 'SIMULATED_WEATHER' not in blob, scenario
    assert simulate(42,'live')['weatherSnapshot']['provider'] in ('OPEN_METEO','QWEATHER')
    for scenario in ('clear','unknown'):
        assert simulate(42,scenario)['weatherSnapshot']['dataType']=='NO_WEATHER_CLAIMED'


# `weatherSnapshot` 里"**描述这次是怎么拿到这份快照的**"的键，不是计划的内容。
#
# 2026-10-15 实测（`simulate(11,'live')` 在同一进程里连跑两次）：
#   · `cache`：`MISS` / `HIT` —— 第一次去取、第二次命中，两者必然不同；
#   · `retrievedAt` / `validUntil`：取数时刻与这次的有效期，同样是过程量；
#   而 7760 条航迹的逐字段内容、`deliveryPlan`、`stats`、`layerUsage` **全部逐位相同**。
# 原断言 `a == b` 把这几个过程键也算进了相等，于是这条用例**只有在"缓存已被前面的
# 用例焐热"时才可能通过** —— 一条随执行顺序变色的判据；它红的时候读起来像"计划不
# 确定"，其实量到的是缓存状态。`validAt`（这份快照说的天气是哪一刻的）**不剔除**：
# 它变了就是换了天气，计划本来就该跟着变。
_WEATHER_PROVENANCE_KEYS = ('cache', 'retrievedAt', 'validUntil')


# `planRevision` 自 0.11.14（H-2③）起是**进程内递增序号**（每建一次 +1），
# 它的用途是"让重建在界面上可判"，因此两次调用必然不同 —— 它不属于"计划内容"。
# 内容版本的标识是 `planVersion`（算法串），那一个必须相同。
_VOLATILE_KEYS = ('planRevision',)


def _plan_identity(run):
    identity = {k: v for k, v in dict(run).items() if k not in _VOLATILE_KEYS}
    snapshot = identity.get('weatherSnapshot')
    if isinstance(snapshot, dict):
        identity['weatherSnapshot'] = {k: v for k, v in snapshot.items()
                                       if k not in _WEATHER_PROVENANCE_KEYS}
    return identity


def test_determinism_and_traffic_plan_is_independent_of_weather():
    """Traffic generation is simulated; it must be identical across weather cases.

    Only the weather channel differs between scenarios, so the flight list has to
    be byte-identical between 'live' and 'clear'. If the planner secretly consumed
    the old synthetic field, this is where it would show.

    比较用 `_plan_identity`：剔掉的是"这次快照是怎么取到的"，不是计划本身。
    另注：live 两次调用若正好跨过雷达拼图刷新，避让几何会变、计划也会跟着变 ——
    那是 live 这个场景的固有性质，不是不确定性。真要多测几次，请把两次调用放在
    同一个雷达帧内（间隔越小越稳）。
    """
    a=simulate(11,'live'); b=simulate(11,'live')
    assert _plan_identity(a)==_plan_identity(b)
    assert a['stats']['flights']==simulate(11,'clear')['stats']['flights']
    # 0.11.26（T-1）：原来这里断言 `closed > 0`，用来证明"关闭原因这条词表是被用到的"。
    # 但那一版关闭里有 123 班**全部**是时间原因（58 机型时长 + 65 越界视界），
    # 而 `closed > 0` 对此完全无感 —— 它只数了数量，没看原因。
    #
    # 现在时间不再是关闭理由，晴朗天空下关闭数就是 0；这条判据改成守**语义**：
    # 只要有班次被关闭，原因就必须是气象类，且不得出现时间类的历史代码。
    closed = [f for f in a['flights'] if f.get('status') == 'CLOSED']
    assert closed or a['stats']['closed'] == 0
    allowed = {'WEATHER_BLOCKED', 'WEATHER_UNAVAILABLE',
               'FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED',
               'STATIC_AIRSPACE_BLOCKED', 'TURN_RADIUS_OR_BOUNDARY_LIMIT',
               'ALTITUDE_PROFILE_LIMIT', 'NO_GEOMETRIC_PATH'}
    bad = {f['reason'] for f in closed} - allowed
    assert not bad, '时间类关闭理由不许再出现：%s' % bad


def test_active_flights_avoid_future_weather(run):
    from traffic.service import weather_snapshot_entry
    w=LiveWeatherEnvelope(weather_snapshot_entry(cities()),cities()) if run['scenario']=='live' \
        else LiveWeatherEnvelope(None,cities())
    for f in run['flights']:
        if f['points']:
            line=LineString([p[:2] for p in f['points']])
            assert not line.intersects(w.envelope(f['departureMinute'],f['arrivalMinute']))


def test_no_trajectory_point_enters_the_drawn_risk_surface():
    """Avoidance must hold against the merged geometry the operator actually sees.

    The drawn surface is the dissolved ``frame()``. Risk areas are point-anchored
    here, so the contour does not move with the minute -- but the check is still
    made per-minute because that is the property a moving field would have to
    satisfy, and this test would catch a regression that reintroduced motion.

    FIELD is the outer caution contour that routing may clip; BAN is the core it
    may not. Only a BAN hit is a defect, but both are asserted because the envelope
    contract covers both.
    """
    run=simulate(42,'live')
    accepted=[f for f in run['flights'] if f['points']]
    assert accepted
    from traffic.service import weather_snapshot_entry
    world=PublicWeather(weather_snapshot_entry(cities()),cities())
    # Points bucketed by their own minute, so each minute is tested against its own surface.
    by_minute={}
    for f in accepted:
        for p in f['points']:
            by_minute.setdefault(int(p[3]),[]).append((f['id'],p[0],p[1]))
    sampled=sorted(by_minute)[::16]
    assert len(sampled)>20, sampled
    for minute in sampled:
        regions=world.frame(minute)
        if not regions:
            continue
        for key in ('field','ban'):
            prepared=[]
            for region in regions:
                geometry=to_shape(region[key])
                if not geometry.is_empty and geometry.geom_type in ('Polygon','MultiPolygon'):
                    prepared.append(prep(geometry))
            if not prepared:
                continue
            for flight_id,x,y in by_minute[minute]:
                point=Point(x,y)
                assert not any(g.contains(point) for g in prepared), (flight_id,key,minute,x,y)


def test_profile_holds_a_declared_layer_without_stacking():
    points=trajectory([[0,0],[2500,0]],0,45,90)
    assert [p[2] for p in points]==[0.0,90.0,90.0,0.0]
    assert all(p[3]<=q[3] for p,q in zip(points,points[1:]))
    # 交叉点只消耗时隙与资源，不再抬高高度
    assert max(p[2] for p in trajectory([[0,0],[2500,0]],0,45,90,crossings=[1200],max_altitude=200))==90
    # 超过机型上限直接拒绝，而不是临时抬升
    assert trajectory([[0,0],[2500,0]],0,45,210,max_altitude=200) is None
    assert trajectory([[0,0],[2500,0]],0,45,0) is None
    assert trajectory([[0,0],[2500,0]],0,0,90) is None


def test_checked_route_has_bounded_turn_geometry_without_extra_crossing_lift():
    rounded=rounded_path([[0,0],[1000,0],[1000,1000]],100)
    assert rounded and len(rounded)>3
    points=trajectory(rounded,0,45,90,crossings=[700],max_altitude=200)
    assert max(point[2] for point in points)==90


def test_live_winds_cover_the_whole_operating_area_not_just_the_hubs():
    """Winds are a province-wide background field, not a decoration on the markers.

    Both earlier states of this test were wrong in opposite directions, so the
    assertions here are about the property that actually matters rather than
    about how the vectors are produced:

    * The original asserted >300 synthetic glyphs on a generated grid. When the
      generator was retired the test had nothing to say.
    * The replacement asserted one vector per city observation, each >500 m from
      every hub (the old "offset the label off the marker" rule). That made the
      arrows a property of the **city markers**, which is exactly the defect an
      operator reported: on the three-province view the arrows appeared only at
      the 36 hubs and the rest of the map was bare, while the layer is named
      background wind field.
    * The first lattice attempt fixed the clustering but sampled the *bounding
      box*, so its nodes fell mostly on blank map and its edge tolerance kept the
      ones that landed off the outline. Measured: 27 vectors, 11 of them outside
      the area, a 228 km hole, and 38% of the area more than 100 km from any
      arrow.

    What is asserted now is the three properties an operator can see: the field
    reaches across the area, every sample is on the area, and there are no large
    holes in it.
    """
    frame=weather_frame(42,'live',60)
    if not frame.get('available'):
        pytest.skip('live weather source unavailable in this environment')
    assert frame['source'] in ('OPEN_METEO','QWEATHER')
    winds=frame['winds']
    assert winds, 'live snapshot carried no wind vectors'
    assert all(w['source'] in ('OPEN_METEO','QWEATHER') for w in winds)
    # A still day is not a reason to drop a vector: zero-length arrows would be
    # invisible and the layer would look broken rather than calm.
    assert all(math.hypot(w['u'],w['v'])>0 for w in winds)

    area=boundary()
    # Region-wide view: the lattice must span most of the operating area.
    span_x=max(w['xy'][0] for w in winds)-min(w['xy'][0] for w in winds)
    span_y=max(w['xy'][1] for w in winds)-min(w['xy'][1] for w in winds)
    box=area.bounds
    assert span_x/abs(box[2]-box[0])>0.85, 'wind lattice does not reach across the area'
    assert span_y/abs(box[3]-box[1])>0.85, 'wind lattice does not reach across the area'

    # Every sample sits *inside* the operating area. This is the rule the old
    # 40 km edge tolerance broke: it deliberately kept samples that had fallen
    # off the outline, which put arrows on foreign territory -- measured at 11 of
    # 27 vectors, the worst 39.7 km outside, which is what the operator saw as an
    # arrow "running out of the country".
    lon_min,lat_min=geometry.unproject((box[0],box[1]))
    lon_max,lat_max=geometry.unproject((box[2],box[3]))
    outside=[]
    for w in winds:
        lon,lat=geometry.unproject((w['xy'][0],w['xy'][1]))
        if lon<lon_min-1e-6 or lon>lon_max+1e-6 or lat<lat_min-1e-6 or lat>lat_max+1e-6:
            outside.append((lon,lat))
    assert not outside, 'wind samples fell outside the operating area: %r' % (outside[:4],)
    # Containment is the stronger statement and the one that actually matters --
    # the bounding box above is a rectangle, so a sample can be inside the box
    # and still be nowhere near the three-province outline.
    off_outline=[w['xy'] for w in winds if not area.covers(Point(w['xy']))]
    assert not off_outline, '%d wind samples are not on the operating area' % len(off_outline)

    # Density: the field is what an operator reads to see which way a band will
    # drift, so it has to be present everywhere rather than clustered on the
    # hubs. Measured worst gap is 78.5 km at 45/55 km spacing, against 228 km
    # before the sampler was rewritten. The threshold is set well above the
    # measurement so it fails on a regression, not on a boundary nudge.
    worst=0.0
    step=0.25
    lat=lat_min
    while lat<=lat_max:
        lon=lon_min
        while lon<=lon_max:
            x,y=geometry.project((lon,lat))
            if area.covers(Point(x,y)):
                d=min(math.dist(w['xy'],(x,y)) for w in winds)
                if d>worst:
                    worst=d
            lon+=step
        lat+=step
    assert worst<150_000, 'wind field has a %.0f km hole; field must cover the area' % (worst/1000.0)

    # A sample is now interpolated from its neighbours, so its `cityId` names the
    # nearest station rather than claiming to be that station's own reading.
    assert any(w.get('interpolated') for w in winds)
    assert len({w['cityId'] for w in winds})>1

    # The city view still collapses to a single vector: a province-wide lattice
    # over a few kilometres would say nothing, and the old marker-offset rule
    # still applies there because the arrow sits next to the hub label.
    urban=weather_frame(42,'live',60,'1-01')
    if urban['winds']:
        assert len(urban['winds'])==1
        assert all(w['cityId']=='1-01' for w in urban['winds'])
        assert all(math.dist(urban['winds'][0]['xy'],c['xy'])>0 for c in cities() if c['id']=='1-01')


def test_clear_and_unknown_claim_no_weather():
    """These two scenarios differ in what is stated, and both state 'no data'."""
    clear=weather_frame(42,'clear',60)
    assert clear['cells']==[] and clear['winds']==[]
    assert clear['available'] is True
    assert clear['dataType']=='NO_WEATHER_CLAIMED'
    unknown=weather_frame(42,'unknown',60)
    assert unknown['cells']==[] and unknown['winds']==[]
    assert unknown['available'] is False
    assert 'WEATHER_SOURCE_UNAVAILABLE' in unknown['qualityFlags']


def test_traffic_api_input_validation():
    from fastapi.testclient import TestClient
    from main import app
    client=TestClient(app)
    for path in ('/traffic/session?seed=-1','/traffic/session?scenario=typo',
                 '/traffic/weather?minute=nan','/traffic/weather?minute=481','/traffic/weather?cityId=missing'):
        assert client.get(path).status_code==422
    assert client.get('/traffic/weather?scenario=unknown').json()['available'] is False
    # The retired scenario name must now be rejected, not silently accepted.
    assert client.get('/traffic/weather?scenario=moving').status_code==422

def _max_extra():
    """地面等待上限的**唯一来源**：机队档案里的 `separation.maxExtraMinutes`。"""
    return profiles()['separation']['maxExtraMinutes']
