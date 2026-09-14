import math
from collections import Counter
import pytest
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from traffic.catalog import cities, connections
from traffic.service import network, simulate, weather_frame
from traffic.spatial import conflict, trajectory
from traffic.weather import NetworkWeather
from weather.geometry import boundary


@pytest.fixture(scope='module',params=['clear','moving'])
def run(request):
    return simulate(42,request.param)


def test_city_coverage_and_capital_only_crossings():
    n=network(); lookup={c['id']:c for c in n['cities']}
    assert len(lookup)==36
    assert sorted(Counter(c['province'] for c in cities()).values())==[9,13,14]
    assert sum(r['interprovincial'] for r in n['routes'])==2
    for r in n['routes']:
        assert r['path']
        assert r['path'][0]==r['fromXY'] and r['path'][-1]==r['toXY']
        assert boundary(r['province']).covers(LineString(r['path']))
        if r['interprovincial']: assert lookup[r['fromCity']]['capital'] and lookup[r['toCity']]['capital']
        if r['mode']=='DELIVERY':
            assert r['fromCity']==r['toCity']
            assert all(math.dist(p,lookup[r['fromCity']]['xy'])<=3000 for p in r['path'])
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
            assert Point(centre).buffer(3000).covers(LineString([p[:2] for p in points]))
        assert f['delayMinutes']+f['detourMinutes']<=60.001
        assert points[-1][3]<=480
        for a,b in zip(points,points[1:]):
            assert b[3]>a[3]
            assert abs(b[2]-a[2])/((b[3]-a[3])*60)<=3.000001
            assert math.dist(a[:2],b[:2])/((b[3]-a[3])*60)<= (50.000001 if f['mode']=='CAR' else 12.500001)


def test_weather_envelope_contains_intermediate_risks():
    world=NetworkWeather(42,'moving'); swept=world.envelope(10,70)
    for minute in (10,12.4,29.3,45.1,69.8,70):
        for _,_,ban,caution in world.shapes(minute):
            assert swept.covers(ban) and swept.covers(caution)
    assert world.frame(10)!=world.frame(11)
    assert world.frame(10)!=NetworkWeather(43,'moving').frame(10)


def test_unknown_fails_closed_and_no_wind():
    s=simulate(42,'unknown')
    assert s['stats']['accepted']==0
    assert all(f['reason']=='WEATHER_UNAVAILABLE' for f in s['flights'])
    frame=weather_frame(42,'unknown',30)
    assert not frame['available'] and frame['winds']==[] and frame['cells']==[]


def test_determinism_and_actual_detours():
    a=simulate(11,'moving'); b=simulate(11,'moving')
    assert a==b
    assert a['stats']['detours']>0
    assert a['stats']['closed']>0


def test_active_flights_avoid_future_weather(run):
    w=NetworkWeather(42,run['scenario'])
    for f in run['flights']:
        if f['points']:
            line=LineString([p[:2] for p in f['points']])
            assert not line.intersects(w.envelope(f['departureMinute'],f['arrivalMinute']))


def test_crossing_ramps_have_return_to_original_layer():
    points=trajectory([[0,0],[2500,0]],0,45,90,True)
    assert [p[2] for p in points]==[0,90,90,190,190,90,90,0]
    assert all(p[3]<q[3] for p,q in zip(points,points[1:]))


def test_ramp_follows_actual_offcentre_crossing():
    points=trajectory([[0,0],[5000,0]],0,45,90,crossings=[1200])
    plateau=[p[0] for p in points if p[2]==190]
    assert min(plateau)<1200<max(plateau)
    assert points[-2][2]==90 and points[-1][2]==0


def test_winds_are_in_region_and_avoid_city_labels():
    frame=weather_frame(42,'moving',60)
    assert len(frame['winds'])>300
    assert all(boundary().covers(Point(w['xy'])) for w in frame['winds'])
    assert all(math.dist(w['xy'],c['xy'])>12000 for w in frame['winds'] for c in cities())
    urban=weather_frame(42,'moving',60,'1-01')
    assert len(urban['winds'])>30


def test_traffic_api_input_validation():
    from fastapi.testclient import TestClient
    from main import app
    client=TestClient(app)
    for path in ('/traffic/session?seed=-1','/traffic/session?scenario=typo',
                 '/traffic/weather?minute=nan','/traffic/weather?minute=481','/traffic/weather?cityId=missing'):
        assert client.get(path).status_code==422
    assert client.get('/traffic/weather?scenario=unknown').json()['available'] is False
