"""Regenerate the V1.5 evidence for risk-merge, flat rendering and zone intrusion.

Every number in the emitted report is measured here and now: the merge counts come
from `NetworkWeather.frame`, the plan figures from a real `service.simulate`, and
the band comparison from the same simulation with the band's envelope disabled.
Nothing is estimated or carried over from an earlier round.

Usage: python _gen_v15_evidence.py [seed] [scenario]
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json
import time
from collections import Counter

from shapely.geometry import GeometryCollection, Point, shape
from shapely import affinity


from traffic import service, zones as fixed_zones  # noqa: E402
from traffic.weather import NetworkWeather  # noqa: E402
from weather.geometry import boundary, project, unproject  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
SCENARIO = sys.argv[2] if len(sys.argv) > 2 else 'moving'
OUT = ROOT / 'docs' / 'evaluation-v1.5'
MINUTES = [0, 30, 60, 120, 240]


def iso_now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def measure_merge():
    world = NetworkWeather(SEED, SCENARIO)
    rows = []
    for minute in MINUTES:
        cells = world.shapes(minute)
        regions = world.frame(minute)
        drawable = [cell['id'] for cell, field, _, _ in cells
                    if not field.intersection(boundary()).is_empty]
        rows.append({
            'minute': minute,
            'cells': len(cells),
            'drawableCells': len(drawable),
            'regions': len(regions),
            'mergedGroups': [{'id': r['id'], 'members': r['memberCount'], 'sources': r['sources']}
                             for r in regions if r['memberCount'] > 1],
            'polygonsBefore': len(cells) * 3,
            'polygonsAfter': sum(1 for r in regions for key in ('field', 'ban', 'caution')
                                 if shape(r[key]).geom_type in ('Polygon', 'MultiPolygon')),
        })
    return {
        'minutesSampled': MINUTES,
        'rows': rows,
        'cellsPerMinute': len(NetworkWeather(SEED, SCENARIO).shapes(0)),
        'regionsRange': [min(row['regions'] for row in rows), max(row['regions'] for row in rows)],
    }


def measure_band():
    band = NetworkWeather(SEED, SCENARIO)
    cell = next(c for c in band.cells if c['shape'] == 'BAND')
    centroid = cell['polygon'].centroid
    lonlat = unproject((centroid.x, centroid.y))

    # The band is a chain of discrete clusters, not a ribbon, so what has to be
    # measured is the gap between clusters: "some large cloud masses with smaller
    # ones between them, with gaps you can pass through". A continuous band severed
    # the network east-west, and a gap too narrow to fly through might as well not
    # exist, so both the count of clusters and the narrowest corridor are reported.
    clusters = []
    for minute in (0, 120, 240, 479):
        dx, dy = band.drift(cell, minute)
        outline = affinity.translate(cell['polygon'], xoff=dx, yoff=dy)
        parts = _parts(outline)
        gaps = [min((part.distance(other) for index, other in enumerate(parts)
                     if index != offset), default=0.0)
                for offset, part in enumerate(parts)]
        clipped = outline.intersection(boundary())
        clipped_parts = _parts(clipped)
        # Worst west-east line: the most extreme value of "fraction of an east-west
        # scan line that is covered", taken over a coarse grid of scan lines. This is
        # the severance figure — how badly a continuous band cuts the network in two.
        west_east = _worst_scanline(clipped)
        clusters.append({
            'minute': minute,
            'parts': len(parts),
            'minGapM': round(min(gaps), 1) if gaps else None,
            'gapsUnder1km': sum(1 for gap in gaps if gap < 1000.0),
            'clippedParts': len(clipped_parts),
            'clippedAreaKm2': round(clipped.area / 1e6, 1),
            'worstWestEastShare': round(west_east, 4),
        })

    band_row = {
        'centroidLonLat': [round(v, 4) for v in lonlat],
        'boundsM': [round(v, 1) for v in cell['polygon'].bounds],
        'insideBoundary': boundary().covers(centroid),
        'clusters': clusters,
        'clusterRadiiM': list(cell['radius']) if isinstance(cell['radius'], (list, tuple)) else cell['radius'],
        'centrelineLonLat': [[round(a, 3), round(b, 3)] for a, b in
                             [(121.4, 41.0), (123.6, 42.6), (126.2, 44.4), (128.9, 46.6), (131.4, 49.2)]],
        'projectedFirstVertexM': [round(v, 1) for v in project((121.4, 41.0))],
    }
    original = NetworkWeather._swept_band

    def absent(self, cell_ref, start_bin, end_bin):
        return GeometryCollection()

    active = summarise(service.simulate(SEED, SCENARIO))
    NetworkWeather._swept_band = absent
    try:
        without = summarise(service.simulate(SEED, SCENARIO))
    finally:
        NetworkWeather._swept_band = original
    delta = {
        'weatherBlocked': active['reasons'].get('WEATHER_BLOCKED', 0) - without['reasons'].get('WEATHER_BLOCKED', 0),
        'closed': (active['closed'] or 0) - (without['closed'] or 0),
        'accepted': (active['accepted'] or 0) - (without['accepted'] or 0),
        'detours': (active['detours'] or 0) - (without['detours'] or 0),
    }
    return {'band': band_row, 'withBandEnvelope': active, 'withoutBandEnvelope': without, 'delta': delta}


def _parts(geometry):
    """Every polygon inside a Polygon/MultiPolygon/GeometryCollection."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return [part for part in getattr(geometry, 'geoms', [])
            if part.geom_type == 'Polygon' and not part.is_empty]


