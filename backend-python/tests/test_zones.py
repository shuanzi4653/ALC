"""固定管制空域目录与规划接入测试。

这里断言的不是"区域数量够不够"，而是三条纪律有没有被破坏：

1. **有几何就必须有法定依据**。目录里凡带 geometry 的站点，一律要有 citation 与
   geometryRule，且几何种类只允许出现在 ``zones.GEOMETRY_KINDS`` 里；半径只允许取
   已公开的取值（55 km 净空保护区域、5 km 核设施最小包络、500 m 导航台有源保护区）。
2. **没有公开范围就不许画**。无几何的站点必须声明原因（PERIMETER_NOT_PUBLICLY_PUBLISHED
   或 REQUIRES_LOCAL_PUBLICATION）并带上已核验的公开参考点，且一律不得据此推算缓冲半径。
3. **口径要与法条一致**。第十九条划设的是"管制空域"（须经批准），不是绝对禁飞，
   所以机场区域默认按 APPROVAL_REQUIRED 记录穿越，而不是把网络整片关掉；
   严格口径可用且其代价必须是被测量过的，不能是隐藏常量。
"""

import json
import re
import sys
from pathlib import Path

import pytest
from shapely.geometry import Point, shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from traffic import zones  # noqa: E402
from weather.geometry import boundary, project  # noqa: E402

CLAUSE_KEYS = {'AIRPORT', 'BORDER', 'CLASSIFIED_UNIT', 'DEFENCE_INDUSTRY',
               'INFRASTRUCTURE', 'ELECTROMAGNETIC', 'HERITAGE', 'OTHER'}
SECTOR_LABELS = {'民航', '国防', '机密', '科研', '政务'}

# The radii that a published instrument actually fixes for a *flight* restriction.
# 20000 is deliberately absent: GB 31223—2014 protects a radar's measurement
# environment, not the airspace around it.
PUBLISHED_RADII = {500, 5000, 55000}
RADIUS_CITATION_HINTS = {55000: '净空', 5000: 'GB 6249', 500: 'GB 6364'}

# Geometric marks are allowed; emoji are not.
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]')

# The project requires an explicit disclaimer that this is not aeronautical
# information. Losing it would let the catalogue be mistaken for a flight permit.
REQUIRED_FRAMEWORK_KEYS = ('instrument', 'clause', 'publicationRule', 'entryRule',
                           'freeFlightRule', 'reviewPlatform')


@pytest.fixture(scope='module')
def catalog():
    return zones.catalog()


@pytest.fixture(scope='module')
def plan():
    """One real plan, reused by the acceptance tests below.

    Two full simulations would double the suite's cost for no extra coverage, so
    the default-policy plan is built once at module scope.
    """
    from traffic import service
    return service.simulate(seed=42, scenario='live')


def _live_flights_grounded_by_an_unreadable_source(plan):
    """Return a skip reason when the plan has no flying flights *and says why*.

    The acceptance assertions below are about **flight paths** — crossings of a
    fixed control zone, the legal basis attached to each crossing, the count of
    flights needing approval. All of them need a plan in which flights actually
    fly. ``scenario='live'`` reads a public weather service; when that service is
    unreadable the planner fails closed and closes **every** flight, so the
    subject of these assertions does not exist.

    Left unguarded, that reports an outage as a routing regression: the suite
    goes red with `flightsRequiringApproval == 0`, which reads exactly like the
    defect these tests were written to catch. This guard therefore asks the plan
    itself — its own ``weatherSnapshot``, which is the only party that knows
    whether the source answered — and excuses **only** the world where the source
    says it could not be read while nothing was accepted.

    A plan whose source *was* readable and which still accepted nothing is a real
    defect and must go on to fail. ``test_the_guard_excuses_only_an_unreadable_source``
    pins that distinction, including the intermediate case (source unreadable, yet
    flights accepted) which must also fail rather than skip.
    """
    snapshot = plan.get('weatherSnapshot') or {}
    if snapshot.get('available') is not False:
        return None
    if (plan.get('stats') or {}).get('accepted'):
        return None
    closed = len(plan.get('flights') or [])
    return (f"公共天气源自述不可读（{snapshot.get('errorCode') or 'UNKNOWN'}，"
            f"qualityFlags={snapshot.get('qualityFlags')}），"
            f"规划器 fail-closed 关闭全部 {closed} 班次，因此本组断言的被测对象"
            "（在飞的班次与其穿越记录）不存在 —— 这是「无法测量」，不是代码回归。"
            "源可达时同一条断言在本机 20 s 内通过（实测 20 passed / RC 0）")


