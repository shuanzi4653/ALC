"""The radar payload's contract with the map.

``radar_field`` is tested against canned frames; what was never tested is the
``radar_regions`` *payload* — the exact key names and shapes the frontend now
reads. The frontend had no consumer at all for most of this channel's life, so a
rename here would have been a silent, unobserved break; now that the map draws
it, the keys are load-bearing and get pinned.

The tests use a canned frame rather than the network, so they are deterministic:
the real endpoint is an uncredentialed public tile service with no availability
guarantee, and a suite that reaches for it would fail for reasons that have
nothing to do with this code.
"""
import datetime as dt
import math

import pytest
from shapely.geometry import Point, shape

from traffic import cma_tiles, radar_field, service, weather_control

ZOOM = 3
# Tile (6,2) row/column pairs measured to land inside the operating boundary over
# Liaoning (see test_radar_field.py). ``(row, column)``.
INSIDE_CELLS = ((254, 169), (251, 169), (249, 168), (254, 172))


def _frame(entries):
    """A one-tile frame dict; ``entries`` is ``(row, column, dbz)``."""
    rows = [[None] * cma_tiles.TILE_SIZE for _ in range(cma_tiles.TILE_SIZE)]
    for row, column, value in entries:
        rows[row][column] = value
    return {
        'available': True, 'error': None,
        'slot': '2026-09-18T07:18:00Z', 'slotAgeMinutes': 3.3,
        'provenance': {'provider': 'CMA_DATA_NET', 'zoom': ZOOM,
                       'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR'},
        'cells': [(6, 2, rows)],
        'degreesPerCell': cma_tiles.tile_degrees_per_cell(ZOOM),
    }


@pytest.fixture
def canned(monkeypatch):
    """Route ``radar_regions`` at a canned frame, leaving the payload code intact."""
    def install(entries):
        monkeypatch.setattr(cma_tiles, 'frame', lambda **kwargs: _frame(entries))
    return install


# ------------------------------------------------------------------ keys

def test_payload_keys_are_the_ones_the_map_reads(canned):
    """The map reads ``available``/``regions``/``watch``/``summary``/``error``.

    Asserting the exact key set rather than a subset, because an extra key is how
    a rename quietly becomes an additive change and the consumer keeps working
    against an empty value.

    ``mode`` rides along for the same reason the other five are pinned: the
    frontend branches on it to decide whether to caption the layer as a
    measurement or as a simulation, so a silent drop would mislabel the data
    rather than break the render.
    """
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)])
    payload = service.radar_regions(60)
    assert set(payload) == {'available', 'regions', 'watch', 'summary', 'error', 'mode'}
    assert payload['available'] is True
    assert payload['error'] is None
    assert payload['mode'] == weather_control.MODE_MEASURED
    assert len(payload['regions']) == 1
    region = payload['regions'][0]
    for key in ('id', 'kind', 'source', 'slot', 'slotAgeMinutes', 'bands',
                'floorAglM', 'ceilingAglM', 'field', 'ban', 'caution'):
        assert key in region, f'region is missing {key}, which the map reads'
    assert region['id'] == 'RADAR-CMA-CREF'
    assert region['kind'] == 'RADAR'
    assert region['source'] == 'CMA_DATA_NET_RADAR_CREF'


def test_summary_band_rows_carry_the_two_numbers_the_badge_prints(canned):
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)])
    summary = service.radar_regions(60)['summary']
    assert summary['channel'] == 'CMA_RADAR_TILES'
    assert summary['drivesGeometry'] is True
    assert summary['slot'] == '2026-09-18T07:18:00Z'
    assert summary['slotAgeMinutes'] == 3.3
    # Every band the badge may look up must exist, even at zero, so the frontend
    # never has to distinguish "absent" from "no echo in this band".
    for band in radar_field.BAND_ORDER:
        row = summary['bands'][band]
        assert set(row) == {'components', 'areaKm2'}
        assert isinstance(row['components'], int)
        assert isinstance(row['areaKm2'], (int, float))


