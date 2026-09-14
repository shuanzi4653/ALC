"""Deterministic city-network dispatch, conservative weather avoidance and 4D slots."""
import hashlib
import json
import math
import random
import heapq
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from shapely.geometry import LineString, Point, mapping
from shapely.strtree import STRtree
from weather.geometry import boundary, geojson, BOUNDARY_VERSION
from .catalog import cities, connections
from .routing import route
from .spatial import conflict, trajectory
from .weather import NetworkWeather

VERSION='city-traffic-1'
FINGERPRINT=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))+BOUNDARY_VERSION.encode()).hexdigest()[:16]
STORE=Path(__file__).resolve().parents[2]/'.run'/'traffic'
LOCK=threading.Lock()
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='traffic')
JOBS={}


def _terminal(city,dx,dy):
    x,y=city['xy']; allowed=boundary(city['province'])
    for scale in (1,.7,.4,.15,0):
        p=[x+dx*scale,y+dy*scale]
        if allowed.covers(LineString([[x,y],p])): return p
    return [x,y]


@lru_cache(maxsize=1)
def network():
    lookup={c['id']:c for c in cities()}; routes=[]
    for a,b in connections():
        ca,cb=lookup[a],lookup[b]
        province=ca['province'] if ca['province']==cb['province'] else None
        start=_terminal(ca,-2000,-1800); end=_terminal(cb,-2000,-1800)
        path=route(start,end,boundary(province))
        routes.append(dict(id=f'CAR-{a}-{b}',mode='CAR',fromCity=a,toCity=b,
                           name=f"{ca['name']} ↔ {cb['name']}",province=province,
                           interprovincial=province is None,path=path,fromXY=start,toXY=end))
    # Some provincial corridors require a long dogleg around the administrative
    # boundary. Reuse already validated neighbouring legs instead of crossing it.
    for missing in [r for r in routes if not r['path']]:
        edges={c['id']:[] for c in cities()}
        for r in routes:
            if r['path'] and r['province']==missing['province']:
                length=LineString(r['path']).length
                edges[r['fromCity']].append((r['toCity'],length,r['path']))
                edges[r['toCity']].append((r['fromCity'],length,list(reversed(r['path']))))
        queue=[(0,missing['fromCity'],[])]; visited=set()
        while queue:
            cost,node,legs=heapq.heappop(queue)
            if node in visited: continue
            visited.add(node)
            if node==missing['toCity']:
                missing['path']=legs; break
            for dest,length,leg in edges[node]:
                if dest not in visited: heapq.heappush(queue,(cost+length,dest,legs+leg[bool(legs):]))
    for c in cities():
        nodes=[_terminal(c,*offset) for offset in ((-1100,-600),(1300,950),(-900,1100),(1500,-650))]
        for i,(a,b) in enumerate(((0,1),(2,3),(0,3))):
            path=route(nodes[a],nodes[b],boundary(c['province']))
            routes.append(dict(id=f"DEL-{c['id']}-{i}",mode='DELIVERY',fromCity=c['id'],toCity=c['id'],
                               name=f"{c['name']} · 配送站{a+1}—收货点{b+1}",province=c['province'],
                               interprovincial=False,path=path,fromXY=nodes[a],toXY=nodes[b]))
    return dict(cities=cities(),routes=routes,boundary=geojson(boundary()),boundaryXY=mapping(boundary().simplify(150,preserve_topology=True)),
                source='SIMULATION',version=VERSION,
                assumptions=dict(horizontalSeparationM=250,verticalSeparationM=60,climbMps=3,
                                 carSpeedKmh=180,deliverySpeedKmh=45,maxExtraMinutes=60,
                                 departureHorizonMinutes=180,timelineMinutes=480,
                                 altitudeDatum='模拟平面地面之上的相对高度，不含真实地形与建筑物避障',
                                 cityCoordinates='城市近似中心，节点与服务区为合成数据，非真实起降场'))


def _keys(points):
    """Conservative spatiotemporal broad phase, including the separation margin."""
    keys=set()
    for a,b in zip(points,points[1:]):
        for x in range(math.floor((min(a[0],b[0])-250)/15000),math.floor((max(a[0],b[0])+250)/15000)+1):
            for y in range(math.floor((min(a[1],b[1])-250)/15000),math.floor((max(a[1],b[1])+250)/15000)+1):
                for t in range(math.floor(a[3]/10),math.floor(b[3]/10)+1): keys.add((x,y,t))
    return keys


def _lateral(path,width,allowed):
    # Opposing directions use separate lateral corridors; exact terminals retained.
    if len(path)<2: return path
    points=[path[0]]
    for a,b in zip(path,path[1:]):
        length=math.dist(a,b)
        if length<1: continue
        dx,dy=(b[0]-a[0])/length,(b[1]-a[1])/length
        for f in (.12,.88): points.append([a[0]+(b[0]-a[0])*f+dy*width,a[1]+(b[1]-a[1])*f-dx*width])
    points.append(path[-1])
    return points if allowed.covers(LineString(points)) else path