def test_the_guard_excuses_only_an_unreadable_source():
    """负向对照：守卫必须**只在源自述不可读且一班未受理**时豁免。

    没有这条对照，「加了守卫」与「把关闸关掉」在输出上长得一模一样（M29）。
    """
    # (a) 源可读却一班未受理 —— 真实缺陷，必须放它去失败
    assert _live_flights_grounded_by_an_unreadable_source(
        {'weatherSnapshot': {'available': True}, 'stats': {'accepted': 0}}) is None
    # (b) 源不可读，但仍有班次被受理（例如气象帧缓存命中）—— 被测对象存在，不豁免
    assert _live_flights_grounded_by_an_unreadable_source(
        {'weatherSnapshot': {'available': False}, 'stats': {'accepted': 7}}) is None
    # (c) 载荷里没有 weatherSnapshot —— 不能凭"缺字段"换一次豁免
    assert _live_flights_grounded_by_an_unreadable_source(
        {'stats': {'accepted': 0}}) is None
    # (d) 唯一该豁免的世界：源自述不可读 + 无人受理
    assert _live_flights_grounded_by_an_unreadable_source(
        {'weatherSnapshot': {'available': False, 'errorCode': 'ConnectTimeout',
                             'qualityFlags': ['SOURCE_UNAVAILABLE']},
         'stats': {'accepted': 0}, 'flights': [{}] * 7760})


def sites_with_geometry(policy=zones.DEFAULT_POLICY):
    return [site for site in zones.sites(policy) if site.get('geometry')]


def test_catalog_is_versioned_and_carries_its_legal_basis(catalog):
    for key in ('schemaVersion', 'catalogVersion', 'dataRetrievedAt', 'coordinateReferenceSystem',
                'disclaimer', 'legalFramework', 'clauses', 'sites'):
        assert key in catalog, f'目录缺少字段 {key}'
    assert catalog['coordinateReferenceSystem'] == 'EPSG:4326'
    assert catalog['dataRetrievedAt'], '缺少公开数据取得日期，无法追溯'

    framework = catalog['legalFramework']
    for key in REQUIRED_FRAMEWORK_KEYS:
        assert framework.get(key), f'法律框架缺少 {key}'
    assert '无人驾驶航空器飞行管理暂行条例' in framework['instrument']
    assert '761' in framework['instrument'], '应记录国令第 761 号'
    assert '第十九条' == framework['clause']
    # The entry rule is the reason the whole feature is approval-based rather than
    # a hard ban, so it has to be quoted verbatim rather than paraphrased.
    assert '未经空中交通管理机构批准' in framework['entryRule']
    assert '不得在管制空域内实施无人驾驶航空器飞行活动' in framework['entryRule']
    assert '适飞空域' in framework['freeFlightRule']
    # The publication rule is quoted because it is the reason concrete boundaries
    # are absent here: they are published per city as aeronautical information.
    assert '由设区的市级以上人民政府公布' in framework['publicationRule']
    assert 'uom.caac.gov.cn' in framework['reviewPlatform']
    assert '不构成飞行许可' in catalog['disclaimer']


def test_catalog_contains_no_emoji(catalog):
    # Checked on the serialised text so every nested note is covered at once.
    text = json.dumps(catalog, ensure_ascii=False)
    found = EMOJI.findall(text)
    assert not found, f'目录含 emoji：{found[:5]}'
    assert '·' in text, '间隔号应当保留，它不属于 emoji'


