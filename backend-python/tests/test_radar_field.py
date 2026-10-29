"""Radar reflectivity -> risk geometry: registration, classification, filtering.

These are the properties that were got wrong at least once while building the
channel, so each one is pinned rather than trusted:

  * registration -- a cell's quad must land where the tile maths says it does,
    verified against an independently written slippy-map formula. The band once
    shipped with a hand-written metre polygon that had never been projected and
    sat ~4300 km north; nothing caught it because the wrong geometry was still
    *valid*. A registration test that only checks "a polygon came back" would
    have passed that too.
  * classification -- band edges are the standard's, and the boundaries are
    inclusive on the low side, so 35.0 is convective and 34.999 is not.
  * the noise floor -- a **cell count**, not an area. Two area floors were tried
    and both deleted genuine echo; the second is the interesting one because it
    looked reasonable (one cell's worth of area) and was still wrong: a cell on
    the boundary is clipped to less than a cell.
  * registry of failure -- an unavailable frame yields no geometry and no
    exception. A fabricated risk area is worse than a missing one.
"""
import math
import time

import pytest
from shapely.geometry import GeometryCollection

from traffic import cma_tiles, radar_field

ZOOM = 3


def _reference_lonlat(tile_x, tile_y, column, row, zoom=ZOOM):
    """The standard slippy-map formula, written out independently.

    Deliberately not a call into ``cma_tiles``: comparing a function against
    itself proves nothing, and this is the check that would have caught the
    ~4300 km misregistration of the band.
    """
    size = cma_tiles.TILE_SIZE
    scale = 2 ** zoom
    world_x = (tile_x + (column + 0.5) / size) / scale
    world_y = (tile_y + (row + 0.5) / size) / scale
    longitude = world_x * 360.0 - 180.0
    latitude = math.degrees(math.atan(math.sinh(math.pi - 2.0 * math.pi * world_y)))
    return longitude, latitude


class _FakeFrame:
    """A frame dict in ``cma_tiles.frame()``'s shape, with no network involved."""

    def __init__(self, tiles, zoom=ZOOM, available=True, error=None):
        self.tiles = tiles
        self.payload = {
            'available': available,
            'error': error,
            'slot': '2026-09-17T14:30:00Z',
            'slotAgeMinutes': 3.8,
            'provenance': {'provider': 'CMA_DATA_NET', 'zoom': zoom,
                           'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR'},
            'cells': tiles,
            'degreesPerCell': cma_tiles.tile_degrees_per_cell(zoom),
        }

    def as_dict(self):
        return self.payload


# Raster coordinates that fall inside the operating boundary, measured rather
# than guessed (see tools/probes/_probe_radar_fixture_cells.py). Tile (6,2),
# columns ~167-172, rows ~249-254 sit over Liaoning at ~119.7E / 41.2-41.9N, and
# each such cell is ~217 km2.
#
# This mattered twice over. First the fixtures used row 120 / column 120, which
# is ~113E / 53N -- over Russia -- so every area assertion failed for the right
# reason (the clip removed it) while looking like a product bug. Then, after the
# coordinates were measured, they were still written in the wrong order: the
# named tuples below are ``(row, column)`` to match ``cell_quad(x, y, column,
# row)``'s argument order at the call site and this module's own row-major frame
# entries, and reading them as ``(column, row)`` moved every fixture cell ~85
# cells east and 85 north. Both mistakes produced the same symptom -- "the
# product found nothing" -- and neither was a product defect.
INTERIOR = (6, 2)
INSIDE_CELLS = ((254, 169), (251, 169), (249, 168), (254, 172))


def _blank_tile():
    return [[None] * cma_tiles.TILE_SIZE for _ in range(cma_tiles.TILE_SIZE)]


def _frame_with(entries, tile=INTERIOR):
    """Build a one-tile frame; ``entries`` is ``(row, column, dbz)``."""
    rows = _blank_tile()
    for row, column, value in entries:
        rows[row][column] = value
    return _FakeFrame([(tile[0], tile[1], rows)]).as_dict()


def _asserted_entry():
    """One measured in-boundary cell as ``(row, column)``, for the single-cell cases."""
    return INSIDE_CELLS[0]


# ---------------------------------------------------------------- classification

def test_band_of_uses_the_standard_edges_and_is_inclusive_on_the_low_side():
    assert radar_field.band_of(None) is None
    assert radar_field.band_of(0.0) is None
    assert radar_field.band_of(14.9) is None
    assert radar_field.band_of(cma_tiles.ECHO_FLOOR_DBZ) == 'STRATIFORM'
    assert radar_field.band_of(34.9) == 'STRATIFORM'
    assert radar_field.band_of(cma_tiles.CONVECTIVE_DBZ) == 'CONVECTIVE'
    assert radar_field.band_of(44.9) == 'CONVECTIVE'
    assert radar_field.band_of(cma_tiles.STRONG_DBZ) == 'STRONG'
    assert radar_field.band_of(70.0) == 'STRONG'


