import math
import random
from collections import Counter
from functools import lru_cache
from shapely import affinity
from shapely.geometry import MultiPoint, MultiPolygon, Polygon, GeometryCollection, LineString, Point, mapping
from shapely.ops import unary_union
from weather.geometry import boundary, geojson, project
from .catalog import cities, connections

RING_VERTICES=64
RING_HARMONICS=((1,.10),(2,.04),(3,.02))
SIMPLIFY_TOLERANCE=120

OUTLINE_VERTICES=128
OUTLINE_MAX_TURN_RAD=math.radians(45.0)
MIN_CORE_VERTICES=32
OUTLINE_ROUGHNESS=0.42
OUTLINE_ROUGHNESS_LOW_ORDER=0.26

CELL_ORBIT_M=(12000,9000)
CELL_ORBIT_PERIOD_MIN=(70,90)

CELL_LIFE_MINUTES=(42,75)
CELL_PEAK_AGE_FRACTION=0.42
CELL_MIN_SIZE_FRACTION=0.18
MIN_VISIBLE_RADIUS_M=900
CELL_ENVELOPE_GROWTH_MARGIN=1.25
CELL_LATE_BIRTH_MINUTES=(0,470)
CELL_PREEXISTING_BIRTH_RANGE=(-70,-20)
CELL_PREEXISTING_SHARE=0.35
CELL_SPLIT_SHARE=0.12
CELL_DAUGHTER_OFFSET_M=(9000,17000)
CELL_DAUGHTER_RADIUS_FRACTION=(0.55,0.8)
CELL_DAUGHTER_BIRTH_FRACTION=(0.30,0.55)

BAND_CENTRELINE_LONLAT=[(121.4,41.0),(123.6,42.6),(126.2,44.4),(128.9,46.6),(131.4,49.2)]
BAND_CLUSTER_RADII_M=(30000,12000,22000,11000,18000,10000)
BAND_CLUSTER_SPACING_M=62000
BAND_CLUSTER_GAP_M=9000
BAND_CORE_INSET_M=9500
BAND_WIND=(2.5,1.2)

BAND_CLUSTER_LIFE_MINUTES=(300,420)
BAND_CLUSTER_BIRTH_SPAN_MIN=840.0
BAND_CLUSTER_BIRTH_JITTER_MIN=95.0
BAND_CLUSTER_LEAD_BIAS_MIN=90.0
BAND_CLUSTER_RADIUS_SCALE=(0.45,1.25)
BAND_CLUSTER_MIN_RADIUS_M=2600
SWEPT_TRACK_PAD_M=2200
SWEPT_BAND_PAD_M=2200

KIND_SEVERITY={'THUNDERSTORM':5,'HEAVY_RAIN':4,'EXTREME_WIND':3,'STORM':3,
               'LOW_VISIBILITY':1,'WIND':2,'RAIN':1}

def _operation_gust_limit(key: str, fallback: float) -> float:
    try:
        import json as _json
        from pathlib import Path as _Path
        path = _Path(__file__).resolve().parents[2] / 'config' / 'rules-v1.json'
        return float(((_json.loads(path.read_text(encoding='utf-8')) or {})
                      .get('operations') or {}).get(key) or fallback)
    except Exception:  # noqa: BLE001
        return fallback

EXTREME_WIND_GUST_MPS=_operation_gust_limit('extremeGustMps', 17.0)
EXTREME_VISIBILITY_M=1000.0
EXTREME_HOURLY_RAIN_MM=8.0
EXTREME_CORE_RADIUS_M=6000.0

def extreme_thresholds():
    return {
        'gustMps': EXTREME_WIND_GUST_MPS,
        'visibilityM': EXTREME_VISIBILITY_M,
        'hourlyRainMm': EXTREME_HOURLY_RAIN_MM,
        'coreRadiusM': EXTREME_CORE_RADIUS_M,
        'note': '单一站点读数达到以上任一项时，在该站生成一个禁止进入内核；'
                '未达到的轻度过境只作观测记录，不生成几何。'
                '**能见度例外**：它另有一条两档派生通道（见 ``fog_rule_block``），'
                '低于禁飞阈值的一档仍按本表生成禁止几何，偏低的一档只掰弯航路。',
    }