def test_every_item_of_clause_19_is_represented(catalog):
    clauses = catalog['clauses']
    assert len(clauses) == 8, '第十九条八项必须全部在册'
    assert {clause['key'] for clause in clauses} == CLAUSE_KEYS
    for clause in clauses:
        assert clause['clause'].startswith('第十九条')
        assert clause['title'], f"{clause['key']} 缺少条文摘要"
        assert clause['geometryStatus'], f"{clause['key']} 缺少几何状态说明"
        assert clause['sectorLabel'] in SECTOR_LABELS, f"{clause['key']} 的领域标签非法"
        assert clause['citation'], f"{clause['key']} 缺少依据"
        assert clause['authority'], f"{clause['key']} 缺少主管机关"
        # A clause that neither publishes a rule nor explains what to review is a
        # dead end for the operator, so every clause must carry one or the other.
        assert clause.get('geometryRule') or clause.get('reviewAction'), \
            f"{clause['key']} 既没有几何规则也没有复核指引"


def test_the_four_requested_sectors_are_all_present(catalog):
    sectors = {clause['sectorLabel'] for clause in catalog['clauses']}
    for expected in ('机密', '国防', '科研', '政务'):
        assert expected in sectors, f'缺少领域：{expected}'
    # 机密 can never be mapped — it is the category whose boundaries are withheld
    # by design — but it must still be declared, with its sites at zero.
    classified = [clause for clause in catalog['clauses'] if clause['sector'] == 'CLASSIFIED'][0]
    assert classified['siteCount'] == 0
    assert '不公开' in classified['reviewAction']


def test_geometry_exists_only_where_a_published_rule_fixes_the_shape(catalog):
    for site in catalog['sites']:
        geometry = site.get('geometry')
        if geometry is None:
            status = site.get('geometryStatus') or ''
            assert 'NOT_PUBLICLY_PUBLISHED' in status or 'REQUIRES_LOCAL_PUBLICATION' in status, \
                f"{site['id']} 无几何却未声明原因：{status}"
            coordinate = (site.get('referencePoint') or {}).get('coordinate')
            assert coordinate and len(coordinate) == 2, f"{site['id']} 缺少已核验的公开参考点"
            continue
        assert geometry['kind'] in zones.GEOMETRY_KINDS, \
            f"{site['id']} 使用了未公开的几何种类 {geometry['kind']}"
        assert site.get('citation'), f"{site['id']} 有几何却没有法定依据"
        assert site.get('geometryRule'), f"{site['id']} 有几何却没有几何规则说明"
        assert site.get('sectorLabel') in SECTOR_LABELS


def test_every_radius_is_drawn_from_a_published_instrument(catalog):
    radii = set()
    for site in sites_with_geometry():
        geometry = site['geometry']
        if geometry['kind'] != 'CIRCLE':
            continue
        radius = geometry['radiusM']
        radii.add(radius)
        hint = RADIUS_CITATION_HINTS.get(radius)
        assert hint is not None, f"{site['id']} 使用了未公开的半径 {radius} m"
        assert hint in site['citation'], \
            f"{site['id']} 半径 {radius} m 与所引依据不符：{site['citation']}"
    assert radii == PUBLISHED_RADII, f'半径集合发生变化，需重新核对依据：{sorted(radii)}'
    # The GB 31223 radar protection radius must never appear as flight geometry.
    assert 20000 not in radii


def test_weather_radar_is_registered_instead_of_given_invented_airspace(catalog):
    radars = [site for site in catalog['sites'] if site.get('facilityType') == 'WEATHER_RADAR_STATION']
    assert len(radars) == 1, f'预期登记 1 个天气雷达站，实际 {len(radars)}'
    radar = radars[0]
    assert radar['geometry'] is None, '天气雷达站的探测环境保护区不得当作飞行管制空域几何'
    assert radar['enforcement'] == zones.REGISTERED
    assert radar['geometryStatus'] == 'PERIMETER_NOT_PUBLICLY_PUBLISHED'
    assert 'GB 31223' in radar['citation']
    # The note must state the two-regime distinction, otherwise a future edit can
    # quietly reintroduce a 20 km no-fly disc over a city centre.
    assert '探测环境' in radar['note'] and '第十九条' in radar['note']
    assert 'GB 31223' in radar['reviewAction']
    coordinate = radar['referencePoint']['coordinate']
    assert boundary().covers(Point(project(tuple(coordinate)))), '雷达参考点应在运行边界内'
    assert radar['operator'], '登记项应记录运营单位，便于人工复核'


