# -*- coding: utf-8 -*-
"""0.11.7 · B 前端：地图上画出雾区（4 站实测影响圈）+ 列表能见度。

## 为什么画圈而不是画走廊染色

走廊染色只是"线变灰"，读者仍不知道雾在哪、有多大。圈能回答三个问题：
**哪里**（圆心=机场站）、**多重**（半径按能见度档）、**谁说的**（站名+实测值）。

## 半径不是编的

- `banValue`（1000 m）→ 深灰圈，半径 **6 km**
- `warnValue`（5000 m）→ 浅灰圈，半径 **12 km**

这两个半径写在 `FOG_RING_KM` 里，来源是判据阈值而不是"看着差不多"。**必须标注
"圈是影响范围示意，不是实测雾区边界"** —— 实测边界需要格点场，本案例只有 4 个站。

## 一个刻意的取舍

**不画走廊染色**。后端已经给了 `verdict`（18 条不可飞），前端列表已经用颜色区分。
再在图上把 53 条线按 3 档染色，会和"雾圈"抢视觉权重，而读者分不清"这条线灰是因为
走廊判据，还是因为雾覆盖"。**一屏只讲一件事**：圈讲雾，列表讲判据。
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / 'backend-python' / 'traffic' / 'v2.py'
MAP = ROOT / 'frontend' / 'src' / 'components' / 'CityTrafficMap.vue'
HOME = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'HomeStage.vue'
CORR = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'CorridorPanel.vue'

# ============================================================
# 1) 后端：observation.stations 补经纬度（前端画圈要用）
# ============================================================
text = V2.read_text(encoding='utf-8')
old = """            'stations': [{'station': s['station'], 'available': s.get('available'),
                          'observedAt': s.get('observedAt'),"""
new = """            'stations': [{'station': s['station'], 'available': s.get('available'),
                          # 0.11.7（B）：经纬度。前端要按站点画"影响圈"，没有坐标就画不了；
                          # 让前端硬编码 4 组坐标等于把站点表复制两份。
                          'lat': (STATIONS.get(s['station']) or {}).get('lat'),
                          'lon': (STATIONS.get(s['station']) or {}).get('lon'),
                          'observedAt': s.get('observedAt'),"""
if old not in text:
    raise SystemExit('observation.stations 锚点不存在')
text = text.replace(old, new, 1)
V2.write_text(text, encoding='utf-8')
print('① 后端：observation.stations 已补 lat/lon')

# ============================================================
# 2) 地图：加雾区影响圈
# ============================================================
map_src = MAP.read_text(encoding='utf-8')

# 2.1 prop
if 'stationVisibility' not in map_src:
    anchor = "  network:{type:Object,default:null},"
    if anchor not in map_src:
        # 找 props 定义里任意一项作为锚点
        import re
        m = re.search(r"defineProps\(\{", map_src)
        if not m:
            raise SystemExit('找不到 defineProps')
        map_src = map_src[:m.end()] + "\n  stationVisibility:{type:Array,default:()=>[]}," + map_src[m.end():]
    else:
        map_src = map_src.replace(anchor, anchor + "\n  stationVisibility:{type:Array,default:()=>[]},", 1)

# 2.2 绘制函数：插在 template 之前
draw_fn = '''
// ---- 雾区影响圈（0.11.7 / B）------------------------------------------------
//
// 半径来源是**判据阈值**，不是"看着差不多"：
//   banValue 1000 m -> 6 km 深灰 ；warnValue 5000 m -> 12 km 浅灰
// 这两个数写在 FOG_RING_KM，改变它们等于改口径，要同步 rules-v1.json。
const FOG_RING_KM = { BAN: 6, CAUTION: 12 }

// 正 24 边形。用多边形而不是 MapLibre 的 circle 图层：circle 的半径单位是像素，
// 缩放时大小不变；而"雾区半径 6 km"是**地理距离**，必须随缩放变化。
function fogRing(lat, lon, radiusKm, steps = 24) {
  const coords = []
  const dLat = radiusKm / 111.32
  const dLon = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180) || 1)
  for (let i = 0; i <= steps; i += 1) {
    const a = (i / steps) * Math.PI * 2
    coords.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)])
  }
  return coords
}

function fogFeatureCollection(stations) {
  const features = []
  for (const s of Array.isArray(stations) ? stations : []) {
    // 只画"有实测且达到某一档"的站。CLEAR 的站不画 —— 那会让地图上
    // 出现一堆"雾区"，而它们恰恰是能见度良好的地方。
    const level = s.visLevel || (s.visM != null && s.visM <= 1000 ? 'BAN' : (s.visM != null && s.visM <= 5000 ? 'CAUTION' : 'CLEAR'))
    if (level !== 'BAN' && level !== 'CAUTION') continue
    if (typeof s.lat !== 'number' || typeof s.lon !== 'number') continue
    features.push({
      type: 'Feature',
      properties: {
        station: s.station,
        visM: s.visM,
        level,
        title: `${s.station} 实测能见度 ${Math.round(s.visM)} m（${level === 'BAN' ? '低于禁飞阈值' : '偏低'}）· 圈为影响范围示意，非实测雾区边界`,
      },
      geometry: { type: 'Polygon', coordinates: [fogRing(s.lat, s.lon, FOG_RING_KM[level])] },
    })
  }
  return { type: 'FeatureCollection', features }
}

function paintFogCircles() {
  if (!map) return
  const data = fogFeatureCollection(props.stationVisibility)
  if (map.getSource('fog-rings')) {
    map.getSource('fog-rings').setData(data)
    return
  }
  map.addSource('fog-rings', { type: 'geojson', data })
  // 面：很淡，只用来示意范围
  map.addLayer({
    id: 'fog-rings-fill', type: 'fill', source: 'fog-rings',
    paint: {
      'fill-color': ['match', ['get', 'level'], 'BAN', 'rgba(74,85,104,0.30)', 'rgba(160,174,192,0.22)'],
      'fill-outline-color': 'rgba(0,0,0,0)',
    },
  })
  // 描边：深灰档画实线，浅灰档画虚线 —— 两档在缩得很小的屏幕上也能分开
  map.addLayer({
    id: 'fog-rings-line', type: 'line', source: 'fog-rings',
    paint: {
      'line-color': ['match', ['get', 'level'], 'BAN', '#4A5568', '#A0AEC0'],
      'line-width': 1.4,
      'line-dasharray': ['case', ['==', ['get', 'level'], 'BAN'], ['literal', [1, 0]], ['literal', [3, 2]]],
    },
  })
}
'''

anchor_fn = '<template>'
if anchor_fn not in map_src:
    raise SystemExit('模板锚点不存在')
if 'FOG_RING_KM' not in map_src:
    map_src = map_src.replace(anchor_fn, draw_fn + '\n' + anchor_fn, 1)

# 2.3 触发：watch stationVisibility + 地图就绪后
if "watch(()=>props.stationVisibility" not in map_src:
    map_src = map_src.replace(
        'function paintFogCircles() {',
        """watch(() => props.stationVisibility, () => paintFogCircles(), { deep: true })
function paintFogCircles() {""", 1)
MAP.write_text(map_src, encoding='utf-8')
print('② 地图：雾区影响圈函数已加（正 24 边形，半径按能见度档）')

# ============================================================
# 3) HomeStage 把 stationVisibility 传下去
# ============================================================
home = HOME.read_text(encoding='utf-8')
old = "<CityTrafficMap :network=\"network\" :flights=\"flights\" :minute=\"minute\" :city=\"city\""
new = "<CityTrafficMap :network=\"network\" :flights=\"flights\" :minute=\"minute\" :city=\"city\"\n              :station-visibility=\"stationVisibility\""
if old in home and 'station-visibility' not in home:
    home = home.replace(old, new, 1)
    # 从 props.weather 里取（corridors 的 observation 才是权威，但地图只需要 4 个值）
    if 'const stationVisibility' not in home:
        home = home.replace("const layerDefs = computed(",
                            """// 0.11.7（B）：4 站实测能见度（给地图画影响圈）。
// 来源是 `weather` 载荷里的 `stationVisibility`（后端 field 直接产出），
// **不在这里重算** —— 重算就是第二套口径。
const stationVisibility = computed(() => props.weather?.stationVisibility || [])

const layerDefs = computed(""", 1)
    HOME.write_text(home, encoding='utf-8')
    print('③ HomeStage：stationVisibility 已传')
else:
    print('③ HomeStage：锚点不符或已传（跳过）')

# ============================================================
# 4) 列表：走廊行显示能见度
# ============================================================
corr = CORR.read_text(encoding='utf-8')
old = '<span class="corr-row-verdict">{{ row.verdict }}</span>'
new = '''<span class="corr-row-verdict">{{ row.verdict }}</span>
      <!-- 0.11.7（B）：能见度。`visM` 是**最近站原始值**（与判据同源），
           `visMidpointM` 是中点插值（只作参考）—— 两个数并列会让人问"哪个算数"，
           所以默认只显示判据同源的那个，插值值放 title。 -->
      <span class="corr-row-vis" v-if="row.visM != null"
            :title="`最近站 ${row.visNearestStation || '—'}（${row.visNearestKm ?? '—'} km）实测 ${Math.round(row.visM)} m；中点插值 ${row.visMidpointM != null ? Math.round(row.visMidpointM) + ' m' : '—'}（仅参考）`">
        {{ Math.round(row.visM / 100) / 10 }} km
      </span>'''
if old in corr and 'corr-row-vis' not in corr:
    corr = corr.replace(old, new, 1)
    corr = corr.replace('.corr-row-verdict{', """.corr-row-vis{font-size:11px;color:var(--alc-text-dim);font-variant-numeric:tabular-nums;margin-left:6px}
.corr-row-verdict{""", 1)
    CORR.write_text(corr, encoding='utf-8')
    print('④ 列表：走廊行已加能见度')
else:
    print('④ 列表：锚点不符或已加（跳过）')