def test_band_edges_are_taken_from_the_reader_not_retyped():
    """If the two ever drift, the reader and the classifier disagree silently."""
    assert [name for name, _lo, _hi in radar_field.BAND_EDGES] == list(radar_field.BAND_ORDER)
    assert radar_field.BAND_EDGES[0][1] == cma_tiles.ECHO_FLOOR_DBZ
    assert radar_field.BAND_EDGES[1][1] == cma_tiles.CONVECTIVE_DBZ
    assert radar_field.BAND_EDGES[2][1] == cma_tiles.STRONG_DBZ


# ---------------------------------------------------------------- registration

def test_cell_quad_corners_match_an_independent_slippy_map_formula():
    """The check that the band's misregistration would have failed.

    Compared on the quad's *longitude*, which is linear in the tile maths, and on
    the projected metres rather than on degrees of latitude. Averaging the four
    corners in degree space does not give the cell centre, because latitude is a
    nonlinear function of the mercator y -- asserting the degree-space average
    would be asserting a property the projection does not have.
    """
    from weather.geometry import project
    for tile in ((6, 2), (6, 3)):
        for column, row in ((0, 0), (100, 137), (169, 251), (255, 255)):
            quad = radar_field.cell_quad(tile[0], tile[1], column, row, ZOOM)
            nw, ne, se, sw, close = quad
            assert close == nw, 'ring must be closed'
            # longitude is linear, so the corner average is exact there
            centre_lon = sum(point[0] for point in quad[:4]) / 4
            reference = _reference_lonlat(tile[0], tile[1], column + 0.5, row + 0.5)
            assert abs(centre_lon - reference[0]) < 1e-9
            # and the projected centre must land within a cell of the reference
            centre = project((centre_lon,
                              sum(point[1] for point in quad[:4]) / 4))
            target = project(reference)
            assert math.dist(centre, target) < 10000.0, (
                'projected cell centre %.0f m from the reference point'
                % math.dist(centre, target))


def test_cell_quad_is_not_square_in_degrees():
    """A mercator cell is square in metres and *not* square in degrees.

    Degrees of longitude are constant across a mercator tile while degrees of
    latitude shrink toward the pole, so at 66N a cell spans far more longitude
    than latitude. This is worth pinning because the opposite ("a cell is a
    square block of degrees") is the intuitive assumption, and building the quad
    from it puts the echo in the right shape in the wrong place.
    """
    quad = radar_field.cell_quad(6, 2, 128, 128, ZOOM)
    lons = [point[0] for point in quad[:4]]
    lats = [point[1] for point in quad[:4]]
    lon_span = max(lons) - min(lons)
    lat_span = max(lats) - min(lats)
    assert lon_span > lat_span, 'at 55N a mercator cell spans more longitude than latitude'
    # and the metropolitan span must be roughly square, which is the real check
    from weather.geometry import project
    corners = [project(point) for point in quad[:4]]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert 0.5 < width / height < 2.0, 'projected cell should be roughly square (%.0f x %.0f m)' % (
        width, height)


def test_projection_round_trips_through_the_planners_own_transformer():
    from weather.geometry import project, unproject
    point = cma_tiles.cell_centre_lonlat(6, 2, 136, 148, ZOOM)
    back = unproject(project(point))
    assert abs(back[0] - point[0]) < 1e-9
    assert abs(back[1] - point[1]) < 1e-9


# ---------------------------------------------------------------- components

def test_only_edge_contacts_join_cells():
    """A diagonal touch must not fuse two echoes; real echo lines are diagonal."""
    # two cells touching only at a corner
    diagonal = [('STRATIFORM', 10, 10, (6, 2)), ('STRATIFORM', 11, 11, (6, 2))]
    groups = radar_field._components(diagonal)
    assert len(groups) == 2, 'a corner contact is not a connection'

    # two cells sharing an edge
    adjacent = [('STRATIFORM', 10, 10, (6, 2)), ('STRATIFORM', 10, 11, (6, 2))]
    groups = radar_field._components(adjacent)
    assert len(groups) == 1


def test_bands_do_not_join_across_a_band_change():
    """A convective cell beside a stratiform cell is two areas, not one."""
    mixed = [('STRATIFORM', 10, 10, (6, 2)), ('CONVECTIVE', 10, 11, (6, 2))]
    assert len(radar_field._components(mixed)) == 2


# ---------------------------------------------------------------- the floor