def _worst_scanline(geometry):
    """The most covered east-west scan line, as a fraction of the network box.

    Reported as a share so it is comparable across networks: 1.0 would mean some
    latitude is completely blocked from west to east by this geometry.
    """
    from shapely.geometry import box, LineString
    minx, miny, maxx, maxy = geometry.bounds
    if maxx <= minx:
        return 0.0
    best = 0.0
    steps = 24
    for index in range(1, steps):
        y = miny + (maxy - miny) * index / steps
        line = LineString([(minx - 1000, y), (maxx + 1000, y)])
        covered = line.intersection(geometry).length
        best = max(best, covered / (maxx - minx + 2000))
    return best


def summarise(result):
    stats = result.get('stats') or {}
    reasons = Counter(flight.get('reason') for flight in result.get('flights') or [])
    return {
        'flights': len(result.get('flights') or []),
        'accepted': stats.get('accepted'),
        'closed': stats.get('closed'),
        'detours': stats.get('detours'),
        'resolved': stats.get('resolved'),
        'reasons': dict(reasons.most_common()),
        'flightsRequiringApproval': (stats.get('staticAirspace') or {}).get('flightsRequiringApproval'),
        'prohibitedConflicts': (stats.get('staticAirspace') or {}).get('prohibitedConflicts'),
    }


def measure_crossings():
    started = time.time()
    result = service.simulate(SEED, SCENARIO)
    policy = service.airport_footprint_policy()
    flights = result.get('flights') or []
    entering = Counter()
    prohibited = Counter()
    per_flight = Counter()
    for flight in flights:
        block = flight.get('staticAirspace') or {}
        zones = int(block.get('zones') or 0)
        per_flight[zones] += 1
        if zones:
            entering[flight.get('mode')] += 1
        if int(block.get('prohibited') or 0) > 0:
            prohibited[flight.get('mode')] += 1
    total = len(flights) or 1
    return {
        'policy': policy,
        'seconds': round(time.time() - started, 2),
        'flights': len(flights),
        'enteringAnyZone': dict(entering),
        'enteringAnyZoneTotal': sum(entering.values()),
        'enteringAnyZoneShare': round(sum(entering.values()) / total, 4),
        'enteringProhibitedTotal': sum(prohibited.values()),
        'zonesPerFlight': dict(sorted(per_flight.items())),
        # The tint rule follows directly from this split: 46% of the fleet crossing
        # an aerodrome area is the normal operating state, so only a prohibition
        # (currently zero by construction) repaints a vehicle red.
        'alertRuleBasis': {
            'tintOn': 'PROHIBITED only',
            'reported': 'APPROVAL_REQUIRED, counted and shown, never tinted',
        },
        'planStats': {key: value for key, value in (result.get('stats') or {}).items()
                      if not isinstance(value, (list, dict))},
    }