FOG_CAUTION_RADIUS_M = 12_000.0
FOG_BAN_RADIUS_M = EXTREME_CORE_RADIUS_M

@lru_cache(maxsize=1)
def visibility_thresholds():
    try:
        from rules import load_spec
        for factor in load_spec().factors:
            if factor.key == 'visibilityM':
                warn, ban = factor.warnValue, factor.banValue
                if warn is not None and ban is not None:
                    return float(warn), float(ban)
    except Exception:
        pass
    return 5000.0, float(EXTREME_VISIBILITY_M)

def _fog_disc(xy, radius_m):
    return Point(xy).buffer(radius_m, quad_segs=16).simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)

def fog_tiers(snapshot, city_rows):
    if not snapshot.get('available'):
        return []
    caution_m, ban_m = visibility_thresholds()
    city_lookup = {city['id']: city for city in city_rows}
    rows = []
    for observation in snapshot.get('observations', []):
        visibility = _first_visibility(observation)
        if visibility is None:
            continue
        city = city_lookup.get(observation.get('cityId'))
        if not city:
            continue
        if visibility >= caution_m:
            continue
        banned = visibility < ban_m
        outer = _fog_disc(city['xy'], FOG_CAUTION_RADIUS_M)
        if banned:
            inner = _fog_disc(city['xy'], FOG_BAN_RADIUS_M)
            caution = outer.difference(inner)
        else:
            inner = GeometryCollection()
            caution = outer
        rows.append(({
            'id': f"FOG-{city['id']}",
            'cityId': city['id'],
            'cityName': city.get('name'),
            'kind': 'LOW_VISIBILITY',
            'tier': 'BAN' if banned else 'CAUTION',
            'visibilityM': visibility,
            **fog_rule_block(),
            'derivedFrom': {'visibilityM': visibility,
                            'provider': snapshot.get('provider'),
                            'dataType': snapshot.get('dataType')},
        }, caution, inner))
    return rows

def fog_rule_block():
    caution_m, ban_m = visibility_thresholds()
    return {
        'tiers': 'LOW_VISIBILITY_2',
        'cautionVisibilityM': caution_m,
        'banVisibilityM': ban_m,
        'cautionRadiusM': FOG_CAUTION_RADIUS_M,
        'banRadiusM': FOG_BAN_RADIUS_M,
        'hardTier': 'BAN',
        'softTier': 'CAUTION',
        'padExemptTier': 'CAUTION',
        'thresholdSource': 'config/rules-v1.json::visibilityM',
        'note': '站点能见度读数派生的两档近似范围（不是实测雾区边界）：'
                '低于禁飞阈值＝深灰禁止进入；偏低＝浅灰须绕飞，可擦边，不单独拒绝起降。',
    }

def _areal(geometry):
    return geometry is not None and not geometry.is_empty and geometry.geom_type in ('Polygon','MultiPolygon')

def _mapping_tier(geometry):
    return mapping(geometry) if _areal(geometry) else {'type': 'Polygon', 'coordinates': []}

def _polygon_parts(geometry):
    if not _areal(geometry):
        return [part for part in getattr(geometry,'geoms',[]) if _areal(part)]
    if geometry.geom_type=='Polygon':
        return [geometry]
    return [part for part in geometry.geoms if _areal(part)]

def _outline_hull_coords(geometry):
    parts=_polygon_parts(geometry)
    if not parts:
        return []
    hull=parts[0].convex_hull if len(parts)==1 else MultiPolygon(parts).convex_hull
    return _hull_ring_coords(hull)

def _hull_ring_coords(hull):
    if hull is None or hull.is_empty:
        return []
    kind=hull.geom_type
    if kind=='Polygon':
        return [(x,y) for x,y in hull.exterior.coords]
    if kind in ('LineString','LinearRing'):
        return [(x,y) for x,y in hull.coords]
    if kind=='Point':
        return [(hull.x,hull.y)]
    return [(point.x,point.y) for point in getattr(hull,'geoms',[])]