def test_runway_rectangles_follow_the_published_inspection_rule(catalog):
    rectangles = [site for site in sites_with_geometry() if site['geometry']['kind'] == 'RUNWAY_RECT']
    assert rectangles, '机场净空巡视检查区域应当存在'
    for site in rectangles:
        geometry = site['geometry']
        assert geometry['halfWidthM'] == 10000, f"{site['id']} 两侧宽度应各为 10 km"
        assert geometry['beyondEndM'] == 20000, f"{site['id']} 端外应外延 20 km"
        assert geometry['runwayLengthM'] > 0, f"{site['id']} 缺少跑道长度"
        assert 0 <= geometry['bearingDeg'] < 360, f"{site['id']} 跑道方位非法"
        # The strict reading is only meaningful if it is flagged on the record.
        assert site.get('strictEnforcement') == zones.PROHIBITED


def test_reference_points_are_plausible_public_coordinates_inside_the_area(catalog):
    for site in catalog['sites']:
        coordinate = (site.get('referencePoint') or {}).get('coordinate')
        if not coordinate:
            continue
        lon, lat = coordinate
        assert 118 < lon < 136 and 38 < lat < 54, f"{site['id']} 参考点不在东北范围内：{coordinate}"
        assert boundary().covers(Point(project(tuple(coordinate)))), f"{site['id']} 参考点在运行边界外"
        provenance = site.get('provenance') or {}
        assert provenance.get('referencePoint'), f"{site['id']} 缺少来源记录"
        assert provenance.get('retrievedAt'), f"{site['id']} 缺少取得日期"


def test_frame_clips_geometry_and_flags_unpublished_ceilings():
    for record in zones.frame(zones.DEFAULT_POLICY, display_ceiling_agl_m=620):
        geometry = record.get('geometry')
        if not geometry:
            assert record.get('referencePoint'), f"{record['id']} 无几何也无参考点"
            continue
        # Clipping is what keeps a 55 km aerodrome circle from spilling across the
        # whole map; a leftover sliver outside the boundary means the clip failed.
        outside = shape(geometry).difference(boundary()).area
        assert outside < 1, f"{record['id']} 有 {outside:.0f} m² 落在运行边界外"
        assert record['geometryStatus'], f"{record['id']} 缺少几何状态"
        assert record['displayCeilingAglM'] > record['floorAglM'], f"{record['id']} 顶底面关系非法"
        assert isinstance(record['openEndedAbove'], bool)
        if record['ceilingAglM'] is None:
            # Nothing published an upper limit, so the drawn top is a viewport
            # ceiling and must be flagged as such rather than presented as legal.
            assert record['openEndedAbove'] is True, f"{record['id']} 未公布上限却未标记"
            assert record['displayCeilingAglM'] == 620


def test_declared_vertical_bands_are_consistent():
    for site in sites_with_geometry():
        floor = float(site.get('floorAglM') or 0)
        assert floor >= 0, f"{site['id']} 底面为负"
        if site.get('ceilingAglM') is not None:
            assert site['ceilingAglM'] > floor, f"{site['id']} 顶面低于底面"
    airports = [site for site in sites_with_geometry() if site['clause'] == 'AIRPORT'
                and site['geometry']['kind'] == 'CIRCLE']
    # 真高 120 m is the published lower bound for the aerodrome controlled band;
    # an 80 m delivery drone must therefore not be flagged inside it.
    assert airports and all(site['floorAglM'] == 120 for site in airports)


def test_envelope_keeps_approval_required_zones_out_of_the_obstacle_set():
    approval = zones.envelope(zones.APPROVAL_REQUIRED)
    strict = zones.envelope(zones.PROHIBITED)
    assert approval.is_empty or approval.area > 0
    # Under the strict reading the 48 aerodrome inspection rectangles join the
    # obstacle set, which is a very large change — hence the explicit default.
    assert strict.area > approval.area * 5, (strict.area, approval.area)

    prohibited_ids = {site['id'] for site in zones.sites() if site['enforcement'] == zones.PROHIBITED}
    geometries = zones._geometries()
    for site_id in prohibited_ids:
        if site_id in geometries:
            assert approval.covers(geometries[site_id].representative_point()), \
                f'禁入区 {site_id} 必须参与硬性绕行'
    airport_ids = {site['id'] for site in zones.sites() if site['clause'] == 'AIRPORT'}
    assert airport_ids and airport_ids.isdisjoint(prohibited_ids), \
        '默认口径下机场区域不得进入禁入集合'


