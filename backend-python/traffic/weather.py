"""Seeded advecting synthetic cells over the entire city network."""
import math
import random
from functools import lru_cache
from shapely.geometry import Polygon, GeometryCollection, LineString, Point, mapping
from shapely.ops import unary_union
from weather.geometry import boundary, geojson
from .catalog import cities, connections


class NetworkWeather:
    def __init__(self,seed,scenario):
        self.seed,self.scenario=seed,scenario
        rng=random.Random(seed)
        self.cells=[]
        lookup={c['id']:c for c in cities()}
        links=rng.sample(connections(),8)
        for index,city in enumerate(rng.sample(cities(),12)):
            if index<8:
                a,b=(lookup[key]['xy'] for key in links[index])
                centre=[(a[k]+b[k])/2 for k in range(2)]
            else:
                centre=[city['xy'][0]+18000,city['xy'][1]-12000]
            self.cells.append(dict(id=f"WX-{city['id']}",city=city['id'],xy=centre,
                                  phase=rng.uniform(0,2*math.pi),radius=rng.uniform(5000,11000),
                                  kind=rng.choice(['RAIN','STORM','WIND'])))

    def shapes(self,t):
        if self.scenario in ('clear','unknown'): return []
        result=[]
        for cell in self.cells:
            phase=cell['phase']; radius=cell['radius']
            # Speed bounded by 6.7 m/s; no discontinuous jump when the timeline moves.
            x=cell['xy'][0]+12000*math.sin(t/70+phase)
            y=cell['xy'][1]+9000*math.cos(t/90+phase)
            ring=[(x+radius*(1+.18*math.sin(i*3+phase))*math.cos(i*math.tau/24),
                   y+radius*(1+.18*math.sin(i*3+phase))*math.sin(i*math.tau/24)) for i in range(24)]
            field=Polygon(ring)
            ban=Polygon([(x+(px-x)*.58+400,y+(py-y)*.58+250) for px,py in ring]).buffer(300)
            caution=field.buffer(900).difference(ban)
            result.append((cell,field,ban,caution))
        return result

    @lru_cache(maxsize=128)
    def swept(self,start_bin,end_bin):
        # Every point in an interval is within 150 seconds of a sample; 1200 m
        # bounds translation (<=6.7 m/s). Shape is fixed; both risk levels excluded.
        if self.scenario in ('clear','unknown'): return GeometryCollection()
        shapes=[]
        for cell in self.cells:
            phase=cell['phase']; x,y=cell['xy']
            centres=[(x+12000*math.sin(tick*5/70+phase),y+9000*math.cos(tick*5/90+phase))
                     for tick in range(start_bin,end_bin+1)]
            track=LineString(centres) if len(centres)>1 else Point(centres[0])
            # Circumscribed field radius + risk buffer + motion/interpolation and
            # polygon chord allowance. Conservative but much cheaper than 100s of unions.
            shapes.append(track.buffer(cell['radius']*1.18+2200,quad_segs=8))
        return unary_union(shapes)

    def envelope(self,start,end):
        return self.swept(math.floor(start/5),math.ceil(end/5))

    def frame(self,t):
        return [dict(id=c['id'],kind=c['kind'],cityId=c['city'],
                     field=mapping(field.intersection(boundary())),
                     ban=mapping(ban.intersection(boundary())),
                     caution=mapping(caution.intersection(boundary())))
                for c,field,ban,caution in self.shapes(t)]