def _dissolve_regions(shapes):
    tiers={'FIELD':[],'BAN':[],'CAUTION':[]}
    for cell,field,ban,caution in shapes:
        tiers['FIELD'].append((cell,field))
        tiers['BAN'].append((cell,ban))
        tiers['CAUTION'].append((cell,caution))

    fields=_polygon_parts(unary_union([geometry for _,geometry in tiers['FIELD'] if _areal(geometry)]))
    regions=[]
    for field in fields:
        members=[cell for cell,geometry in tiers['FIELD']
                 if _areal(_clip(geometry,field))]
        if not members:
            continue
        ban=unary_union(_clipped_tier('BAN',tiers,members,field))
        outer=unary_union(_clipped_tier('FIELD',tiers,members,field)
                          +_clipped_tier('CAUTION',tiers,members,field))
        regions.append((members,field,ban,outer.difference(ban)))
    return regions

def _clip(geometry,field):
    if not _areal(geometry):
        return GeometryCollection()
    return unary_union([part.intersection(field) for part in _polygon_parts(geometry)
                        if part.intersects(field)])

def _clipped_tier(tier,tiers,members,field):
    result=[]
    keys={id(cell) for cell in members}
    for cell,geometry in tiers[tier]:
        if id(cell) not in keys:
            continue
        clipped=_clip(geometry,field)
        if _areal(clipped):
            result.extend(_polygon_parts(clipped))
    return result

def _region_identity(members):
    point_cells=sorted((cell for cell in members if not _spans_regions(cell)),
                       key=lambda cell:cell['id'])
    spanning=sorted((cell for cell in members if _spans_regions(cell)),
                    key=lambda cell:cell['id'])
    sources=[cell['id'] for cell in point_cells]
    sources+=[f"{cell['id']}::CLUSTER" for cell in spanning]
    kinds=Counter(cell['kind'] for cell in point_cells+spanning)
    dominant=max(kinds,key=lambda kind:(KIND_SEVERITY.get(kind,0),kinds[kind]))
    if point_cells:
        anchor=point_cells[0]
        city_ids={cell['city'] for cell in point_cells}
        identity=anchor['id'] if len(sources)==1 else f"{anchor['id']}+{len(sources)-1}"
        city=anchor['city'] if len(city_ids)==1 else 'REGION'
    else:
        identity=f"{spanning[0]['id']}::CLUSTER"
        city='REGION'
    return {
        'id':identity,
        'kind':dominant,
        'cityId':city,
        'sources':sources,
        'memberKinds':dict(kinds),
        'memberCount':len(sources),
    }

def _spans_regions(cell):
    return cell.get('shape')=='BAND' or len(_polygon_parts(cell.get('polygon')))>1

def cell_outline_params(rng,lobes=None):
    count=lobes if lobes is not None else rng.randint(5,8)
    harmonics=[]
    for order in range(2,2+count):
        amplitude=rng.uniform(.55,1.0)/(order**0.9)
        harmonics.append((order,amplitude,rng.uniform(0,math.tau)))
    return {'harmonics':harmonics,
            'stretch':rng.uniform(1.0,1.45),
            'axis':rng.uniform(0,math.pi)}