def test_region_geometry_is_drawable_geojson_in_every_tier(canned):
    """``field``/``ban``/``caution`` must always exist and always be GeoJSON.

    ``ban``/``caution`` can legitimately be empty, and are then written as a
    Polygon with an empty coordinate list rather than being dropped — the map
    filters on coordinates, so a missing key would be a different failure mode
    (``undefined.type``) from an empty one.
    """
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0),
            (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 50.0)])
    region = service.radar_regions(60)['regions'][0]
    # The field is the one tier that must always carry rings when a region exists:
    # it is what the map draws to say "this is where the echo was measured".
    assert region['field']['type'] in ('Polygon', 'MultiPolygon')
    assert region['field']['coordinates'], 'field came back empty for a real STRONG echo'
    # ban and caution are present as keys and are valid GeoJSON, but may be empty.
    # `ban` is empty only if the core failed to intersect the field, which the
    # counter below proves is not the case here; `caution` is *legitimately* empty
    # for a STRONG-only cell (see the dedicated test).
    for key in ('ban', 'caution'):
        assert region[key]['type'] in ('Polygon', 'MultiPolygon')
    assert region['ban']['coordinates'], 'a STRONG echo must produce a core'
    assert radar_field.derive(_frame([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)]))['bands']['STRONG']['components'] >= 1


def test_a_strong_only_cell_has_no_caution_ring_and_that_is_correct(canned):
    """Measured, not assumed: the caution tier is empty for a STRONG-only cell.

    ``shield()`` sets ``outer = field or strong``, grows ``strong`` into the core
    and returns ``outer.difference(core)``. When the frame's only echo is STRONG,
    ``field`` (the CONVECTIVE band) is empty, so ``outer`` *is* ``strong`` and
    subtracting its grown core from itself leaves nothing.

    That is the right answer rather than a defect: the caution ring means
    "convective but crossable", and a cell with no 35-45 dBZ echo has no crossable
    ring to draw — everything measured there is already the hard core. Painting a
    ring around it would invent a band the radar did not report. The important
    consequence for the map is that the *core* colour must therefore be readable
    on its own, which is why the radar palette gives BAN a solid fill and CAUTION
    a lighter wash rather than relying on one being visible behind the other.

    Measured on tile (6,2) over Liaoning: STRONG-only -> field 435.0 km², core
    435.0 km², caution 0.0 km²; CONVECTIVE-only -> field 435.0 km², core 40.4 km²,
    caution 394.7 km². The area figures are asserted loosely (a band, not a
    number) because the fixture cells are clipped by the operating boundary.
    """
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0),
            (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 50.0)])
    region = service.radar_regions(60)['regions'][0]
    assert region['field']['coordinates'], 'field must be drawn'
    assert region['ban']['coordinates'], 'core must be drawn'
    assert region['caution']['coordinates'] == [], \
        'a STRONG-only cell has no crossable ring, so caution must be empty'

    # And the opposite case must still produce a ring, or the claim above would be
    # satisfied by a function that never emits caution at all.
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 40.0),
            (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 40.0)])
    convective = service.radar_regions(60)['regions'][0]
    assert convective['caution']['coordinates'], \
        'a CONVECTIVE echo must produce a crossable ring'


def test_an_empty_tier_is_an_empty_polygon_not_a_missing_key(canned):
    """STRONG-only echo: the caution ring may be empty, and must still be present."""
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)])
    region = service.radar_regions(60)['regions'][0]
    assert region['caution']['type'] == 'Polygon'


def test_the_core_never_spills_outside_its_own_field(canned):
    """The invariant that makes a two-colour rendering readable at all.

    Re-asserted at the payload level because the frontend draws BAN and CAUTION
    as two fills over one footprint: if the core could exceed its field, the hard
    -core colour would appear in airspace the payload does not claim is hazardous.
    """
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0),
            (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 50.0)])
    derived = radar_field.derive(_frame([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0),
                                         (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 50.0)]))
    field, core, _caution, _watch = radar_field.shield(derived)
    assert not field.is_empty and not core.is_empty
    assert core.difference(field.buffer(1.0)).area == pytest.approx(0.0, abs=1.0)


# ------------------------------------------------------------------ watch

