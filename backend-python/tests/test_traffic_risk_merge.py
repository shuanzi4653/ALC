"""Merged presentation of the derived risk field.

The dissolve is presentation only, and these tests exist to keep it that way. The
dangerous failure would be a merged outline that covers less than the per-cell
geometry it replaces — that is exactly how the original rain-band defect arose,
where the rendered field and the routing envelope were built from two different
copies of the cell positions and the envelope lost the largest hazard entirely.

The project no longer synthesises weather, so the dissolve is exercised here on an
explicit fixture that constructs the *shape* the dissolve has to survive: one cell
whose core is a chain of far-apart clusters, which is what makes per-component
attribution load-bearing. Back when that cell came from the synthetic rain band the
fixture was ``NetworkWeather(42, 'moving')``; the geometry it must handle is the
same, and pinning it here keeps the guard independent of any weather source.
"""
import math

from shapely.geometry import Point
from shapely.ops import unary_union
from weather.geometry import boundary, project
from traffic.weather import (
    PublicWeather,
    _dissolve_regions,
    _polygon_parts,
)


def _area(geometry):
    return geometry.area if geometry is not None and not geometry.is_empty else 0.0


def _polygon_parts_of(geometry):
    """Every polygon inside a Polygon/MultiPolygon/GeometryCollection."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return [part for part in getattr(geometry, 'geoms', [])
            if part.geom_type == 'Polygon' and not part.is_empty]


def _chained_band(centres, radius=8000.0, core=4200.0):
    """One cell whose field spans many components and whose core chains through them.

    ``centres`` are far enough apart that their discs do not touch, so the field
    tier has one component per centre. The cell is a *single* member spanning all of
    them — the exact situation that made "carry the member's whole ban" hand every
    region all the cores.
    """
    field = unary_union([Point(c).buffer(radius, quad_segs=16) for c in centres])
    ban = unary_union([Point(c).buffer(core, quad_segs=16) for c in centres])
    caution = field.difference(ban)
    cell = {'id': 'FIXTURE-BAND', 'kind': 'BAND', 'shape': 'BAND',
            'derivedFrom': {'gustMps': 22, 'precipitationMm': 4, 'visibilityM': 4000}}
    return cell, field, ban, caution


# Two clusters ~430 km apart, both well inside the operation boundary, so the
# province clip below keeps both and the chained-cell case is actually exercised.
_CHAIN = [project((125.00, 43.50)), project((121.60, 40.00))]
_FIXTURE = [
    _chained_band(_CHAIN),
    # A second, independent cell whose disc overlaps the chain's southern cluster:
    # one component then has two members, so the merge path is genuinely exercised
    # rather than only the split path.
    ({'id': 'FIXTURE-A', 'kind': 'WIND', 'shape': 'POINT',
      'derivedFrom': {'gustMps': 20, 'precipitationMm': 2, 'visibilityM': 3000}},
     Point(_CHAIN[1][0] + 3000.0, _CHAIN[1][1] + 2000.0).buffer(9000.0, quad_segs=16),
     Point(_CHAIN[1][0] + 3000.0, _CHAIN[1][1] + 2000.0).buffer(4000.0, quad_segs=16),
     Point(_CHAIN[1][0] + 3000.0, _CHAIN[1][1] + 2000.0).buffer(9000.0, quad_segs=16)
     .difference(Point(_CHAIN[1][0] + 3000.0, _CHAIN[1][1] + 2000.0).buffer(4000.0, quad_segs=16))),
]


def _clipped(shapes):
    return [(cell, field.intersection(boundary()), ban.intersection(boundary()),
             caution.intersection(boundary()))
            for cell, field, ban, caution in shapes]


def _frame(shapes, source='FIXTURE_DERIVED_RISK'):
    """The same assembly ``PublicWeather.frame`` performs, over explicit shapes."""
    records = []
    for members, field, ban, caution in _dissolve_regions(_clipped(shapes)):
        records.append({'id': members[0]['id'] if len(members) == 1 else None,
                        'members': members, 'field': field, 'ban': ban,
                        'caution': caution, 'source': source})
    return records


def test_merged_areas_cover_exactly_the_geometry_they_replace():
    per_cell = unary_union([field.intersection(boundary())
                            for _, field, _, _ in _clipped(_FIXTURE)])
    merged = unary_union([record['field'] for record in _frame(_FIXTURE)])
    # Same total area, same footprint: the union of the merged parts has to be
    # the union of the clipped per-cell fields, or the map is hiding a hazard.
    assert math.isclose(_area(merged), _area(per_cell), rel_tol=1e-9)
    assert merged.symmetric_difference(per_cell).area < 1.0


def test_merging_reduces_the_number_of_areas_without_dropping_members():
    """Merging must never split anything, and must never lose a cell."""
    cells = _FIXTURE
    regions = _frame(cells)
    # Only cells with geometry inside the operation can become an area; a cell
    # whose field clips to nothing is dropped rather than sent to the client as
    # an empty polygon. Every *remaining* cell is accounted for exactly once, so
    # a merged area can always be traced back to the cells behind it.
    drawable = sorted(cell['id'] for cell, field, _, _ in cells
                      if not field.intersection(boundary()).is_empty)
    members = [member['id'] for region in regions for member in region['members']]
    assert sorted(set(members)) == drawable
    # Components of the field tier are the regions: no splitting, no merging
    # beyond what actually touches.
    fields = unary_union([field.intersection(boundary()) for _, field, _, _ in cells])
    components = [part for part in _polygon_parts_of(fields)]
    assert len(regions) == len(components)
    # Nothing empty ever reaches the client.
    assert all(not record['field'].is_empty for record in regions)


def test_each_merged_tier_stays_nested_the_way_the_cells_were():
    """A region's core must belong to that region, not merely to the field tier.

    The first version of this test only compared areas and passed against code that
    handed every region all the band cores: the band's own component was correct, and
    the extra cores were clipped away by the *other* regions' fields, so the total
    outside-field area still summed to zero. Comparing each region against its own
    field is what makes the assertion fail when attribution is wrong, and comparing
    the *nearest approach* catches it even when the stray core is clipped small
    enough to round away. Measured against the un-clipped version: 142,047,519,714
    m^2 of core outside its region's field, worst nearest approach 1,135,977 m.
    """
    for record in _frame(_FIXTURE):
        field, ban, caution = record['field'], record['ban'], record['caution']
        if not ban.is_empty:
            # A core is a scaled copy of its own ring, so it sits strictly
            # inside the field it belongs to; a square metre of slack absorbs
            # the vertex rounding without letting a real excursion through.
            assert ban.difference(field).area < 1.0, record['id']
            # Area alone can round away a needle-thin excursion, so measure how
            # far the core gets from its own field as well.
            assert ban.distance(field) < 1.0, (record['id'], ban.distance(field))
        if not caution.is_empty:
            # The caution band is the field buffered outwards minus the core, so it
            # has to stay inside that slightly larger footprint and never overlap
            # the core it surrounds.
            assert ban.intersection(caution).area < 1.0, record['id']
            assert caution.distance(field) < 1.0, record['id']


def test_a_chained_cell_attributes_each_core_to_its_own_component():
    """The band's cores must be split across its regions, not replicated into each.

    Regression for the defect the nesting test could not see. ``_dissolve_regions``
    groups members by field component but collects each member's whole ban, so once
    one cell's ban became a MultiPolygon every region received every core. This test
    compares the *number* of core polygons a region reports against the number that
    actually lie inside it, and asserts no region reports a core it does not contain.
    """
    ban = _FIXTURE[0][2]
    assert len(_polygon_parts_of(ban)) > 1, '构造的雨带应为多簇形态，否则本测试失去意义'

    for record in _frame(_FIXTURE):
        field, ban = record['field'], record['ban']
        if ban.is_empty:
            continue
        stray = [part for part in _polygon_parts_of(ban) if part.distance(field) > 1.0]
        assert not stray, (record['id'], len(stray))


def test_the_routing_envelope_still_covers_every_merged_area():
    # `envelope()` blankets every cell while the client draws one merged area per
    # clump. That asymmetry is safe only in one direction: the envelope has to be
    # a superset of what is drawn, never the other way round.
    envelope = unary_union([
        ban.union(caution).intersection(boundary())
        for _, _, ban, caution in _clipped(_FIXTURE)
    ])
    for record in _frame(_FIXTURE):
        for key in ('field', 'ban', 'caution'):
            geometry = record[key]
            if geometry.is_empty:
                continue
            assert envelope.covers(geometry), (record['id'], key)


def test_merged_areas_are_deterministic_and_vanish_when_there_is_no_weather():
    assert _frame(_FIXTURE) == _frame(_FIXTURE)
    # No weather at all: the derive step produces no cells, so the dissolve has
    # nothing to merge and the frame is empty rather than an empty region.
    assert _frame([]) == []
    assert _dissolve_regions([]) == []


def test_live_derived_risk_merges_cities_but_keeps_each_derivation():
    from traffic.catalog import cities
    rows = cities()
    # Two neighbouring cities in identical conditions: previously two discs, now
    # one area that still reports both derivations.
    snapshot = {
        'available': True, 'provider': 'OPEN_METEO', 'dataType': 'MODEL_ESTIMATE',
        'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION'],
        'observations': [
            {'cityId': row['id'], 'windGusts10mMps': 19, 'precipitationMm': 2,
             'hourly': {'visibility': [800]}}
            for row in rows[:2]
        ],
    }
    weather = PublicWeather(snapshot, rows)
    regions = weather.frame(0)
    assert regions
    assert len(regions) <= 2
    assert all(region['source'] == 'OPEN_METEO_DERIVED_RISK' for region in regions)
    for region in regions:
        assert region['memberCount'] == len(region['sources'])
        # A single-site area still hands back one derivation object, not a list, so
        # an existing client keeps reading `derivedFrom.gustMps`.
        if region['memberCount'] == 1:
            assert region['derivedFrom']['gustMps'] == 19
        else:
            assert [item['gustMps'] for item in region['derivedFrom']] == [19] * region['memberCount']


def test_dissolve_of_nothing_is_nothing():
    assert _dissolve_regions([]) == []


def test_merged_identifiers_are_plain_ascii_tokens():
    # Ids reach the DOM and the ledger; they stay machine-readable tokens rather
    # than carrying any decorative glyph.
    from traffic.catalog import cities
    rows = cities()
    snapshot = {
        'available': True, 'provider': 'OPEN_METEO', 'dataType': 'MODEL_ESTIMATE',
        'qualityFlags': [],
        'observations': [
            {'cityId': row['id'], 'windGusts10mMps': 19, 'precipitationMm': 2,
             'hourly': {'visibility': [800]}}
            for row in rows[:3]
        ],
    }
    for region in PublicWeather(snapshot, rows).frame(0):
        assert region['id'].isascii(), region['id']
        assert region['kind'].isascii()
        assert all(source.isascii() for source in region['sources'])

def test_threshold_table_matches_constants():
    """界面引用的阈值表必须与判定用的常量同源。

    ``extreme_thresholds()`` 的存在理由是让气象情报面板能报出"这块几何是按什么
    阈值划的"，而不是打印一个占位符。它因此是一份**副本** —— 而副本会漂移：
    有人把 ``EXTREME_WIND_GUST_MPS`` 从 17 调到 20，忘了改表，面板就会继续
    宣称 17 m/s，操作员按面板数字复核怎么都对不上。

    这条测试把两者钉在一起。它测的是"表 == 常量"，不是表里有没有某个数字。
    """
    from traffic import weather as traffic_weather

    table = traffic_weather.extreme_thresholds()
    assert table['gustMps'] == traffic_weather.EXTREME_WIND_GUST_MPS
    assert table['visibilityM'] == traffic_weather.EXTREME_VISIBILITY_M
    assert table['hourlyRainMm'] == traffic_weather.EXTREME_HOURLY_RAIN_MM
    assert table['coreRadiusM'] == traffic_weather.EXTREME_CORE_RADIUS_M


def test_threshold_table_carries_the_accountability_note():
    """表里必须带着"轻度过境不生成几何"这句。

    单看四个数字，读者会以为只要阵风过了线就会画圈；而实际口径是只有极值才
    生成内核，轻度只作观测记录。这句话是口径的一部分，不是装饰。
    """
    from traffic.weather import extreme_thresholds

    note = extreme_thresholds()['note']
    assert '禁止进入内核' in note
    assert '不生成几何' in note


def test_weather_frame_publishes_the_threshold_table():
    """接口载荷里必须有这张表 —— 面板读的是它，不是本地常量。"""
    from traffic import service

    frame = service.weather_frame(42, 'clear', 60)
    assert frame['extremeThresholds']['gustMps'] == 17.0
    assert frame['extremeThresholds']['visibilityM'] == 1000.0