def _irregular_outline(cx,cy,radius,cfg,harmonics=None):
    harmonics=harmonics if harmonics is not None else cfg['harmonics']
    stretch=cfg['stretch']
    axis=cfg['axis']
    cos_axis,sin_axis=math.cos(axis),math.sin(axis)

    normaliser=sum(amplitude for _,amplitude,_ in harmonics)
    roughness=OUTLINE_ROUGHNESS_LOW_ORDER if len(harmonics)<4 else OUTLINE_ROUGHNESS
    highest=max(order for order,_,_ in harmonics)
    slope=sum(amplitude*order for order,amplitude,_ in harmonics)
    stretch_factor=(stretch+1/stretch)/2
    budget_vertices=math.ceil(roughness*slope*stretch_factor*math.tau
                              /max(normaliser,1e-9)/OUTLINE_MAX_TURN_RAD)
    vertices=int(max(24,24*highest//2,budget_vertices))
    vertices=min(vertices,OUTLINE_VERTICES)

    def _sample(count):
        phase=math.pi/count
        sampled=[]
        for index in range(count):
            theta=index*math.tau/count+phase
            wave=sum(amplitude*math.sin(order*theta+harmonic_phase)
                     for order,amplitude,harmonic_phase in harmonics)
            scale=1+roughness*wave/max(normaliser,1e-9)
            px=radius*scale*stretch*math.cos(theta)
            py=radius*scale*(1/stretch)*math.sin(theta)
            sampled.append((cx+px*cos_axis-py*sin_axis,
                            cy+px*sin_axis+py*cos_axis))
        return sampled

    sample_cap=max(OUTLINE_VERTICES,256)
    points=_sample(vertices)
    for _round in range(6):
        worst=_worst_exterior_turn(points)
        if worst<=OUTLINE_MAX_TURN_RAD or len(points)>=sample_cap:
            break
        wanted=min(sample_cap,math.ceil(len(points)*1.08*worst/OUTLINE_MAX_TURN_RAD))
        vertices=min(sample_cap,max(wanted,vertices+24))
        points=_sample(vertices)
    return Polygon(points).buffer(0)

def _simplify_keeping_detail(geometry,tolerance):
    simplified=geometry.simplify(tolerance,preserve_topology=True)
    if not simplified.is_empty and _exterior_vertex_count(simplified) >= MIN_CORE_VERTICES:
        return simplified
    return geometry

def _exterior_vertex_count(geometry):
    polygons=[geometry] if geometry.geom_type=='Polygon' else list(getattr(geometry,'geoms',[]))
    return sum(max(len(polygon.exterior.coords)-1,0)
               for polygon in polygons if polygon.geom_type=='Polygon')

def _worst_exterior_turn(points):
    count=len(points)
    if count<3:
        return 0.0
    worst=0.0
    for index in range(count):
        prev=points[(index-1)%count]
        cur=points[index]
        nxt=points[(index+1)%count]
        ax,ay=cur[0]-prev[0],cur[1]-prev[1]
        bx,by=nxt[0]-cur[0],nxt[1]-cur[1]
        length_a=math.hypot(ax,ay)
        length_b=math.hypot(bx,by)
        if length_a<1e-12 or length_b<1e-12:
            continue
        cosine=max(-1.0,min(1.0,(ax*bx+ay*by)/(length_a*length_b)))
        worst=max(worst,math.acos(cosine))
    return worst

def _caution_ring(cx,cy,cell,buffer_m=900):
    cfg=cell['outline']
    low=cfg['harmonics'][:2]
    inner=cell['radius']*core_scale(cell)
    outer=inner+buffer_m
    shift=CORE_OFFSET_M
    inner_shape=_irregular_outline(cx+shift[0],cy+shift[1],inner,cfg,harmonics=low)
    outer_shape=_irregular_outline(cx+shift[0],cy+shift[1],outer,cfg,harmonics=low)
    return outer_shape.difference(inner_shape)

CORE_OFFSET_M=(400,250)

def core_scale(cell,scale=0.58):
    return scale

def _core_outline(cx,cy,cell,scale=0.58,offset=(400,250)):
    cfg=cell['outline']
    smooth=_irregular_outline(cx,cy,cell['radius'],cfg,
                              harmonics=cfg['harmonics'][:2])
    scale=core_scale(cell,scale)
    points=[(cx+(px-cx)*scale+offset[0], cy+(py-cy)*scale+offset[1])
            for px,py in smooth.exterior.coords]
    return Polygon(points).buffer(0)

def _band_clusters():
    path=[project(point) for point in BAND_CENTRELINE_LONLAT]
    line=LineString(path)
    length=line.length
    count=max(2,int(length//BAND_CLUSTER_SPACING_M))
    centres=[]
    for index in range(count+1):
        point=line.interpolate(min(index*BAND_CLUSTER_SPACING_M,length))
        centres.append((point.x,point.y,BAND_CLUSTER_RADII_M[index%len(BAND_CLUSTER_RADII_M)]))
    for index in (0,len(centres)-1):
        x,y,_=centres[index]
        for city in cities():
            if not city['capital']:
                continue
            city_x,city_y=city['xy']
            if math.hypot(x-city_x,y-city_y)<26000:
                centres[index]=(x,y,9000)
                break
    cluster_rng=random.Random(20240917)
    life_rng=random.Random(20240918)
    clusters=[]
    total=len(centres)
    for index,(x,y,radius) in enumerate(centres):
        cfg=cell_outline_params(cluster_rng,lobes=6 if radius>=18000 else 8)
        lead=index/max(1,total-1)
        stride=BAND_CLUSTER_BIRTH_SPAN_MIN/max(1,total)
        margin=BAND_CLUSTER_BIRTH_JITTER_MIN+BAND_CLUSTER_LEAD_BIAS_MIN
        slot=-BAND_CLUSTER_BIRTH_SPAN_MIN/2.0+margin+stride*index
        birth=(slot
               +life_rng.uniform(-BAND_CLUSTER_BIRTH_JITTER_MIN,BAND_CLUSTER_BIRTH_JITTER_MIN)
               +lead*BAND_CLUSTER_LEAD_BIAS_MIN)
        clusters.append(dict(
            index=index,centre=(x,y),baseRadius=radius,outline=cfg,
            birth=birth,
            lifeMinutes=life_rng.uniform(*BAND_CLUSTER_LIFE_MINUTES),
            radiusPhase=life_rng.uniform(0.0,1.0),
        ))
    anchor_x=sum(c['centre'][0] for c in clusters)/max(1,len(clusters))
    anchor_y=sum(c['centre'][1] for c in clusters)/max(1,len(clusters))
    return clusters,Point(anchor_x,anchor_y)

def _band_cluster_radius(cluster,t):
    life=cluster.get('lifeMinutes')
    age=t-cluster.get('birth',0.0)
    if life is None or age<0 or age>life:
        return 0.0
    progress=age/life
    peak=CELL_PEAK_AGE_FRACTION
    shape=max(0.0,1-((progress-peak)/max(peak,1e-9))**2)
    low,high=BAND_CLUSTER_RADIUS_SCALE
    radius=cluster['baseRadius']*(low+(high-low)*shape)
    return radius if radius>=BAND_CLUSTER_MIN_RADIUS_M else 0.0

def _band_cluster_outlines(cluster,t):
    return _band_outline_memo(cluster,t)

_OUTLINE_CLUSTERS={}

def _forget_outlines():
    _band_cluster_outlines_cached.cache_clear()
    _band_cluster_hull_coords_cached.cache_clear()
    _OUTLINE_CLUSTERS.clear()

def _band_outline_memo(cluster,t):
    key=id(cluster)
    if key not in _OUTLINE_CLUSTERS:
        _OUTLINE_CLUSTERS[key]=cluster
    return _band_cluster_outlines_cached(key,t)

@lru_cache(maxsize=8192)
def _band_cluster_outlines_cached(cluster_key,t):
    cluster=_OUTLINE_CLUSTERS.get(cluster_key)
    if cluster is None:
        return None,None
    radius=_band_cluster_radius(cluster,t)
    if radius<=0.0:
        return None,None
    x,y=cluster['centre']
    cfg=cluster['outline']
    field=_irregular_outline(x,y,radius,cfg)
    inset_scale=max(.05,(radius-BAND_CORE_INSET_M)/radius)
    core=_irregular_outline(x,y,radius*inset_scale,cfg,harmonics=cfg['harmonics'][:2])
    return field,core

def _band_cluster_hull_coords(cluster,t):
    return _band_cluster_hull_coords_cached(id(cluster),t)

@lru_cache(maxsize=8192)
def _band_cluster_hull_coords_cached(cluster_key,t):
    cluster=_OUTLINE_CLUSTERS.get(cluster_key)
    if cluster is None:
        return []
    outline,_core=_band_cluster_outlines_cached(cluster_key,t)
    if outline is None:
        return []
    return _outline_hull_coords(outline)

class NetworkWeather:
    def __init__(self,seed,scenario):
        self.seed,self.scenario=seed,scenario
        rng=random.Random(seed)
        self.cells=[]
        lookup={c['id']:c for c in cities()}
        links=rng.sample(connections(),8)
        for index,city in enumerate(rng.sample(cities(),20)):
            if index<8:
                a,b=(lookup[key]['xy'] for key in links[index])
                centre=[(a[k]+b[k])/2 for k in range(2)]
            else:
                centre=[city['xy'][0]+18000,city['xy'][1]-12000]
            radius=rng.uniform(5000,11000)
            life=rng.uniform(*CELL_LIFE_MINUTES)
            if rng.random()<CELL_PREEXISTING_SHARE:
                birth=rng.uniform(*CELL_PREEXISTING_BIRTH_RANGE)
            else:
                birth=rng.uniform(*CELL_LATE_BIRTH_MINUTES)
            wind=(rng.uniform(-5.5,5.5),rng.uniform(-5.5,5.5))
            shape_seed=rng.randrange(1<<30)
            kind=rng.choice(['RAIN','STORM','WIND'])
            cfg=cell_outline_params(random.Random(shape_seed))
            cell=dict(id=f"WX-{city['id']}",shape='RING',city=city['id'],xy=centre,
                      phase=rng.uniform(0,2*math.pi),radius=radius,
                      wind=wind,kind=kind,shapeSeed=shape_seed,outline=cfg,
                      birth=birth,lifeMinutes=life,
                      sweptPad=radius*1.18+SWEPT_TRACK_PAD_M)
            self.cells.append(cell)
            if rng.random()<CELL_SPLIT_SHARE:
                daughter=self._shed_daughter(cell,rng)
                if daughter is not None:
                    self.cells.append(daughter)
        band_clusters,band_anchor=_band_clusters()
        self._band_clusters=band_clusters
        _forget_outlines()
        live_t0=[outline for outline,_core in
                 (_band_cluster_outlines(cluster,0.0) for cluster in band_clusters)
                 if outline is not None]
        band_polygon=unary_union(live_t0) if live_t0 else GeometryCollection()
        self.cells.append(dict(id='WX-NORTHEAST-BAND',shape='BAND',city='REGION',kind='STORM',
                               polygon=band_polygon,xy=[band_anchor.x,band_anchor.y],
                               phase=0.0,radius=BAND_CLUSTER_RADII_M[0],wind=BAND_WIND,sweptPad=0.0,
                               birth=0.0,lifeMinutes=None,clusters=band_clusters))

    def _shed_daughter(self,parent,rng):
        birth=parent['birth']+parent['lifeMinutes']*rng.uniform(*CELL_DAUGHTER_BIRTH_FRACTION)
        if birth>=480:
            return None
        offset=rng.uniform(*CELL_DAUGHTER_OFFSET_M)
        wx,wy=parent['wind']
        norm=math.hypot(wx,wy) or 1.0
        along_angle=math.atan2(wy/norm,wx/norm)+rng.uniform(-0.6,0.6)
        centre=[parent['xy'][0]+offset*math.cos(along_angle),
                parent['xy'][1]+offset*math.sin(along_angle)]
        radius=parent['radius']*rng.uniform(*CELL_DAUGHTER_RADIUS_FRACTION)
        shape_seed=rng.randrange(1<<30)
        return dict(id=f"{parent['id']}-D1",shape='RING',city=parent['city'],
                    parent=parent['id'],
                    xy=centre,phase=rng.uniform(0,2*math.pi),radius=radius,
                    wind=(wx+rng.uniform(-1.8,1.8),wy+rng.uniform(-1.8,1.8)),
                    kind=parent['kind'],shapeSeed=shape_seed,
                    outline=cell_outline_params(random.Random(shape_seed)),
                    birth=birth,lifeMinutes=parent['lifeMinutes']*rng.uniform(.6,.9),
                    sweptPad=radius*1.18+SWEPT_TRACK_PAD_M)

    def centre_at(self,cell,t):
        wx,wy=cell['wind']
        orbit_x,orbit_y=CELL_ORBIT_M
        period_x,period_y=CELL_ORBIT_PERIOD_MIN
        phase=cell['phase']
        return (cell['xy'][0]+wx*t*60+orbit_x*math.sin(t/period_x+phase),
                cell['xy'][1]+wy*t*60+orbit_y*math.cos(t/period_y+phase))

    def radius_at(self,cell,t):
        life=cell.get('lifeMinutes')
        if life is None:
            return cell['radius']
        birth=cell['birth']
        age=t-birth
        if age<0 or age>life:
            return 0.0
        progress=age/life
        peak=CELL_PEAK_AGE_FRACTION
        shape=1-((progress-peak)/max(peak,1e-9))**2 if progress<=peak \
            else 1-((progress-peak)/max(1-peak,1e-9))**2
        shape=max(shape,0.0)
        return cell['radius']*(CELL_MIN_SIZE_FRACTION+(1-CELL_MIN_SIZE_FRACTION)*shape)

    def is_alive(self,cell,t):
        if cell.get('lifeMinutes') is None:
            return True
        return self.radius_at(cell,t)>=MIN_VISIBLE_RADIUS_M

    def drift(self,cell,t):
        x0,y0=self.centre_at(cell,0)
        x,y=self.centre_at(cell,t)
        return x-x0,y-y0

    def shapes(self,t):
        if self.scenario in ('clear','unknown'): return []
        result=[]
        for cell in self.cells:
            if cell['shape']=='BAND':
                dx,dy=self.drift(cell,t)
                live=[]
                for cluster in cell.get('clusters',()):
                    outline,core=_band_cluster_outlines(cluster,t)
                    if outline is None:
                        continue
                    live.append((affinity.translate(outline,xoff=dx,yoff=dy),
                                 affinity.translate(core,xoff=dx,yoff=dy)))
                if not live:
                    continue
                outlines=[outline for outline,_core in live]
                cores=[core for _outline,core in live]
                field=unary_union(outlines)
                ban=unary_union(cores)
                result.append((cell,field,ban,field.difference(ban)))
                continue
            radius=self.radius_at(cell,t)
            if radius<MIN_VISIBLE_RADIUS_M:
                continue
            x,y=self.centre_at(cell,t)
            field=_irregular_outline(x,y,radius,cell['outline'])
            ban=_core_outline(x,y,cell)
            caution=_caution_ring(x,y,cell)
            cell_tolerance=radius*0.01
            ban=_simplify_keeping_detail(ban,cell_tolerance)
            caution=_simplify_keeping_detail(caution,cell_tolerance)
            result.append((cell,field,ban,caution))
        return result

    def swept(self,start_bin,end_bin):
        return self._swept_window(int(start_bin), int(end_bin))

    @lru_cache(maxsize=2048)
    def _swept_window(self,start_bin,end_bin):
        if self.scenario in ('clear','unknown'): return GeometryCollection()
        shapes=[]
        for index,cell in enumerate(self.cells):
            if cell['shape']=='BAND':
                shapes.append(self._swept_band(index,start_bin,end_bin))
                continue
            if not any(self.is_alive(cell,tick*5)
                       for tick in range(start_bin,end_bin+1)):
                continue
            centres=[self.centre_at(cell,tick*5) for tick in range(start_bin,end_bin+1)]
            track=LineString(centres) if len(centres)>1 else Point(centres[0])
            shapes.append(track.buffer(cell['sweptPad']*CELL_ENVELOPE_GROWTH_MARGIN,quad_segs=8))
        return unary_union(shapes)

    def _swept_band(self,cell_index,start_bin,end_bin):
        return self._band_hull(int(cell_index),int(start_bin),int(end_bin))

    def _band_hull(self,cell_index,start_bin,end_bin):
        cell=self.cells[cell_index]
        ticks=list(range(start_bin,end_bin+1))
        offsets=[self.drift(cell,tick*5) for tick in ticks]
        offsets.append((0.0,0.0))
        drift_hull=MultiPoint(offsets).convex_hull
        cluster_coords=[]
        for cluster in cell.get('clusters',()):
            for tick in ticks:
                cluster_coords.extend(_band_cluster_hull_coords(cluster,tick*5))
        if not cluster_coords:
            return GeometryCollection()
        ca=_hull_ring_coords(MultiPoint(cluster_coords).convex_hull)
        cb=_hull_ring_coords(drift_hull)
        if not ca or not cb:
            return GeometryCollection()
        points=[(ax+bx,ay+by) for ax,ay in ca for bx,by in cb]
        return MultiPoint(points).convex_hull.buffer(SWEPT_BAND_PAD_M,quad_segs=4)

    def envelope(self,start,end):
        return self._swept_window(math.floor(start/5), math.ceil(end/5))

    def frame(self,t):
        shapes=[(cell,field.intersection(boundary()),ban.intersection(boundary()),caution.intersection(boundary()))
                for cell,field,ban,caution in self.shapes(t)]
        return [dict(**_region_identity(members),
                     field=mapping(field),ban=_mapping_tier(ban),caution=_mapping_tier(caution))
                for members,field,ban,caution in _dissolve_regions(shapes)]

def _first_visibility(observation):
    direct=observation.get('visibilityM')
    if direct is not None:
        return direct
    hourly=observation.get('hourly') or {}
    return next((value for value in (hourly.get('visibility') or []) if value is not None),None)

def _extreme_kind(observation):
    condition=observation.get('conditionClass')
    if condition in ('THUNDERSTORM','HEAVY_RAIN'):
        return condition
    gust=observation.get('windGusts10mMps')
    if gust is not None and gust>=EXTREME_WIND_GUST_MPS:
        return 'EXTREME_WIND'
    visibility=_first_visibility(observation)
    if visibility is not None and visibility<EXTREME_VISIBILITY_M:
        return 'LOW_VISIBILITY'
    precipitation=observation.get('precipitationMm')
    if precipitation is not None and precipitation>=EXTREME_HOURLY_RAIN_MM:
        return 'HEAVY_RAIN'
    return None

def point_risk_shapes(snapshot, city_rows):
    if not snapshot.get('available'):
        return []
    city_lookup={city['id']:city for city in city_rows}
    result=[]
    for observation in snapshot.get('observations',[]):
        city=city_lookup.get(observation['cityId'])
        if not city:
            continue
        kind=_extreme_kind(observation)
        if kind is None:
            continue
        if kind=='LOW_VISIBILITY':
            continue
        core=Point(city['xy']).buffer(EXTREME_CORE_RADIUS_M,quad_segs=16)
        core=core.simplify(SIMPLIFY_TOLERANCE,preserve_topology=True)
        result.append((
            {'id': f"LIVE-{observation['cityId']}", 'city': observation['cityId'], 'kind': kind,
             'extreme': True,
             'derivedFrom': {'gustMps': observation.get('windGusts10mMps'),
                             'precipitationMm': observation.get('precipitationMm'),
                             'visibilityM': _first_visibility(observation),
                             'weatherCode': observation.get('weatherCode')}},
            core, core, GeometryCollection(),
        ))
    return result

class PublicWeather:
    def __init__(self, snapshot, city_rows):
        self.snapshot = snapshot
        self.city_lookup = {city['id']: city for city in city_rows}

    def shapes(self, _minute):
        return self._risk_shapes()

    def _risk_shapes(self):
        cached = getattr(self, '_risk_shapes_cache', None)
        if cached is None:
            cached = point_risk_shapes(self.snapshot, self.city_lookup.values())
            self._risk_shapes_cache = cached
        return cached

    def envelope(self, start, end):
        if not self.snapshot.get('available'):
            return GeometryCollection()
        cached = getattr(self, '_envelope_cache', None)
        if cached is None:
            bans=[ban for _cell, _field, ban, _caution in self._risk_shapes()
                  if ban is not None and not ban.is_empty]
            cached = unary_union(bans) if bans else GeometryCollection()
            self._envelope_cache = cached
        return cached

    def frame(self, minute):
        source = f"{self.snapshot.get('provider') or 'UNKNOWN'}_DERIVED_RISK"
        shapes=[(cell,field.intersection(boundary()),ban.intersection(boundary()),caution.intersection(boundary()))
                for cell,field,ban,caution in self.shapes(minute)]
        records=[]
        for members,field,ban,caution in _dissolve_regions(shapes):
            ordered=sorted(members,key=lambda cell:cell['id'])
            records.append(dict(
                **_region_identity(members),
                derivedFrom=ordered[0]['derivedFrom'] if len(ordered)==1
                            else [cell['derivedFrom'] for cell in ordered],
                source=source,
                field=mapping(field),ban=_mapping_tier(ban),caution=_mapping_tier(caution)))
        return records

class LiveWeatherEnvelope:

    def __init__(self, snapshot, city_rows):
        self.snapshot = snapshot or {}
        self.city_lookup = {city['id']: city for city in city_rows}

    @property
    def available(self):
        return bool(self.snapshot.get('available'))

    def shapes(self, _minute):
        return self._risk_shapes()

    def _risk_shapes(self):
        cached = getattr(self, '_risk_shapes_cache', None)
        if cached is None:
            cached = point_risk_shapes(self.snapshot, self.city_lookup.values())
            self._risk_shapes_cache = cached
        return cached

    def envelope(self, start, end):
        if not self.available:
            return GeometryCollection()
        cached = getattr(self, '_envelope_cache', None)
        if cached is None:
            bans=[ban for _cell, _field, ban, _caution in self._risk_shapes()
                  if ban is not None and not ban.is_empty]
            cached = unary_union(bans) if bans else GeometryCollection()
            self._envelope_cache = cached
        return cached