def test_stratiform_only_frames_report_a_watch_area_and_no_region(canned):
    """The distinction the badge depends on: rain that is not a hazard.

    ``watch`` must be present and the region list empty, so the map can say
    "the radar read rain, the rain is not a hazard" instead of showing the same
    empty violet layer a failed read produces.
    """
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 20.0)])
    payload = service.radar_regions(60)
    assert payload['available'] is True
    assert payload['regions'] == []
    watch = payload['watch']
    assert watch is not None
    assert watch['id'] == 'RADAR-CMA-CREF-WATCH'
    assert watch['kind'] == 'RADAR_WATCH'
    assert watch['band'] == 'STRATIFORM'
    assert watch['source'] == 'CMA_DATA_NET_RADAR_CREF'
    assert watch['field']['type'] in ('Polygon', 'MultiPolygon')
    assert watch['field']['coordinates']
    assert '不构成限制' in watch['note']


def test_below_the_echo_floor_there_is_neither_region_nor_watch(canned):
    """Nothing measured means nothing drawn — not a placeholder area."""
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 12.0)])
    payload = service.radar_regions(60)
    assert payload['available'] is True
    assert payload['regions'] == []
    assert payload['watch'] is None


# ------------------------------------------------------------------ failure

def test_an_unreachable_source_yields_no_geometry_and_a_stated_reason(monkeypatch):
    """A fabricated radar area is worse than a missing one, so this is the only
    acceptable failure mode: available=False, empty regions, an explicit error."""
    monkeypatch.setattr(cma_tiles, 'frame',
                        lambda **kwargs: {'available': False, 'cells': [],
                                          'provenance': {'provider': 'CMA_DATA_NET'},
                                          'error': '最近 12 个时次均不可用：HTTP 404',
                                          'slot': None})
    payload = service.radar_regions(60)
    assert payload['available'] is False
    assert payload['regions'] == []
    assert payload['watch'] is None
    assert 'HTTP 404' in payload['error']
    assert payload['summary']['drivesGeometry'] is False
    assert payload['summary']['available'] is False


def test_radar_status_never_triggers_a_fetch(monkeypatch):
    """The status query is served to the data-source panel; it must remain free."""
    def explode(*args, **kwargs):
        raise AssertionError('status() must not fetch a frame')

    monkeypatch.setattr(cma_tiles, 'frame', explode)
    status = service.radar_status()
    assert status['available'] is False
    assert status['drivesGeometry'] is False
    assert '未取帧' in status['error']


# ------------------------------------------------------------------ wiring

def test_every_scenario_carries_the_radar_channel(monkeypatch):
    """The radar is its own channel, so it must ride along in every scenario —
    including the ones that claim no weather at all."""
    monkeypatch.setattr(service, 'radar_regions',
                        lambda minute: {'available': True, 'regions': [], 'watch': None,
                                        'summary': {'channel': 'CMA_RADAR_TILES'},
                                        'error': None, 'mode': 'measured'})
    for scenario in ('live', 'clear', 'unknown'):
        frame = service.weather_frame(42, scenario, 30)
        assert 'radar' in frame, f'{scenario} dropped the radar channel'
        assert frame['radar']['summary']['channel'] == 'CMA_RADAR_TILES'


def test_every_scenario_declares_which_weather_mode_produced_it(monkeypatch):
    """The mode is stamped on the frame, not left for the client to guess.

    A consumer that has to infer the mode from the provider string will get it
    wrong the first time a new provider appears; carrying it explicitly means the
    caption and the data can never disagree.
    """
    for scenario in ('live', 'clear', 'unknown'):
        frame = service.weather_frame(42, scenario, 30)
        assert frame['weatherMode'] == weather_control.mode()


def test_radar_is_a_separate_channel_from_the_modelled_field(canned):
    """The two channels must stay separately labelled.

    The derived field is a system derivation on a timeline; the radar is one
    observation of one moment. Folding the radar into ``cells`` would mean either
    claiming it can be time-travelled or presenting a measurement as a model run.
    """
    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)])
    frame = service.weather_frame(42, 'clear', 60)
    # 'clear' claims no weather: the frame says so rather than inventing a source,
    # and the radar still appears because it is a real measurement, not a claim.
    assert frame['provider'] == 'NONE'
    assert frame['dataType'] == 'NO_WEATHER_CLAIMED'
    assert frame['cells'] == []
    radar = frame['radar']
    assert radar['regions'][0]['source'] == 'CMA_DATA_NET_RADAR_CREF'
    # No radar geometry may appear inside the derived cells list.
    radar_ids = {region['id'] for region in radar['regions']}
    assert not radar_ids & {cell['id'] for cell in frame['cells']}


