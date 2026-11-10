<script setup>
import {computed,defineAsyncComponent,onMounted,onUnmounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'
import {store} from '../../store.js'
import NationMap from './NationMap.vue'
import NationBriefing from './NationBriefing.vue'
import {parseScope,scopeKey} from '../../traffic/scope.js'
import {probeGPU,gpuLabel} from '../../traffic/gpu.js'

// 三维单独切包：maplibre + 地形瓦片只在真进三维时才加载。
// 首页首屏用不到它，没必要为它多等一个 chunk。
const NationGlobe=defineAsyncComponent(()=>import('./NationGlobe.vue'))

// 全国运行台：态势 / 台账 / 情报 / 处置 四个视图共用同一份 `payload`。
//
// 三条纪律：
//   ① **数字按块写**：每级、每省、每市都显示自己的航线/在飞/异常，总数单独在顶部；
//   ② **班次是对象**：图上点哪一架，台账就选哪一架，详情里就是这一架的许可与剖面；
//   ③ **逐级重新请求**：下钻与返回都清空上一屏，内存里不留整棵树。
const props=defineProps({
  compact:{type:Boolean,default:false},
  // 当前作用域（`nation` / `region:north` / `province:河北省` / `city:石家庄市`）。
  // NationPanel 仍是下钻的执行者，但"现在在哪一级"不再由它独占 ——
  // 气象、台账、处置、取证读的是同一份 store.scope。
  scopeKey:{type:String,default:'nation'},
  // 从导航进入时先落哪个视图：气象/走廊看 map，处置看 alerts，取证看 ledger。
  // 目的是让左侧导航与页内视图一致，避免"点处置却停在态势图"。
  initialView:{type:String,default:'map'},
  // 'weather' = 气象监测视图：右栏气象列表展开到全部城市、给更高高度。
  // 否则三个态势子页（首页/总览/气象监测）看起来一模一样。
  mode:{type:String,default:''},
  // 从左侧导航进入时隐藏内部 tab 条：导航已经表达了"我在哪一页"，
  // 再挂一条「态势/台账/情报/处置」只会和导航打架
  // （例如从「大模型取证」进来却看到「台账」高亮）。
  hideTabs:{type:Boolean,default:false},
  // 从导航进来时的一句"该做什么"。这些页面共用一张图，
  // 不给提示的话用户看到的就是一张空地图，不知道从哪下手。
  hint:{type:String,default:''},
})
const emit=defineEmits(['scope-change'])

const level=ref('nation')
const ident=ref('')
const trail=ref([{level:'nation',id:'',label:'全国'}])
const data=ref(null)
const view=ref(props.initialView||'map')
const error=ref(''),loading=ref(false)
const busy=ref('')
const evidence=ref(null)
const evidenceBusy=ref(false)
const evidenceErr=ref('')

const minute=ref(60)
const playing=ref(false)
const speed=ref(1)                    // 分钟/秒：0.25≈15×、1=60×、5=300×
const radarOn=ref(true)
const fogOn=ref(true)
const terrainOn=ref(false)
const tilt=ref(false)
const virtualMode=ref(false)
const density=ref('full')
const selectedId=ref('')
const selectedCorridor=ref('')
const followId=ref('')

// —— 视角：平面 / 倾斜（SVG 透视）/ 三维（maplibre 真透视） ——
// 三维之前先问 GPU 能不能扛。软件渲染（SwiftShader）下进去就是拖死页面，
// 所以按钮点了也会被挡回来，并说清"为什么不能看"，而不是默默什么都不发生。
const gpu=probeGPU()
const threeD=ref(false)
const liftNote=ref('')
const fps=ref(0)
// —— 双受众视角 ——
// 同一套几何两种读法：运行视角看航线与班次，空域视角看净空边界与等级。
// 不做第二套数据，只是图层显隐 + 侧栏内容切换。
const audience=ref('ops')
const zoneGeom=ref(null)
const zoneBusy=ref(false)
const zoneErr=ref('')
const zonePolicy=ref('APPROVAL_REQUIRED')

const flights=ref([])
const live=ref({corridors:0,airborne:0,delayed:0,hold:0,blocked:0,lowVisCities:0})
const byProvince=ref({})
const byCity=ref({})
let timer=null,pushTimer=null,fetchAt=0,seq=0

const MINUTES=180
const mapRef=ref(null)

const summary=computed(()=>data.value?.summary||{})
const rollup=computed(()=>data.value?.rollup||{level:'nation',total:{},regions:[],provinces:[],cities:[]})
const total=computed(()=>({...(rollup.value.total||{}),...live.value}))
const radarMeta=computed(()=>data.value?.radar||{})
const border=computed(()=>data.value?.border||{})
const fog=computed(()=>data.value?.fog||{available:false,counts:{},bands:{},cities:[]})
// 机场净空（DERIVED）。与 border 的 OFFICIAL 管制区分开显示：
// 两套几何一个是官方公布、一个是规则化生成，混在一起说会被追问依据。
const zones=computed(()=>data.value?.zones||{available:false,counts:{},rows:[]})

// 回波范围：三档环一起算，定位按钮按它飞过去
const radarBBox=computed(()=>{
  const bands=data.value?.radar?.bands||{}
  let minLon=999,minLat=999,maxLon=-999,maxLat=-999,any=false
  for(const level of ['STRONG','CONVECTIVE','WEAK']){
    for(const ring of bands[level]||[]){
      for(const [lon,lat] of ring||[]){
        any=true
        if(lon<minLon)minLon=lon; if(lon>maxLon)maxLon=lon
        if(lat<minLat)minLat=lat; if(lat>maxLat)maxLat=lat
      }
    }
  }
  return any?[minLon,minLat,maxLon,maxLat]:null
})
// —— 全国取证 ——
// 给的是"每一行都有来源"的证据链；大模型没配置就只显示规则链，不冒充模型结论。
async function loadEvidence(){
  const flight=selectedFlight.value
  if(!flight) return
  evidenceBusy.value=true
  evidenceErr.value=''
  try{
    evidence.value=await requestJson(
      `/api/traffic/v2/nation/evidence?flight=${encodeURIComponent(flight.id)}&minute=${Math.round(minute.value)}`,
      {timeoutMs:25000})
  }catch(e){evidenceErr.value=e.message||String(e);evidence.value=null}
  finally{evidenceBusy.value=false}
}
function clearEvidence(){evidence.value=null;evidenceErr.value=''}

// 立体与平面是两套渲染，但"定位/复位"对用户是同一个动作：按当前模式找对那个组件。
const globeRef=ref(null)
function activeMap(){
  return threeD.value?globeRef.value:(mapRef.value||null)
}
function locateLayer(kind){
  followId.value=''
  const box=kind==='radar'?radarBBox.value:(data.value?.fog?.bbox||null)
  if(box) activeMap()?.fitBounds?.(box)
}
function resetMap(){
  followId.value=''
  activeMap()?.resetView?.()
}

// —— 视角切换（含 WebGL 护栏） ——
function toggle3d(){
  if(threeD.value){threeD.value=false;liftNote.value='';return}
  const probe=gpu||probeGPU()
  if(!probe.ok){
    // 不进三维，直接给倾斜视图 + 原因。静默失败是最糟的选择：
    // 用户会以为是按钮坏了，然后反复点。
    tilt.value=true
    threeD.value=false
    liftNote.value=`本机没开硬件加速，真实三维会拖死页面：${probe.reason}。已切到倾斜视图（同样的俯角，不依赖 GPU）`
    return
  }
  threeD.value=true
  tilt.value=false
  liftNote.value=''
  ensureZones()
}
function toggleTilt(){
  tilt.value=!tilt.value
  if(tilt.value){threeD.value=false}
  liftNote.value=''
}
function onGlobeDegrade(info){
  // ③ 看门狗触发：退出三维，落到倾斜视图，并说明是帧率问题而不是数据问题
  threeD.value=false
  tilt.value=true
  liftNote.value=`三维帧率只有 ${info?.fps ?? '?'} fps（连续 3 秒低于 20），已自动降级为倾斜视图。多半是显卡驱动没走上硬件加速`
}
function onGlobeUnsupported(probe){
  threeD.value=false
  tilt.value=true
  liftNote.value=`真实三维不可用：${probe?.reason||'本机 WebGL 未启用'}。已切到倾斜视图`
}
function onGlobeFps(value){fps.value=value}

// —— 净空几何按需取 ——
// 287 个 28 点环约 250 KB，首页不画它，所以不放进主载荷；只有切到空域视角
// 或进了三维的省/市层才取。取过一次就留着，切换视角不再重复请求。
function ensureZones(){
  if(zoneGeom.value||zoneBusy.value) return
  zoneBusy.value=true
  zoneErr.value=''
  requestJson(`/api/traffic/v2/nation/zones?policy=${zonePolicy.value}`,{timeoutMs:30000})
    .then(body=>{zoneGeom.value=body||null})
    .catch(e=>{zoneErr.value=e.message||String(e)})
    .finally(()=>{zoneBusy.value=false})
}
function setAudience(next){
  if(audience.value===next) return
  audience.value=next
  if(next==='airspace') ensureZones()
}
function switchZonePolicy(){
  zonePolicy.value=zonePolicy.value==='PROHIBITED'?'APPROVAL_REQUIRED':'PROHIBITED'
  zoneGeom.value=null
  ensureZones()
}
// 空域视角下的统计：净空覆盖、待审穿越 —— 都来自后端可复算的计数
const zoneCounts=computed(()=>zoneGeom.value?.counts||zones.value?.counts||{})
const zoneCrossings=computed(()=>zoneGeom.value?.crossings||null)
const alerts=computed(()=>data.value?.alerts||[])
const intel=computed(()=>data.value?.intel||[])
const upcoming=computed(()=>data.value?.upcoming||[])

const headline=computed(()=>{
  const t=total.value
  const where=level.value==='nation'?'全国':(trail.value[trail.value.length-1]?.label||'本级')
  const parts=[`${where} ${t.corridors||0} 条航线`,`在飞 ${t.airborne||0} 架`]
  if(t.delayed)parts.push(`绕飞 ${t.delayed} 架`)
  if(t.hold)parts.push(`暂缓 ${t.hold} 架`)
  if(t.blocked)parts.push(`边境停飞 ${t.blocked} 条`)
  if(t.lowVisCities)parts.push(`低能见度 ${t.lowVisCities} 城`)
  return parts.join(' · ')
})

const selectedFlight=computed(()=>flights.value.find(f=>f.id===selectedId.value)||null)
const selectedLine=computed(()=>(data.value?.corridors||[]).find(c=>c.id===selectedCorridor.value)||null)

function clock(m){
  // 跨零点要能分清今天/明天：时间轴上界 1440 分钟、从 08:00 起算，
  // 走到 m=960 就过 24:00，于是 m=1000 与 m=40 都落在 00:40。
  // 只给 HH:MM 的话，界面无法回答"这是几点"。
  const raw=8*60+Math.round(m||0)
  const day=Math.floor(raw/1440)
  const t=((raw%1440)+1440)%1440
  const hhmm=`${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`
  return day>0?`${hhmm} +${day}d`:hhmm
}
function shortName(name){
  // 省级与市级共用一个规则：先剥自治区/特区/省，再剥市/地区/盟/自治州。
  // 两处（地图标签、右栏列表）必须一致，否则同一个省在图上叫"新疆"、在右栏叫"新疆维吾尔自治区"。
  return (name||'')
    .replace(/维吾尔自治区$/,'').replace(/壮族自治区$/,'').replace(/回族自治区$/,'')
    .replace(/特别行政区$/,'').replace(/自治区$/,'').replace(/省$/,'')
    .replace(/(市|地区|盟|自治州|自治县)$/,'')
    .replace(/(朝鲜族|蒙古族|藏族|苗族|侗族|彝族|哈尼族|壮族|傣族|白族|土家族|布依族|傈僳族|景颇族|羌族|回族|维吾尔族)$/,'')
}

async function loadFlights(){
  const now=Date.now()
  if(now<fetchAt) return
  fetchAt=now+850
  const my=++seq
  try{
    const payload=await requestJson(
      `/api/traffic/v2/nation/flights?level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${Math.round(minute.value)}`,
      {timeoutMs:20000})
    if(my!==seq) return
    flights.value=payload.flights||[]
    byProvince.value=payload.byProvince||{}
    byCity.value=payload.byCity||{}
    live.value={...live.value,...(payload.traffic||{})}
  }catch(e){/* 时间轴刷新失败不打断主界面 */}
}

async function load(){
  loading.value=true
  error.value=''
  data.value=null
  selectedId.value=''
  selectedCorridor.value=''
  followId.value=''
  flights.value=[]
  try{
    data.value=await requestJson(
      `/api/traffic/v2/nation?level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${Math.round(minute.value)}`,
      {timeoutMs:45000})
    flights.value=data.value?.flights||[]
    live.value={...(data.value?.traffic||{})}
    byProvince.value={}
    byCity.value={}
    resetMap()
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}

function go(nextLevel,nextId,nextLabel){
  level.value=nextLevel
  ident.value=nextId||''
  if(nextLevel==='nation') trail.value=[{level:'nation',id:'',label:'全国'}]
  else{
    const cut=trail.value.findIndex(item=>item.level===nextLevel)
    if(cut>=0) trail.value=trail.value.slice(0,cut)
    trail.value=[...trail.value,{level:nextLevel,id:nextId||'',label:nextLabel||nextId}]
  }
  emitScope()
  load()
}

// 把当前作用域广播出去：外部据此写 store 与地址栏，其它视图跟着切。
function emitScope(){
  const last=trail.value[trail.value.length-1]||{level:'nation',id:'',label:'全国'}
  emit('scope-change',{
    level:level.value,id:ident.value,label:last.label||ident.value||'全国',
    trail:trail.value.map(item=>({...item})),
  })
}
function back(){
  if(trail.value.length<=1) return
  const next=trail.value[trail.value.length-2]
  trail.value=trail.value.slice(0,-1)
  level.value=next.level
  ident.value=next.id
  emitScope()
  load()
}
function drill(nextLevel,nextId,label){
  if(nextLevel==='province'&&level.value==='province') return
  if(nextLevel==='city'&&level.value==='city') return
  go(nextLevel,nextId,label)
}

function togglePlay(){
  playing.value=!playing.value
  if(playing.value){
    timer=setInterval(()=>{
      minute.value=(minute.value+speed.value)%MINUTES
      loadFlights()
    },1000)
  }else if(timer){clearInterval(timer);timer=null}
}
watch(speed,()=>{ if(playing.value){togglePlay();togglePlay()} })

function pickFlight(flight){
  if(selectedId.value!==flight.id){followId.value='';clearEvidence()}
  selectedId.value=flight.id
  selectedCorridor.value=''
}
function toggleFollow(){
  followId.value=followId.value===selectedId.value?'':selectedId.value
}
function pickCorridor(line){
  selectedCorridor.value=line.id
  selectedId.value=''
  followId.value=''
}
function locate(){ if(selectedFlight.value) minute.value=selectedFlight.value.departMinute; playing.value=false }

const ledgerRows=computed(()=>{
  const rows=[...(flights.value||[]).map(f=>({...f,state:'AIRBORNE'}))]
  const limit=density.value==='slim'?20:(density.value==='min'?10:120)
  return rows.slice(0,limit)
})
const upcomingRows=computed(()=>upcoming.value.slice(0,density.value==='slim'?12:30))
const intelRows=computed(()=>{
  const limit=density.value==='slim'?16:80
  return intel.value.slice(0,limit)
})
const weatherRows=computed(()=>{
  const rows=(data.value?.nodes||[]).filter(n=>n.weather).map(n=>({
    name:n.name,short:shortName(n.name),capital:!!n.capital,rank:n.rank||3,
    temp:n.weather.tempC,wind:n.weather.windMps,vis:n.weather.visM,low:!!n.weather.low,
  }))
  rows.sort((a,b)=>(b.low?1:0)-(a.low?1:0)||(b.capital?1:0)-(a.capital?1:0)||a.rank-b.rank)
  return rows.slice(0,level.value==='nation'?12:(density.value==='slim'?16:40))
})

// 时间轴推进时，只刷新"在飞/绕飞/暂缓"这三个会变的数；航线数、停飞数是静态的，
// 不该跟着分钟乱跳。所以按省/市名去 byProvince/byCity 里取，取不到就退回快照值。
function airOf(name,fallback){const row=byProvince.value[name];return row?row.airborne:(fallback||0)}
function airOfCity(name,fallback){const row=byCity.value[name];return row?row.airborne:(fallback||0)}

// —— 走廊逐公里剖面 ——
// 为什么要"逐公里"而不是一个总数：一条 120 km 的航路，回波可能只压住中间 15 km，
// 说"穿回波"会让人以为整条都不能飞；逐段标出来，才知道是哪一段、多长。
const BAND_LABEL={STRONG:'强回波（45 dBZ 以上）',CONVECTIVE:'对流回波（35–45）',WEAK:'弱回波（15–35）','':'无回波'}
const BAND_COLOR={STRONG:'rgba(238,72,60,.55)',CONVECTIVE:'rgba(245,190,60,.45)',WEAK:'rgba(40,190,110,.30)','':'transparent'}

function haversine(a,b){
  const R=6371,rad=Math.PI/180
  const dLat=(b[1]-a[1])*rad,dLon=(b[0]-a[0])*rad
  const h=Math.sin(dLat/2)**2+Math.cos(a[1]*rad)*Math.cos(b[1]*rad)*Math.sin(dLon/2)**2
  return 2*R*Math.asin(Math.min(1,Math.sqrt(h)))
}
function ringHit(ring,lon,lat){
  let inside=false
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1]
    if(((yi>lat)!==(yj>lat))&&(lon<(xj-xi)*(lat-yi)/((yj-yi)||1e-9)+xi)) inside=!inside
  }
  return inside
}
function bandAt(lon,lat){
  const bands=data.value?.radar?.bands||{}
  for(const name of ['STRONG','CONVECTIVE','WEAK']){
    for(const ring of bands[name]||[]){ if(ringHit(ring,lon,lat)) return name }
  }
  return ''
}
const corridorProfile=computed(()=>{
  const line=selectedLine.value
  if(!line) return null
  const path=(line.path&&line.path.length>1)?line.path:[line.fromLonLat,line.toLonLat]
  const legs=[]
  let total=0
  for(let i=0;i<path.length-1;i++){
    const len=haversine(path[i],path[i+1])
    legs.push({a:path[i],b:path[i+1],len,start:total})
    total+=len
  }
  if(!legs.length||total<=0) return null
  const count=Math.min(72,Math.max(16,Math.round(total/6)))
  const samples=[]
  for(let k=0;k<=count;k++){
    const target=total*k/count
    const leg=legs.find(item=>target<=item.start+item.len)||legs[legs.length-1]
    const t=leg.len?(target-leg.start)/leg.len:0
    const lon=leg.a[0]+(leg.b[0]-leg.a[0])*t
    const lat=leg.a[1]+(leg.b[1]-leg.a[1])*t
    samples.push({km:Math.round(target),lon,lat,band:bandAt(lon,lat)})
  }
  const segments=[]
  for(const sample of samples){
    const last=segments[segments.length-1]
    if(last&&last.band===sample.band) last.to=sample.km
    else segments.push({band:sample.band,from:sample.km,to:sample.km})
  }
  return {totalKm:Math.round(total),segments}
})
// 剖面里的计划高度包线：15% 爬升 / 70% 巡航 / 15% 下降
const profilePoints=computed(()=>{
  const prof=corridorProfile.value
  if(!prof) return ''
  const x0=8,w=304,yGround=68,yTop=14
  return [[0,yGround],[0.15,yTop],[0.85,yTop],[1,yGround]]
    .map(([fx,fy])=>`${(x0+fx*w).toFixed(1)},${fy}`).join(' ')
})