def test_the_noise_floor_is_a_cell_count_not_an_area():
    """Guards the second wrong fix, which looked right and deleted real echo.

    An area floor of "one cell's worth" (383 km2) failed because a cell on the
    boundary clips to less than a cell -- measured 219 km2 for the single
    in-boundary convective cell. Asserting the floor is a count is the only
    formulation that cannot be unsatisfiable at the coast.
    """
    assert radar_field.MIN_COMPONENT_CELLS == 1
    assert not hasattr(radar_field, 'MIN_COMPONENT_AREA_M2')
    assert not hasattr(radar_field, 'component_area_floor_m2')


def test_a_single_isolated_cell_survives():
    """One cell of convective echo is a real hazard, not a speck."""
    row, column = _asserted_entry()
    frame = _frame_with([(row, column, 40.0)])  # CONVECTIVE, one cell
    derived = radar_field.derive(frame)
    assert derived['available']
    assert derived['bands']['CONVECTIVE']['components'] == 1
    assert derived['bands']['CONVECTIVE']['areaM2'] > 0.0


def test_a_cell_outside_the_boundary_is_clipped_away():
    """The clip is the reason a nationally-real echo may not be drawn.

    At 14:12Z the strongest cell in the frame was 54 dBZ over Russia; the honest
    outcome is that it does not appear, not that the boundary is ignored.
    """
    frame = _frame_with([(120, 120, 70.0)])  # over Russia, measured
    derived = radar_field.derive(frame)
    assert derived['available']
    assert derived['echoCells'] == 1, 'the cell was read'
    for band in radar_field.BAND_ORDER:
        assert derived['bands'][band]['components'] == 0, (
            'a cell outside the boundary must not be drawn')


def test_below_the_echo_floor_nothing_is_reported():
    row_a, column_a = INSIDE_CELLS[0]
    row_b, column_b = INSIDE_CELLS[1]
    frame = _frame_with([(row_a, column_a, 5.0), (row_b, column_b, 12.0)])
    derived = radar_field.derive(frame)
    assert derived['available']
    assert derived['echoCells'] == 0
    for band in radar_field.BAND_ORDER:
        assert derived['bands'][band]['components'] == 0


# ---------------------------------------------------------------- failure modes

def test_an_unavailable_frame_yields_no_geometry_and_no_exception():
    frame = _FakeFrame([], available=False, error='最近 12 个时次均不可用').as_dict()
    derived = radar_field.derive(frame)
    assert derived['available'] is False
    assert derived['error'] == '最近 12 个时次均不可用'
    assert derived['bands'] == {}
    field, core, caution, watch = radar_field.shield(derived)
    for tier in (field, core, caution, watch):
        assert tier.is_empty


def test_a_frame_without_zoom_refuses_rather_than_guessing():
    """Registration is impossible without the zoom, so it must not be assumed."""
    frame = _FakeFrame([], available=True).as_dict()
    del frame['provenance']['zoom']
    derived = radar_field.derive(frame)
    assert derived['available'] is False
    assert 'zoom' in derived['error']


def test_a_non_frame_argument_is_reported_not_raised():
    derived = radar_field.derive(None)
    assert derived['available'] is False
    assert derived['error']


def test_empty_tiers_are_empty_geometries_never_none():
    """A None that reaches a coordinate read becomes NaN, and NaN is not JSON."""
    row, column = _asserted_entry()
    frame = _frame_with([(row, column, 40.0)])
    derived = radar_field.derive(frame)
    for band in radar_field.BAND_ORDER:
        geometry = derived['bands'][band]['geometry']
        assert geometry is not None
        assert isinstance(geometry, GeometryCollection) or not geometry.is_empty
        # the geometry must be readable, which is what NaN would break
        assert geometry.bounds is not None


# ---------------------------------------------------------------- shield

def test_shield_keeps_the_core_inside_the_field():
    """The invariant that makes the two-colour rendering readable."""
    (row_a, column_a), (row_b, column_b) = INSIDE_CELLS[0], INSIDE_CELLS[3]
    frame = _frame_with([(row_a, column_a, 50.0), (row_b, column_b, 50.0)])
    derived = radar_field.derive(frame)
    field, core, caution, watch = radar_field.shield(derived)
    assert not field.is_empty
    outside = core.difference(field.buffer(1.0)).area
    assert outside == pytest.approx(0.0, abs=1.0), 'core must not spill outside its field'


def test_shield_reports_stratiform_even_when_there_is_no_hazard():
    """Otherwise "no hazard" and "no radar" look identical to the operator."""
    row, column = _asserted_entry()
    frame = _frame_with([(row, column, 20.0)])  # STRATIFORM only
    derived = radar_field.derive(frame)
    field, core, caution, watch = radar_field.shield(derived)
    assert field.is_empty and core.is_empty and caution.is_empty
    assert not watch.is_empty