def _crossings(path,rid,mode,lines,tree,route_ids,route_modes):
    line=LineString(path); distances=[]
    for index in tree.query(line,predicate='intersects'):
        if route_ids[index]==rid: continue
        # Raise cars at car/delivery intersections; drone/drone crossings also
        # receive ramps. Same-terminal convergence is handled by departure slots.
        if mode=='CAR' and route_modes[index]=='CAR': continue
        intersection=line.intersection(lines[index])
        points=[intersection] if intersection.geom_type=='Point' else list(intersection.geoms) if intersection.geom_type=='MultiPoint' else []
        for point in points:
            d=line.project(point)
            if 300<d<line.length-300: distances.append(d)
    return sorted(set(distances))


def simulate(seed=42,scenario='moving',progress=lambda _:None):
    catalog=network(); weather=NetworkWeather(seed,scenario); rng=random.Random(seed)
    geometries=[LineString(r['path']) for r in catalog['routes'] if r['path']]
    route_ids=[r['id'] for r in catalog['routes'] if r['path']]
    route_modes=[r['mode'] for r in catalog['routes'] if r['path']]
    tree=STRtree(geometries)
    pending=[]
    for r in catalog['routes']:
        interval=60 if r['mode']=='CAR' else 30
        for departure in range(0,180,interval):
            for direction in (0,1):
                scheduled=departure+direction*8+rng.randint(0,5)
                pending.append((scheduled,r['id'],direction,r))
    pending.sort(key=lambda item:item[:3])
    accepted=[]; flights=[]; buckets={}; path_cache={}
    for index,(scheduled,rid,direction,r) in enumerate(pending):
        fid=f'{rid}-{direction}-{scheduled}'
        flight=dict(id=fid,routeId=rid,mode=r['mode'],direction=direction,scheduledMinute=scheduled,
                    name=r['name'],fromCity=r['fromCity'] if not direction else r['toCity'],
                    toCity=r['toCity'] if not direction else r['fromCity'],status='CLOSED',
                    reason='NO_GEOMETRIC_PATH',points=[],delayMinutes=0,detourMinutes=0,
                    separationAction='NONE',conflictWith=[],payload=rng.randint(1,4) if r['mode']=='CAR' else rng.randint(1,3))
        flights.append(flight)
        progress(round((index+1)/len(pending)*100))
        if scenario=='unknown': flight['reason']='WEATHER_UNAVAILABLE'; continue
        if not r['path']: continue
        allowed=boundary(r['province'])
        if r['mode']=='DELIVERY':
            city=next(c for c in catalog['cities'] if c['id']==r['fromCity'])
            allowed=allowed.intersection(Point(city['xy']).buffer(3000))
        base=list(reversed(r['path'])) if direction else r['path']
        base=_lateral(base,220 if r['mode']=='CAR' else 90,allowed)
        speed=180 if r['mode']=='CAR' else 45
        altitude=(400+direction*100) if r['mode']=='CAR' else (90+direction*80)
        # The second urban corridor climbs across its central crossing, then descends.
        crossings=_crossings(base,rid,r['mode'],geometries,tree,route_ids,route_modes)
        basepoints=trajectory(base,scheduled,speed,altitude,crossings=crossings)
        base_duration=basepoints[-1][3]-scheduled
        path=base; detour=False
        # Plan against the entire permitted arrival interval, including holds. This
        # is conservative: a route may close even if a finer planner could fit it.
        obstacle=weather.envelope(scheduled,scheduled+base_duration+60)
        if LineString(path).intersects(obstacle):
            cachekey=(rid,direction,int(scheduled//5))
            if cachekey not in path_cache: path_cache[cachekey]=route(base[0],base[-1],allowed,obstacle)
            path=path_cache[cachekey]; detour=True
        if not path: flight['reason']='WEATHER_BLOCKED'; continue
        crossings=_crossings(path,rid,r['mode'],geometries,tree,route_ids,route_modes)
        chosen=None; encountered=set()
        for delay in range(0,61,5):
            for lift in (0,100):
                points=trajectory(path,scheduled+delay,speed,altitude+lift,crossings=crossings)
                extra=points[-1][3]-scheduled-base_duration
                if extra>60+1e-8: continue
                if points[-1][3]-points[0][3]>(300 if r['mode']=='CAR' else 40): continue
                keys=_keys(points)
                possible=set().union(*(buckets.get(k,set()) for k in keys))
                collisions=[i for i in possible if conflict(points,accepted[i]['points'])]
                if collisions:
                    encountered.update(accepted[i]['id'] for i in collisions)
                    continue
                chosen=(points,delay,lift,keys); break
            if chosen: break
        if not chosen:
            flight['reason']='SEPARATION_OR_TIME_LIMIT'; flight['conflictWith']=sorted(encountered)[:8]; continue
        points,delay,lift,keys=chosen
        # Independent final guards cover terminal links, climbing and shifted times.
        if not allowed.covers(LineString([p[:2] for p in points])) or LineString([p[:2] for p in points]).intersects(weather.envelope(points[0][3],points[-1][3])):
            flight['reason']='FINAL_WEATHER_CHECK_FAILED'; continue
        flight.update(status='SCHEDULED',reason='WEATHER_DETOUR' if detour else 'CLEAR',points=points,
                      departureMinute=points[0][3],arrivalMinute=points[-1][3],delayMinutes=delay,
                      detourMinutes=round(points[-1][3]-points[0][3]-base_duration,2),
                      distanceKm=round(LineString([p[:2] for p in points]).length/1000,2),
                      separationAction='ALTITUDE_AND_SLOT' if lift and delay else 'ALTITUDE' if lift else 'SLOT' if delay else 'CROSSING_RAMP' if crossings else 'LAYERED',
                      crossingDistancesM=[round(d,2) for d in crossings],
                      conflictWith=sorted(encountered)[:8],maxAltitudeM=max(p[2] for p in points))
        ai=len(accepted); accepted.append(flight)
        for key in keys: buckets.setdefault(key,set()).add(ai)
    return dict(source='SIMULATION',version=VERSION,fingerprint=FINGERPRINT,seed=seed,scenario=scenario,
                status='READY',progress=100,flights=flights,
                stats=dict(cities=len(catalog['cities']),routes=len(catalog['routes']),
                           carRoutes=sum(r['mode']=='CAR' for r in catalog['routes']),
                           deliveryRoutes=sum(r['mode']=='DELIVERY' for r in catalog['routes']),
                           interprovincialRoutes=sum(r['interprovincial'] for r in catalog['routes']),
                           flights=len(flights),accepted=len(accepted),closed=len(flights)-len(accepted),
                           detours=sum(f['reason']=='WEATHER_DETOUR' for f in accepted),
                           resolved=sum(bool(f['conflictWith']) for f in accepted)))


def identity(seed,scenario):
    return hashlib.sha256(f'{VERSION}:{FINGERPRINT}:{seed}:{scenario}'.encode()).hexdigest()[:24]


def _build(key,seed,scenario):
    try:
        def progress(value):
            with LOCK: JOBS[key]['progress']=value
        result=simulate(seed,scenario,progress); result['sessionId']=key
        STORE.mkdir(parents=True,exist_ok=True)
        temp=STORE/f'{key}.tmp'; temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        temp.replace(STORE/f'{key}.json')
        with LOCK: JOBS[key]=result
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Traffic simulation failed')
        with LOCK: JOBS[key]=dict(status='ERROR',sessionId=key,message='运行计划计算失败，请查看本地 Python 日志')


def session(seed,scenario):
    key=identity(seed,scenario)
    with LOCK:
        if key in JOBS: return JOBS[key]
        if sum(v['status']=='BUILDING' for v in JOBS.values())>=2:
            return dict(status='BUSY',message='已有模拟计划正在计算，请稍后重试')
        if len(JOBS)>=4:
            old=next((k for k,v in JOBS.items() if v['status']!='BUILDING'),None)
            if old: del JOBS[old]
        saved=STORE/f'{key}.json'
        if saved.exists():
            try:
                result=json.loads(saved.read_text(encoding='utf-8'))
                if result.get('fingerprint')==FINGERPRINT:
                    JOBS[key]=result; return result
            except (ValueError,OSError): pass
        JOBS[key]=dict(status='BUILDING',progress=0,sessionId=key)
        POOL.submit(_build,key,seed,scenario)
        return JOBS[key]


def weather_frame(seed,scenario,minute,city_id=None):
    city=next((c for c in cities() if c['id']==city_id),None)
    if city_id and not city: raise ValueError('Unknown city')
    winds=[]
    if scenario!='unknown':
        if city:
            cx,cy=city['xy']; xmin,ymin,xmax,ymax=cx-3000,cy-3000,cx+3000,cy+3000; step=700
        else:
            xmin,ymin,xmax,ymax=boundary().bounds; step=40000
        for x in range(int(xmin),int(xmax)+1,step):
            for y in range(int(ymin),int(ymax)+1,step):
                if boundary().covers(Point(x,y)) and all(math.dist([x,y],c['xy'])>(350 if city else 12000) for c in cities()):
                    u=3+math.sin(minute/45+y/180000+seed*.01)
                    v=1.5+math.cos(minute/60+x/180000)
                    winds.append(dict(xy=[x,y],u=u,v=v))
    return dict(source='SIMULATION',seed=seed,scenario=scenario,minute=minute,
                cityId=city_id,available=scenario!='unknown',cells=NetworkWeather(seed,scenario).frame(minute),winds=winds)
