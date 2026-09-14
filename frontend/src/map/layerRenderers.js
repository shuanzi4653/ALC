/** 东北三省态势图层：风场、天气范围、运行限制区与安全航线使用独立视觉语义。 */
export const HUBS = [
  { name: '大连', coord: [121.62, 38.92] }, { name: '沈阳', coord: [123.43, 41.80] },
  { name: '丹东', coord: [124.38, 40.13] }, { name: '长春', coord: [125.32, 43.90] },
  { name: '延吉', coord: [129.51, 42.89] }, { name: '哈尔滨', coord: [126.64, 45.76] },
  { name: '齐齐哈尔', coord: [123.92, 47.35] }, { name: '牡丹江', coord: [129.63, 44.55] },
  { name: '佳木斯', coord: [130.32, 46.80] }, { name: '黑河', coord: [127.53, 50.25] }
]
export const DESTS = HUBS
const byName = name => HUBS.find(point => point.name === name)?.coord
export const ROUTES = [
  ['大连', '沈阳'], ['丹东', '沈阳'], ['沈阳', '长春'], ['长春', '哈尔滨'],
  ['长春', '延吉'], ['哈尔滨', '齐齐哈尔'], ['哈尔滨', '佳木斯'],
  ['哈尔滨', '牡丹江'], ['哈尔滨', '黑河']
]
const isNum = value => typeof value === 'number' && Number.isFinite(value)
const ready = (findLayer, kind) => findLayer(kind)?.status === 'READY' ? findLayer(kind) : null
const validPoint = point => isNum(point?.lon) && isNum(point?.lat)
const validRing = ring => Array.isArray(ring) && ring.length >= 4 && ring.every(p => Array.isArray(p) && isNum(p[0]) && isNum(p[1]))
const arrowPath = 'path://M0,-10 L6,4 L2,3 L2,10 L-2,10 L-2,3 L-6,4 Z'

export function windLine(center, windDeg, windSpeed) {
  if (!Number.isInteger(windDeg) || windDeg < 0 || windDeg > 359 || !isNum(windSpeed) || windSpeed < 0) return null
  if (windSpeed <= 0.2) return [center]
  const len = 0.28 + Math.min(windSpeed, 20) * 0.025
  const rad = ((windDeg + 180) % 360) * Math.PI / 180
  return [center, [center[0] + len * Math.sin(rad) / Math.max(0.4, Math.cos(center[1] * Math.PI / 180)), center[1] + len * Math.cos(rad)]]
}

function polygonsFrom(layer) {
  const geometry = layer?.geometry
  if (geometry?.type === 'Polygon') return [geometry.coordinates?.[0]].filter(validRing)
  if (geometry?.type === 'MultiPolygon') return (geometry.coordinates || []).map(p => p?.[0]).filter(validRing)
  return []
}
function riskAreas(layer, fallbackLevel = layer?.data?.level) {
  const configured = Array.isArray(layer?.data?.areas) ? layer.data.areas.filter(a => validRing(a?.polygon)) : []
  if (configured.length) return configured
  return polygonsFrom(layer).map((polygon, index) => ({ name: `运行限制区 ${index + 1}`, zoneType: fallbackLevel === 'BAN' ? 'BAN' : 'CAUTION', polygon }))
}