def test_the_strong_band_drives_the_core_when_it_is_present():
    (row_a, column_a) = INSIDE_CELLS[0]
    (row_b, column_b) = INSIDE_CELLS[3]
    frame = _frame_with([(row_a, column_a, 70.0), (row_a, column_b, 70.0),
                         (row_b, column_a, 70.0), (row_b, column_b, 70.0)])
    derived = radar_field.derive(frame)
    assert derived['bands']['STRONG']['components'] >= 1
    field, core, caution, watch = radar_field.shield(derived)
    assert not core.is_empty
    assert field.area >= core.area


# ---------------------------------------------------------------- summary

def test_summary_states_that_the_channel_does_not_drive_geometry_when_down():
    summary = radar_field.summary(derived={'available': False, 'error': 'no frame'})
    assert summary['available'] is False
    assert summary['drivesGeometry'] is False
    assert summary['error'] == 'no frame'


def test_summary_never_claims_geometry_from_an_unavailable_channel():
    summary = radar_field.summary(frame_result=_FakeFrame([], available=False,
                                                         error='x').as_dict())
    assert summary['drivesGeometry'] is False


# ------------------------------------------------- tile fetch concurrency (DX-12)

def test_the_two_default_tiles_of_an_attempt_are_kept_in_grid_order(monkeypatch):
    """一次尝试内的瓦片并发取，但**结果顺序与网格一致**。

    顺序不是装饰：调用方按顺序拼 ``cells``，``gridTiles`` 直接由它导出，顺序
    变了，下游按网格定位的代码就会读错瓦片。
    """
    body = bytes(cma_tiles.TILE_SIZE * cma_tiles.TILE_SIZE * cma_tiles.BYTES_PER_CELL)

    def fake_fetch(slot, zoom=3, x=6, y=3, opener=None):
        return body

    monkeypatch.setattr(cma_tiles, 'fetch_tile', fake_fetch)
    result = cma_tiles._fetch_tiles(None, ZOOM, ((6, 2), (6, 3)))
    assert [row[0] for row in result] == [(6, 2), (6, 3)]
    assert all(row[1] == body and row[2] is None for row in result)


def test_a_failure_reports_the_first_grid_tile_not_the_last_to_finish(monkeypatch):
    """并发下「谁先完成」与「谁在网格里更靠前」是两件事，必须报后者。

    这里让**网格里第一块更慢**完成，所以一个按完成顺序记录失败的实现会报
    ``(6,3)``。这条判据正是把这两种实现分开的东西。
    """
    def fake_fetch(slot, zoom=3, x=6, y=3, opener=None):
        time.sleep(0.08 if (x, y) == (6, 2) else 0.01)
        raise cma_tiles.RadarTileUnavailable('boom-%d,%d' % (x, y))

    monkeypatch.setattr(cma_tiles, 'fetch_tile', fake_fetch)
    result = cma_tiles._fetch_tiles(None, ZOOM, ((6, 2), (6, 3)))
    assert result[0][0] == (6, 2) and 'boom-6,2' in result[0][2]
    assert result[1][0] == (6, 3) and 'boom-6,3' in result[1][2]


def test_the_two_tile_fetches_really_overlap(monkeypatch):
    """并行必须**真的**发生，否则这次改动只是换了个写法。

    判据是墙钟：两块各睡 0.15 s，串行必然 >= 0.30 s。阈值取 1.8 倍而不是
    「小于两倍」，是因为调度抖动不该让一条正确的实现变红。
    """
    delay = 0.15

    def fake_fetch(slot, zoom=3, x=6, y=3, opener=None):
        time.sleep(delay)
        return b'ok'

    monkeypatch.setattr(cma_tiles, 'fetch_tile', fake_fetch)
    started = time.monotonic()
    cma_tiles._fetch_tiles(None, ZOOM, ((6, 2), (6, 3)))
    elapsed = time.monotonic() - started
    assert elapsed < delay * 1.8, '两块瓦片看起来是串行取的（%.3f s）' % elapsed


def test_a_partly_failed_attempt_is_not_a_usable_frame(monkeypatch):
    """一块成功、一块失败 => 这个时次**不算**可用，与串行时的结论一致。

    并发没有放宽「完整帧」的定义：只有两块都在手里，这一帧才是测量。
    """
    body = bytes(cma_tiles.TILE_SIZE * cma_tiles.TILE_SIZE * cma_tiles.BYTES_PER_CELL)

    def fake_fetch(slot, zoom=3, x=6, y=3, opener=None):
        if (x, y) == (6, 3):
            raise cma_tiles.RadarTileUnavailable('nope')
        return body

    monkeypatch.setattr(cma_tiles, 'fetch_tile', fake_fetch)
    cma_tiles._CACHE.clear()
    result = cma_tiles.frame(zoom=ZOOM, grid=((6, 2), (6, 3)), force=True)
    assert result['available'] is False
    assert '(6,3)' in result['error']