// 右下的气象行：用当前层级已下发的节点（全国 319 → 大区 → 省 → 市自动收窄）
const wxRows=computed(()=>{
  const rows=(data.value?.nodes||[]).filter(n=>n.weather).map(n=>({
    name:n.name, short:shortName(n.name), rank:n.rank||3, capital:!!n.capital,
    temp:n.weather.tempC, wind:n.weather.windMps, vis:n.weather.visM, low:!!n.weather.low,
    p:n.pLowVis==null?null:n.pLowVis,
  }))
  rows.sort((a,b)=>((b.p??-1)-(a.p??-1))||((b.low?1:0)-(a.low?1:0))||a.rank-b.rank)
  if(props.mode==='weather') return rows.slice(0,320)
  return rows.slice(0,level.value==='nation'?40:60)
})
const wxTotal=computed(()=>(data.value?.nodes||[]).filter(n=>n.weather).length)
// 实况从哪来、是不是旧的、是不是还在补 —— "0/0" 必须能解释成"补数中"而不是"没有"
const weatherMeta=computed(()=>data.value?.weatherMeta||{})
const wxRefreshing=computed(()=>!!weatherMeta.value.refreshing)
const wxStale=computed(()=>!!weatherMeta.value.stale)
// 旧数据要能回答"旧到什么程度"。只有 stale 布尔时，3 天前的快照和
// 2 分钟前的过期缓存显示完全一样，读者无法判断能不能采信。
const wxAgeText=computed(()=>{
  const ts=weatherMeta.value.fetchedAt
  if(!ts) return ''
  const diff=Date.now()-Date.parse(ts)
  if(!Number.isFinite(diff)) return ''
  const mins=Math.max(0,Math.round(diff/60000))
  if(mins<1) return '刚刚'
  if(mins<60) return `${mins} 分钟前`
  return `${(mins/60).toFixed(1)} 小时前`
})
const wxSourceText=computed(()=>{
  const src=weatherMeta.value.sources||{}
  const parts=[]
  if(src.OPEN_METEO) parts.push(`open-meteo ${src.OPEN_METEO}`)
  if(src.WTTR) parts.push(`wttr ${src.WTTR}`)
  return parts.join(' + ')
})
function pBand(p){return p==null?'':(p>=0.6?'bad':(p>=0.35?'warn':(p>=0.15?'watch':'')))}