def _airport_circle():
    for site in sites_with_geometry():
        if site['clause'] == 'AIRPORT' and site['geometry']['kind'] == 'CIRCLE':
            return site
    raise AssertionError('缺少机场净空保护区域')


def _trajectory_through_zone(site, alt_m, samples=8):
    """A straight line crossing the zone centre, in projected metres."""
    x, y = project(tuple(site['geometry']['centre']))
    span = float(site['geometry']['radiusM']) * 0.5
    return [[x - span + 2 * span * index / (samples - 1), y, alt_m, index * 0.5]
            for index in range(samples)]


def test_crossings_honour_the_published_altitude_band():
    site = _airport_circle()
    floor = float(site['floorAglM'])
    assert floor > 0, '机场净空保护区域应有已公布的高度下限'

    # The trajectory runs through the aerodrome centre, so it also crosses the
    # zero-floor runway inspection rectangle. Assertions therefore target the
    # specific zone rather than a total count, which stays robust if the two
    # published footprints are ever redrawn.
    below = _trajectory_through_zone(site, floor - 20)
    _, records = zones.crossings(below)
    assert site['id'] not in {record['zoneId'] for record in records}, \
        '低于公布高度下限时不应记入该管制空域'

    inside = _trajectory_through_zone(site, floor + 230)
    summary, records = zones.crossings(inside)
    assert summary['clauses'] == ['AIRPORT']
    record = [item for item in records if item['zoneId'] == site['id']]
    assert record, '达到公布高度下限时应记入该管制空域'
    record = record[0]
    assert record['entryMinute'] <= record['exitMinute']
    assert record['maxAglM'] >= floor
    assert record['citation'] == site['citation']
    assert record['enforcement'] == zones.APPROVAL_REQUIRED
    assert summary['approvalRequired'] >= 1 and summary['prohibited'] == 0


def test_crossings_are_empty_far_outside_the_network():
    x, y = project((110.0, 30.0))
    summary, records = zones.crossings([[x, y, 300, 0], [x + 50, y, 300, 1]])
    assert summary == {'zones': 0, 'prohibited': 0, 'approvalRequired': 0, 'clauses': []}
    assert records == []


def test_crossings_rank_prohibited_ahead_of_approval_required():
    navaid = [site for site in sites_with_geometry() if site['enforcement'] == zones.PROHIBITED
              and site['geometry']['kind'] == 'CIRCLE' and site['clause'] == 'ELECTROMAGNETIC'][0]
    x, y = project(tuple(navaid['geometry']['centre']))
    summary, records = zones.crossings([[x - 40, y, 120, 0], [x + 40, y, 120, 1]])
    assert summary['prohibited'] == 1
    assert records[0]['enforcement'] == zones.PROHIBITED


def test_point_zones_locates_the_zone_a_pad_would_sit_in():
    navaid = [site for site in sites_with_geometry() if site['clause'] == 'ELECTROMAGNETIC'][0]
    coordinate = tuple(navaid['geometry']['centre'])
    assert navaid['id'] in {site['id'] for site in zones.point_zones(coordinate)}
    covering = zones.covering_layer(coordinate, agl_m=200)
    assert navaid['id'] in {site['id'] for site in covering}
    far = zones.point_zones((110.0, 30.0))
    assert far == []