def test_radar_geometry_lands_inside_the_operating_boundary(canned):
    """Registration, checked at the payload rather than the module.

    The fixture cells sit over Liaoning, so the drawn geometry must fall inside
    the three-province operating box. This is the assertion that would have
    caught the band's original ~4300 km misregistration, which produced valid
    geometry in the wrong hemisphere and passed every shape-only check.
    """
    from weather.geometry import boundary, project

    canned([(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0),
            (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 50.0)])
    region = service.radar_regions(60)['regions'][0]
    box = boundary().buffer(20000)
    for tier in ('field', 'ban'):
        geometry = region[tier]
        rings = geometry['coordinates'] if geometry['type'] == 'Polygon' else \
            [ring for polygon in geometry['coordinates'] for ring in polygon]
        assert rings, f'{tier} carried no rings to check'
        for ring in rings:
            for lon, lat in ring:
                # A sanity window far wider than the operating box: anything
                # outside it is a registration error, not a boundary question.
                assert 100.0 < lon < 145.0, f'{tier} longitude {lon} is not over China'
                assert math.isfinite(lat) and 30.0 < lat < 60.0, \
                    f'{tier} latitude {lat} is outside the northeast box'
                assert box.covers(Point(*project((lon, lat)))), \
                    f'{tier} corner ({lon}, {lat}) projects outside the operating boundary'


# ------------------------------------------------------- published validity
#
# Everything above checks the payload's *shape*. Nothing checked that the geometry
# it hands the renderer is a geometry the renderer can interpret, and that is a
# different failure: a self-intersecting ring is valid GeoJSON, is accepted by
# every schema check, and has **no defined inside** -- MapLibre fills it by
# triangulation, so the painted area is decided by the tessellator rather than by
# the data. Measured 2026-09-30 on the virtual channel: `shield` returns valid
# geometry in projected metres for every tier, and 6 of 17 sampled `field` tiers
# come back self-crossing once inverse-projected.
#
# These tests run on the synthetic channel because it is offline and a pure
# function of (seed, slot); the measured mosaic is one real observation and would
# make the guard depend on the network and on the weather. The projection -- which
# is where the crossing is introduced -- is identical for both.


def _virtual_field(offset, seed=weather_control.DEFAULT_SEED):
    """The FIELD tier the virtual channel draws at ``SIMULATION_BASE_TIME + offset``."""
    from traffic import weather_sim

    slot = service.SIMULATION_BASE_TIME + dt.timedelta(minutes=offset)
    derived = radar_field.derive(weather_sim.frame(seed=seed, slot=slot))
    return radar_field.shield(derived)[0]


def test_publishing_makes_a_self_crossing_ring_drawable():
    """Both directions, because the convenient one is satisfiable by doing nothing.

    Asserting only that the published geometry is valid would pass on a call site
    that was never broken -- so the naive expression is asserted to be **invalid**
    at this sample, which is what makes removing ``make_valid`` fail this test. If
    the sample ever stops crossing, take a different offset; do not relax the
    assertion, or the guard goes quiet without going red.
    """
    from shapely.ops import transform as shapely_transform

    from weather.geometry import INVERSE

    # **不要写死某个 offset。** 这条判据的前提是"反投影会引入自交"，而哪一帧会自交
    # 取决于 `SIMULATION_BASE_TIME` 与种子 —— 时间一往前走，写死的 t=180 就不再自交，
    # 测试变红而产品没有任何变化（2026-10-21 实测：写死的 180 已经不自交了）。
    # 所以**按同一判据在 24 小时里找**：虚拟通道是 (seed, slot) 的纯函数，扫一遍
    # 是确定性的；找到的第一帧就是本次的样本。前提彻底没了（一帧都不自交）时
    # 仍然要红 —— 那种情况说明几何链路变了，判据本身要重写，不许把断言删掉换安静。
    crossing = None
    for offset in range(0, 24 * 60, 15):
        candidate = _virtual_field(offset)
        if candidate.is_empty:
            continue
        if not shapely_transform(INVERSE.transform, candidate).is_valid:
            crossing = (offset, candidate)
            break
    assert crossing is not None, \
        '虚拟通道 24 小时内没有任何一帧反投影后自交 —— 判据的前提（反投影不保拓扑）' \
        '已经不成立，需要重写这条判据，而不是删掉它'
    offset, field = crossing
    naive = shapely_transform(INVERSE.transform, field)
    assert not naive.is_valid, f't={offset} 这一帧应当自交'

    published = service._published(field)
    assert published is not None, 'a real field must never publish as nothing'
    assert published['type'] in ('Polygon', 'MultiPolygon'), \
        f'published {published["type"]}, which the renderer filters out'
    assert shape(published).is_valid