const orientation = (a, b, c) => (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
const onSegment = (a,b,p) => Math.min(a[0],b[0])-1e-8<=p[0] && p[0]<=Math.max(a[0],b[0])+1e-8 && Math.min(a[1],b[1])-1e-8<=p[1] && p[1]<=Math.max(a[1],b[1])+1e-8
function segmentsIntersect(a,b,c,d) {
  const o1=orientation(a,b,c), o2=orientation(a,b,d), o3=orientation(c,d,a), o4=orientation(c,d,b)
  if (((o1>0&&o2<0)||(o1<0&&o2>0)) && ((o3>0&&o4<0)||(o3<0&&o4>0))) return true
  return (Math.abs(o1)<1e-8&&onSegment(a,b,c))||(Math.abs(o2)<1e-8&&onSegment(a,b,d))||(Math.abs(o3)<1e-8&&onSegment(c,d,a))||(Math.abs(o4)<1e-8&&onSegment(c,d,b))
}
function pointInPolygon(point, ring) {
  let inside=false
  for(let i=0,j=ring.length-1;i<ring.length;j=i++) { const [xi,yi]=ring[i], [xj,yj]=ring[j]
    if ((yi>point[1])!==(yj>point[1]) && point[0]<(xj-xi)*(point[1]-yi)/(yj-yi)+xi) inside=!inside }
  return inside
}
export function segmentHitsPolygon(a,b,ring) {
  if(pointInPolygon(a,ring)||pointInPolygon(b,ring)) return true
  for(let i=1;i<ring.length;i++) if(segmentsIntersect(a,b,ring[i-1],ring[i])) return true
  return false
}
const pathSafe=(coords,rings)=>coords.slice(1).every((p,i)=>rings.every(r=>!segmentHitsPolygon(coords[i],p,r)))
const km=(a,b)=>{ const lat=(a[1]+b[1])*Math.PI/360; return Math.hypot((b[0]-a[0])*111*Math.cos(lat),(b[1]-a[1])*111) }
const pathKm=coords=>coords.slice(1).reduce((sum,p,i)=>sum+km(coords[i],p),0)

/** 以限制区外扩包围盒角点建立可视图，自动选择左/右最短安全绕行。 */
export function planSafeRoute(from,to,areas,cruiseKmh=120) {
  if(!isNum(cruiseKmh)||cruiseKmh<=0)return {status:'CLOSED',coords:[],extraMinutes:null}
  const rings=areas.map(a=>a.polygon).filter(validRing), directKm=km(from,to)
  if(!rings.some(r=>segmentHitsPolygon(from,to,r))) return {status:'DIRECT',coords:[from,to],extraMinutes:0}
  const nodes=[from,to]
  for(const ring of rings) { const xs=ring.map(p=>p[0]), ys=ring.map(p=>p[1]), m=.16
    nodes.push([Math.min(...xs)-m,Math.min(...ys)-m],[Math.min(...xs)-m,Math.max(...ys)+m],[Math.max(...xs)+m,Math.min(...ys)-m],[Math.max(...xs)+m,Math.max(...ys)+m]) }
  const dist=Array(nodes.length).fill(Infinity), prev=Array(nodes.length).fill(-1), used=Array(nodes.length).fill(false); dist[0]=0
  for(let step=0;step<nodes.length;step++) { let u=-1
    for(let i=0;i<nodes.length;i++) if(!used[i]&&(u<0||dist[i]<dist[u])) u=i
    if(u<0||!Number.isFinite(dist[u])) break; used[u]=true
    for(let v=0;v<nodes.length;v++) { if(u===v||!pathSafe([nodes[u],nodes[v]],rings)) continue
      const next=dist[u]+km(nodes[u],nodes[v]); if(next<dist[v]) {dist[v]=next;prev[v]=u} } }
  if(!Number.isFinite(dist[1])) return {status:'CLOSED',coords:[],extraMinutes:Infinity}
  const coords=[]; for(let at=1;at>=0;at=prev[at]) {coords.push(nodes[at]);if(at===0)break} coords.reverse()
  const extraMinutes=Math.max(0,(pathKm(coords)-directKm)/cruiseKmh*60)
  return extraMinutes>60?{status:'CLOSED',coords:[],extraMinutes}:{status:'DETOUR',coords,extraMinutes}
}

export function buildRouteSeries(_center,color,enabled,riskLayer=null) {
  if(!enabled) return []
  if(riskLayer?.status!=='READY' || riskLayer?.data?.assessmentStatus==='UNKNOWN')return []
  const areas=riskAreas(riskLayer), planned=ROUTES.map(([from,to])=>({from,to,...planSafeRoute(byName(from),byName(to),areas)}))
  const open=planned.filter(r=>r.status!=='CLOSED').map(r=>({name:`${r.from}—${r.to}${r.status==='DETOUR'?` · 绕行 +${Math.ceil(r.extraMinutes)}分钟`:''}`,coords:r.coords,
    lineStyle:r.status==='DETOUR'?{color:'#68e0ff',width:2.8,type:'solid'}:undefined}))
  const closed=planned.filter(r=>r.status==='CLOSED')
  return [{id:'routes',name:'安全低空走廊',type:'lines',coordinateSystem:'geo',zlevel:5,polyline:true,lineStyle:{color:'#47d7ff',width:2,opacity:.7,type:'dashed',curveness:0},
    effect:{show:true,period:7,trailLength:.08,symbol:'triangle',symbolSize:6,color:'#fff'},data:open},
  {id:'route-points',name:'东北低空节点',type:'scatter',coordinateSystem:'geo',zlevel:7,symbol:'roundRect',symbolSize:[8,8],itemStyle:{color,borderColor:'#d8f4ff',borderWidth:1},
    label:{show:true,position:'right',distance:5,color:'#9fc9eb',fontSize:10,formatter:p=>p.name},data:HUBS.map(p=>({name:p.name,value:[...p.coord,1]}))},
  {id:'closed-routes',name:'关闭航线',type:'scatter',coordinateSystem:'geo',zlevel:9,symbol:'rect',symbolSize:8,itemStyle:{color:'#ff665c'},
    label:{show:true,position:'left',color:'#ff9a8f',fontSize:9,formatter:p=>p.data.label},data:closed.map(r=>({value:[...byName(r.from),1],label:`${r.from}—${r.to} 已关闭`}))}]
}

function fallbackPoint(layer,valueKey='value'){return validPoint(layer?.data)?[{...layer.data,value:layer.data[valueKey]}]:[]}
function cellPolygon(cell,thunder){ if(validRing(cell.polygon))return cell.polygon; const rx=thunder?.48:.42,ry=thunder?.34:.30
  return [[cell.lon-rx,cell.lat],[cell.lon-rx*.45,cell.lat+ry],[cell.lon+rx*.7,cell.lat+ry*.7],[cell.lon+rx,cell.lat-ry*.2],[cell.lon,cell.lat-ry],[cell.lon-rx,cell.lat]] }
function weatherAreaSeries(id,name,cells,thunder){ const color=thunder?'#ffd54f':'#2f8cff',fill=thunder?'rgba(255,184,45,.18)':'rgba(47,140,255,.18)'
  const areas=cells.map(cell=>({...cell,polygon:cellPolygon(cell,thunder)}))
  return [{id:`${id}-areas`,name:`${name}范围`,type:'custom',coordinateSystem:'geo',zlevel:thunder?4:3,silent:true,
    renderItem:(params,api)=>({type:'polygon',shape:{points:areas[params.dataIndex].polygon.map(p=>api.coord(p))},style:{fill,stroke:color,lineWidth:1.4,lineDash:thunder?[3,3]:null}}),data:areas.map((_,i)=>[i])},
  {id:`${id}-stations`,name,type:'effectScatter',coordinateSystem:'geo',zlevel:7,rippleEffect:{scale:thunder?2.8:2.2,brushType:'stroke',period:thunder?3.6:5},symbol:thunder?'diamond':'circle',symbolSize:thunder?10:8,
    itemStyle:{color,borderColor:thunder?'#fff4bd':'#a8d9ff',borderWidth:1},label:{show:true,position:thunder?'right':'left',distance:7,color:thunder?'#ffe9a0':'#b9dcff',fontSize:9,formatter:p=>p.data.label},
    data:areas.map(cell=>({name:cell.name,value:[cell.lon,cell.lat,cell.value],label:thunder?`${cell.name} ${Math.round(cell.value*100)}%`:`${cell.name} ${cell.value.toFixed(1)}`}))}]
}
export function buildWeatherSeries({findLayer,enabled}) {
  const series=[],wind=ready(findLayer,'WIND')
  if(enabled.wind&&wind){const points=Array.isArray(wind.data?.samples) && wind.data.samples.length ? wind.data.samples.filter(validPoint) : (Array.isArray(wind.data?.points)?wind.data.points.filter(validPoint):fallbackPoint(wind,'windSpeed'))
    const valid=points.filter(p=>Number.isInteger(p.windDeg)&&p.windDeg>=0&&p.windDeg<=359&&isNum(p.windSpeed)&&p.windSpeed>=0)
    if(valid.length)series.push({id:'wind-field',name:'密集区域风场',type:'scatter',coordinateSystem:'geo',zlevel:6,symbol:arrowPath,
      symbolSize:v=>[6+Math.min(v[2],20)*.18,10+Math.min(v[2],20)*.3],itemStyle:{color:'#71f2df',borderColor:'#d9fff9',borderWidth:.45,opacity:.82},
      data:valid.map(p=>({name:`${p.name} ${p.windDeg}° · ${p.windSpeed.toFixed(1)} m/s`,value:[p.lon,p.lat,p.windSpeed],symbolRotate:(p.windDeg+180)%360}))})}
  const rain=ready(findLayer,'PRECIPITATION'),rainCells=Array.isArray(rain?.data?.cells)?rain.data.cells.filter(validPoint):fallbackPoint(rain)
  if(enabled.precipitation&&rainCells.some(c=>isNum(c.value)&&c.value>0))series.push(...weatherAreaSeries('precipitation','移动降水单体',rainCells.filter(c=>isNum(c.value)&&c.value>0),false))
  const storm=ready(findLayer,'THUNDER_PROBABILITY'),stormCells=Array.isArray(storm?.data?.cells)?storm.data.cells.filter(validPoint):fallbackPoint(storm)
  if(enabled.thunder&&stormCells.some(c=>isNum(c.value)&&c.value>0))series.push(...weatherAreaSeries('thunder','移动雷暴单体',stormCells.filter(c=>isNum(c.value)&&c.value>0),true))
  return series
}

export function buildRiskSeries({center,layer,level,style,enabled}) {
  const areas=enabled&&layer?.status==='READY'?riskAreas(layer,level):[]
  if(!areas.length||!level)return[]
  return [{id:'risk-areas',name:'独立运行限制区',type:'custom',coordinateSystem:'geo',zlevel:4,silent:true,
    renderItem:(params,api)=>{const area=areas[params.dataIndex],ban=area.zoneType==='BAN';return{type:'polygon',shape:{points:area.polygon.map(p=>api.coord(p))},
      style:{fill:ban?'rgba(192,57,43,.20)':'rgba(217,138,43,.15)',stroke:ban?'#ff665c':'#e7a548',lineWidth:2,lineDash:ban?null:[7,4]}}},data:areas.map((_,i)=>[i])},
  {id:'risk-labels',name:'限制区标签',type:'scatter',coordinateSystem:'geo',zlevel:8,silent:true,symbolSize:0,
    label:{show:true,position:'top',fontSize:9,formatter:p=>p.data.label,color:p=>p.data.zoneType==='BAN'?'#ff8b82':'#efba68'},
    data:areas.map(area=>{const xs=area.polygon.map(p=>p[0]),ys=area.polygon.map(p=>p[1]);return{value:[(Math.min(...xs)+Math.max(...xs))/2||center[0],Math.max(...ys)],zoneType:area.zoneType,
      label:`${area.name} · ${area.zoneType==='BAN'?'禁飞':'谨慎'}`}})}]
}
export function buildOperationPoint({center,region,sfi,conditionText,levelLabel,color}) {
  return{id:'operation-point',name:'当前监测中心',type:'scatter',coordinateSystem:'geo',zlevel:9,symbol:'pin',symbolSize:24,itemStyle:{color,borderColor:'#eef7ff',borderWidth:1},
    label:{show:true,position:'top',offset:[0,-5],color:'#e7f5ff',fontSize:11,fontWeight:700,formatter:`${region||'区域中心'} · SFI ${sfi??'--'} · ${conditionText||'现象未知'} · ${levelLabel}`},
    data:[{name:region,value:[...center,10]}]}
}