// —— 推演个性化：先选对象，再看链路 ——
// 之前这一页只能"在地图上点"，点到什么算什么。推演的逻辑应该是**先立题**：
// 选一座城市（在哪一片空域）或一班航班（哪一条航路），再顺着实况→判据→裁决往下看。
const pickCity=ref('')
const cityOptions=computed(()=>{
  const rows=(data.value?.nodes||[]).filter(n=>n.name)
  // 省会/机场城市排前面：从 319 个城里找一个县城，用下拉是折磨
  const weight=n=>(n.rank||3)*10+((n.hasAirport||n.airport)?0:1)
  return [...rows].sort((a,b)=>weight(a)-weight(b)||String(a.name).localeCompare(String(b.name),'zh')).slice(0,120)
})
const flightOptions=computed(()=>{
  const rows=[...flights.value]
  rows.sort((a,b)=>String(a.callsign).localeCompare(String(b.callsign)))
  return rows.slice(0,80)
})
function jumpToCity(){
  const name=pickCity.value
  if(!name) return
  if(level.value==='city'&&ident.value===name) return
  go('city',name,name)
}
function pickFromList(){
  const flight=flights.value.find(f=>f.id===selectedId.value)
  if(flight) pickFlight(flight)
}
// 选题行里的一句话：选中的这一班现在怎么样，细的看下方详情
const pickSummary=computed(()=>{
  const flight=selectedFlight.value
  if(!flight) return ''
  const wx=(data.value?.nodes||[]).find(n=>n.name===flight.fromName||n.name===flight.toName)
  const parts=[flight.decisionLabel, `风险 ${flight.riskP.toFixed(2)}`]
  if(wx?.weather) parts.push(`实况 ${wx.weather.tempC==null?'—':wx.weather.tempC+' °C'} / 能见度 ${visText(wx.weather.visM)}`)
  return parts.join(' · ')
})

const profileText=computed(()=>{
  const prof=corridorProfile.value
  if(!prof) return ''
  // 雷达没取到时，所有采样点都会判成"无回波"——那是缺失，不是结论。
  // 不区分的话，这一行会写出"全线无回波"，等于替不确定的天气背了书。
  if(!data.value?.radar?.available) return '回波数据不可用（本帧未取到），此处不给出"全线无回波"结论'
  return prof.segments.filter(s=>s.band)
    .map(s=>`${s.from}–${s.to} km ${BAND_LABEL[s.band]}`).join(' · ')||'全线无回波'
})

function visText(vis){
  if(vis==null) return '—'
  const km=vis/1000
  return (km>=10?Math.round(km):km.toFixed(1))+' km'
}

// 推送：网关每 5 秒广播一条心跳，只有"雷达换帧 / 实况更新 / 模型换版"才算变化。
// 变化时重取本级数据；没变化就什么都不做 —— 屏幕空闲时不再定时轮询整份载荷。
const pushAge=ref(0)
const viewport=ref({w:0,h:0,root:0})
// 只在 ?diag=1 时显示尺寸诊断，平时不占地方
const showDiag=typeof location!=='undefined'&&/[?&]diag=1/.test(location.search)
function measureViewport(){
  viewport.value={
    w:window.innerWidth,h:window.innerHeight,
    root:Math.round(document.querySelector('.traffic-workbench')?.clientWidth||0),
  }
}
watch(()=>store.nationPulse,(value)=>{
  if(!value) return
  pushAge.value=0
  // 心跳只说明"某个源变了"，不代表要立刻重拉整份载荷：
  // 限流期间实况时刻会抖，5 秒一次全量重取会把页面拖住。这里设最小间隔。
  if(value.changed&&Date.now()-fetchAt>20000) load()
})

// 外部改作用域（命令面板输地名、其它视图联动、地址栏还原）时跟着走。
// 比较 level+id 而不是比字符串：自己 emit 出去的那一次，本地已经改过了，
// 这里会比较出"相同"而直接返回 —— 不会重复发一次请求。
watch(()=>props.initialView,(next)=>{
  if(next&&next!==view.value) view.value=next
})

let scopeReady=false
watch(()=>props.scopeKey,(key)=>{
  const next=parseScope(key)
  if(next.level===level.value&&next.id===ident.value) return
  level.value=next.level
  ident.value=next.id
  trail.value=(next.level==='nation')
    ?[{level:'nation',id:'',label:'全国'}]
    :[{level:'nation',id:'',label:'全国'},{level:next.level,id:next.id,label:next.label}]
  if(scopeReady) load()
},{immediate:true})

onMounted(()=>{
  scopeReady=true
  measureViewport()
  window.addEventListener('resize',measureViewport)
  load()
  // 推送计时用独立定时器：不能和推演播放共用一个变量，否则一开播就把计时器顶掉
  pushTimer=setInterval(()=>{pushAge.value+=1},1000)
})
onUnmounted(()=>{
  window.removeEventListener('resize',measureViewport)
  if(timer) clearInterval(timer)
  if(pushTimer) clearInterval(pushTimer)
})
</script>