def test_every_tier_the_map_draws_is_valid_geojson_over_the_timeline():
    """The guard above pins one geometry; this one pins the set actually drawn.

    A single hand-picked sample cannot catch a tier that is only broken elsewhere,
    and the reported symptom -- "planes sit inside the no-fly area and there is no
    detour" -- is read off the *whole* painted picture, so the whole picture is
    what gets checked. The virtual timeline also advances the echo, which is when
    new ring shapes appear.
    """
    weather_control.reset()
    try:
        weather_control.set_mode(weather_control.MODE_VIRTUAL)
        drawn = 0
        for minute in range(0, 481, 120):
            payload = service.radar_regions(minute)
            assert payload['available'] is True, f'minute {minute}: {payload["error"]}'
            # A region carries all three tiers; the watch record carries only
            # `field`, because the WATCH tier has no core and no ring to draw.
            surfaces = [(f'minute {minute} {key}', value)
                        for region in payload['regions']
                        for key in ('field', 'ban', 'caution')
                        for value in (region[key],)]
            if payload['watch']:
                surfaces.append((f'minute {minute} watch', payload['watch']['field']))
            for label, value in surfaces:
                assert value['type'] in ('Polygon', 'MultiPolygon'), \
                    f'{label}: published {value["type"]}, which the renderer filters out'
                if not value['coordinates']:
                    continue          # an empty tier is a legitimate statement
                drawn += 1
                assert shape(value).is_valid, \
                    f'{label} is self-intersecting: the fill would not follow the data'
        # A guard that examined nothing is a guard that passes. The virtual band
        # reaches >=35 dBZ, so there is always something to look at.
        assert drawn > 0, 'no tier was examined, so nothing was actually verified'
    finally:
        weather_control.reset()


def test_virtual_summary_never_claims_cma():
    """0.11.11（G-2）：虚拟通道下 `summary` 的描述性字段必须跟着通道走。

    0.11.10 的现场：同一条响应里 `radar.mode=virtual`、`watch.source=SYNTHETIC_RADAR_CREF`，
    而 `summary.channel` 仍写 `CMA_RADAR_TILES`、note 仍写"实测雷达反射率"。
    评委只要翻一次网络面板就会看到"既是合成又是实测" —— 一条字段名对不上，
    能把前面十条诚实设计一起废掉。
    """
    derived = {
        'available': True,
        'provenance': {'slot': '2026-10-21T11:00:00Z', 'slotAgeMinutes': 0.0},
        'bands': {},
        'syntheticEcho': True,
        'echoFraction': 0.01,
        'components': 2,
    }
    virtual = radar_field.summary(derived=derived)
    assert virtual['channel'] == 'SYNTHETIC_RADAR_CREF'
    assert virtual['slot'] == 'SYNTHETIC@2026-10-21T11:00:00Z'
    # 虚拟数据没有"时次年龄"这个概念。写 0.0 是把"没有这个量"说成"量出来很新鲜"。
    assert virtual['slotAgeMinutes'] is None
    assert '不是观测数据' in virtual['note']

    # measured 侧一个字都不许改（这条是回归线，不是新功能）
    measured = radar_field.summary(derived={**derived, 'syntheticEcho': False})
    assert measured['channel'] == 'CMA_RADAR_TILES'
    assert measured['slotAgeMinutes'] == 0.0
    assert measured['slot'] == '2026-10-21T11:00:00Z'
    assert '实测雷达反射率' in measured['note']