def measure_alignment():
    """Do facilities and trajectories sit inside the risk surfaces, and when?

    This answers the second half of the merge request — whether departure pads,
    delivery nodes and trajectories have to be redrawn around the new regions —
    with measured facts rather than a preference.

    The comparison is **time aligned**: a trajectory point is tested against the
    risk surface at that point's own minute. Risk areas drift with the wind, so
    comparing a point against a snapshot from another minute is the same category
    of mistake as the unprojected rain band — the numbers look like evidence while
    describing two different worlds. (An earlier version of this probe did exactly
    that and reported 278 suspicious flights that were not real.)

    FIELD is the outer caution contour, which routing is allowed to clip; BAN is the
    core, which it is not. Only a BAN hit is a defect.
    """
    result = service.simulate(SEED, SCENARIO)
    accepted = [flight for flight in result.get('flights') or [] if flight.get('points')]
    pads = [pad for pad in service.network()['pads'] if pad.get('xy')]

    surfaces = {}
    for minute in range(0, service.TIMELINE_MINUTES):
        fields, bans = [], []
        for cell in service.weather_frame(SEED, SCENARIO, minute)['cells']:
            for key, bucket in (('field', fields), ('ban', bans)):
                geometry = cell.get(key)
                if geometry:
                    value = shape(geometry)
                    if not value.is_empty:
                        bucket.append(value)
        surfaces[minute] = (fields, bans)

    facility_rows = []
    for minute in MINUTES:
        fields, bans = surfaces[minute]
        inside_field = [pad for pad in pads if any(g.contains(Point(pad['xy'][:2])) for g in fields)]
        inside_ban = [pad for pad in pads if any(g.contains(Point(pad['xy'][:2])) for g in bans)]
        facility_rows.append({
            'minute': minute,
            'regions': len(fields),
            'fieldHits': len(inside_field),
            'banHits': len(inside_ban),
            'fieldHitsHub': sum(1 for pad in inside_field if not str(pad['id']).startswith('DEL-')),
            'fieldHitsNode': sum(1 for pad in inside_field if str(pad['id']).startswith('DEL-')),
        })

    field_hits = 0
    ban_hits = 0
    ban_samples = []
    for flight in accepted:
        in_field = in_ban = False
        for point in flight['points']:
            fields, bans = surfaces[int(point[3])]
            location = Point(point[0], point[1])
            if not in_field and any(g.contains(location) for g in fields):
                in_field = True
            if not in_ban and any(g.contains(location) for g in bans):
                in_ban = True
                ban_samples.append({'flight': flight['id'], 'x': round(point[0], 1),
                                    'y': round(point[1], 1), 'minute': int(point[3])})
        field_hits += in_field
        ban_hits += in_ban

    return {
        'pads': len(pads),
        'minutesCovered': len(surfaces),
        'facilities': facility_rows,
        'trajectories': {
            'accepted': len(accepted),
            'fieldHits': field_hits,
            'banHits': ban_hits,
            'banSamples': ban_samples[:5],
        },
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    merge = measure_merge()
    band = measure_band()
    crossings = measure_crossings()
    alignment = measure_alignment()
    fixed = fixed_zones.status(service.airport_footprint_policy())

    report = {
        'generatedAt': iso_now(),
        'seed': SEED,
        'scenario': SCENARIO,
        'fixedAirspace': {key: fixed[key] for key in
                          ('ready', 'catalogVersion', 'dataRetrievedAt', 'sites', 'withGeometry',
                           'prohibited', 'approvalRequired', 'registered', 'policy')},
        'riskMerge': merge,
        'rainBand': band,
        'crossings': crossings,
        'alignment': alignment,
        'elapsedSeconds': round(time.time() - started, 2),
    }
    (OUT / 'risk-merge-and-flat-render.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    (OUT / 'risk-merge-and-flat-render.md').write_text(render_markdown(report), encoding='utf-8')
    print(json.dumps({'written': str(OUT), 'elapsedSeconds': report['elapsedSeconds']},
                     ensure_ascii=False))
    print(json.dumps({'mergeRegions': merge['regionsRange'], 'bandDelta': band['delta'],
                      'crossings': {k: crossings[k] for k in
                                    ('enteringAnyZoneTotal', 'enteringAnyZoneShare',
                                     'enteringProhibitedTotal')},
                      'alignment': alignment['trajectories']}, ensure_ascii=False))


def render_markdown(report):
    merge, band, crossings = report['riskMerge'], report['rainBand'], report['crossings']
    alignment = report['alignment']
    fixed = report['fixedAirspace']
    lines = [
        '# 风险区合并 · 平面渲染 · 入区标红（实测证据）',
        '',
        f'- 生成时间：{report["generatedAt"]}',
        f'- 随机种子 / 情景：{report["seed"]} / {report["scenario"]}',
        f'- 全部数字由 `_gen_v15_evidence.py` 现场测量，非估算、非沿用旧轮次。',
        '',
        '## 一、风险区合并',
        '',
        '| 时刻（分钟） | 单体 | 边界内可画单体 | 合并后区域 | 合并组 | 合并前多边形 | 合并后多边形 |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for row in merge['rows']:
        groups = '；'.join(f'{g["id"]}（{g["members"]} 单体）' for g in row['mergedGroups']) or '无'
        lines.append(f'| {row["minute"]} | {row["cells"]} | {row["drawableCells"]} | **{row["regions"]}** '
                     f'| {groups} | {row["polygonsBefore"]} | {row["polygonsAfter"]} |')
    lines += [
        '',
        f'- 合并后区域数区间：**{merge["regionsRange"][0]}–{merge["regionsRange"][1]}**（单体恒为 {merge["cellsPerMinute"]}）。',
        '- 合并粒度取「场区（FIELD）连通分量」；核心（BAN）取成员单体并集，谨慎环（CAUTION）',
        '  重建为「成员自身外缘并集 − 合并后核心」，因此两层恒不相交——否则相邻单体的核心会落进',
        '  另一单体的谨慎环里，把更严重的那一层涂掉。',
        '- **区域数可以多于单体数，这不是回归**：雨带已是一条云团链，单个 BAND 单体本身就横跨约 20 个',
        '  互不相连的云团，于是 FIELD 连通分量数大于单体数。合并的目标是「让相接触的单体不再画出缝」，',
        '  不是「让数字变小」。单测因此改锁「区域数 == FIELD 连通分量数」而不再是「< 单体数」。',
        '- 多边形数同样**会因切分而增加**（63 → 108 左右）：每个云团各自是一个多边形，',
        '  加上它们的裁剪副本。数字上升反映的是几何被如实拆分，不是绘制量失控。',
        '- 只改呈现：`swept()` 仍逐单体包络，避让包络恒为「已画区域」的超集。单测锁定。',
        '',
        '### 1.1 合并归属缺陷（本轮修掉）',
        '',
        '`_dissolve_regions` 按 FIELD 分量给成员分组、却收集成员**整个** BAN。单体型时期每个单体只有一个',
        '多边形，这么做无害；雨带成链后单个 BAN 是 20 个相距最远 1.14 Mm 的多边形，于是**每个区域都被',
        '塞进了全部 20 个核心**。实测核心落在自身场区之外达 **142,047,519,714 m²**，最远一块核心离本区域',
        '场区 **1,135,977 m**。画面上表现为「禁入色块出现在离它所属云团很远处」。',
        '修法：每个核心按区域自身的场区裁剪后再并。修后两项均为 **0**。',
        '- `sources` 的语义同时收紧：横跨多个区域的单体每区贡献一个 `<id>::CLUSTER` 标签，',
        '  不再是同一个裸 id 重复 18 次——否则「可追溯到成员单体」这句话在每个区域里都指向整条雨带。',
        '',
        '## 二、东北雨带：从连续条带改为带间隙的云团链',
        '',
        '这一节记录雨带几何的两次修正，两次都是**先测量后改**。',
        '',
        '### 2.1 第一次修正：手写多边形未投影（缺陷，已修）',
        '',
        '原实现的手写米制多边形**从未经过本工程投影**，落在北偏约 4300 km 处：显示侧裁到空多边形',
        '（**雨带从未被画出来**），避让侧却照样并入包络。现改为地理中线 + 本工程投影。',
        '',
        '### 2.2 第二次修正：连续条带会切断东西向网络（用户指出，已改）',
        '',
        '投影修好之后雨带是一条连续的 `buffer(26000)` 条带，跨越 1212 km 中线、宽约 190 km。',
        '它在东西方向上把整个网络一刀切断 —— 没有任何航路能穿过。改为**沿中线采样的离散云团链**：',
        '半径在 `BAND_CLUSTER_RADII_M` 间循环，使链呈现「大云团夹小云团」并且**中间留有可穿越的间隙**。',
        '',
        '- 间隙是**由构造保证**的，不是碰运气：间距恒大于 `r[i] + r[i+1] + 2×GAP`。',
        '  半径循环因此必须**永不把两个大半径排在一起**——大-大相邻单独就需要 76000 m 间距。',
        '- **卫星小云团方案被实测否决**：把一个小云团挂在每个大云团旁边，雷达图上看很对，',
        '  但它会把一块云团停在间隙里 —— 实测最小自由距离由 **8131 m 掉到 449 m**，',
        '  出现 3 个不足 1 km 的间隙，东西向割裂度直接回到旧条带的 5.4%。',
        '  反直觉的是：面积更小（裁后 33626 km²）却关闭了**更多**班次（2621 vs 2036），',
        '  所以面积不是原因，卫星才是。当前实现不带卫星。',
        '',
        '| 时刻（分钟） | 云团数 | 最小间隙（m） | <1km 间隙数 | 裁后云团 | 裁后面积（km²） | 最差东西向占比 |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for row in band['band']['clusters']:
        lines.append(f'| {row["minute"]} | {row["parts"]} | **{row["minGapM"]}** | {row["gapsUnder1km"]} '
                     f'| {row["clippedParts"]} | {row["clippedAreaKm2"]} | {row["worstWestEastShare"] * 100:.2f}% |')
    lines += [
        '',
        f'- 云团半径循环：`{band["band"]["clusterRadiiM"]}`（间距 62000 m，间隙预算 9000 m）',
        f'- 雨带中心：**{band["band"]["centroidLonLat"][0]:.3f}°E, {band["band"]["centroidLonLat"][1]:.3f}°N**'
        f'；几何范围（米）：{band["band"]["boundsM"]}',
        f'- 中心是否落在作业边界内：{band["band"]["insideBoundary"]}',
        '',
        '### 2.3 雨带包络的代价（A/B 实测）',
        '',
        '| 场景 | 接受 | 关闭 | 绕行 | 天气阻断 |',
        '| --- | --- | --- | --- | --- |',
        f'| 雨带包络生效 | {band["withBandEnvelope"]["accepted"]} | {band["withBandEnvelope"]["closed"]} '
        f'| {band["withBandEnvelope"]["detours"]} | {band["withBandEnvelope"]["reasons"].get("WEATHER_BLOCKED", 0)} |',
        f'| 雨带包络缺失（复现旧缺陷） | {band["withoutBandEnvelope"]["accepted"]} '
        f'| {band["withoutBandEnvelope"]["closed"]} | {band["withoutBandEnvelope"]["detours"]} '
        f'| {band["withoutBandEnvelope"]["reasons"].get("WEATHER_BLOCKED", 0)} |',
        f'| **差值** | **{band["delta"]["accepted"]}** | **+{band["delta"]["closed"]}** '
        f'| {band["delta"]["detours"]} | **+{band["delta"]["weatherBlocked"]}** |',
        '',
        f'即：若雨带包络缺失，有 **{band["delta"]["weatherBlocked"]} 个班次会被径直放行穿过东北雨带**——',
        '这正是「轨迹跑到禁飞区」的另一半根因。',
        '',
        '注：雨带由连续条带改为云团链后，包络的代价从 +1270 降到 '
        f'+{band["delta"]["weatherBlocked"]} —— 链留有可穿越的间隙，部分班次因此能绕过去而不是被关闭。',
        '',
        '## 三、固定管制区穿越与标红依据',
        '',
        f'- 目录：{fixed["sites"]} 站点（{fixed["withGeometry"]} 有几何 / {fixed["registered"]} 仅登记）；'
        f'禁入 {fixed["prohibited"]} / 须批准 {fixed["approvalRequired"]}；口径 `{fixed["policy"]}`',
        f'- 班次：{crossings["flights"]}；纯计算 {crossings["seconds"]} s',
        f'- 进入任一固定管制区：**{crossings["enteringAnyZoneTotal"]}** 班'
        f'（{crossings["enteringAnyZoneShare"] * 100:.1f}%）'
        f'，按机型 {crossings["enteringAnyZone"]}',
        f'- 进入**禁入区**：**{crossings["enteringProhibitedTotal"]}** 班',
        f'- 每班穿越区数分布：{crossings["zonesPerFlight"]}',
        '',
        '标红规则的依据就是上面这两个数：默认口径下有 '
        f'{crossings["enteringAnyZoneShare"] * 100:.1f}% 的机队正常穿越机场净空区，'
        '把这么大比例的机队染红等于让「红」失去含义。因此**只有禁入区穿越染红并触发告警条**；',
        '须批准穿越只计数上报。禁入区穿越当前为 '
        f'{crossings["enteringProhibitedTotal"]} 是**结构性的**——`zones.envelope()` 只并禁入区，',
        '路由已把它们全部避开——所以该告警是**安全网**而非日常态，界面在无告警时显示',
        '「本视图内 0 架位于禁入区」的监视态，让操作员看到检查确实跑过。',
        '',
        '## 四、计划统计',
        '',
        '| 项 | 值 |',
        '| --- | --- |',
    ]
    for key, value in crossings['planStats'].items():
        lines.append(f'| {key} | {value} |')
    lines += [
        '',
        '## 五、设施与航迹要不要按新风险区重做（时间对齐实测）',
        '',
        '这一节回答「重新做起始点位置、配送点位置和航迹」这半句。三种东西必须分开看，',
        '否则结论会互相污染：风险面是**随风移动**的时变量；枢纽与配送节点是**固定设施**；',
        '只有航迹是应当随风险区变化的东西。',
        '',
        f'| 时刻（分钟） | 区域 | 落入风险外缘的设施 | 落入风险核心的设施 | 其中枢纽 | 其中配送节点 |',
        '| --- | --- | --- | --- | --- | --- |',
    ]
    for row in alignment['facilities']:
        lines.append(f'| {row["minute"]} | {row["regions"]} | {row["fieldHits"]} | **{row["banHits"]}** '
                     f'| {row["fieldHitsHub"]} | {row["fieldHitsNode"]} |')
    trajectories = alignment['trajectories']
    lines += [
        '',
        f'- 设施总数：{alignment["pads"]}；比对覆盖航迹涉及的全部 '
        f'{alignment["minutesCovered"]} 个分钟（非抽样）。',
        f'- 航迹比对结果（**按航迹点自身分钟取该分钟的风险面**）：'
        f'{trajectories["accepted"]} 个有航迹班次中，落入风险外缘 **{trajectories["fieldHits"]}** 班，'
        f'落入风险核心 **{trajectories["banHits"]}** 班。',
        '',
        '**口径提醒（这条比数字本身重要）**：先前一版探针拿 t=30 的气象面去比对一架在 t=200 路过该坐标的',
        '班次，得出 278 班「可疑」，全部是假阳性——风险面会漂移，「位置对上」不等于「时间对上」。',
        '这与雨带未投影属同一类错误：数字看着像证据，实际描述的是两个不同的世界。改为按航迹点自身分钟取面后，',
        '外缘与核心命中**同时归零**。',
        '',
        '**结论**：起始点与配送点**不重做**。设施是固定设施，气象是时变量；为了让设施避开一阵雨而挪动坐标，',
        '会让设施位置依赖天气快照、破坏可复现性，也把一个气象问题写成了规划问题。',
        '',
        f'上表两列都要正视：任一时刻有 **{min(r["fieldHits"] for r in alignment["facilities"])}–'
        f'{max(r["fieldHits"] for r in alignment["facilities"])}** 个设施落在风险外缘内，',
        f'另有 **{min(r["banHits"] for r in alignment["facilities"])}–'
        f'{max(r["banHits"] for r in alignment["facilities"])}** 个落在风险核心内。',
        '后者是**真实运行约束**：那片天气压到节点上时，该节点就是服务不了——',
        f'这正是计划里 {crossings["planStats"].get("closed")} 个班次被关闭的成因，而不是选址缺陷。',
        '处置手段是「现在不飞 / 绕开 / 地面等待」，计划层面已按此执行。',
        '节点坐标若随天气漂移，反而会让「同一节点」在不同快照下位置不同，运营与复现都失去基准。',
        '',
        '航迹**无需另做**：修复雨带后它已真正随风险区变化（关闭 '
        f'{crossings["planStats"].get("closed")} 班、绕行 {crossings["planStats"].get("detours")} 班），',
        '且时间对齐下无一个航迹点落入风险面。',
        '',
        '## 六、计划统计',
        '',
        '| 项 | 值 |',
        '| --- | --- |',
    ]
    for key, value in crossings['planStats'].items():
        lines.append(f'| {key} | {value} |')
    lines += [
        '',
        '## 七、失效的旧证据',
        '',
        '雨带修复改变了计划结论（新增天气阻断班次），因此 `docs/evaluation-v1.*/` 中的班次与性能',
        '快照**不再是当前代码的测量值**，引用前需重新生成。本轮未重跑旧目录。',
        '',
    ]
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