<template>
<section class="nrn">
  <header class="nrn-hd">
    <div class="nrn-crumb">
      <template v-for="(item,index) in trail" :key="item.level+item.id">
        <button v-if="index<trail.length-1" @click="go(item.level,item.id,item.label)">{{ item.label }}</button>
        <b v-else>{{ item.label }}</b>
        <span v-if="index<trail.length-1" class="sep">›</span>
      </template>
      <button v-if="trail.length>1" class="back" @click="back">返回上一级</button>
    </div>
    <p class="nrn-headline" data-nation-headline>{{ headline }}</p>
    <p class="nrn-sub">
      省 <b>{{ summary.provinces }}</b> · 市 <b>{{ summary.cities }}</b> ·
      机场 <b>{{ summary.airports }}</b> · 无机场市 <b>{{ summary.feedCities }}</b> ·
      逐市气象 <b>{{ summary.weatherCities }}</b>
      <span v-if="level==='nation'&&border.excludeKm"> · 边境 {{ border.excludeKm }} km 内 <b>{{ (border.excludedCities||[]).length }}</b> 城已退出通航</span>
    </p>
    <!-- 双受众：同一套几何两种读法，不做第二套数据 -->
    <div class="nrn-aud" v-if="view==='map'" data-audience-switch>
      <button :class="{on:audience==='ops'}" @click="setAudience('ops')"
              title="运行视角：看航线穿不穿净空、绕飞代价多少">运行视角</button>
      <button :class="{on:audience==='airspace'}" @click="setAudience('airspace')"
              title="空域视角：看净空边界、禁飞等级与待审穿越">空域视角</button>
      <button class="policy" v-if="audience==='airspace'" @click="switchZonePolicy"
              :title="'规则化净空整体切到「一律禁止进入」，用于演示；真实世界里这是审批结果不是开关'">
        {{ zonePolicy==='PROHIBITED'?'一律禁飞':'可申请穿越' }}</button>
    </div>
  </header>

  <nav class="nrn-tabs" data-nation-tabs v-if="!hideTabs">
    <button :class="{on:view==='map'}" @click="view='map'">态势</button>
    <button :class="{on:view==='ledger'}" @click="view='ledger'">台账 <em>{{ flights.length }}</em></button>
    <button :class="{on:view==='intel'}" @click="view='intel'">情报 <em>{{ intel.length }}</em></button>
    <button :class="{on:view==='alerts'}" @click="view='alerts'">处置 <em :class="{bad:alerts.length}">{{ alerts.length }}</em></button>
  </nav>

  <!-- 推演页的"立题"行：先选对象，再看链路。不给选择器的话，
       这一页只能靠在地图上盲点，点不中就什么都没发生。 -->
  <div class="nrn-pick" v-if="mode==='card'" data-card-picker>
    <label>城市
      <select v-model="pickCity" @change="jumpToCity" aria-label="推演城市">
        <option value="">选择城市…</option>
        <option v-for="c in cityOptions" :key="c.name" :value="c.name">
          {{ shortName(c.name) }}{{ c.airport?(' · '+c.airport):' · 无机场' }}</option>
      </select>
    </label>
    <label>班次
      <select v-model="selectedId" @change="pickFromList" aria-label="推演班次">
        <option value="">选择班次…</option>
        <option v-for="f in flightOptions" :key="f.id" :value="f.id">
          {{ f.callsign }} · {{ shortName(f.fromName) }}→{{ shortName(f.toName) }}</option>
      </select>
    </label>
    <span class="pick-note" v-if="pickSummary">{{ pickSummary }}</span>
    <span class="pick-note quiet" v-else>选城市定位空域，选班次看这一架的实况 → 判据 → 裁决</span>
  </div>

  <p class="nrn-state" v-if="loading">正在加载本级数据…</p>
  <p class="nrn-state bad" v-else-if="error">本级不可用 · {{ error }}<button @click="load">重试</button></p>

  <!-- 注意：这两条必须是**各自独立**的 v-if。
       `nrn-body` 原本是承接 loading/error 的 `v-else-if`，在它前面的任何 v-if
       都会把链条打断 —— 提示条有值时整个内容区会被排除掉（实测整页空白）。
       所以这里显式写全条件，不用 else-if 链。 -->
  <p class="nrn-hint" v-if="hint&&data&&!loading&&!error" data-nation-hint>{{ hint }}</p>
  <div class="nrn-body" v-if="data&&!loading&&!error" :class="{'no-map':view!=='map'}">
    <!-- ================= 态势 ================= -->
    <div class="nrn-map" v-show="view==='map'">
      <div class="nrn-tools">
        <button class="play" @click="togglePlay">{{ playing?'Ⅱ 暂停':'▶ 推演' }}</button>
        <input type="range" min="0" :max="MINUTES" step="1" v-model.number="minute"
               @input="loadFlights" aria-label="推演时间"/>
        <b class="clock">{{ clock(minute) }}</b>
        <select v-model.number="speed" aria-label="推演倍速">
          <option :value="0.25">15 倍速</option>
          <option :value="1">60 倍速</option>
          <option :value="5">300 倍速</option>
        </select>
        <button :class="{on:radarOn}" @click="radarOn=!radarOn">回波</button>
        <button :class="{on:fogOn}" @click="fogOn=!fogOn" :disabled="!fog.available">雾区</button>
        <button :class="{on:terrainOn}" @click="terrainOn=!terrainOn">地形</button>
        <button :class="{on:tilt}" @click="toggleTilt">倾斜</button>
        <button :class="{on:threeD}" @click="toggle3d"
                :title="gpu.ok?('真实三维 · '+gpuLabel(gpu)):(gpu.reason||'本机 WebGL 不可用')">三维</button>
        <button :class="{on:virtualMode}" @click="virtualMode=!virtualMode"
                :title="'虚拟增强：回波与绕飞/停飞在图上更醒目，用于演示'">{{ virtualMode?'虚拟':'实测' }}</button>
        <select v-model="density" aria-label="信息密度">
          <option value="full">标准</option>
          <option value="slim">精简</option>
          <option value="min">极简</option>
        </select>
        <button :disabled="!radarBBox" @click="locateLayer('radar')">定位回波</button>
        <button :disabled="!fog.bbox" @click="locateLayer('fog')">定位雾区</button>
        <button @click="resetMap()">复位</button>
      </div>

      <p class="nrn-lift" v-if="liftNote" data-lift-note>{{ liftNote }}</p>

      <!-- 三维＝maplibre 真透视（俯角/旋转/DEM/体块），但先进能力探测：
           软件渲染（SwiftShader）一律不进，直接退到倾斜视图并说明原因。
           这是 V1.0.1 两次把 Edge 拖死的教训 —— 卡死的是浏览器 GPU，不是服务器。
           倾斜＝不依赖 WebGL 的 CSS 透视，轻、稳、切页不卡，代价是没有真实高程。 -->
      <div class="nrn-canvas">
      <NationGlobe v-if="threeD" ref="globeRef" :data="data" :flights="flights"
                   :radar-on="radarOn" :fog-on="fogOn" :density="density"
                   :selected-id="selectedId" :selected-corridor="selectedCorridor"
                   :follow-id="followId" :zones="zoneGeom" :audience="audience"
                   @drill="drill" @select-flight="pickFlight" @select-corridor="pickCorridor"
                   @degrade="onGlobeDegrade" @unsupported="onGlobeUnsupported" @fps="onGlobeFps"/>
      <NationMap v-else ref="mapRef" :data="data" :flights="flights" :minute="minute"
                 :radar-on="radarOn" :fog-on="fogOn" :terrain-on="terrainOn" :tilt="tilt"
                 :density="density" :virtual-mode="virtualMode" :audience="audience"
                 :zone-bands="zoneGeom&&zoneGeom.bands" :zone-policy="zonePolicy"
                 :selected-id="selectedId" :selected-corridor="selectedCorridor"
                 :follow-id="followId"
                 @drill="drill" @select-flight="pickFlight" @select-corridor="pickCorridor"/>
      </div>

      <div class="nrn-monitor" data-border-monitor>
        <strong>越界监视：本视图内 {{ border.inside||0 }} 架位于管制带</strong>
        <span>比对范围：{{ border.scope }}</span>
        <span>停飞航线 {{ border.blockedCorridors||0 }} 条<template v-if="(border.blockedNames||[]).length">（{{ (border.blockedNames||[]).slice(0,3).join('、') }}{{ (border.blockedNames||[]).length>3?' 等':'' }}）</template></span>
        <span>已改线 {{ border.reroutedCorridors||0 }} 条</span>
        <span v-if="fog.available">低能见度 {{ fog.counts.cities }} 城（&lt;1.5 km {{ fog.counts.BAN }} 城）</span>
        <span v-if="zones.available" title="规则化生成，非官方公布；与东北 69 站点法定管制区分开计数">
          净空 {{ zones.counts.airports }} 机场 · 覆盖 {{ ((zones.counts.coverageRatio||0)*100).toFixed(2) }}%</span>
        <span class="diag" v-if="showDiag">视口 {{ viewport.w }}×{{ viewport.h }} · 根容器 {{ viewport.root }}px</span>
        <span class="push" :class="{on:store.wsConnected}" :title="store.wsConnected?'雷达/实况/模型任一变化由服务端推送':'未连上推送，仅按需拉取'">
          {{ store.wsConnected?('推送 · '+pushAge+'s 前'):'未连推送' }}</span>
        <span class="quiet">{{ border.note }}</span>
      </div>

      <p class="nrn-legend" v-if="audience==='ops'">
        <i class="dot"></i>节点三级：省会/首府（大点+浅环）＞机场城市＞一般
        <i class="line"></i>航线同色同宽
        <i class="line warn"></i>琥珀＝绕飞航迹
        <i class="line bad"></i>红＝边境受限停飞
        <i class="zone"></i>琥珀圈＝机场净空限制区（规则化 DERIVED）
        <span v-if="virtualMode" class="virt">虚拟增强：回波与绕飞/停飞加亮</span>
      </p>
      <p class="nrn-legend air" v-else>
        <i class="zone"></i><template v-if="zonePolicy==='PROHIBITED'">红圈＝净空限制区（演示态：一律禁止进入）</template><template v-else>琥珀圈＝净空限制区（默认：可申请穿越）</template>
        <i class="line dim"></i>淡线＝航路（空域视角下不作为主体）
        <span class="quiet">几何按公开跑道方位与机场等级规则化生成，非官方公布</span>
        <span v-if="zoneBusy" class="quiet">净空几何载入中…</span>
        <span v-else-if="zoneErr" class="bad">净空几何不可用：{{ zoneErr }}</span>
      </p>
    </div>

    <!-- ================= 台账 / 情报：与原生页共用同一份组件 ================= -->
    <div class="nrn-table" v-show="view==='ledger'">
      <NationBriefing view="ledger" :payload="data" :flights="flights"
                      :minute="minute" :density="density" :selected-id="selectedId"
                      @select="pickFlight"/>
    </div>
    <div class="nrn-table" v-show="view==='intel'">
      <NationBriefing view="intel" :payload="data" :density="density"/>
    </div>

    <!-- ================= 处置 ================= -->
    <div class="nrn-table" v-show="view==='alerts'">
      <div class="nrn-table-hd">
        <h3>事件处置 <small>{{ alerts.length }} 条</small></h3>
        <p>低能见度、回波绕飞、边境停飞、放行暂缓四类。自动处置的是规则动作，待处置的需要人工确认。</p>
      </div>
      <ul class="nrn-alerts">
        <li v-for="row in alerts" :key="row.id" :class="row.severity">
          <b>{{ row.kind }}</b>
          <em>{{ row.place }}</em>
          <p>{{ row.detail }}</p>
          <p class="act">处置：{{ row.action }}</p>
          <span class="tag" :class="row.auto?'good':'warn'">{{ row.status }}</span>
        </li>
        <li v-if="!alerts.length" class="empty">本级暂无需要处置的事件</li>
      </ul>
    </div>

    <!-- ================= 右栏：分块统计 ================= -->
    <aside class="nrn-side" :class="{'wx-wide':mode==='weather'}">
      <div class="nrn-total">
        <div><b>{{ total.corridors||0 }}</b><span>航线</span></div>
        <div><b>{{ total.airborne||0 }}</b><span>在飞</span></div>
        <div :class="{alarm:total.delayed>0}"><b>{{ total.delayed||0 }}</b><span>绕飞</span></div>
        <div :class="{alarm:total.blocked>0}"><b>{{ total.blocked||0 }}</b><span>停飞</span></div>
        <div :class="{alarm:total.hold>0}"><b>{{ total.hold||0 }}</b><span>暂缓</span></div>
      </div>

      <!-- 上：区块。全国只列大区，点进去才换成省；再往里换城市 —— 一层只放一层 -->
      <div class="nrn-blocks">
        <template v-if="rollup.level==='nation'">
          <h3>各大区<small>点区块下钻</small></h3>
          <button class="nrn-region" v-for="region in rollup.regions" :key="region.id"
                  :title="`${region.name}：${region.total.corridors} 条航线（含跨省航线在本区计入，故各区之和大于全国 ${total.corridors} 条）`"
                  @click="go('region',region.id,region.name)">
            <b>{{ region.name }}</b>
            <span>{{ region.total.cities }} 市 · {{ region.total.corridors }} 条</span>
            <em :class="{warn:region.total.airborne>0}">在飞 {{ region.total.airborne }}</em>
            <em class="sub" v-if="region.total.blocked">停飞 {{ region.total.blocked }}</em>
          </button>
        </template>

        <template v-else-if="rollup.level==='region'">
          <h3>本区省份<small>点省下钻</small></h3>
          <button class="nrn-region" v-for="p in rollup.provinces" :key="p.name"
                  :title="`${p.name}：${p.corridors} 条航线（跨省航线在两端省份各计一次）`"
                  @click="go('province',p.name,p.name)">
            <b>{{ p.name }}</b>
            <span>{{ p.cities }} 市 · 机场 {{ p.airports }} · {{ p.corridors }} 条</span>
            <em :class="{warn:airOf(p.name,p.airborne)>0}">在飞 {{ airOf(p.name,p.airborne) }}</em>
            <em class="sub" v-if="p.blocked">停飞 {{ p.blocked }}</em>
          </button>
        </template>

        <template v-else-if="rollup.level==='province'">
          <h3>本省城市<small>{{ (rollup.cities||[]).length }} 个节点</small></h3>
          <button class="nrn-city" v-for="city in rollup.cities" :key="city.name"
                  @click="go('city',city.name,city.name)">
            <b>{{ shortName(city.name) }}<i :class="['tag',city.hasAirport?'good':'quiet']">{{ city.hasAirport?city.airport:'无机场' }}</i></b>
            <span>{{ city.feedTarget?('接驳 → '+shortName(city.feedTarget)):'' }} {{ city.corridors }} 条</span>
            <em :class="{warn:airOfCity(city.name,city.airborne)>0}">在飞 {{ airOfCity(city.name,city.airborne) }}</em>
          </button>
        </template>

        <template v-else>
          <h3>城市节点<small>{{ data.city?.name }}</small></h3>
          <div class="nrn-city-detail">
            <p><span>省</span><b>{{ data.city?.province }}</b></p>
            <p><span>机场</span><b>{{ data.city?.airport||'无（有专用接驳）' }}</b></p>
            <p><span>航线</span><b>{{ data.city?.links }} 条</b></p>
            <p><span>在飞</span><b>{{ data.city?.airborne }}</b></p>
            <p><span>相邻</span><b>{{ (data.city?.neighbours||[]).map(shortName).join('、') }}</b></p>
          </div>
        </template>
      </div>

      <!-- 双受众的另一半：空域视角的侧栏。同一套几何，换成"哪些点禁飞、边界在哪"的读法 -->
      <div class="nrn-zone" v-if="audience==='airspace'" data-zone-panel>
        <h4>空域净空
          <small>DERIVED · {{ zonePolicy==='PROHIBITED'?'一律禁飞':'可申请穿越' }}</small></h4>
        <p><span>受限额</span><b>{{ zoneCounts.airports||0 }} 机场</b></p>
        <p><span>限制区</span><b>{{ zoneCounts.limitZones||0 }} 个 · {{ zoneCounts.coverageSqKm||0 }} km²</b></p>
        <p><span>覆盖率</span><b>{{ ((zoneCounts.coverageRatio||0)*100).toFixed(2) }}% 陆域</b></p>
        <p><span>待审穿越</span><b v-if="zoneCrossings">{{ zoneCrossings.hit }} / {{ zoneCrossings.corridors }} 条（{{ ((zoneCrossings.ratio||0)*100).toFixed(0) }}%）</b><b v-else>—</b></p>
        <ul v-if="(zoneCrossings?.rows||[]).length">
          <li v-for="row in (zoneCrossings.rows||[]).slice(0,6)" :key="row.id">
            <b>{{ row.place }}</b>
            <em>{{ row.crossings }} 个限制区</em>
            <span>{{ (row.airports||[]).join('、') }}</span>
          </li>
        </ul>
        <p class="note">{{ zoneCrossings?.note||zones.note }}</p>
      </div>

      <!-- 下：气象。跟着上面的粒度走：全国看重点城市，进区看该区各市，进省看本省各市 -->
      <div class="nrn-wx" data-nation-weather>
        <h4>气象实况
          <small v-if="wxTotal">{{ wxTotal }} 城<template v-if="wxSourceText"> · {{ wxSourceText }}</template><template v-if="wxStale"> · 旧数据<template v-if="wxAgeText">（{{ wxAgeText }}）</template></template><template v-else-if="wxAgeText"> · {{ wxAgeText }}</template></small>
          <small v-else>{{ wxRefreshing?'补数中…（后台抓取多源实况）':(weatherMeta.expiredSnapshot?'快照超过 6 小时已作废，等重新抓取':'暂无实况') }}</small>
        </h4>
        <ul>
          <li v-for="row in wxRows" :key="row.name" :class="{bad:row.low}">
            <b>{{ row.short }}</b>
            <em :class="pBand(row.p)">{{ row.p==null?'—':(row.p*100).toFixed(0)+'%' }}</em>
            <span>{{ row.temp==null?'—':row.temp+'°' }}</span>
            <span>{{ row.wind==null?'—':row.wind+' m/s' }}</span>
            <span>{{ visText(row.vis) }}</span>
          </li>
          <li v-if="!wxRows.length" class="empty">
            {{ wxRefreshing?'实况补数中，约 1 分钟刷新后可见':'本级暂无逐市气象' }}</li>
        </ul>
      </div>

      <details class="nrn-border-card" v-if="(border.excludedCities||[]).length&&level==='nation'">
        <summary>边境 {{ border.excludeKm }} km 内 {{ (border.excludedCities||[]).length }} 城已退出通航</summary>
        <p>{{ (border.excludedCities||[]).map(c=>shortName(c.name)+' '+c.distanceKm+'km').join('、') }}</p>
      </details>
    </aside>
  </div>

  <!-- ================= 详情：班次 / 走廊 ================= -->
  <div class="nrn-detail" v-if="selectedFlight||selectedLine" data-nation-detail>
    <template v-if="selectedFlight">
      <header>
        <b>{{ selectedFlight.callsign }}</b>
        <code>{{ selectedFlight.id }}</code>
        <span class="tag" :class="selectedFlight.riskLevel==='HIGH'?'bad':(selectedFlight.riskLevel==='MEDIUM'?'warn':'good')">{{ selectedFlight.decisionLabel }}</span>
        <button class="follow" :class="{on:followId===selectedFlight.id}" @click="toggleFollow">
          {{ followId===selectedFlight.id?'取消跟随':'跟随此班次' }}</button>
        <button class="follow" :disabled="evidenceBusy" @click="loadEvidence">
          {{ evidenceBusy?'取证中…':'取证' }}</button>
        <button @click="selectedId='';clearEvidence()">收起</button>
      </header>
      <div class="cols">
        <div>
          <h4>班次</h4>
          <p><span>航线</span><b>{{ selectedFlight.fromName }} → {{ selectedFlight.toName }}</b></p>
          <p><span>计划</span><b>{{ selectedFlight.departAt }}–{{ selectedFlight.arriveAt }}</b></p>
          <p><span>已飞</span><b>{{ selectedFlight.elapsedMin }} / {{ selectedFlight.durationMin }} 分</b></p>
          <p><span>高度</span><b>{{ selectedFlight.altM }} m AGL</b></p>
          <p><span>速度</span><b>{{ selectedFlight.speedKmh }} km/h</b></p>
          <button class="mini" @click="locate">跳到起飞时刻</button>
        </div>
        <div>
          <h4>放行许可 <small>{{ selectedFlight.clearance?.statusLabel }}</small></h4>
          <p><span>航路</span><b>{{ selectedFlight.clearance?.route }}</b></p>
          <p><span>高度带</span><b>{{ selectedFlight.clearance?.altitudeBand }}</b></p>
          <p><span>时窗</span><b>{{ selectedFlight.clearance?.timeWindow }}</b></p>
          <p><span>条件</span><b>{{ (selectedFlight.clearance?.conditions||[]).join('；') }}</b></p>
        </div>
        <div>
          <h4>裁决依据 <small>规则派生</small></h4>
          <p><span>风险</span><b>{{ selectedFlight.riskP.toFixed(2) }}（{{ selectedFlight.riskLevelLabel }}）</b></p>
          <p v-for="(d,i) in selectedFlight.drivers" :key="i"><span>依据 {{ i+1 }}</span><b>{{ d }}</b></p>
          <p><span>反事实</span><b>不绕飞将暴露 {{ selectedFlight.exposure?.directMin||0 }} 分钟；绕飞后 0</b></p>
        </div>
        <div class="prof">
          <h4>高度剖面 <small>计划</small></h4>
          <svg viewBox="0 0 260 96" role="img" aria-label="班次高度剖面">
            <path d="M8 8V80H252" stroke="#2c4a60" fill="none"/>
            <polyline :points="(selectedFlight.altProfile||[]).map((p,i)=>`${8+i*244/Math.max(1,(selectedFlight.altProfile.length-1))},${80-p[1]*64/1200}`).join(' ')"
                      fill="none" stroke="#59dffc" stroke-width="1.8"/>
            <text x="10" y="92" fill="#7d9cb3" font-size="7.5">0 分</text>
            <text x="222" y="92" fill="#7d9cb3" font-size="7.5">{{ Math.round(selectedFlight.durationMin) }} 分</text>
            <text x="10" y="16" fill="#7d9cb3" font-size="7.5">1200 m</text>
          </svg>
        </div>
      </div>

      <div class="evidence" v-if="evidence||evidenceErr" data-nation-evidence>
        <p class="ev-err" v-if="evidenceErr">取证失败：{{ evidenceErr }}</p>
        <template v-else>
          <div class="ev-hd">
            <b>取证链</b>
            <span>{{ evidence.conclusion }}</span>
            <em>{{ evidence.steps.length }} 步 · {{ evidence.generatedAt }}</em>
          </div>
          <div class="ev-steps">
            <div class="ev-step" v-for="step in evidence.steps" :key="step.n">
              <h5><i>{{ step.n }}</i>{{ step.title }}</h5>
              <p v-for="row in step.rows" :key="row.label">
                <span>{{ row.label }}</span>
                <b>{{ row.value }}</b>
                <code :class="row.source">{{ row.source }}</code>
              </p>
            </div>
          </div>
          <p class="ev-note">{{ evidence.llm?.note }}</p>
          <p class="ev-note quiet">{{ evidence.discipline }}</p>
        </template>
      </div>
    </template>

    <template v-else-if="selectedLine">
      <header>
        <b>{{ selectedLine.fromName }} → {{ selectedLine.toName }}</b>
        <code>{{ selectedLine.id }}</code>
        <span class="tag" :class="selectedLine.borderBlocked?'bad':(selectedLine.detour?'warn':'good')">
          {{ selectedLine.borderBlocked?'边境停飞':(selectedLine.detour?'绕飞放行':'直飞') }}
        </span>
        <button @click="selectedCorridor=''">收起</button>
      </header>
      <div class="cols">
        <div>
          <h4>航线</h4>
          <p><span>类型</span><b>{{ selectedLine.kindLabel }}</b></p>
          <p><span>长度</span><b>{{ selectedLine.lengthKm }} km</b></p>
          <p><span>两端</span><b>{{ selectedLine.fromProvince }} / {{ selectedLine.toProvince }}</b></p>
          <p><span>边境</span><b>{{ selectedLine.borderDetour?'已改线避让':'未触发' }}</b></p>
        </div>
        <div>
          <h4>回波遭遇</h4>
          <p><span>绕飞</span><b>{{ selectedLine.detour?('外偏 '+selectedLine.detour.shiftKm+' km'):'未绕飞' }}</b></p>
          <p><span>暴露</span><b>{{ selectedLine.detour?('原航路 '+selectedLine.detour.hitKm+' km 穿回波'):'无' }}</b></p>
          <p><span>高度带</span><b>600–1100 m AGL</b></p>
          <p><span>班次</span><b>{{ flights.filter(f=>f.corridor===selectedLine.id).length }} 架在飞</b></p>
        </div>
        <div class="prof span2" v-if="corridorProfile">
          <h4>逐公里剖面 <small>{{ corridorProfile.totalKm }} km · {{ corridorProfile.segments.length }} 段 · 采样步长约 6 km</small></h4>
          <svg viewBox="0 0 320 92" preserveAspectRatio="none" role="img" aria-label="走廊逐公里回波剖面">
            <rect x="8" y="6" width="304" height="62" fill="rgba(8,22,34,.7)" stroke="rgba(70,110,140,.35)"/>
            <rect v-for="(seg,i) in corridorProfile.segments" :key="'sg'+i"
                  :x="8+304*seg.from/corridorProfile.totalKm"
                  :width="Math.max(1,304*(seg.to-seg.from)/corridorProfile.totalKm)"
                  y="6" height="62" :fill="BAND_COLOR[seg.band]"/>
            <polyline :points="profilePoints" fill="none" stroke="#59dffc" stroke-width="1.4"/>
            <text x="10" y="82" fill="#7d9cb3" font-size="7.5">0 km · {{ selectedLine.fromName }}</text>
            <text x="310" y="82" fill="#7d9cb3" font-size="7.5" text-anchor="end">{{ corridorProfile.totalKm }} km · {{ selectedLine.toName }}</text>
            <text x="10" y="14" fill="#7d9cb3" font-size="7.5">1100 m</text>
          </svg>
          <p class="quiet">{{ profileText }}</p>
          <p class="quiet" v-if="selectedLine.detour">
            琥珀色航迹＝按法线外偏 {{ selectedLine.detour.shiftKm }} km 后的实际航路；原航路穿回波 {{ selectedLine.detour.hitKm }} km。
          </p>
        </div>
      </div>
    </template>
  </div>
