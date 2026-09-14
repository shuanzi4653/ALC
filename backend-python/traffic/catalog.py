"""Prefecture coverage and approximate city centres, not certified landing sites."""
from functools import lru_cache
from math import hypot
from shapely.geometry import Point
from shapely.ops import nearest_points
from weather.geometry import boundary, project, unproject

ROWS = {
    '辽宁省': [('沈阳',123.43,41.80),('大连',121.61,38.91),('鞍山',122.99,41.11),('抚顺',123.96,41.88),('本溪',123.77,41.30),('丹东',124.35,40.00),('锦州',121.13,41.10),('营口',122.24,40.67),('阜新',121.67,42.02),('辽阳',123.17,41.27),('盘锦',122.07,41.12),('铁岭',123.84,42.29),('朝阳',120.45,41.57),('葫芦岛',120.84,40.71)],
    '吉林省': [('长春',125.32,43.82),('吉林',126.55,43.84),('四平',124.35,43.17),('辽源',125.14,42.89),('通化',125.94,41.73),('白山',126.42,41.94),('松原',124.82,45.14),('白城',122.84,45.62),('延边州',129.51,42.90)],
    '黑龙江省': [('哈尔滨',126.64,45.76),('齐齐哈尔',123.95,47.34),('鸡西',130.97,45.30),('鹤岗',130.30,47.35),('双鸭山',131.16,46.65),('大庆',125.10,46.59),('伊春',128.84,47.73),('佳木斯',130.36,46.80),('七台河',131.00,45.77),('牡丹江',129.63,44.55),('黑河',127.50,50.25),('绥化',126.97,46.64),('大兴安岭地区',124.71,52.34)],
}


@lru_cache(maxsize=1)
def cities():
    result=[]
    for pidx,(province,rows) in enumerate(ROWS.items()):
        allowed=boundary(province).buffer(-500)
        for idx,(name,lon,lat) in enumerate(rows):
            p=Point(project([lon,lat]))
            if not allowed.covers(p):
                p=nearest_points(allowed,p)[0]
            result.append(dict(id=f'{pidx+1}-{idx+1:02}',name=name,province=province,
                               capital=idx==0,coordinate=unproject(p.coords[0]),xy=list(p.coords[0])))
    return result


@lru_cache(maxsize=1)
def connections():
    """Two nearest neighbours plus a minimum spanning tree in each province."""
    result=set()
    for province in ROWS:
        group=[c for c in cities() if c['province']==province]
        pairs=sorted((hypot(a['xy'][0]-b['xy'][0],a['xy'][1]-b['xy'][1]),a['id'],b['id'])
                     for i,a in enumerate(group) for b in group[i+1:])
        components={c['id']:{c['id']} for c in group}
        for _,a,b in pairs:
            if b not in components[a]:
                merged=components[a]|components[b]
                result.add(tuple(sorted((a,b))))
                for key in merged: components[key]=merged
        for c in group:
            near=[(d,a,b) for d,a,b in pairs if c['id'] in (a,b)][:2]
            result.update(tuple(sorted((a,b))) for _,a,b in near)
    result.update([('1-01','2-01'),('2-01','3-01')])
    return sorted(result)
