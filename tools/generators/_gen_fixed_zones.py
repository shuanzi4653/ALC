"""Generate ``backend-python/data/traffic/fixed-zones.json``.

The catalogue of fixed, non-weather airspace restrictions for the Northeast
network. Two rules govern what may be written here:

1. A geometry is only emitted when a *published rule* fixes its shape (a
   statutory radius, a standard protection radius, or a published rectangle).
   Where the concrete extent is not published, the site is registered with its
   name, clause and verified public coordinate, and ``geometry`` stays ``null``
   so nothing fabricated reaches the map.
2. Every reference coordinate is copied programmatically from a public dataset
   that is cached under ``.run/zones_recon`` — never typed by hand — so the
   catalogue can be regenerated and audited.

Inputs (all fetched once, cached under .run/zones_recon):
  * OurAirports public-domain ``airports.csv`` and ``runways.csv``.
  * OpenStreetMap via Overpass (runways, reservoirs, harbours, museums, nuclear).

Run:  backend-python\\.venv\\Scripts\\python.exe _gen_fixed_zones.py
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import csv
import io
import json
from datetime import date
CACHE = ROOT / '.run' / 'zones_recon'
OUTPUT = ROOT / 'backend-python' / 'data' / 'traffic' / 'fixed-zones.json'
RETRIEVED = '2026-09-16'

# ---------------------------------------------------------------------------
# Chinese facility names. OurAirports only carries English names, so the display
# name is an explicit project cross-reference rather than a machine translation.
# ---------------------------------------------------------------------------
AIRPORT_NAMES = {
    'ZYAS': '鞍山腾鳌机场', 'ZYBA': '白城长安机场', 'ZYBS': '长白山机场',
    'ZYCC': '长春龙嘉国际机场', 'ZYCY': '朝阳机场', 'ZYDD': '丹东浪头机场',
    'ZYDU': '五大连池德都机场', 'ZYFY': '抚远东极机场', 'ZYHB': '哈尔滨太平国际机场',
    'ZYHE': '黑河爱辉机场', 'ZYJM': '佳木斯东郊机场', 'ZYJS': '建三江湿地机场',
    'ZYJX': '鸡西兴凯湖机场', 'ZYJZ': '锦州湾机场', 'ZYLD': '伊春林都机场',
    'ZYMD': '牡丹江海浪机场', 'ZYMH': '漠河古莲机场', 'ZYQQ': '齐齐哈尔三家子机场',
    'ZYSQ': '松原查干湖机场', 'ZYTL': '大连周水子国际机场', 'ZYTN': '通化三源浦机场',
    'ZYTX': '沈阳桃仙国际机场', 'ZYYJ': '延吉朝阳川机场', 'ZYYK': '营口兰旗机场',
}

# ---------------------------------------------------------------------------
# Statutory / standard radii, each with the instrument it comes from.
# ---------------------------------------------------------------------------
AIRPORT_PROTECTION_RADIUS_M = 55000
AIRPORT_PROTECTION_RULE = (
    '运输机场净空保护区域：以机场基准点为圆心、水平半径 55 公里的空间区域。'
    '见《运输机场净空保护管理办法》及各地《机场净空保护管理规定》净空保护相关用语说明第 1 条。')
AIRPORT_PROTECTION_CITATION = '《运输机场净空保护管理办法》《民用机场管理条例》第四十九条'

AIRPORT_INSPECTION_RULE = (
    '净空巡视检查区域：机场跑道中心线两侧各 10 公里、跑道端外 20 公里以内的区域'
    '（机场障碍物限制面区域加上适当的面外区域）。见各地《机场净空保护管理规定》'
    '净空保护相关用语说明第 2 条。')
AIRPORT_INSPECTION_CITATION = '各地《机场净空保护管理规定》净空保护相关用语说明第 2 条'

NUCLEAR_RULE = (
    '非居住区边界与反应堆的距离不得小于 500 m；规划限制区外边界与反应堆的距离不得小于 5 km。'
    '按下限生成最小包络，实际边界由省级人民政府确认，可能更大。')
NUCLEAR_CITATION = 'GB 6249—2025《核动力厂环境辐射防护规定》第 5.6 条'

RADAR_RULE = (
    '天气雷达站探测环境保护区由一级保护区和二级保护区构成；二级保护区为一级保护区外沿'
    '至距离雷达 20 km 的环形区域。')
RADAR_CITATION = 'GB 31223—2014《气象探测环境保护规范 天气雷达站》第 4.2、4.3 条'
# Why the 20 km weather-radar protection area is *not* turned into a flight
# restriction even though its radius is published. GB 31223 protects the radar's
# *measurement* environment against obstacles and interference sources; the
# airspace around such a facility is designated separately by the air traffic
# management authority under 第十九条, and that extent is published per city
# rather than nationally. Drawing the meteorological protection ring as controlled
# airspace would merge two different legal regimes — and a 20 km circle around a
# radar sited 5.5 km from its city would then declare the entire city controlled.
# The same reasoning does not block the 500 m navaid circle: that one is the
# radio-frequency *active* protection zone, i.e. the volume in which operating a
# transmitter is itself the regulated act.
RADAR_REGISTER_NOTE = (
    '本系统按已公开名称与运营单位认定该设施为天气雷达站，登记其已核验位置，'
    '但不把 GB 31223—2014 的探测环境保护区当作飞行管制空域几何：该标准保护的是'
    '雷达探测环境，周边管制空域范围由空中交通管理机构依《无人驾驶航空器飞行管理暂行条例》'
    '第十九条另行确定并按城市公布。')
RADAR_REVIEW_ACTION = (
    '待该雷达站周边管制空域范围由设区的市级以上人民政府公布后补全几何；'
    '在此之前，本系统不以 GB 31223 的保护半径推算禁飞范围。')

NAVAID_RULE = (
    '无方向信标台（NDB）与多普勒全向信标台／常规测距仪台（DVOR/DME）以天线中心为基准，'
    '半径 500 米的圆形区域为有源保护区，针对有源干扰进行保护；半径 5 千米范围为限制保护区，'
    '该区域内限制障碍物高度。此处只按有源保护区生成禁止进入区，限制保护区属障碍物高度管控，'
    '不是飞行禁区，故不生成几何。')
NAVAID_CITATION = ('GB 6364—2013《航空无线电导航台站电磁环境要求》，'
                   'MH/T 4003.1—2014《民用航空通信导航监视台（站）设置场地规范 第 1 部分：导航》；'
                   '半径取值见《湖南省民用机场及民用航空无线电台（站）电磁环境保护区管理规定》第十一条')

NAVAID_PROTECTION_RADIUS_M = 500
# Several OSM nodes within a few hundred metres are one physical facility mapped
# element by element, so they are merged before a protection circle is drawn.
NAVAID_CLUSTER_M = 600

CLAUSE_SECTORS = {
    'AIRPORT': ('CIVIL_AVIATION', '民航'),
    'BORDER': ('DEFENCE', '国防'),
    'CLASSIFIED_UNIT': ('CLASSIFIED', '机密'),
    'DEFENCE_INDUSTRY': ('DEFENCE', '国防'),
    'INFRASTRUCTURE': ('GOVERNMENT', '政务'),
    'ELECTROMAGNETIC': ('RESEARCH', '科研'),
    'HERITAGE': ('GOVERNMENT', '政务'),
    'OTHER': ('GOVERNMENT', '政务'),
}

CLAUSES = [
    {'key': 'AIRPORT', 'clause': '第十九条第（一）项', 'title': '机场以及周边一定范围的区域',
     'geometryStatus': 'PARTIALLY_PUBLISHED',
     'geometryRule': AIRPORT_PROTECTION_RULE + ' ' + AIRPORT_INSPECTION_RULE,
     'citation': AIRPORT_PROTECTION_CITATION + '；' + AIRPORT_INSPECTION_CITATION,
     'authority': '民用航空管理部门 / 空中交通管理机构'},
    {'key': 'BORDER', 'clause': '第十九条第（二）项', 'title': '国界线、实际控制线、边境线向我方一侧一定范围的区域',
     'geometryStatus': 'PERIMETER_NOT_PUBLICLY_PUBLISHED',
     'geometryRule': None,
     'citation': '范围由各级空中交通管理机构确定，由设区的市级以上人民政府公布',
     'authority': '空中交通管理机构 / 边境管理部门',
     'reviewAction': '本系统不自行测绘边境带宽度。需按设区的市级以上人民政府公布的范围补全；'
                     '在此之前，边境城市航线的合规性只能标注为待核。'},
    {'key': 'CLASSIFIED_UNIT', 'clause': '第十九条第（三）项', 'title': '军事禁区、军事管理区、监管场所等涉密单位以及周边一定范围的区域',
     'geometryStatus': 'PERIMETER_NOT_PUBLICLY_PUBLISHED',
     'geometryRule': None,
     'citation': '范围由各级空中交通管理机构确定，由设区的市级以上人民政府公布',
     'authority': '空中交通管理机构 / 有关涉密单位',
     'reviewAction': '涉密单位与监管场所边界依法不公开，本系统不生成、不推测任何几何，'
                     '也不以任何形式声称已避开该类区域。'},
    {'key': 'DEFENCE_INDUSTRY', 'clause': '第十九条第（四）项', 'title': '重要军工设施保护区域、核设施控制区域、易燃易爆等危险品的生产和仓储区域，以及可燃重要物资的大型仓储区域',
     'geometryStatus': 'PARTIALLY_PUBLISHED',
     'geometryRule': '核设施按 GB 6249—2025 非居住区与规划限制区下限建最小包络；'
                     '重要军工设施保护区域无公开范围。',
     'citation': NUCLEAR_CITATION,
     'authority': '空中交通管理机构 / 生态环境主管部门 / 有关涉密单位',
     'reviewAction': '重要军工设施与危险品仓储的边界不公开，仅登记类别，不生成几何。'},
    {'key': 'INFRASTRUCTURE', 'clause': '第十九条第（五）项', 'title': '发电厂、变电站、加油（气）站、供水厂、公共交通枢纽、航电枢纽、重大水利设施、港口、高速公路、铁路电气化线路等公共基础设施以及周边一定范围的区域和饮用水水源保护区',
     'geometryStatus': 'AREA_EXTENT_REQUIRES_LOCAL_PUBLICATION',
     'geometryRule': None,
     'citation': '饮用水水源保护区范围由省级人民政府批复公布；其余设施周边范围由各级空中交通管理机构确定',
     'authority': '空中交通管理机构 / 地方人民政府',
     'reviewAction': '本系统登记已公开定位的设施参考点，但不自行给设施套用统一缓冲半径：'
                     '该类设施"周边一定范围"没有全国统一定量标准，需要逐项按地方公布范围补全。'},
    {'key': 'ELECTROMAGNETIC', 'clause': '第十九条第（六）项', 'title': '射电天文台、卫星测控（导航）站、航空无线电导航台、雷达站等需要电磁环境特殊保护的设施以及周边一定范围的区域',
     'geometryStatus': 'PARTIALLY_PUBLISHED',
     'geometryRule': NAVAID_RULE + ' ' + RADAR_RULE + ' 但天气雷达站的探测环境保护区不是飞行管制空域，'
                                  '本系统仅登记设施位置，不据此生成几何。'
                                  '射电天文台电磁波宁静区仅贵州省有公开地方立法（半径 30 km），'
                                  '东北三省未见公开定量范围。',
     'citation': NAVAID_CITATION + '；' + RADAR_CITATION
                 + '；《贵州省500米口径球面射电望远镜电磁波宁静区保护办法》',
     'authority': '气象主管机构 / 无线电管理机构 / 空中交通管理机构',
     'reviewAction': RADAR_REVIEW_ACTION},
    {'key': 'HERITAGE', 'clause': '第十九条第（七）项', 'title': '重要革命纪念地、重要不可移动文物以及周边一定范围的区域',
     'geometryStatus': 'AREA_EXTENT_REQUIRES_LOCAL_PUBLICATION',
     'geometryRule': None,
     'citation': '范围由各级空中交通管理机构确定，由设区的市级以上人民政府公布',
     'authority': '空中交通管理机构 / 文物主管部门',
     'reviewAction': '本系统登记已公开定位的纪念地与不可移动文物参考点，不自行套用缓冲半径。'},
    {'key': 'OTHER', 'clause': '第十九条第（八）项', 'title': '国家空中交通管理领导机构规定的其他区域',
     'geometryStatus': 'PERIMETER_NOT_PUBLICLY_PUBLISHED',
     'geometryRule': None,
     'citation': '由国家空中交通管理领导机构规定',
     'authority': '国家空中交通管理领导机构',
     'reviewAction': '无法预先枚举，随国家规定与临时公告更新。'},
]


def load(name):
    return json.loads((CACHE / name).read_text(encoding='utf-8'))


def locate(rows, name, extra=None):
    """Fetch one OSM feature by exact name, failing loudly when absent."""
    matches = [row for row in rows if row.get('name') == name]
    if extra:
        matches = [row for row in matches if extra(row)]
    if not matches:
        raise SystemExit(f'未在公开数据中找到设施：{name}')
    matches.sort(key=lambda row: row['osm'])
    return matches[0]


def site(key, name, clause, geometry, **kwargs):
    sector, sector_label = CLAUSE_SECTORS[clause]
    record = {
        'id': f'FZ-{key}',
        'name': name,
        'clause': clause,
        'sector': sector,
        'sectorLabel': sector_label,
        'geometry': geometry,
    }
    record.update(kwargs)
    return record


def build_airports():
    airports = [row for row in load('candidates.json')['airports'] if row['scheduled'] == 'yes']
    bearings = load('runway_bearings.json')
    lengths = {}
    for row in csv.DictReader(io.StringIO((CACHE / 'runways.csv').read_text(encoding='utf-8', errors='replace'))):
        ident = row.get('airport_ident')
        try:
            length = float(row.get('length_ft') or 0)
        except ValueError:
            continue
        if ident not in lengths or length > lengths[ident]:
            lengths[ident] = length
    sites = []
    for airport in sorted(airports, key=lambda row: row['icao']):
        icao = airport['icao']
        chinese = AIRPORT_NAMES.get(icao)
        if not chinese:
            raise SystemExit(f'缺少 {icao} 的中文名对照，拒绝生成')
        bearing = bearings.get(icao)
        if bearing is None:
            raise SystemExit(f'缺少 {icao} 的跑道方位，拒绝生成')
        centre = [round(airport['lon'], 5), round(airport['lat'], 5)]
        runway_length_m = round(lengths.get(icao, 0) * 0.3048)
        common = dict(
            facilityType='CIVIL_TRANSPORT_AIRPORT',
            authority='民用航空管理部门 / 空中交通管理机构',
            publication='由设区的市级以上人民政府公布，民用航空管理部门发布航行情报',
            provenance={
                'referencePoint': f"OurAirports airports.csv（ICAO {icao}，公共领域数据集）",
                'runwayGeometry': f"OpenStreetMap 跑道几何（{'、'.join(k for k in [icao])}）",
                'name': '项目人工中英文对照',
                'retrievedAt': RETRIEVED,
            },
        )
        sites.append(site(
            f'AP-{icao}-P', f'{chinese}净空保护区域', 'AIRPORT',
            {'kind': 'CIRCLE', 'centre': centre, 'radiusM': AIRPORT_PROTECTION_RADIUS_M},
            enforcement='APPROVAL_REQUIRED', floorAglM=120, ceilingAglM=None,
            geometryStatus='PUBLISHED_STANDARD', geometryRule=AIRPORT_PROTECTION_RULE,
            citation=AIRPORT_PROTECTION_CITATION,
            note='真高 120 米以上属于管制空域；本系统按下限标注垂直范围，'
                 '低于 120 米仍受《民用机场管理条例》第四十九条关于净空保护区域的限制。',
            **common,
        ))
        sites.append(site(
            f'AP-{icao}-I', f'{chinese}净空巡视检查区域', 'AIRPORT',
            {'kind': 'RUNWAY_RECT', 'centre': centre, 'bearingDeg': bearing,
             'runwayLengthM': runway_length_m, 'halfWidthM': 10000, 'beyondEndM': 20000},
            enforcement='APPROVAL_REQUIRED', strictEnforcement='PROHIBITED',
            floorAglM=0, ceilingAglM=None,
            geometryStatus='PUBLISHED_STANDARD', geometryRule=AIRPORT_INSPECTION_RULE,
            citation=AIRPORT_INSPECTION_CITATION,
            note='跑道方位取自 OpenStreetMap 跑道几何（真实方位角），'
                 '矩形按公布的两侧各 10 公里、端外 20 公里生成。',
            **common,
        ))
    return sites


def build_nuclear():
    rows = load('candidates.json')['facilities']
    plants = [row for row in rows if (row.get('tags') or {}).get('plant:source') == 'nuclear']
    wanted = {'红沿河核电站': '红沿河核电站', '徐大堡核电站': '徐大堡核电站'}
    sites = []
    for name, chinese in wanted.items():
        row = locate(plants, name)
        sites.append(site(
            f'NUC-{row["osm"].split("/")[1]}', f'{chinese}控制区域（最小包络）', 'DEFENCE_INDUSTRY',
            {'kind': 'CIRCLE', 'centre': [row['lon'], row['lat']],
             'radiusM': 5000, 'radiusRole': 'STATUTORY_MINIMUM'},
            enforcement='PROHIBITED', floorAglM=0, ceilingAglM=None,
            geometryStatus='STATUTORY_MINIMUM_RADIUS', geometryRule=NUCLEAR_RULE,
            citation=NUCLEAR_CITATION,
            facilityType='NUCLEAR_POWER_PLANT',
            authority='生态环境主管部门 / 空中交通管理机构',
            publication='非居住区与规划限制区边界由省级人民政府确认',
            note='核设施控制区域的实际范围由空中交通管理机构确定并公布；'
                 '此处按国家标准下限生成最小包络，属于保守下界，真实范围可能更大。',
            provenance={'referencePoint': f'OpenStreetMap {row["osm"]}', 'retrievedAt': RETRIEVED},
        ))
    return sites


def build_navigation_aids():
    """Clause (六) 航空无线电导航台.

    OSM tags these ``aeroway=navigationaid`` but does not say whether each one is
    an NDB or a DVOR/DME. Both carry the same published active-protection radius
    (500 m), so the geometry is unambiguous even when the subtype is not — which
    is the only reason a circle can be drawn here at all.

    Several nodes within a few hundred metres are one physical facility mapped
    element by element, so they are merged first. Clustering runs in projected
    metres throughout: an earlier version averaged longitude/latitude degrees and
    then compared them against metres, which silently stopped merging.
    """
    import math

    sys.path.insert(0, str(ROOT / 'backend-python'))
    from shapely.geometry import Point as ShapelyPoint
    from weather.geometry import boundary, project
    from traffic.catalog import cities

    located = []
    for element in load('navigationaid.json')['elements']:
        lat, lon = element.get('lat'), element.get('lon')
        if lat is None or lon is None:
            continue
        xy = project((lon, lat))
        if not boundary().covers(ShapelyPoint(xy)):
            continue
        located.append({'xy': list(xy), 'coordinate': [lon, lat], 'osm': f"node/{element['id']}"})

    clusters = []
    for row in sorted(located, key=lambda item: item['osm']):
        for cluster in clusters:
            centre = [sum(member['xy'][0] for member in cluster) / len(cluster),
                      sum(member['xy'][1] for member in cluster) / len(cluster)]
            if math.dist(centre, row['xy']) <= NAVAID_CLUSTER_M:
                cluster.append(row)
                break
        else:
            clusters.append([row])

    sites = []
    for index, cluster in enumerate(sorted(clusters, key=lambda group: group[0]['osm']), start=1):
        centre = [sum(member['xy'][0] for member in cluster) / len(cluster),
                  sum(member['xy'][1] for member in cluster) / len(cluster)]
        coordinate = [sum(member['coordinate'][0] for member in cluster) / len(cluster),
                      sum(member['coordinate'][1] for member in cluster) / len(cluster)]
        nearest = min(cities(), key=lambda city: math.dist(city['xy'], centre))
        distance_km = math.dist(nearest['xy'], centre) / 1000
        osm = '、'.join(member['osm'] for member in cluster)
        sites.append(site(
            f'NAV-{nearest["id"]}-{index:02}', f'{nearest["name"]}航空无线电导航台电磁环境有源保护区',
            'ELECTROMAGNETIC',
            {'kind': 'CIRCLE', 'centre': [round(coordinate[0], 5), round(coordinate[1], 5)],
             'radiusM': NAVAID_PROTECTION_RADIUS_M},
            enforcement='PROHIBITED', floorAglM=0, ceilingAglM=None,
            geometryStatus='PUBLISHED_STANDARD', geometryRule=NAVAID_RULE, citation=NAVAID_CITATION,
            facilityType='AERONAUTICAL_RADIO_NAVIGATION_AID',
            authority='无线电管理机构 / 民用航空管理部门',
            publication='由无线电管理机构与民用航空管理部门按国家规定确定',
            note=f'距{nearest["name"]}城区约 {distance_km:.1f} km；公开数据未区分 NDB 与 DVOR/DME，'
                 f'两者有源保护区半径同为 500 米。',
            provenance={'referencePoint': f'OpenStreetMap {osm}', 'retrievedAt': RETRIEVED,
                        'clusteredNodes': len(cluster)},
        ))
    return sites


def build_registered():
    """Sites with a verified public position but no publicly quantified extent.

    No geometry is generated for these: the extent of the restriction is
    published per city as aeronautical information, so inventing a buffer would
    put unverified boundary data on the map.
    """
    rows = load('candidates.json')['facilities']
    wanted = [
        ('HERITAGE', '九·一八历史博物馆', '重要革命纪念地'),
        ('HERITAGE', '侵华日军第七三一部队罪证陈列馆', '重要革命纪念地'),
        ('HERITAGE', '辽沈战役纪念馆', '重要革命纪念地'),
        ('HERITAGE', '抗美援朝纪念馆', '重要革命纪念地'),
        ('HERITAGE', '四平战役纪念馆', '重要革命纪念地'),
        ('HERITAGE', '旅顺日俄监狱旧址博物馆', '重要不可移动文物'),
        ('HERITAGE', '平顶山惨案史实陈列馆', '重要革命纪念地'),
        ('HERITAGE', '东北沦陷史陈列馆', '重要不可移动文物'),
    ]
    sites = []
    for clause, name, kind in wanted:
        row = locate(rows, name)
        site_id = 'REG-' + row['osm'].replace('/', '-').upper()
        sites.append(site(
            site_id, name, clause, None,
            facilityType=kind,
            geometryStatus='AREA_EXTENT_REQUIRES_LOCAL_PUBLICATION',
            enforcement='REGISTERED_REVIEW_REQUIRED',
            referencePoint={'coordinate': [row['lon'], row['lat']], 'source': f'OpenStreetMap {row["osm"]}'},
            authority='空中交通管理机构 / 文物主管部门',
            publication='由设区的市级以上人民政府公布，民用航空管理部门发布航行情报',
            note='"周边一定范围"没有全国统一定量标准，本系统只登记已公开定位，'
                 '待地方公布范围后再生成几何。',
            provenance={'referencePoint': f'OpenStreetMap {row["osm"]}', 'retrievedAt': RETRIEVED},
        ))
    return sites


def build_electromagnetic_registered():
    """Clause (六) 天气雷达站: located publicly, but no flight geometry.

    OSM carries exactly one explicitly named meteorological radar in the three
    provinces — ``绥化气象雷达``, operator ``绥化市气象局``. Its position is a
    verified public fact, so the facility belongs in the catalogue; its *airspace*
    extent does not, for the reason recorded in ``RADAR_REGISTER_NOTE``. Matching
    is done on the name and requires an operator tag, so a plain weather
    observation station can never be promoted to a radar by accident.
    """
    matches = []
    for element in load('weather_station.json')['elements']:
        tags = element.get('tags') or {}
        name = (tags.get('name') or '').strip()
        operator = (tags.get('operator') or '').strip()
        if '雷达' not in name or not operator:
            continue
        coordinate = element.get('center') or {'lat': element.get('lat'), 'lon': element.get('lon')}
        if coordinate.get('lat') is None or coordinate.get('lon') is None:
            continue
        matches.append({'name': name, 'operator': operator, 'coordinate': coordinate,
                        'osm': f"{element['type']}/{element['id']}"})
    if len(matches) != 1:
        raise SystemExit(f'预期公开数据中有且仅有 1 个实名气象雷达，实际 {len(matches)} 个，拒绝生成')
    row = matches[0]
    return [site(
        'REG-' + row['osm'].replace('/', '-').upper(),
        f'{row["name"]}周边管制空域', 'ELECTROMAGNETIC', None,
        facilityType='WEATHER_RADAR_STATION',
        geometryStatus='PERIMETER_NOT_PUBLICLY_PUBLISHED',
        enforcement='REGISTERED_REVIEW_REQUIRED',
        referencePoint={'coordinate': [round(row['coordinate']['lon'], 5), round(row['coordinate']['lat'], 5)],
                        'source': f'OpenStreetMap {row["osm"]}'},
        authority='气象主管机构 / 空中交通管理机构',
        publication='由设区的市级以上人民政府公布，民用航空管理部门发布航行情报',
        operator=row['operator'],
        note=RADAR_REGISTER_NOTE,
        reviewAction=RADAR_REVIEW_ACTION,
        citation=RADAR_CITATION,
        provenance={'referencePoint': f'OpenStreetMap {row["osm"]}', 'retrievedAt': RETRIEVED,
                    'identificationBasis': '要素名称含"雷达"且带 operator 标签'},
    )]


if __name__ == '__main__':
    sites = (build_airports() + build_nuclear() + build_navigation_aids()
             + build_electromagnetic_registered() + build_registered())
    counts = {}
    for record in sites:
        counts[record['clause']] = counts.get(record['clause'], 0) + 1
    payload = {
        'schemaVersion': '1.0',
        'catalogVersion': 'northeast-fixed-airspace-v1',
        'coordinateReferenceSystem': 'EPSG:4326',
        'generatedAt': date.today().isoformat(),
        'dataRetrievedAt': RETRIEVED,
        'disclaimer': '本目录依据公开法规与公开数据登记固定管制空域，用于模拟运行中心的合规检查。'
                      '它不是航行情报，不构成飞行许可，也不能替代空中交通管理机构公布的管制空域边界。'
                      '凡未取得公开定量范围者一律不生成几何。',
        'legalFramework': {
            'instrument': '《无人驾驶航空器飞行管理暂行条例》（国令第 761 号，2024-01-01 施行）',
            'clause': '第十九条',
            'publicationRule': '管制空域的具体范围由各级空中交通管理机构按照国家空中交通管理领导机构的规定确定，'
                               '由设区的市级以上人民政府公布，民用航空管理部门和承担相应职责的单位发布航行情报。',
            'entryRule': '未经空中交通管理机构批准，不得在管制空域内实施无人驾驶航空器飞行活动。',
            'freeFlightRule': '管制空域范围以外的空域为微型、轻型、小型无人驾驶航空器的适飞空域。',
            'reviewPlatform': '民用无人驾驶航空器综合管理平台 https://uom.caac.gov.cn',
        },
        'clauses': [{**clause, 'sector': CLAUSE_SECTORS[clause['key']][0],
                     'sectorLabel': CLAUSE_SECTORS[clause['key']][1],
                     'siteCount': counts.get(clause['key'], 0)} for clause in CLAUSES],
        'sites': sites,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with_geometry = sum(1 for record in sites if record['geometry'])
    print(f'写入 {OUTPUT}')
    print(f'  区域总数 {len(sites)}，其中有确定几何 {with_geometry}，仅登记 {len(sites) - with_geometry}')
    for key, value in sorted(counts.items()):
        print(f'  {key}: {value}')
