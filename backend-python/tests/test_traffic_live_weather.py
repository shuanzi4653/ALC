"""The point feed may only mint geometry for a genuinely extreme reading.

Two defects are pinned here, and the second is the one that cost real capacity.

**Defect 1 (vocabulary).** The old rule named *every* mildly adverse city and
gave it an 18 km field with a 12 km caution ring centred on the city. Measured
2026-09-30 on the live snapshot: eleven such discs, none with a prohibition core.
A 12 km disc is an invented footprint -- the reading is a value at a point, and
the project forbids manufacturing a boundary from one.

**Defect 2 (routing).** `envelope()` unioned ``ban | caution`` into the planner's
obstacle set, and `routing.route()` refuses outright when a flight's own start or
end point is inside that set. So every departure from a merely gusty city was
closed: 2488 flights, with zero detours produced by a radar channel that carried
528 km2 of >=35 dBZ echo. This is the direction the negative tests below guard --
"caution is advice, not a refusal" is only true if something asserts it.
"""
from traffic.catalog import cities
from traffic.weather import PublicWeather, _extreme_kind, point_risk_shapes


def _snapshot(observation, provider='OPEN_METEO'):
    return {
        'available': True, 'provider': provider, 'dataType': 'MODEL_ESTIMATE',
        'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION'],
        'observations': [observation],
    }


def _observation(city, **overrides):
    row = {'cityId': city['id'], 'windGusts10mMps': 0.0, 'precipitationMm': 0.0,
           'conditionClass': None, 'hourly': {'visibility': [10000]}}
    row.update(overrides)
    return row


def test_public_weather_marks_provenance_and_derived_risk_without_fake_thunder():
    city = cities()[0]
    snapshot = _snapshot(_observation(city, windGusts10mMps=18, hourly={'visibility': [900]}))
    weather = PublicWeather(snapshot, cities())
    cells = weather.frame(0)
    assert len(cells) == 1
    assert cells[0]['source'] == 'OPEN_METEO_DERIVED_RISK'
    # An 8 级 gust is the extreme branch. The old vocabulary (WIND / RAIN /
    # LOW_VISIBILITY) named the *mild* thresholds; those now mint nothing at all.
    assert cells[0]['kind'] == 'EXTREME_WIND'
    assert cells[0]['derivedFrom']['gustMps'] == 18
    assert not weather.envelope(0, 20).is_empty


def test_a_thunderstorm_reading_is_a_risk_cell_and_says_why():
    city = cities()[0]
    snapshot = _snapshot(_observation(city, conditionClass='THUNDERSTORM'))
    cells = PublicWeather(snapshot, cities()).frame(0)
    assert len(cells) == 1
    assert cells[0]['kind'] == 'THUNDERSTORM'
    # The disc is the *core* on both tiers: one reading, one enforcement level.
    assert cells[0]['ban']['coordinates'], '雷暴必须给出禁止内核'
    assert not cells[0]['caution']['coordinates'], \
        '点观测不解析"内部与边缘"，不得凭空造出缓变环'


def test_public_weather_without_snapshot_does_not_invent_a_risk_field():
    weather = PublicWeather({'available': False, 'observations': []}, cities())
    assert weather.frame(0) == []
    assert weather.envelope(0, 20).is_empty


# ---------------------------------------------------------------------------
# Negative direction. Everything below asserts that *nothing* happens.
# ---------------------------------------------------------------------------
def test_mildly_adverse_weather_mints_no_geometry_and_no_obstacle():
    """A gusty or drizzly city is reported, never drawn, never avoided.

    This is the regression guard for the 2488 closures. Each case here used to
    clear the mild threshold (gust >= 12, precipitation >= 1 mm,
    visibility < 5000 m) and therefore produced a disc that the planner treated
    as airspace it could not enter -- over the city's own pads.
    """
    city = cities()[0]
    for label, observation in {
        '阵风 15 m/s': _observation(city, windGusts10mMps=15.0),
        '小雨 2 mm/h': _observation(city, precipitationMm=2.0),
        '能见度 3 km': _observation(city, hourly={'visibility': [3000.0]}),
        '中雨现象码': _observation(city, conditionClass=None, precipitationMm=0.5),
    }.items():
        shapes = point_risk_shapes(_snapshot(observation), cities())
        assert shapes == [], f'{label} 不该生成任何风险几何'
        weather = PublicWeather(_snapshot(observation), cities())
        assert weather.frame(0) == [], label
        assert weather.envelope(0, 480).is_empty, f'{label} 不该进入航路障碍集合'


def test_the_extreme_branches_are_the_documented_ones():
    """Every branch that *does* mint geometry, and the order that labels them."""
    city = cities()[0]
    assert _extreme_kind(_observation(city, conditionClass='THUNDERSTORM')) == 'THUNDERSTORM'
    assert _extreme_kind(_observation(city, conditionClass='HEAVY_RAIN')) == 'HEAVY_RAIN'
    assert _extreme_kind(_observation(city, windGusts10mMps=17.0)) == 'EXTREME_WIND'
    assert _extreme_kind(_observation(city, hourly={'visibility': [999.0]})) == 'LOW_VISIBILITY'
    assert _extreme_kind(_observation(city, precipitationMm=8.0)) == 'HEAVY_RAIN'
    # A thunderstorm that also gusts hard is reported as the thunderstorm: that
    # is the condition that puts the airspace out of use.
    assert _extreme_kind(_observation(city, conditionClass='THUNDERSTORM',
                                      windGusts10mMps=25.0)) == 'THUNDERSTORM'
    # Just below every threshold, and a payload whose adapter did not classify
    # its condition code: both are "no evidence", not "probably fine".
    assert _extreme_kind(_observation(city, windGusts10mMps=16.9)) is None
    assert _extreme_kind(_observation(city, hourly={'visibility': [1000.0]})) is None
    assert _extreme_kind(_observation(city, precipitationMm=7.9)) is None


def test_the_caution_tier_is_never_in_the_routing_envelope():
    """Direction 2 of the same guard, stated on the shape the planner consumes.

    ``envelope`` must contain the prohibition core and must not contain anything
    else. Asserted as a property of the returned geometry rather than of the
    branch that built it, so a future edit that starts unioning the tiers again
    is caught even if it renames everything.
    """
    city = cities()[0]
    weather = PublicWeather(_snapshot(_observation(city, conditionClass='THUNDERSTORM')), cities())
    regions = weather.frame(0)
    assert regions, '构造用例必须真的产出一个区域，否则本测试什么也没验证'
    envelope = weather.envelope(0, 480)
    core = regions[0]['ban']
    assert core['coordinates']
    from shapely.geometry import shape
    core_shape = shape(core)
    assert envelope.covers(core_shape)
    # And the envelope is *exactly* the core: no ring was added around it.
    assert abs(envelope.area - core_shape.area) < 1.0