</section>
</template>

<style scoped>
.nrn{display:flex;flex-direction:column;gap:8px;min-height:0;height:100%;overflow:hidden;color:#cfe6f5}
.nrn-hd{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;padding:2px 2px 0}
.nrn-crumb{display:flex;align-items:center;gap:5px;font-size:13px}
.nrn-crumb button{background:none;border:0;color:#7fd4ff;cursor:pointer;font-size:13px;padding:2px 4px}
.nrn-crumb button:hover{text-decoration:underline}
.nrn-crumb .sep{color:#4f7288}
.nrn-crumb .back{margin-left:8px;border:1px solid #2c4a60;border-radius:5px;padding:2px 8px;color:#a8cee6}
.nrn-headline{margin:0;font-size:13.5px;color:#eaf6ff;letter-spacing:.2px}
.nrn-sub{margin:0;font-size:11.5px;color:#82a6bd}
.nrn-sub b{color:#cfe9f8;font-variant-numeric:tabular-nums}

.nrn-tabs{display:flex;gap:6px;border-bottom:1px solid rgba(70,110,140,.35);padding-bottom:6px}
.nrn-tabs button{background:transparent;border:1px solid transparent;color:#8fb2c8;padding:5px 13px;border-radius:6px;cursor:pointer;font-size:12.5px}
.nrn-tabs button.on{background:#17394d;border-color:#2e6b85;color:#bfe9ff}
.nrn-tabs em{font-style:normal;opacity:.75;margin-left:4px;font-size:11px}
.nrn-tabs em.bad{color:#ffb38a}

/* 双受众切换：和 tab 条同一视觉语言，但靠右，表示"换个读法"而不是"换一页" */
.nrn-aud{margin-left:auto;display:flex;gap:4px;align-items:center}
.nrn-aud button{background:transparent;border:1px solid rgba(70,110,140,.45);color:#8fb2c8;
  border-radius:5px;padding:3px 9px;font-size:11px;cursor:pointer}
.nrn-aud button.on{background:#17394d;border-color:#2e6b85;color:#bfe9ff}
.nrn-aud button.policy{border-color:rgba(245,190,60,.5);color:#ffd479}
.nrn-lift{margin:0;padding:4px 9px;border-radius:6px;font-size:11px;color:#ffd08a;
  background:rgba(70,50,14,.5);border:1px solid rgba(160,120,40,.45)}

/* 推演的立题行 */
.nrn-pick{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:4px 8px;border-radius:7px;
  background:rgba(14,36,52,.72);border:1px solid rgba(60,110,140,.4)}
.nrn-pick label{display:flex;align-items:center;gap:5px;font-size:11.5px;color:#8fb2c8}
.nrn-pick select{background:#10283a;border:1px solid #2b4c62;color:#cfe6f5;border-radius:5px;
  padding:3px 6px;font-size:11.5px;max-width:260px}
.nrn-pick .pick-note{font-size:11px;color:#a9cde2}
.nrn-pick .pick-note.quiet{color:#6f92a8}

.nrn-body{display:grid;gap:10px;min-height:0;flex:1;align-items:stretch;
  /* 右栏固定 560：再宽就只是把数字拉到离名字很远的地方；剩下的宽度给地图，
     地图多出来的部分会被 svg 居中留白，但总比"地图一条缝、右栏一大片"好看。 */
  grid-template-columns:minmax(0,1fr) 560px}
.nrn-body>.nrn-map{min-width:0;overflow:hidden}
.nrn-body>.nrn-side{min-width:0}
.nrn-body.no-map{grid-template-columns:minmax(0,1fr) 360px}

.nrn-map{position:relative;display:flex;flex-direction:column;min-height:0;gap:6px;min-width:0;width:auto}
.nrn-hint{margin:0;padding:5px 9px;border-radius:6px;font-size:11.5px;color:#a9cde2;
  background:rgba(20,60,80,.55);border:1px solid rgba(70,140,170,.35)}
.nrn-canvas{position:relative;flex:1;min-height:240px;border-radius:10px;overflow:hidden;
  border:1px solid rgba(70,110,140,.3)}
.nrn-tools{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:12px}
.nrn-tools button,.nrn-tools select{background:#10283a;border:1px solid #2b4c62;color:#a9cde2;border-radius:5px;padding:4px 9px;font-size:11.5px;cursor:pointer}
.nrn-tools button.on{background:#1d5670;border-color:#3f8ba8;color:#c8f0ff}
.nrn-tools button.play{background:#1b4d63;color:#d6f6ff;border-color:#3d8aa6}
.nrn-tools input[type=range]{flex:1;min-width:90px}
.nrn-tools .clock{font-variant-numeric:tabular-nums;color:#bfe9ff;font-size:12px}

.nrn-monitor{position:absolute;left:8px;right:8px;bottom:28px;z-index:4;
  padding:5px 9px;border:1px solid rgba(80,130,160,.35);border-radius:7px;
  background:rgba(10,26,38,.9);font-size:11px;color:#8fb2c8;
  display:flex;flex-wrap:wrap;gap:3px 12px;pointer-events:none}
.nrn-monitor strong{color:#ffd08a;font-weight:600}
.nrn-monitor .quiet{color:#6f92a8}
.nrn-monitor .push{color:#7d9cb3}
.nrn-monitor .push.on{color:#7fe0bb}
.nrn-legend{position:absolute;left:8px;right:8px;bottom:5px;z-index:4;margin:0;
  font-size:10.5px;color:#8fb2c8;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  background:rgba(8,18,28,.86);border-radius:6px;padding:2px 8px;pointer-events:none}
.nrn-legend i{display:inline-block;width:14px;height:2px;background:rgba(126,206,255,.62);margin-right:4px;vertical-align:middle}
.nrn-legend i.dot{width:6px;height:6px;border-radius:50%;background:#eaf6ff}
.nrn-legend i.warn{background:rgba(255,206,90,.9)}
.nrn-legend i.bad{background:rgba(226,92,74,.75)}
.nrn-legend i.zone{width:9px;height:9px;border-radius:50%;background:rgba(245,190,60,.22);
  border:1px solid rgba(245,190,60,.75)}
.nrn-legend i.dim{background:rgba(126,206,255,.3)}
.nrn-legend .quiet{color:#6f92a8}
.nrn-legend .bad{color:#ffa08a}
.nrn-legend .virt{color:#ffcf7a}

/* 空域视角侧栏 */
.nrn-zone{border:1px solid rgba(120,150,90,.35);border-radius:8px;background:rgba(18,34,22,.55);
  padding:6px 8px;display:flex;flex-direction:column;gap:2px;max-height:38%;min-height:0;overflow:auto}
.nrn-zone h4{margin:0 0 3px;font-size:11.5px;color:#cfe6b5;display:flex;gap:6px;align-items:baseline}
.nrn-zone h4 small{font-size:10px;color:#8a9c72;font-weight:400}
.nrn-zone p{margin:1px 0;display:grid;grid-template-columns:64px 1fr;gap:6px;font-size:11px}
.nrn-zone p>span{color:#8a9c72}
.nrn-zone p>b{font-weight:400;color:#dbeccb;font-variant-numeric:tabular-nums}
.nrn-zone p.note{display:block;margin-top:4px;font-size:10px;color:#7d8f66;line-height:1.5}
.nrn-zone ul{list-style:none;margin:4px 0 0;padding:0;display:flex;flex-direction:column;gap:3px}
.nrn-zone li{display:grid;grid-template-columns:1fr auto;gap:1px 6px;padding:3px 6px;border-radius:5px;
  background:rgba(24,44,28,.7);font-size:10.5px}
.nrn-zone li b{font-weight:500;color:#d7e8c6;grid-row:1;grid-column:1}
.nrn-zone li em{font-style:normal;color:#ffd479;grid-row:1;grid-column:2;white-space:nowrap}
.nrn-zone li span{grid-column:1/-1;color:#8a9c72;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.nrn-side{display:flex;flex-direction:column;gap:8px;min-height:0;padding-right:2px}
.nrn-side>*{flex:0 0 auto}
/* 层级列表按内容长，不抢剩余高度；剩余高度留给气象表 ——
   否则省层只有一个"本省城市"卡片时，下面会空出一大块，气象挤在底部几行里。 */
.nrn-blocks{display:flex;flex-direction:column;gap:5px;overflow:auto;min-height:0;flex:0 1 auto;max-height:46%}
.nrn-blocks h3{margin:0 0 2px;font-size:11.5px;color:#a9cde2}
.nrn-blocks h3 small{margin-left:6px;font-size:10px;color:#6f92a8;font-weight:400}
/* 一级一个按钮：全国=大区，进区=省，进省=市 */
.nrn-region,.nrn-city{display:grid;grid-template-columns:auto 1fr auto;gap:0 8px;width:100%;text-align:left;
  background:rgba(16,40,56,.75);border:1px solid rgba(60,100,130,.4);border-radius:6px;padding:5px 8px;
  color:#cfe6f5;cursor:pointer;font-size:12px;align-items:baseline}
.nrn-region b{grid-column:1}
.nrn-region span{grid-column:2;text-align:right;font-size:10.5px;color:#7d9cb3}
.nrn-region em{grid-column:3;font-size:10.5px;color:#8fb2c8;white-space:nowrap}
.nrn-region em.sub{display:none}
.nrn-region:hover,.nrn-city:hover{background:rgba(34,86,112,.8);border-color:#3f8ba8}
.nrn-region b,.nrn-city b{font-weight:600}
.nrn-region span,.nrn-city span{grid-column:1;font-size:10.5px;color:#7d9cb3}
.nrn-region em,.nrn-city em{grid-row:1;grid-column:2;font-style:normal;font-size:10.5px;color:#8fb2c8}
.nrn-region em.warn,.nrn-city em.warn{color:#8ef0ff}
.nrn-region em.sub{grid-row:2;color:#ffb38a}
/* 气象面板：占满剩余高度，自己滚 */
.nrn-side.wx-wide .nrn-blocks{flex:0 0 auto;display:grid;grid-template-columns:1fr 1fr;gap:4px;overflow:visible}
.nrn-side.wx-wide .nrn-blocks h3{grid-column:1 / -1;margin:0}
.nrn-side.wx-wide .nrn-region{padding:3px 6px;font-size:11px}
.nrn-side.wx-wide .nrn-region span{font-size:9.5px}
.nrn-side.wx-wide .nrn-wx{flex:1 1 auto;max-height:none;min-height:0}
.nrn-wx{flex:1 1 auto;min-height:132px;max-height:none;display:flex;flex-direction:column;
  border:1px solid rgba(60,100,130,.4);border-radius:8px;background:rgba(10,26,38,.6);padding:6px 8px}
.nrn-wx h4{margin:0 0 4px;font-size:11.5px;color:#a9cde2;display:flex;gap:6px;align-items:baseline}
.nrn-wx h4 small{font-size:10px;color:#6f92a8;font-weight:400}
.nrn-wx ul{list-style:none;margin:0;padding:0;overflow:auto;flex:1;display:flex;flex-direction:column;gap:2px}
.nrn-wx li{display:grid;grid-template-columns:minmax(68px,1fr) 44px 40px 52px 62px;gap:5px;font-size:10.5px;
  padding:2px 5px;border-radius:4px;background:rgba(14,34,48,.75);color:#a8c6d8;white-space:nowrap}
.nrn-wx li.bad{outline:1px solid rgba(226,75,74,.45)}
.nrn-wx li b{color:#d9eefb;font-weight:500;overflow:hidden;text-overflow:ellipsis}
.nrn-wx li em{font-style:normal;text-align:right;font-variant-numeric:tabular-nums;color:#8fb2c8}
.nrn-wx li em.watch{color:#cfe6b0}
.nrn-wx li em.warn{color:#ffd479}
.nrn-wx li em.bad{color:#ff8f6b}
.nrn-wx li span{text-align:right;font-variant-numeric:tabular-nums}
.nrn-wx li.empty{grid-template-columns:1fr;color:#6f92a8;text-align:center}
.nrn-total{display:grid;grid-template-columns:repeat(5,1fr);gap:4px;background:rgba(12,32,46,.8);
  border:1px solid rgba(70,110,140,.4);border-radius:8px;padding:7px 6px}
.nrn-total div{text-align:center}
.nrn-total b{display:block;font-size:15px;color:#eaf6ff;font-variant-numeric:tabular-nums}
.nrn-total span{font-size:10px;color:#7d9cb3}
.nrn-total .alarm b{color:#ffab7a}
.nrn-side h3{margin:4px 0 0;font-size:12px;color:#a9cde2;font-weight:600}
.nrn-side h3 small{margin-left:6px;font-size:10px;color:#6f92a8;font-weight:400}
.nrn-block{border:1px solid rgba(70,110,140,.32);border-radius:8px;overflow:hidden;background:rgba(10,26,38,.6)}
.nrn-block-hd{width:100%;display:grid;grid-template-columns:1fr auto;gap:2px 6px;text-align:left;
  background:rgba(20,52,72,.55);border:0;color:#cfe6f5;padding:6px 9px;cursor:pointer}
.nrn-block-hd b{font-size:12.5px}
.nrn-block-hd span{font-size:10.5px;color:#82a6bd;grid-column:1}
.nrn-block-hd em{font-style:normal;font-size:10.5px;color:#8fb2c8;grid-column:2;grid-row:1}
.nrn-block-hd em.warn{color:#ffb38a}
.nrn-block-list{list-style:none;margin:0;padding:2px 0}
.nrn-block-list li{display:grid;grid-template-columns:1fr auto;gap:2px 6px;padding:4px 9px;cursor:pointer;font-size:11.5px}
.nrn-block-list li:hover{background:rgba(40,96,124,.35)}
.nrn-block-list b{font-weight:500;color:#cfe6f5}
.nrn-block-list span{font-size:10px;color:#7d9cb3;grid-column:1}
.nrn-block-list em{font-style:normal;font-size:10.5px;color:#8fb2c8;grid-row:1;grid-column:2}
.nrn-block-list em.warn{color:#8ef0ff}
/* 省一级的按钮行：三列对齐，和区块头同一套网格 */
.nrn-prov{width:100%;display:grid;grid-template-columns:1fr auto;gap:2px 6px;text-align:left;
  background:transparent;border:0;border-top:1px solid rgba(60,95,120,.22);color:#cfe6f5;
  padding:5px 9px;cursor:pointer;font-size:11.5px}
.nrn-prov:hover{background:rgba(40,96,124,.35)}
.nrn-prov b{font-weight:500;color:#cfe6f5}
.nrn-prov span{grid-column:1;font-size:10px;color:#7d9cb3}
.nrn-prov em{grid-row:1;grid-column:2;font-style:normal;font-size:10.5px;color:#8fb2c8}
.nrn-prov em.warn{color:#8ef0ff}
.nrn-city-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px;overflow:auto}
.nrn-city-list li{display:grid;grid-template-columns:1fr auto;gap:2px 6px;padding:5px 8px;border-radius:6px;
  background:rgba(12,32,46,.6);cursor:pointer;font-size:11.5px}
.nrn-city-list li:hover{background:rgba(40,96,124,.45)}
.nrn-city-list span{font-size:10px;color:#7d9cb3;grid-column:1}
.nrn-city-list em{font-style:normal;font-size:10.5px;color:#8fb2c8;grid-row:1;grid-column:2}
.nrn-city-list em.warn{color:#8ef0ff}
.tag{display:inline-block;font-style:normal;font-size:10px;padding:1px 5px;border-radius:4px;margin-left:4px}
.tag.good{background:rgba(70,190,150,.18);color:#7fe0bb}
.tag.warn{background:rgba(245,190,60,.18);color:#ffd479}
.tag.bad{background:rgba(238,80,60,.2);color:#ffa08a}
.tag.quiet{background:rgba(120,150,175,.15);color:#9fb8c9}

.nrn-city-detail{display:flex;flex-direction:column;gap:4px;font-size:11.5px}
.nrn-city-detail p{margin:0;display:grid;grid-template-columns:48px 1fr;gap:6px}
.nrn-city-detail span{color:#7d9cb3}
.nrn-city-detail b{font-weight:500;color:#d9eefb}
.nrn-border-card{border:1px solid rgba(200,120,80,.35);border-radius:7px;padding:4px 8px;background:rgba(60,28,16,.35)}
.nrn-border-card summary{font-size:11px;color:#ffc0a0;cursor:pointer;list-style:none}
.nrn-border-card summary::-webkit-details-marker{display:none}
.nrn-border-card p{margin:0;font-size:10.5px;color:#e8b9a2;line-height:1.6}
.nrn-border-card small{color:#a98a7a;font-size:10px}

.nrn-table{display:flex;flex-direction:column;gap:8px;min-height:0}
.nrn-table-hd h3{margin:0;font-size:13px;color:#eaf6ff}
.nrn-table-hd h3 small{margin-left:8px;font-size:11px;color:#7d9cb3;font-weight:400}
.nrn-table-hd p{margin:3px 0 0;font-size:11px;color:#7d9cb3}
.nrn-scroll{overflow:auto;min-height:0;flex:1;border:1px solid rgba(70,110,140,.3);border-radius:8px}
.nrn-table table{width:100%;border-collapse:collapse;font-size:11.5px}
.nrn-table th{position:sticky;top:0;background:#0f2a3c;color:#8fb2c8;font-weight:500;text-align:left;
  padding:6px 8px;border-bottom:1px solid rgba(70,110,140,.4);white-space:nowrap;font-size:11px}
.nrn-table td{padding:5px 8px;border-bottom:1px solid rgba(50,80,100,.25);color:#cfe6f5;vertical-align:top}
.nrn-table td small{display:block;font-size:10px;color:#7d9cb3}
.nrn-table tr.sel td{background:rgba(40,110,140,.35)}
.nrn-table tbody tr{cursor:pointer}
.nrn-table tbody tr:hover td{background:rgba(30,70,95,.35)}
.nrn-table tr.future td{color:#9dbccf;opacity:.85}
.nrn-table td.bad{color:#ffa08a}
.nrn-table td.empty{text-align:center;color:#6f92a8;padding:18px}
.risk{font-variant-numeric:tabular-nums;font-size:11px;padding:1px 5px;border-radius:4px}
.risk.HIGH{background:rgba(238,80,60,.22);color:#ffa08a}
.risk.MEDIUM{background:rgba(245,190,60,.18);color:#ffd479}
.risk.LOW{background:rgba(70,190,150,.16);color:#7fe0bb}

.nrn-weather{margin-top:4px}
.nrn-weather h3{margin:0 0 4px;font-size:12px;color:#a9cde2}
.nrn-weather ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:3px}
.nrn-weather li{display:flex;gap:6px;align-items:baseline;font-size:11px;padding:3px 6px;border-radius:5px;background:rgba(12,32,46,.6)}
.nrn-weather li.bad{outline:1px solid rgba(226,75,74,.5)}
.nrn-weather span{color:#8fb2c8}

.nrn-alerts{list-style:none;margin:0;padding:0;display:grid;gap:7px;overflow:auto;min-height:0;
  /* auto-fit 而不是 auto-fill：事件聚合后常常只有 2–5 条，
     auto-fill 会保留空列、卡片挤在左边，右边空一大片。 */
  grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));
  align-content:start}
.nrn-alerts li{border:1px solid rgba(70,110,140,.35);border-left-width:3px;border-radius:7px;padding:7px 9px;background:rgba(10,26,38,.62)}
.nrn-alerts li.bad{border-left-color:#ee5040}
.nrn-alerts li.warn{border-left-color:#f5be3c}
.nrn-alerts li.empty{grid-column:1/-1;text-align:center;color:#6f92a8;padding:20px}
.nrn-alerts b{font-size:12px;color:#eaf6ff}
.nrn-alerts em{font-style:normal;font-size:11px;color:#8fb2c8;margin-left:8px}
.nrn-alerts p{margin:3px 0 0;font-size:11px;color:#a8c6d8;line-height:1.5}
.nrn-alerts p.act{color:#ffd08a}
.nrn-alerts .tag{margin-top:4px}

.nrn-detail{border:1px solid rgba(70,110,140,.4);border-radius:9px;background:rgba(10,26,38,.9);padding:8px 10px}
.nrn-detail header{display:flex;align-items:center;gap:9px;font-size:12.5px;padding-bottom:6px;border-bottom:1px solid rgba(70,110,140,.3)}
.nrn-detail header b{color:#eaf6ff;font-size:13px}
.nrn-detail header code{font-size:10.5px;color:#7fb6d6}
.nrn-detail header button.follow{color:#8ef0ff;border-color:#2e6b85}
.nrn-detail header button.follow.on{background:#1d5670;color:#d6f6ff}
.nrn-detail header button{margin-left:auto;background:none;border:1px solid #2c4a60;color:#9dbccf;border-radius:5px;padding:2px 9px;font-size:11px;cursor:pointer}
.nrn-detail .cols{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding-top:7px}
.nrn-detail h4{margin:0 0 4px;font-size:11px;color:#8fb2c8;font-weight:600}
.nrn-detail h4 small{margin-left:5px;color:#6f92a8;font-weight:400}
.nrn-detail p{margin:2px 0;display:grid;grid-template-columns:52px 1fr;gap:6px;font-size:11px}
.nrn-detail p>span{color:#7493a8}
.nrn-detail p>b{font-weight:400;color:#d9eefb}
.nrn-detail .prof svg{width:100%;height:88px}
.nrn-detail .prof.span2{grid-column:span 2}
@media(max-width:1180px){.nrn-detail .prof.span2{grid-column:span 2}}
.nrn-detail .mini{margin-top:5px;background:#17394d;border:1px solid #2e6b85;color:#bfe9ff;border-radius:5px;padding:3px 8px;font-size:10.5px;cursor:pointer}
.nrn-detail .quiet{display:block;color:#7d9cb3;font-size:10.5px;line-height:1.6}

.evidence{margin-top:8px;border-top:1px solid rgba(70,110,140,.3);padding-top:7px}
.ev-hd{display:flex;align-items:baseline;gap:10px;font-size:11.5px;flex-wrap:wrap}
.ev-hd b{color:#eaf6ff}
.ev-hd span{color:#8ef0ff}
.ev-hd em{font-style:normal;color:#6f92a8;font-size:10.5px;margin-left:auto}
.ev-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-top:6px}
.ev-step{border:1px solid rgba(70,110,140,.3);border-radius:7px;padding:6px 8px;background:rgba(8,22,34,.55)}
.ev-step h5{margin:0 0 4px;font-size:11px;color:#a9cde2;display:flex;align-items:center;gap:5px;font-weight:600}
.ev-step h5 i{font-style:normal;width:14px;height:14px;line-height:14px;text-align:center;border-radius:50%;
  background:rgba(60,130,160,.35);color:#bfe9ff;font-size:9px}
.ev-step p{margin:2px 0;display:grid;grid-template-columns:auto 1fr auto;gap:6px;font-size:10.5px;align-items:baseline}
.ev-step p>span{color:#7493a8}
.ev-step p>b{font-weight:400;color:#d9eefb}
.ev-step code{font-size:9px;padding:0 4px;border-radius:3px;color:#9fb8c9;background:rgba(120,150,175,.12)}
.ev-step code.PUBLIC{color:#7fe0bb;background:rgba(70,190,150,.14)}
.ev-step code.DERIVED{color:#ffd479;background:rgba(245,190,60,.14)}
.ev-step code.OFFICIAL{color:#c6b4ff;background:rgba(160,140,255,.14)}
.ev-note{margin:6px 0 0;font-size:10.5px;color:#ffcf7a;line-height:1.6}
.ev-note.quiet{color:#6f92a8}
.ev-err{color:#ffa08a;font-size:11px}
.nrn-state{margin:6px 0;color:#8fb2c8;font-size:12px}
.nrn-state.bad{color:#ffa08a}
.nrn-state button{margin-left:8px;background:#17394d;border:1px solid #2e6b85;color:#bfe9ff;border-radius:5px;padding:2px 8px;cursor:pointer}

/* 1366×768 是评委席最常见的分辨率（实测项目里记过这一条）。
 * 这一档只做两件事：**把小字抬到 11px 地板**，再靠收紧内边距把高度省回来 ——
 * 抬字号会把一屏撑破，所以必须同时压缩 padding，否则地图会被挤没。 */
@media(max-width:1500px){
  .nrn-monitor,.nrn-legend,.nrn-sub{font-size:11px}
  .nrn-total span,.nrn-block-hd span,.nrn-prov span,.nrn-city-list span{font-size:11px}
  .nrn-total b{font-size:14px}
  .nrn-block-hd b,.nrn-prov b,.nrn-city-list b{font-size:11.5px}
  .nrn-block-hd em,.nrn-prov em,.nrn-city-list em{font-size:11px}
  .nrn-tools{gap:5px}
  .nrn-tools button,.nrn-tools select{font-size:11px;padding:3px 7px}
  .nrn-tabs button{font-size:11.5px;padding:4px 10px}
  .nrn-detail p,.nrn-detail p>b{font-size:11px}
  .nrn-detail header b{font-size:12.5px}
  .nrn-side h3{font-size:11.5px}
  .tag{font-size:10.5px}
  .nrn-table td small{font-size:10.5px}
  .ev-step p{font-size:10.5px}
}
/* 768 高的屏：把详情区限高并允许内部滚动，别让地图被压没 */
@media(max-height:820px){
  .nrn-canvas{min-height:220px}
  .nrn-detail{max-height:44vh;overflow:auto}
  .nrn-side{max-height:none}
}
@media(max-width:1400px){
  .nrn-body{grid-template-columns:minmax(0,1fr) 400px}
  .nrn-tools{gap:4px}
  .nrn-tools button,.nrn-tools select{font-size:10.5px;padding:2px 6px}
  .nrn-tools input[type=range]{min-width:80px}
  .nrn-total b{font-size:15px}
  .nrn-total span{font-size:10px}
}
@media(max-width:1180px){
  .nrn-body{grid-template-columns:minmax(0,1fr) 320px}
  .nrn-detail .cols{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:900px){
  .nrn-body{grid-template-columns:1fr;min-height:0;overflow:auto}
  .nrn-canvas{min-height:320px;max-height:52vh}
  .nrn-side{max-height:none;flex-direction:row;gap:10px;align-items:flex-start}
  .nrn-blocks,.nrn-wx{flex:1 1 0;min-width:0}
  .nrn-wx{max-height:34vh}
}
@media(max-width:760px){
  .nrn-body{grid-template-columns:1fr;min-height:0}
  .nrn-side{max-height:190px;flex-direction:column}
  .nrn-canvas{min-height:200px}
}
</style>