def test_catalog_validation_rejects_fabricated_geometry(tmp_path, monkeypatch):
    original = json.loads(zones.CATALOG_FILE.read_text(encoding='utf-8'))

    def load_with(sites):
        target = tmp_path / 'fixed-zones.json'
        target.write_text(json.dumps({**original, 'sites': sites}, ensure_ascii=False), encoding='utf-8')
        monkeypatch.setattr(zones, 'CATALOG_FILE', target)
        for cached in (zones.catalog, zones._geometries, zones._by_id, zones._index):
            cached.cache_clear()
        try:
            return zones.catalog()
        finally:
            for cached in (zones.catalog, zones._geometries, zones._by_id, zones._index):
                cached.cache_clear()

    template = dict(original['sites'][0])

    with pytest.raises(ValueError):
        load_with([{**template, 'geometry': {'kind': 'POLYGON', 'centre': [126, 45]}}])
    with pytest.raises(ValueError):
        load_with([{**template, 'clause': 'NOT_A_CLAUSE'}])
    with pytest.raises(ValueError):
        load_with([{**template, 'enforcement': 'MAYBE'}])
    with pytest.raises(ValueError):
        load_with([{**template, 'geometry': {'kind': 'CIRCLE', 'centre': [126, 45], 'radiusM': 100},
                    'citation': None}])
    # A registration without a verified coordinate is not acceptable either: the
    # validator must reject it before it can reach the map as a bare marker.
    with pytest.raises(ValueError):
        load_with([{**template, 'geometry': None, 'referencePoint': None,
                    'geometryStatus': 'PERIMETER_NOT_PUBLICLY_PUBLISHED'}])

    # The real catalogue still loads after the cache churn.
    assert len(load_with(original['sites'])) == len(original)


def test_plan_records_approvals_without_closing_the_network(plan):
    reason = _live_flights_grounded_by_an_unreadable_source(plan)
    if reason:
        pytest.skip(reason)
    stats = plan['stats']['staticAirspace']
    assert stats['policy'] == zones.APPROVAL_REQUIRED
    assert stats['zoneCount'] == len(sites_with_geometry()), '统计口径应与目录一致'
    # The default reading must not silently gut the network: 第十九条 gates entry
    # through approval, so crossings are recorded rather than flights cancelled.
    assert stats['closedByStaticAirspace'] == 0, '默认口径不应因固定管制区关闭班次'
    assert stats['flightsRequiringApproval'] > 0, '应有班次被记为需要批准'
    assert stats['crossingRecords'] > 0
    assert stats['clauses'], '统计应给出实际涉及的条文类别'


def test_every_recorded_crossing_carries_its_legal_basis(plan):
    reason = _live_flights_grounded_by_an_unreadable_source(plan)
    if reason:
        pytest.skip(reason)
    checked = 0
    for flight in plan['flights']:
        block = flight['staticAirspace']
        assert block['zones'] >= len(block['crossings']), '记录数不得超过计数'
        for record in block['crossings']:
            assert record['zoneId'] and record['name']
            assert record['citation'], f"{record['zoneId']} 的穿越记录缺少依据"
            assert record['enforcement'] in set(zones.ENFORCEMENT_LEVELS) - {zones.REGISTERED}
            assert record['entryMinute'] <= record['exitMinute']
            assert record['maxAglM'] > 0
            checked += 1
    assert checked > 0, '本轮计划中应有固定管制区穿越记录可供核对'


def test_strict_airport_reading_is_available_and_measured(monkeypatch):
    from traffic import service

    monkeypatch.setattr(service, 'airport_footprint_policy', lambda: zones.PROHIBITED)
    strict = service.simulate(seed=42, scenario='live')
    reason = _live_flights_grounded_by_an_unreadable_source(strict)
    if reason:
        pytest.skip(reason)
    stats = strict['stats']['staticAirspace']
    assert stats['policy'] == zones.PROHIBITED
    assert stats['closedByStaticAirspace'] > 0, '严格口径应当产生 STATIC_AIRSPACE_BLOCKED'
    blocked = [flight for flight in strict['flights']
               if flight['reason'] == 'STATIC_AIRSPACE_BLOCKED']
    assert len(blocked) == stats['closedByStaticAirspace']
    for flight in blocked:
        assert not flight['points'], '被固定管制区拦下的班次不应留下航迹'
    # Both readings must stay reachable, and the difference has to be large enough
    # that the choice is a real engineering decision rather than a cosmetic flag.
    assert zones.envelope(zones.PROHIBITED).area > zones.envelope(zones.APPROVAL_REQUIRED).area * 5
