<script setup>
import {computed,defineAsyncComponent,onMounted,onUnmounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'
import {store} from '../../store.js'
import NationDeduce from './NationDeduce.vue'
import CorridorBrowser from './CorridorBrowser.vue'
import NationMap from './NationMap.vue'
import NationBriefing from './NationBriefing.vue'
import {parseScope,scopeKey} from '../../traffic/scope.js'

// 首页首屏用不到它，没必要为它多等一个 chunk。

// 全国运行台：态势 / 台账 / 情报 / 处置 四个视图共用同一份 `payload`。
//
// 三条纪律：
//   ① **数字按块写**：每级、每省、每市都显示自己的航线/在飞/异常，总数单独在顶部；
//   ② **班次是对象**：图上点哪一架，台账就选哪一架，详情里就是这一架的许可与剖面；
//   ③ **逐级重新请求**：下钻与返回都清空上一屏，内存里不留整棵树。
const props=defineProps({
  compact:{type:Boolean,default:false},
  // 处置事件 / 日志行跳进来时要定位到的走廊号（NC-0200 这类）。
  // 必须是 prop：写成同名的本地 ref，父级传进来的值会被空的本地值遮住（实测跳不过去）。
  focusCorridor:{type:String,default:''},
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
  // 从导航进来时的一句"该做什么"。这些页面共用一张图，
  // 不给提示的话用户看到的就是一张空地图，不知道从哪下手。
  hint:{type:String,default:''},
})
const emit=defineEmits(['scope-change','open-corridor','tick'])

const level=ref('nation')
const ident=ref('')
const trail=ref([{level:'nation',id:'',label:'全国'}])
const data=ref(null)
const view=ref(props.initialView||'map')
const error=ref(''),loading=ref(false)
// 首屏"到底是在转圈还是卡住了"：冷启动实测要 30 秒左右（进程刚起、雷达帧/319 城实况/模型概率
// 都要联网算），只写一句"正在加载"会让人以为坏了。这里记开始时间，每秒更新一次已等待秒数。
const loadingSince=ref(0)
const waitedSeconds=ref(0)
let waitTimer=0
watch(loading,(on)=>{
  clearInterval(waitTimer)
  if(!on){ waitedSeconds.value=0; return }
  loadingSince.value=Date.now()
  waitedSeconds.value=0
  waitTimer=setInterval(()=>{
    waitedSeconds.value=Math.round((Date.now()-loadingSince.value)/1000)
  },1000)
})
onUnmounted(()=>clearInterval(waitTimer))
const busy=ref('')
const evidence=ref(null)
const evidenceBusy=ref(false)
const evidenceErr=ref('')

const minute=ref(60)
// 地图上的飞行汽车是"活的"：默认就在走（像 Flightradar24 那样打开就在动），
// 随时可暂停、可拖时间轴。推进由本地 rAF 负责，后端快照每分钟对齐一次。
const playing=ref(true)
const speed=ref(1)                    // 分钟/秒：0.25≈15×、1=60×、5=300×
// 连续时刻（浮点分钟）。minute 是整数、驱动后端取数；frameMinute 只驱动地图插值，
// 两者差值永远在 [0,1) 内 —— 飞机因此是"滑过去"的，不是整分钟一格一格跳。
const frameMinute=ref(60)
const radarOn=ref(true)
const fogOn=ref(true)
const virtualMode=ref(false)
const density=ref('full')
const selectedId=ref('')
const selectedCorridor=ref('')
const followId=ref('')

// —— 视角：平面 / 倾斜（SVG 透视）/ 三维（maplibre 真透视） ——
// 所以按钮点了也会被挡回来，并说清"为什么不能看"，而不是默默什么都不发生。
const fps=ref(0)
// —— 双受众视角 ——
// 同一套几何两种读法：运行视角看航线与班次，空域视角看净空边界与等级。
// 不做第二套数据，只是图层显隐 + 侧栏内容切换。
const audience=ref('ops')
const zoneGeom=ref(null)
// 禁飞区在首页默认开（用户 2026-11-11 要求：气象与非气象都要在首页看得到）
const zoneOn=ref(true)
// 走廊页/推演页：左侧列表选中的走廊。外部（处置、日志）跳进来时用 focusCorridor 指定。
function onCorridorPick(row){
  if(!row) return
  const f=(flights.value||[]).find(x=>x.corridor===row.id)
  if(f) pickFlight(f)
}
// 虚拟气象演示包：后端 ?virtual=1 生成合成回波并**重算**绕飞与停飞，
// 不是前端加一层滤镜 —— 关掉立刻回到真实回波，两条路径互不污染。
const virtualWx=ref(false)
const wxVirtual=computed(()=>!!data.value?.radar?.virtual)
// —— 航线显示：三档开关 + 条数上限（用户要"人工决定开多少个"） ——
const LINE_KEY='alc.traffic.lines'
const lineKinds=ref({cross:true,feed:true,intra:false})
const lineLimit=ref(291)
const linePanel=ref(false)
try{
  const saved=JSON.parse(localStorage.getItem(LINE_KEY)||'null')
  if(saved&&saved.kinds){ lineKinds.value={...lineKinds.value,...saved.kinds}; lineLimit.value=Number(saved.limit)||291 }
}catch(_){}
watch([lineKinds,lineLimit],()=>{
  try{localStorage.setItem(LINE_KEY,JSON.stringify({kinds:lineKinds.value,limit:lineLimit.value}))}catch(_){}
},{deep:true})
const lineStats=computed(()=>{
  const rows=data.value?.corridors||[]
  const pick=rows.filter(r=>(r.kind==='CROSS'&&lineKinds.value.cross)
    ||(r.kind==='AIRPORT_FEED'&&lineKinds.value.feed)
    ||(r.kind==='INTRA'&&lineKinds.value.intra))
  // 图上"在飞必画"：地图会把在飞班次所在的走廊并进显示集合（不管筛选与上限）。
  // 这里的 shown 必须与地图同口径，否则按钮上写 291、图上却有 328 条。
  const base=pick.slice().sort((a,b)=>(b.lengthKm||0)-(a.lengthKm||0))
    .slice(0,Math.max(0,lineLimit.value))
  const shown=new Set(base.map(r=>r.id))
  const flying=new Set(flights.value.filter(f=>f.decision!=='HOLD').map(f=>f.corridor))
  let forced=0
  for(const row of rows){
    if(shown.has(row.id)||!flying.has(row.id)) continue
    shown.add(row.id);forced+=1
  }
  return {total:rows.length,matched:pick.length,shown:shown.size,forced}
})
const zoneBusy=ref(false)
const zoneErr=ref('')
const zonePolicy=ref('APPROVAL_REQUIRED')

const flights=ref([])
const live=ref({corridors:0,airborne:0,delayed:0,hold:0,blocked:0,lowVisCities:0})
const byProvince=ref({})
const byCity=ref({})
let clockRaf=null,pushTimer=null,fetchAt=0,seq=0

const MINUTES=180
const mapRef=ref(null)

const summary=computed(()=>data.value?.summary||{})
const rollup=computed(()=>data.value?.rollup||{level:'nation',total:{},regions:[],provinces:[],cities:[]})
const total=computed(()=>({...(rollup.value.total||{}),...live.value}))
const radarMeta=computed(()=>data.value?.radar||{})
// 每档上限 200 片是硬截断：一旦不显示"被截掉了"，读者会以为图上就是全部回波。
const echoStats=computed(()=>radarMeta.value.stats||{truncated:false,totalRings:0,keptRings:0,cap:200})
const border=computed(()=>data.value?.border||{})
const fog=computed(()=>data.value?.fog||{available:false,counts:{},bands:{},cities:[]})
// 机场净空（DERIVED）。与 border 的 OFFICIAL 管制区分开显示：
// 两套几何一个是官方公布、一个是规则化生成，混在一起说会被追问依据。
const zones=computed(()=>data.value?.zones||{available:false,counts:{},rows:[]})
// 走廊页的地图要吃净空环（`bands`），不是 NationPanel 自己的 zonePolys
const zoneBandsGeom=computed(()=>zoneGeom.value?.bands||null)

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

// 定位/复位只对平面图这一套。
const globeRef=ref(null)   // 已下线三维，保留 ref 只为兼容模板里的旧引用
function activeMap(){
  return mapRef.value||null
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

// —— 净空几何按需取 ——
// 287 个 28 点环约 250 KB，放进主载荷会让首屏多 0.2 秒，所以走独立接口、按需取。
// 现在首页默认就要画禁飞区（用户 2026-11-11 定），所以进页面后自动取一次；
// 取过一次就留着，切视角/切层级不再重复请求。
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

// 数字占位：载荷未到时显示"——"，而不是 0。0 是"算过，确实没有"，两者不能混。
function num(v){ return data.value ? (v??0) : '—' }

const headline=computed(()=>{
  // 还没拿到本级载荷时**不能**输出"0 条航线 · 在飞 0 架"：
  // 冷启动要等 30 秒左右，这行 0 会被读成"系统说全国没有航线"。
  if(!data.value) return '正在读取本级航线网…'
  const t=total.value
  // 不再以"全国/华北"开头：面包屑上一行已经写明在哪一级，
  // 两行连着读会变成"全国 全国 492 条航线…"。这里只讲这一刻的数字。
  const parts=[`${t.corridors||0} 条航线`,`在飞 ${t.airborne||0} 架`]
  if(t.delayed)parts.push(`绕飞 ${t.delayed} 架`)
  if(t.hold)parts.push(`延期 ${t.hold} 架`)
  if(t.blocked)parts.push(`停飞 ${t.blocked} 条`)
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

// 这批 flights 数据"自己是哪一分钟"的（后端 payload.minute）。
// 地图的本地推进以它为基准，不再以"请求的分钟"为基准 ——
// 否则分钟一翻、新数据还在路上，adv 归零 → 飞机倒退一分钟再被弹回（V1.0.4 #5）。
const flightsMinute=ref(-1)
async function loadFlights(){
  const now=Date.now()
  if(now<fetchAt) return
  fetchAt=now+850
  const my=++seq
  try{
    const payload=await requestJson(
      `/api/traffic/v2/nation/flights?level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${Math.round(minute.value)}${virtualWx.value?'&virtual=1':''}`,
      {timeoutMs:20000})
    if(my!==seq) return
    flights.value=payload.flights||[]
    flightsMinute.value=Number.isFinite(payload.minute)?payload.minute:Math.round(minute.value)
    byProvince.value=payload.byProvince||{}
    byCity.value=payload.byCity||{}
    live.value={...live.value,...(payload.traffic||{})}
    // 选中的那架如果这一分钟已经落地/飞出窗口，选中态必须跟着清掉 ——
    // 否则详情卡还挂着一架"库里已经没有"的飞机，切层级后更是只留下一条画不出来的航线。
    if(selectedId.value&&!flights.value.some(f=>f.id===selectedId.value)){
      selectedId.value='';followId.value='';clearEvidence()
    }
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
      `/api/traffic/v2/nation?level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${Math.round(minute.value)}${virtualWx.value?'&virtual=1':''}`,
      // 冷启动实测 30 秒上下（进程刚起时的第一次全国载荷），45 秒的旧上限会把"正在预热"
      // 直接判成失败；抬到 90 秒，并靠上面的"已等待 Ns"让人知道它还在动。
      {timeoutMs:90000})
    flights.value=data.value?.flights||[]
    flightsMinute.value=Number.isFinite(data.value?.minute)?data.value.minute:Math.round(minute.value)
    // 层级以服务端为准：请求的是 city、后端兜底成 province 时，界面必须跟着回落，
    // 不能一边显示"临沧市"的面包屑、一边给全省的数字与城市列表。
    if(data.value?.level&&data.value.level!==level.value) level.value=data.value.level
    const gotId=data.value?.id==null?'':String(data.value.id)
    if(gotId!==ident.value&&['region','province','city'].includes(level.value)) ident.value=gotId
    trail.value=trailFrom(data.value)
    emitScope()
    live.value={...(data.value?.traffic||{})}
    byProvince.value={}
    byCity.value={}
    resetMap()
    if(zoneOn.value) ensureZones()
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}

// —— 面包屑 = 层级链，不是点击历史（V1.0.4）——
// 以前 `go()` 把点击目标 append 到 trail 尾部：在市级点一下地图空白（底图多边形是背景）
// 就会拼出「全国 › 临沧市 › 云南省」这种不存在的路径，页面还停在省口径 ——
// 用户看到的是"我点了临沧，右边却在讲云南别的机场"。
// 现在 trail 由**服务端返回的层级字段**重建（nation→region→province→city 恒为一条链），
// 后端把 city 兜底成 province 时，链也自动只到省，不会多出一个假的市级。
function trailFrom(d){
  const chain=[{level:'nation',id:'',label:'全国'}]
  if(!d) return chain
  // 只认 payload 里**当前层级**的 province 字段。
  // 不能拿 `provinces[0]` 兜底：大区层的 `provinces` 是"本区所有省"，
  // 取第一个会把「华北」错拼成「全国›华北›北京市」（实测就是这样退不回去的）。
  const prov=d.province||null
  if(d.region&&d.region.name) chain.push({level:'region',id:d.region.id||'',label:d.region.name})
  else if(prov&&prov.regionLabel) chain.push({level:'region',id:prov.region||'',label:prov.regionLabel})
  if(prov&&prov.name) chain.push({level:'province',id:prov.name,label:prov.name})
  if(d.level==='city'&&d.city&&d.city.name) chain.push({level:'city',id:d.city.name,label:d.city.name})
  return chain
}
function go(nextLevel,nextId,nextLabel){
  level.value=nextLevel
  ident.value=nextId||''
  // 先把链改成"到目标为止"的合理前缀，等载荷回来再用 trailFrom 校正
  const rank={nation:0,region:1,province:2,city:3}
  const keep=trail.value.filter(item=>rank[item.level]<rank[nextLevel])
  trail.value=[...keep,{level:nextLevel,id:nextId||'',label:nextLabel||nextId}]
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
  // 市级是本项目最低一级：到了市，点底图多边形（它在市级只是背景）不应该往上跳。
  // 以前会跳回省，还留下一条「全国›临沧市›云南省」的假路径。
  if(nextLevel==='province'&&(level.value==='province'||level.value==='city')) return
  if(nextLevel==='city'&&level.value==='city') return
  go(nextLevel,nextId,label)
}

function togglePlay(){ playing.value=!playing.value }

// 切虚拟气象要整份重取（网络、绕飞、事件、禁飞区全变），
// 只刷航班不够 —— 航班表是从 network 里切出来的。
function toggleVirtual(){
  virtualWx.value=!virtualWx.value
  load()
}

// 常驻 rAF：播放时才推进 frameMinute，暂停时把它对齐回 minute。
// 用 rAF 而不是 setInterval：60fps 的连续性才能让"移动"成立，
// 1 秒一跳的 setInterval 只能做出"瞬移"。
function startClock(){
  if(clockRaf||typeof requestAnimationFrame==='undefined') return
  let last=performance.now()
  const tick=(now)=>{
    // 30fps 足够：1 秒才走 1 分钟，每帧位移不到 0.2px。
    // 压到 30fps 是为了少算一半的 flightDots（97 架 × 每帧重建对象）。
    if(now-last<32){ clockRaf=requestAnimationFrame(tick); return }
    const dt=Math.min(.25,(now-last)/1000)   // 切标签页回来时 dt 会很大，压住免得瞬移
    last=now
    if(playing.value){
      let next=frameMinute.value+dt*speed.value
      if(next>=MINUTES) next-=MINUTES
      frameMinute.value=next
      const m=Math.floor(next)
      if(m!==minute.value){ minute.value=m; loadFlights() }
    }else if(Math.abs(frameMinute.value-minute.value)>.001){
      frameMinute.value=minute.value
    }
    clockRaf=requestAnimationFrame(tick)
  }
  clockRaf=requestAnimationFrame(tick)
}
// 拖时间轴：连续时钟要跟着跳，否则会被下一帧拉回去
function onSeek(){ frameMinute.value=minute.value; loadFlights() }

// 顶栏要显示"推演时刻"，但全国台有自己的 minute（0–1440），和东北那套（0–480）
// 不是一个量，所以由这里把真实状态报上去，不让顶栏去猜。
let tickAt=0
watch([minute,playing],([m,on])=>{
  const now=Date.now()
  if(now-tickAt<500&&on) return
  tickAt=now
  emit('tick',{minute:Number(m)||0,playing:!!on})
},{immediate:true})

// 打开任何对象（班次 / 事件 / 走廊）之前先停表。
// 时间在跑的时候点开一架飞机，选中的瞬间它在 A 点，读两行字它已经飘到 B 点；
// 推演结论里的"当前时刻"也会跟着变，同一句话读两次不一样。
// 只停推演时钟，右上角北京时间（nav-timebase）走的是真实时间，不受影响。
function pauseForInspect(){ playing.value=false }

// 事件卡片的点击：一条事件聚合了多个城市，点开时先进第一个成员城市，
// 该班次若还在飞就同时选中它 —— 否则读者只能对着"青海省 · 2 处"猜是哪两处。
function openAlert(row){
  pauseForInspect()
  const places=row.places||[]
  // 用户要的落点变了：处置点开不再"切到城市让用户自己找"，而是**直接进那个班次的走廊**，
  // 在那里做人工裁决。走廊号就藏在班次 id 里（NC-0270#-1 → NC-0270），不用再查表。
  const fid=row.flightId||(row.memberIds||[]).map(x=>String(x).replace(/^EV-[A-Z]+-/,''))[0]||''
  const corridor=String(fid).split('#')[0]
  if(corridor&&corridor.includes('-')){
    emit('open-corridor',{corridor, flightId:fid})
    return
  }
  // 聚合事件没有单一班次时退回"切到成员城市"，至少让人看见影响面
  const raw=String(places[0]||'')
  const city=raw.split('→')[0].trim()
  const cityHit=(data.value?.nodes||[]).some(n=>n.name===city)
  if(row.flightId){
    const hit=flights.value.find(f=>f.id===row.flightId)
    if(hit){ pickFlight(hit); return }
  }
  if(cityHit&&city!==ident.value){
    go('city',city,city)
    // 切城市会重新取数；等它回来再选中这条事件指向的班次，否则会被 load() 清掉
    if(row.flightId) setTimeout(()=>{
      const hit=flights.value.find(f=>f.id===row.flightId)
      if(hit) pickFlight(hit)
    },1300)
    return
  }
  if(!cityHit&&row.province&&trail.value.length<2){ go('province',row.province,row.province); return }
  // 已经在那个城市：把关联班次选出来
  const ids=row.memberIds||[]
  const hit=flights.value.find(f=>ids.includes(f.id))
  if(hit) pickFlight(hit)
}

function pickFlight(flight){
  pauseForInspect()
  if(selectedId.value!==flight.id){followId.value='';clearEvidence()}
  selectedId.value=flight.id
  selectedCorridor.value=''
}
function toggleFollow(){
  followId.value=followId.value===selectedId.value?'':selectedId.value
}
function pickCorridor(line){
  pauseForInspect()
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

// 时间轴推进时，只刷新"在飞/绕飞/延期"这三个会变的数；航线数、停飞数是静态的，
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
// 市级右栏只讲这一座城（V1.0.4，用户第 4 条）：
// 省 / 机场 / 航线 / 在飞 / 相邻 + 该市自己的实况 + 与它相连的走廊。
// 以前这一屏会退回"本省城市 13 个节点"，用户点了临沧却在读云南别的机场。
const cityCard=computed(()=>{
  if(level.value!=='city') return null
  const c=data.value?.city
  if(!c||!c.name) return null
  const wx=wxRows.value.find(row=>row.name===c.name)||null
  const lines=(data.value?.corridors||[]).map(row=>({
    id:row.id,fromName:row.fromName,toName:row.toName,lengthKm:row.lengthKm,
    kindLabel:row.kindLabel||'',blocked:!!row.borderBlocked,detour:!!row.detour,
  }))
  return {city:c,wx,lines}
})
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
  // 只写用了哪几个源。以前写成 "open-meteo 319"，和前面的 "319 城" 重复，
  // 读者会以为是两个不同的数。各源贡献放在 title 里。
  const parts=[]
  if(src.OPEN_METEO) parts.push('open-meteo')
  if(src.WTTR) parts.push('wttr')
  return parts.length?('源 '+parts.join(' + ')):''
})
const wxSourceDetail=computed(()=>{
  const src=weatherMeta.value.sources||{}
  const parts=[]
  if(src.OPEN_METEO) parts.push(`open-meteo 供 ${src.OPEN_METEO} 城`)
  if(src.WTTR) parts.push(`wttr 补 ${src.WTTR} 城`)
  const errs=(weatherMeta.value.errors||[]).filter(Boolean)
  return [...parts, ...errs].join('；')||'未记录数据来源'
})
function pBand(p){return p==null?'':(p>=0.6?'bad':(p>=0.35?'warn':(p>=0.15?'watch':'')))}
// 气象表要"一眼看出哪列是异常"，所以温度/风速/能见度各自上色。
// 阈值集中在这里，别散到模板里 —— 否则改一次要翻三个地方。
// 推演/走廊已改成「左侧列表 + 右侧详情」，两级下拉（选城市→选班次）随之作废。
// 这里只留一句说明：同一件事不要有两个入口，旧代码留着只会被后来的人当成还在用。
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
  frameMinute.value=minute.value
  startClock()
  measureViewport()
  window.addEventListener('resize',measureViewport)
  load()
  // 推送计时用独立定时器：不能和推演播放共用一个变量，否则一开播就把计时器顶掉
  pushTimer=setInterval(()=>{pushAge.value+=1},1000)
})
onUnmounted(()=>{
  window.removeEventListener('resize',measureViewport)
  if(clockRaf) cancelAnimationFrame(clockRaf)
  clockRaf=null
  if(pushTimer) clearInterval(pushTimer)
})
</script>

<template>
<section class="nrn">
  <!-- 头部三层：面包屑（我在哪）→ 态势一句话（这一刻怎么样）→ 规模与口径（这个视图覆盖什么）。
       以前三层挤在一条 flex 里换行，读起来是一句几十字的长句，
       "492 条航线"和"319 市有实况"在同一行并列，分不清哪个是态势、哪个是分母。 -->
  <header class="nrn-hd">
    <div class="nrn-hd-top">
      <div class="nrn-crumb">
        <template v-for="(item,index) in trail" :key="item.level+item.id">
          <button v-if="index<trail.length-1" @click="go(item.level,item.id,item.label)">{{ item.label }}</button>
          <b v-else>{{ item.label }}</b>
          <span v-if="index<trail.length-1" class="sep">›</span>
        </template>
        <button v-if="trail.length>1" class="back" @click="back">返回上一级</button>
      </div>
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
    </div>
    <!-- 指标块代替"492 条航线 · 在飞 111 架 · 绕飞 2 架…"那一长串。
         以前五个数用间隔号串成一句，哪个数对应哪个指标要靠位置猜；
         数字位数一变整行还会左右挪，读起来像在动。现在一块一个指标：
         上面是数字（等宽、定宽），下面是名称，变动时给 ▲/▼。 -->
    <div class="nrn-metrics" data-nation-headline>
      <div class="m"><b>{{ num(total.corridors) }}</b><span>航线</span></div>
      <div class="m"><b>{{ num(total.airborne) }}</b><span>在飞</span></div>
      <div class="m" :class="{warn:total.delayed>0}"><b>{{ num(total.delayed) }}</b><span>绕飞</span></div>
      <div class="m" :class="{bad:total.blocked>0}"><b>{{ num(total.blocked) }}</b><span>停飞</span></div>
      <div class="m" :class="{warn:total.hold>0}"><b>{{ num(total.hold) }}</b><span>延期</span></div>
      <div class="m"><b>{{ num(total.lowVisCities) }}</b><span>低能见度城市</span></div>
    </div>
    <p class="nrn-sub">
      纳入 <b>{{ num(summary.provinces) }}</b> 省 · <b>{{ num(summary.cities) }}</b> 市 ·
      <b>{{ num(summary.airports) }}</b> 机场 · <b>{{ num(summary.feedCities) }}</b> 市无机场（专用接驳）·
      <b>{{ num(summary.weatherCities) }}</b> 市有实况
      <!-- 演示包必须自带角标：合成回波看起来和实况一模一样，
           不在页头挂一个"虚拟"，任何人截图出去都会当成真实天气。 -->
      <em class="nrn-virt" v-if="wxVirtual" data-virtual-badge>
        虚拟气象 · 合成回波，非实况
      </em>
    </p>
  </header>

  <!-- 推演页的"立题"行：先选对象，再看链路。不给选择器的话，
       这一页只能靠在地图上盲点，点不中就什么都没发生。 -->
  <p class="nrn-state" v-if="loading">
    <template v-if="waitedSeconds<4">正在加载本级数据…</template>
    <template v-else>
      正在预热 <b>{{ waitedSeconds }}s</b> —— 服务刚启动时要把雷达回波、逐市实况与概率算完，
      首次通常 30 秒左右；算完这一次之后都是秒开。
      <button v-if="waitedSeconds>=60" @click="load">仍要重试</button>
    </template>
  </p>
  <p class="nrn-state bad" v-else-if="error">本级不可用 · {{ error }}<button @click="load">重试</button></p>

  <!-- 注意：这两条必须是**各自独立**的 v-if。
       `nrn-body` 原本是承接 loading/error 的 `v-else-if`，在它前面的任何 v-if
       都会把链条打断 —— 提示条有值时整个内容区会被排除掉（实测整页空白）。
       所以这里显式写全条件，不用 else-if 链。 -->
  <p class="nrn-hint" v-if="hint&&mode!=='card'&&data&&!loading&&!error" data-nation-hint>{{ hint }}</p>
  <div class="nrn-body" v-if="data&&!loading&&!error" :class="{'no-map':view!=='map','card-mode':mode==='corridor'||mode==='card'}">
    <!-- 走廊 / 推演：左列表 + 右(这条走廊的地图 + 数据 or 推演链路)。
         这一层不再用"全国地图 + 右栏统计"，因为那一层看不出"这一条航线本身"。 -->
    <CorridorBrowser v-if="mode==='corridor'||mode==='card'"
                     :mode="mode==='card'?'card':'corridor'"
                     :data="data" :flights="flights" :minute="minute"
                     :zone-bands="zoneOn?zoneBandsGeom:null"
                     :focus-corridor="props.focusCorridor"
                     @select="onCorridorPick"/>

    <!-- ================= 态势 ================= -->
    <div class="nrn-map" v-show="view==='map'" v-if="mode!=='corridor'&&mode!=='card'">
      <div class="nrn-tools">
        <button class="play" @click="togglePlay">{{ playing?'Ⅱ 暂停':'▶ 推演' }}</button>
        <input type="range" min="0" :max="MINUTES" step="1" v-model.number="minute"
               @input="onSeek" aria-label="推演时间"/>
        <b class="clock">{{ clock(minute) }}</b>
        <select v-model.number="speed" aria-label="推演倍速">
          <option :value="0.25">15 倍速</option>
          <option :value="1">60 倍速</option>
          <option :value="5">300 倍速</option>
        </select>
        <button :class="{on:radarOn}" @click="radarOn=!radarOn"
                :title="`雷达回波：公开拼图裁剪到国内，三档轮廓按面积排序（本帧 ${echoStats.keptRings||0} 片${echoStats.truncated?'，已截断':''}）`">
          回波<em v-if="echoStats.keptRings" class="nrn-cnt">{{ echoStats.keptRings }}</em></button>
        <button :class="{on:fogOn}" @click="fogOn=!fogOn" :disabled="!fog.available">雾区</button>
        <button :class="{on:lineStats.shown>0}" @click="linePanel=!linePanel"
                :title="`显示哪些航线：跨省主干 / 机场接驳 / 省内短途；条数可以自己拖${lineStats.forced?`。其中 ${lineStats.forced} 条因为此刻有班次在飞而强制显示`:''}`">
          航线 {{ lineStats.shown }}/{{ lineStats.total }}</button>
        <button :class="{on:virtualWx}" @click="toggleVirtual" data-virtual-toggle
                :title="'虚拟气象：只替换雷达回波与雾，气温/风/能见度仍是实况；按同一套判据重算绕飞与停飞'">
          {{ virtualWx?'虚拟气象 · 开':'实测气象' }}</button>
        <button :class="{on:zoneOn}" @click="zoneOn=!zoneOn; zoneOn&&ensureZones()"
                :title="'禁飞区：机场净空 + 强回波，红色多边形框；关掉连绕飞一起隐藏'">禁飞</button>
        <select v-model="density" aria-label="信息密度"
                title="精简：只有航线和城市名；标准：城市胶囊 + 航班编号与高度；详细：再加速度与状态">
          <option value="min">精简</option>
          <option value="full">标准</option>
          <option value="slim">详细</option>
        </select>
        <button :disabled="!radarBBox" @click="locateLayer('radar')">定位回波</button>
        <button :disabled="!fog.bbox" @click="locateLayer('fog')">定位雾区</button>
        <button @click="resetMap()">复位</button>
      </div>

      <!-- 航线显示控制：三档开关 + 条数滑块（用户 2026-11-11 要求"人工决定开多少个"） -->
      <div class="nrn-linepanel" v-if="linePanel" data-line-panel>
        <label><input type="checkbox" v-model="lineKinds.cross"/> 跨省主干 <small>30 条</small></label>
        <label><input type="checkbox" v-model="lineKinds.feed"/> 机场接驳 <small>261 条</small></label>
        <label><input type="checkbox" v-model="lineKinds.intra"/> 省内短途 <small>201 条</small></label>
        <div class="nrn-linerange">
          <span>显示条数</span>
          <input type="range" min="0" :max="Math.max(1,lineStats.matched)" step="1"
                 v-model.number="lineLimit" aria-label="航线显示条数"/>
          <b>{{ lineStats.shown }}</b>
        </div>
        <p class="nrn-linehint">按航程从长到短截取：只开 50 条时看到的是骨架，不是随机 50 条。<template v-if="lineStats.forced">另有 <b>{{ lineStats.forced }}</b> 条因为此刻有班次在飞而强制显示 —— 天上出现一架飞机，它脚下就必须有那条走廊。</template></p>
        <button class="nrn-lineall" @click="lineLimit=0">全部关闭</button>
      </div>


      <!-- V1.0.5：三维 / 倾斜 / 地形三档全部下线，只保留平面矢量图。
           理由是那三档各有各的别扭（透视下标签要反向缩放、地形色带和回波抢注意力），
           而这一页要回答的是"哪片天不能飞"，不是"山有多高"。 -->
      <div class="nrn-canvas">
      <NationMap ref="mapRef" :data="data" :flights="flights" :minute="minute"
                 :frame-minute="frameMinute" :data-minute="flightsMinute"
                 :radar-on="radarOn" :fog-on="fogOn"
                 :density="density" :virtual-mode="virtualMode" :audience="audience"
                 :zone-bands="zoneOn&&zoneGeom?zoneGeom.bands:null"
                 :line-kinds="lineKinds" :line-limit="lineLimit" :zone-policy="zonePolicy"
                 :selected-id="selectedId" :selected-corridor="selectedCorridor"
                 :follow-id="followId"
                 @drill="drill" @select-flight="pickFlight" @select-corridor="pickCorridor"/>
      </div>

      <!-- 选中班次时把底部两条浮层压暗：这一刻用户看的是那一架，
           边界监视与图例退到背景，移上去还能读。 -->
      <div class="nrn-mapfoot" :class="{dim:!!selectedFlight}">
      <div class="nrn-monitor" data-border-monitor>
        <!-- 口径写进 title，不上主行：主行放"这一刻是什么"，规则解释放悬停。
             先前这里既有"比对范围：…30 km 为预警带"整句，又有末尾一句 border.note，
             两条长句把主行挤成两行，反而看不清"到底几架在管制带"。 -->
        <strong :title="`${border.scope}。${border.note}`">边界监视 <b>{{ border.inside||0 }}</b> 架在管制带</strong>
        <span>停飞 {{ border.blockedCorridors||0 }} 条<template v-if="(border.blockedNames||[]).length">（{{ (border.blockedNames||[]).slice(0,3).join('、') }}{{ (border.blockedNames||[]).length>3?' 等':'' }}）</template></span>
        <span>改线 {{ border.reroutedCorridors||0 }} 条</span>
        <span v-if="fog.available" title="能见度低于 3 km 计低能见度；低于 1.5 km 计浓雾">低能见度 {{ fog.counts.cities }} 城（浓雾 {{ fog.counts.BAN }}）</span>
        <span v-if="zones.available" title="规则化生成，非官方公布；与东北 69 站点法定管制区分开计数">
          净空 {{ zones.counts.airports }} 机场 · 覆盖 {{ ((zones.counts.coverageRatio||0)*100).toFixed(2) }}%</span>
        <span class="diag" v-if="showDiag">视口 {{ viewport.w }}×{{ viewport.h }} · 根容器 {{ viewport.root }}px</span>
        <span class="push" :class="{on:store.wsConnected}" :title="store.wsConnected?'雷达/实况/模型任一变化由服务端推送':'未连上推送，仅按需拉取'">
          {{ store.wsConnected?('推送 · '+pushAge+'s 前'):'未连推送' }}</span>
      </div>

      <p class="nrn-legend" v-if="audience==='ops'">
        <span v-if="echoStats.truncated" class="nrn-echo-note" data-echo-truncated>
          回波过多，已按面积取前 {{ echoStats.cap }} 片（原 {{ echoStats.totalRings }} 片）
        </span>
        <i class="star"></i>北京
        <i class="dot"></i>城市
        <!-- V1.0.4：城市点外面那圈红环以前在图上没有任何出处，用户直接问"这是什么"。
             现在进图例，措辞与顶部结论条的"低能见 N 城"同一口径。 -->
        <i class="ring"></i>低能见城市
        <i class="line"></i>航线
        <i class="line warn"></i>绕飞
        <i class="box"></i>{{ level==='province'||level==='city' ? '禁飞区' : '禁飞区（下钻可见）' }}
        <i class="tri"></i>应急
        <span v-if="virtualMode" class="virt">虚拟增强</span>
      </p>
      <p class="nrn-legend air" v-else>
        <i class="zone"></i><template v-if="zonePolicy==='PROHIBITED'">红圈＝净空限制区（演示态：一律禁止进入）</template><template v-else>琥珀圈＝净空限制区（默认：可申请穿越）</template>
        <i class="line dim"></i>淡线＝航路（空域视角下不作为主体）
        <span class="quiet">几何按公开跑道方位与机场等级规则化生成，非官方公布</span>
        <span v-if="zoneBusy" class="quiet">净空几何载入中…</span>
        <span v-else-if="zoneErr" class="bad">净空几何不可用：{{ zoneErr }}</span>
      </p>
      </div>
    </div>

    <!-- ================= 台账 / 情报：与原生页共用同一份组件 ================= -->
    <div class="nrn-table" v-show="view==='ledger'">
      <NationBriefing view="ledger" :variant="mode==='evidence'?'evidence':'ledger'"
                      :payload="data" :flights="flights"
                      :minute="minute" :density="density" :selected-id="selectedId"
                      @select="pickFlight"/>
    </div>
    <!-- 情报 = 两张表：先"在飞班次情报"（这一班为什么这么判），再"空域情报"（机场与净空）。
         两段都吃同一份 payload，不再各自发一次请求。 -->
    <div class="nrn-table" v-show="view==='intel'">
      <NationBriefing view="ledger" variant="briefing"
                      :payload="data" :flights="flights" :minute="minute" :density="density"/>
      <NationBriefing view="intel" :payload="data" :flights="flights"
                      :minute="minute" :density="density"/>
    </div>

    <!-- ================= 处置 ================= -->
    <div class="nrn-table" v-show="view==='alerts'">
      <div class="nrn-table-hd">
        <h3>事件处置 <small>{{ alerts.length }} 条</small></h3>
        <p>四类：低能见度、空域受限、回波绕飞、延期起飞。规则动作自动给出处置建议，需人工确认的标为待处置。</p>
      </div>
      <ul class="nrn-alerts">
        <li v-for="row in alerts" :key="row.id" :class="row.severity"
            role="button" tabindex="0" data-alert-row
            :title="'点开：定位到' + ((row.places&&row.places[0])||'该事件所在城市')"
            @click="openAlert(row)" @keydown.enter.prevent="openAlert(row)"
            @keydown.space.prevent="openAlert(row)">
          <b>{{ row.kind }}</b>
          <em>{{ row.place }}</em>
          <p>{{ row.detail }}</p>
          <p class="act">处置：{{ row.action }}</p>
          <div class="nrn-alert-foot">
            <span class="tag" :class="row.auto?'good':'warn'">{{ row.status }}</span>
            <span class="nrn-alert-go" v-if="(row.places||[]).length||row.flightId">定位 ›</span>
            <span class="nrn-alert-more" v-if="(row.places||[]).length>1">
              成员：{{ (row.places||[]).slice(0,3).join('、') }}{{ (row.places||[]).length>3?' 等':'' }}
            </span>
          </div>
        </li>
        <li v-if="!alerts.length" class="empty">本级暂无需要处置的事件</li>
      </ul>
    </div>

    <!-- ================= 右栏：分块统计 ================= -->
    <aside class="nrn-side" v-if="mode!=='corridor'&&mode!=='card'" :class="{'wx-wide':mode==='weather'}">
      <div class="nrn-total">
        <div><b>{{ total.corridors||0 }}</b><span>航线</span></div>
        <div><b>{{ total.airborne||0 }}</b><span>在飞</span></div>
        <div :class="{alarm:total.delayed>0}"><b>{{ total.delayed||0 }}</b><span>绕飞</span></div>
        <div :class="{alarm:total.blocked>0}"><b>{{ total.blocked||0 }}</b><span>停飞</span></div>
        <div :class="{alarm:total.hold>0}"><b>{{ total.hold||0 }}</b><span>延期</span></div>
      </div>

      <!-- 上：区块。全国只列大区，点进去才换成省；再往里换城市 —— 一层只放一层 -->
      <!-- 推演：六段链路。与态势共用同一栏，但内容完全不同 ——
           之前两页长得一样，是因为推演根本没有自己的面板，直接复用了右栏。 -->
      <NationDeduce v-if="mode==='card'" :flight="selectedFlight" :minute="minute" :paused="!playing"/>

      <div class="nrn-blocks" v-if="mode!=='card'">
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
            <p v-if="cityCard?.wx"><span>低能见概率</span><b :class="{warn:(cityCard.wx.p||0)>=.35}">{{ cityCard.wx.p==null?'—':(cityCard.wx.p*100).toFixed(0)+'%' }}</b></p>
            <p v-if="cityCard?.wx"><span>实况</span><b>{{ cityCard.wx.temp==null?'—':cityCard.wx.temp+'°' }} · {{ cityCard.wx.wind==null?'—':cityCard.wx.wind+' m/s' }} · 能见 {{ visText(cityCard.wx.vis) }}</b></p>
          </div>
          <!-- 市级是本项目最低一级：这一屏只讲这一座城，不列本省别的机场。
               与它相连的走廊在这里可以直接点开（落到走廊页做推演/裁决）。 -->
          <div class="nrn-city-lines" v-if="cityCard?.lines?.length">
            <button v-for="row in cityCard.lines" :key="row.id" :data-city-corridor="row.id"
                    :title="`${row.kindLabel||'航线'} · ${row.lengthKm} km · 点开这条走廊`"
                    @click="emit('open-corridor',{corridor:row.id})">
              <b>{{ shortName(row.fromName) }} ↔ {{ shortName(row.toName) }}</b>
              <span>{{ row.lengthKm }} km<template v-if="row.detour"> · 绕飞</template><template v-if="row.blocked"> · 停飞</template></span>
            </button>
          </div>
        </template>
      </div>

      <!-- 双受众的另一半：空域视角的侧栏。同一套几何，换成"哪些点禁飞、边界在哪"的读法 -->
      <div class="nrn-zone" v-if="mode!=='card'&&audience==='airspace'" data-zone-panel>
        <h4>空域禁飞区
          <small>规则化生成 · {{ zonePolicy==='PROHIBITED'?'一律禁飞':'可申请穿越' }}</small></h4>
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
      <div class="nrn-wx" v-if="mode!=='card'" data-nation-weather>
        <h4 :title="wxSourceDetail">气象实况
          <small v-if="wxTotal">{{ wxTotal }} 城<template v-if="wxSourceText"> · {{ wxSourceText }}</template><template v-if="wxStale"> · 旧数据<template v-if="wxAgeText">（{{ wxAgeText }}）</template></template><template v-else-if="wxAgeText"> · {{ wxAgeText }}</template></small>
          <small v-else>{{ wxRefreshing?'补数中…（后台抓取多源实况）':(weatherMeta.expiredSnapshot?'快照超过 6 小时已作废，等重新抓取':'暂无实况') }}</small>
        </h4>
        <ul>
          <!-- 表头：五列如果没有表头，第二列的百分比会被当成"降水概率"。
               它其实是 ml-v3 算的低能见概率，必须写清楚。 -->
          <li class="head" aria-hidden="true">
            <b>城市</b><em title="ml-v3 模型算出的低能见概率，0.35 以上进入预警带">低能见概率</em>
            <span>温度</span><span>风速</span><span>能见度</span>
          </li>
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
    </aside>
  </div>

  <!-- ================= 详情：班次 / 走廊 ================= -->
  <div class="nrn-detail" v-if="mode!=='card'&&(selectedFlight||selectedLine)" data-nation-detail>
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
            <!-- 模型状态做成一枚小标：已配置就只报"能用 + 走的哪个文件"，不占正文；
                 未配置才展开那段可执行的说明（琥珀色，属于"要你动手"的话）。 -->
            <i class="ev-llm" :class="{off:!evidence.llm?.configured}"
               :title="evidence.llm?.note">
              {{ evidence.llm?.configured ? '大模型就绪 · '+(evidence.llm?.model||'') : '大模型未配置' }}
            </i>
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
          <p class="ev-note" v-if="evidence.llm && !evidence.llm.configured">{{ evidence.llm.note }}</p>
          <p class="ev-note quiet">{{ evidence.discipline }}</p>
        </template>
      </div>
    </template>

    <template v-else-if="selectedLine">
      <header>
        <b>{{ selectedLine.fromName }} → {{ selectedLine.toName }}</b>
        <code>{{ selectedLine.id }}</code>
        <span class="tag" :class="selectedLine.borderBlocked?'bad':(selectedLine.detour?'warn':'good')">
          {{ selectedLine.borderBlocked?'停飞':(selectedLine.detour?'绕飞放行':'直飞') }}
        </span>
        <button @click="selectedCorridor=''">收起</button>
      </header>
      <div class="cols">
        <div>
          <h4>航线</h4>
          <p><span>类型</span><b>{{ selectedLine.kindLabel }}</b></p>
          <p><span>长度</span><b>{{ selectedLine.lengthKm }} km</b></p>
          <p><span>两端</span><b>{{ selectedLine.fromProvince }} / {{ selectedLine.toProvince }}</b></p>
          <p><span>绕飞避让</span><b>{{ selectedLine.borderDetour?'已改线':'未触发' }}</b></p>
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
.nrn-hd{display:flex;flex-direction:column;gap:2px;padding:2px 2px 0}
.nrn-hd-top{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.nrn-crumb{display:flex;align-items:center;gap:5px;font-size:13px}
.nrn-crumb button{background:none;border:0;color:#7fd4ff;cursor:pointer;font-size:13px;padding:2px 4px}
.nrn-crumb button:hover{text-decoration:underline}
.nrn-crumb .sep{color:#4f7288}
.nrn-crumb .back{margin-left:8px;border:1px solid #2c4a60;border-radius:5px;padding:2px 8px;color:#a8cee6}
.nrn-metrics{display:flex;gap:0;margin:2px 0 1px;flex-wrap:wrap}
.nrn-metrics .m{display:flex;flex-direction:column;gap:1px;padding:0 14px;min-width:74px;
  border-left:1px solid rgba(70,110,140,.3)}
.nrn-metrics .m:first-child{padding-left:0;border-left:0}
.nrn-metrics b{font-size:19px;line-height:1.15;color:#eaf6ff;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:.5px}
.nrn-metrics span{font-size:10.5px;color:#82a6bd;white-space:nowrap}
.nrn-metrics .m.warn b{color:#ffc857}
.nrn-metrics .m.bad b{color:#ff8d78}
.nrn-sub{margin:0;font-size:11.5px;color:#82a6bd}
.nrn-sub b{color:#cfe9f8;font-variant-numeric:tabular-nums}

/* 双受众切换：和 tab 条同一视觉语言，但靠右，表示"换个读法"而不是"换一页" */
.nrn-aud{margin-left:auto;display:flex;gap:4px;align-items:center}
.nrn-aud button{background:transparent;border:1px solid rgba(70,110,140,.45);color:#8fb2c8;
  border-radius:5px;padding:3px 9px;font-size:11px;cursor:pointer}
.nrn-aud button.on{background:#17394d;border-color:#2e6b85;color:#bfe9ff}
.nrn-aud button.policy{border-color:rgba(245,190,60,.5);color:#ffd479}
.nrn-cnt{margin-left:3px;font-style:normal;font-size:9.5px;opacity:.62;font-variant-numeric:tabular-nums}
.nrn-echo-note{margin-right:8px;font-size:10px;color:#ffc857}
html[data-theme="light"] .nrn-echo-note{color:#a4610a}
.nrn-virt{margin-left:8px;font-style:normal;font-size:10px;padding:1px 7px;border-radius:999px;
  color:#ffd08a;background:rgba(200,140,30,.16);border:1px solid rgba(220,170,60,.55)}
html[data-theme="light"] .nrn-virt{color:#8a5a00;background:#fdf3e0;border-color:#e0bb78}
.nrn-linepanel{position:absolute;top:52px;left:14px;z-index:9;width:250px;
  display:flex;flex-direction:column;gap:6px;padding:9px 11px;border-radius:9px;
  background:rgba(9,24,36,.97);border:1px solid rgba(70,120,155,.6);
  box-shadow:0 14px 30px -18px rgba(0,0,0,.95);font-size:11.5px;color:#b8d3e6}
.nrn-linepanel label{display:flex;align-items:center;gap:6px;cursor:pointer}
.nrn-linepanel label small{margin-left:auto;color:#7d9cb3}
.nrn-linerange{display:flex;align-items:center;gap:7px;margin-top:2px}
.nrn-linerange span{white-space:nowrap;color:#8fb2c8}
.nrn-linerange input{flex:1;min-width:0}
.nrn-linerange b{color:#8ef0ff;font-variant-numeric:tabular-nums}
.nrn-linehint{margin:0;font-size:10.5px;line-height:1.5;color:#6f92a8}
.nrn-lineall{align-self:flex-start;background:none;border:1px solid #2c4a60;color:#9dbccf;
  border-radius:5px;padding:3px 8px;font-size:10.5px;cursor:pointer}
html[data-theme="light"] .nrn-linepanel{background:rgba(255,255,255,.98);border-color:#cfdcea;
  color:#3f5c76;box-shadow:0 14px 26px -18px rgba(20,50,80,.45)}
html[data-theme="light"] .nrn-linepanel label small{color:#7d97ad}
html[data-theme="light"] .nrn-linerange span{color:#5b7a92}
html[data-theme="light"] .nrn-linepanel b{color:#0b7ea6}
html[data-theme="light"] .nrn-linehint{color:#7d97ad}
html[data-theme="light"] .nrn-lineall{background:#f2f7fc;border-color:#cfdcea;color:#31556f}
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
/* 推演：右栏内容比一屏高。grid 行默认按内容高度撑开，会把右栏顶出容器、
   压到下面的详情卡上（实测板子直接盖住取证按钮）。钉成一整行，让板子自己滚。 */
/* 走廊/推演页只有一列（浏览器自己分左右）：留着一列 560 的右栏，
   浏览器只会挤在左半屏，右边空一条。 */
.nrn-body.card-mode{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr)}
.nrn-body.card-mode>.nrn-side{overflow:hidden}
.nrn-body.card-mode>div{min-height:0}

.nrn-map{position:relative;display:flex;flex-direction:column;min-height:0;gap:6px;min-width:0;width:auto}
.nrn-hint{margin:0;padding:5px 9px;border-radius:6px;font-size:11.5px;color:#a9cde2;
  background:rgba(20,60,80,.55);border:1px solid rgba(70,140,170,.35)}
.nrn-canvas{position:relative;flex:1;min-height:300px;border-radius:10px;overflow:hidden;
  border:1px solid rgba(70,110,140,.3)}
.nrn-tools{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:12px}
.nrn-tools button,.nrn-tools select{background:#10283a;border:1px solid #2b4c62;color:#a9cde2;border-radius:5px;padding:4px 9px;font-size:11.5px;cursor:pointer}
.nrn-tools button.on{background:#1d5670;border-color:#3f8ba8;color:#c8f0ff}
.nrn-tools button.play{background:#1b4d63;color:#d6f6ff;border-color:#3d8aa6}
.nrn-tools input[type=range]{flex:1;min-width:90px}
.nrn-tools .clock{font-variant-numeric:tabular-nums;color:#bfe9ff;font-size:12px}

.nrn-mapfoot{position:absolute;left:8px;right:8px;bottom:6px;z-index:4;
  display:flex;flex-direction:column;gap:4px;pointer-events:none;
  transition:opacity .25s ease}
/* 压暗后鼠标移上去要能恢复：容器是 pointer-events:none（不能挡住地图），
   所以 hover 必须挂在容器自己身上，而不是靠子元素冒泡上去 —— 子元素同样不吃事件。
   做法：容器在压暗时恢复 auto 事件，靠 :has 只在指针真落在浮层上时提亮。 */
.nrn-mapfoot.dim{opacity:.26;pointer-events:none}
.nrn-mapfoot{pointer-events:none}
.nrn-mapfoot:hover{opacity:1}
.nrn-mapfoot.dim:hover{opacity:1}
.nrn-monitor{
  padding:5px 9px;border:1px solid rgba(80,130,160,.35);border-radius:7px;
  background:rgba(10,26,38,.9);font-size:11px;color:#8fb2c8;
  display:flex;flex-wrap:wrap;gap:3px 12px;pointer-events:none}
.nrn-monitor strong{color:#ffd08a;font-weight:600}
.nrn-monitor .quiet{color:#6f92a8}
.nrn-monitor .push{color:#7d9cb3}
.nrn-monitor .push.on{color:#7fe0bb}
.nrn-legend{margin:0;
  font-size:10.5px;color:#8fb2c8;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  background:rgba(8,18,28,.86);border-radius:6px;padding:3px 8px;pointer-events:none}
.nrn-legend i{display:inline-block;width:14px;height:2px;background:var(--map-corridor);margin-right:4px;vertical-align:middle}
.nrn-legend i.dot{width:6px;height:6px;border-radius:50%;background:#eaf6ff}
.nrn-legend i.ring{width:8px;height:8px;border-radius:50%;background:transparent;
  border:1.5px solid rgba(226,75,74,.92)}
.nrn-legend i.warn{background:rgba(255,206,90,.9)}
.nrn-legend i.bad{background:rgba(226,92,74,.75)}
.nrn-legend i.emergency{background:#ff3b30}
.nrn-legend i.zone{width:9px;height:9px;border-radius:50%;background:rgba(245,190,60,.22);
  border:1px solid rgba(245,190,60,.75)}
.nrn-legend i.dim{background:rgba(126,206,255,.3)}
.nrn-legend i.star{width:9px;height:9px;background:#e03131;clip-path:polygon(50% 0,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%)}
.nrn-legend i.box{width:10px;height:8px;background:rgba(224,49,49,.08);border:1.4px solid #e03131;border-radius:1px}
.nrn-legend i.tri{width:0;height:0;background:none;border-left:4.5px solid transparent;
  border-right:4.5px solid transparent;border-bottom:8px solid #ff3b30;margin-right:6px}
html[data-theme="light"] .nrn-legend i.star{background:#c92a2a}
html[data-theme="light"] .nrn-legend i.box{border-color:#c92a2a}
.nrn-legend .bad{color:#ffa08a}
.nrn-legend .virt{color:#ffcf7a}

/* 空域视角侧栏 */
.nrn-zone{border:1px solid rgba(120,150,90,.35);border-radius:8px;background:rgba(18,34,22,.55);
  padding:6px 8px;display:flex;flex-direction:column;gap:2px;max-height:38%;min-height:0;overflow:auto}
/* 标题 + 一句副标在同一行：1366 下侧栏只有 400 宽，
   "规则化生成 · 可申请穿越" 会被挤出面板（右边缘直接裁掉）。
   允许换行，宁可占两行，也不要半句。 */
.nrn-zone h4{margin:0 0 3px;font-size:11.5px;color:#cfe6b5;display:flex;gap:6px;
  align-items:baseline;flex-wrap:wrap;line-height:1.45}
.nrn-zone h4 small{font-size:10px;color:#8a9c72;font-weight:400;white-space:normal;min-width:0}
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
.nrn-blocks{display:flex;flex-direction:column;gap:4px;overflow:auto;min-height:0;flex:0 1 auto;max-height:50%}
.nrn-blocks h3{margin:0 0 2px;font-size:11.5px;color:#a9cde2}
.nrn-blocks h3 small{margin-left:6px;font-size:10px;color:#6f92a8;font-weight:400}
/* 一级一个按钮：全国=大区，进区=省，进省=市 */
/* 一级一个按钮：全国=大区，进区=省，进省=市。
   单行排布（名字 · 规模 · 在飞/停飞）。两行会让 6 个大区占到 300 px，
   右栏一半高度被导航吃掉，气象只剩三四行。 */
.nrn-region,.nrn-city{display:flex;align-items:center;gap:8px;width:100%;text-align:left;min-width:0;
  background:rgba(16,40,56,.75);border:1px solid rgba(60,100,130,.4);border-radius:6px;padding:4px 8px;
  color:#cfe6f5;cursor:pointer;font-size:11.5px;line-height:1.6}
.nrn-region b,.nrn-city b{flex:0 0 auto;font-weight:600;white-space:nowrap}
.nrn-region span,.nrn-city span{flex:1 1 auto;min-width:0;font-size:10.5px;color:#7d9cb3;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nrn-region em,.nrn-city em{flex:0 0 auto;font-style:normal;font-size:10.5px;color:#8fb2c8;white-space:nowrap}
.nrn-region em.warn,.nrn-city em.warn{color:#8ef0ff}
.nrn-region em.sub,.nrn-city em.sub{color:#ffb38a}
.nrn-region:hover,.nrn-city:hover{background:rgba(34,86,112,.8);border-color:#3f8ba8}
/* 气象面板：占满剩余高度，自己滚 */
.nrn-side.wx-wide .nrn-blocks{flex:0 0 auto;display:grid;grid-template-columns:1fr 1fr;gap:4px;overflow:visible}
.nrn-side.wx-wide .nrn-blocks h3{grid-column:1 / -1;margin:0}
.nrn-side.wx-wide .nrn-region{padding:3px 6px;font-size:11px}
.nrn-side.wx-wide .nrn-region span{font-size:9.5px}
.nrn-side.wx-wide .nrn-wx{flex:1 1 auto;max-height:none;min-height:0}
/* 气象表吃满剩余高度：flex-basis 设 0 而不是 auto，
   否则它按内容高度（300+ px）定尺寸，把上面的区块列表压到只剩一行半。 */
.nrn-wx{flex:1 1 0;min-height:132px;max-height:none;display:flex;flex-direction:column;
  border:1px solid rgba(60,100,130,.4);border-radius:8px;background:rgba(10,26,38,.6);padding:6px 8px}
.nrn-wx h4{margin:0 0 4px;font-size:11.5px;color:#a9cde2;display:flex;gap:6px;align-items:baseline}
.nrn-wx h4 small{font-size:10px;color:#6f92a8;font-weight:400}
.nrn-wx ul{list-style:none;margin:0;padding:0;overflow:auto;flex:1;display:flex;flex-direction:column;gap:2px}
.nrn-wx li{display:grid;grid-template-columns:minmax(60px,1fr) 58px 40px 52px 60px;gap:5px;font-size:10.5px;
  padding:2px 5px;border-radius:4px;background:rgba(14,34,48,.75);color:#a8c6d8;white-space:nowrap}
.nrn-wx li.bad{outline:1px solid rgba(226,75,74,.45)}
.nrn-wx li b{color:#d9eefb;font-weight:500;overflow:hidden;text-overflow:ellipsis}
.nrn-wx li em{font-style:normal;text-align:right;font-variant-numeric:tabular-nums;color:#8fb2c8}
.nrn-wx li em.watch{color:#cfe6b0}
.nrn-wx li em.warn{color:#ffd479}
.nrn-wx li em.bad{color:#ff8f6b}
.nrn-wx li span{text-align:right;font-variant-numeric:tabular-nums}

.nrn-wx li.empty{grid-template-columns:1fr;color:#6f92a8;text-align:center}
.nrn-wx li.head{background:none;color:#6a8ca2;font-size:9.5px;padding:0 5px 2px;letter-spacing:.2px;
  position:sticky;top:0;z-index:1}
.nrn-wx li.head b,.nrn-wx li.head em,.nrn-wx li.head span{color:#6a8ca2;font-weight:400}
.nrn-total{display:grid;grid-template-columns:repeat(5,1fr);gap:4px;background:rgba(12,32,46,.8);
  border:1px solid rgba(70,110,140,.4);border-radius:8px;padding:7px 6px}
.nrn-total div{text-align:center}
.nrn-total b{display:block;font-size:15px;color:#eaf6ff;font-variant-numeric:tabular-nums}
.nrn-total span{font-size:10px;color:#7d9cb3}
.nrn-total .alarm b{color:#ffc857}
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
.nrn-city-detail b.warn{color:#ffb59a}
/* 市级最低一级：右栏只讲这一座城，下面挂上"与它相连的这几条走廊"，点一条就去推演 */
.nrn-city-lines{display:flex;flex-direction:column;gap:3px;margin-top:6px}
.nrn-city-lines button{display:flex;justify-content:space-between;gap:8px;align-items:baseline;
  text-align:left;padding:5px 8px;border-radius:6px;border:1px solid rgba(70,110,140,.3);
  background:rgba(12,38,54,.5);color:#cfe6f5;font-size:11.5px;cursor:pointer}
.nrn-city-lines button:hover{background:rgba(89,223,252,.12);border-color:rgba(89,223,252,.35)}
.nrn-city-lines button b{font-weight:500;color:#e6f8ff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nrn-city-lines button span{font-size:10.5px;color:#7d9cb3;flex:0 0 auto}

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
.nrn-alerts li{border:1px solid rgba(70,110,140,.35);border-left-width:3px;border-radius:7px;padding:7px 9px;
  background:rgba(10,26,38,.62);cursor:pointer;transition:border-color .15s,background .15s}
.nrn-alerts li:hover,.nrn-alerts li:focus-visible{background:rgba(22,52,74,.8);border-color:rgba(110,180,215,.6)}
.nrn-alerts li.empty{cursor:default}
.nrn-alert-foot{display:flex;align-items:center;gap:8px;margin-top:3px;flex-wrap:wrap}
.nrn-alert-go{margin-left:auto;font-size:10.5px;color:#8ef0ff}
.nrn-alert-more{font-size:10.5px;color:#7d9cb3}
html[data-theme="light"] .nrn-alerts li:hover{background:#eef6fd;border-color:#9cc7e8}
html[data-theme="light"] .nrn-alert-go{color:#0b7ea6}
.nrn-alerts li.bad{border-left-color:#ee5040}
.nrn-alerts li.warn{border-left-color:#f5be3c}
.nrn-alerts li.empty{grid-column:1/-1;text-align:center;color:#6f92a8;padding:20px}
.nrn-alerts b{font-size:12px;color:#eaf6ff}
.nrn-alerts em{font-style:normal;font-size:11px;color:#8fb2c8;margin-left:8px}
.nrn-alerts p{margin:3px 0 0;font-size:11px;color:#a8c6d8;line-height:1.5}
.nrn-alerts p.act{color:#ffd08a}
.nrn-alerts .tag{margin-top:4px}

.nrn-detail{border:1px solid rgba(70,110,140,.4);border-radius:9px;background:rgba(10,26,38,.9);padding:8px 10px;
  /* 选中班次的详情会长到 300px 以上，把地图压成一条缝；
     限高并让它自己滚，地图（画布）才是主角。 */
  max-height:26vh;overflow:auto}
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
.ev-llm{margin-left:auto;font-style:normal;font-size:9.5px;padding:1px 6px;border-radius:999px;
  color:#6fe0a8;border:1px solid rgba(80,200,140,.45);background:rgba(40,140,95,.14);white-space:nowrap}
.ev-llm.off{color:#ffcf7a;border-color:rgba(220,170,60,.5);background:rgba(180,130,30,.14)}
.ev-note.quiet{color:#6f92a8}
.ev-err{color:#ffa08a;font-size:11px}
.nrn-state{margin:6px 0;color:#8fb2c8;font-size:12px;line-height:1.6;
  background:rgba(14,32,48,.6);border:1px solid rgba(70,110,140,.35);
  border-left:3px solid #59dffc;border-radius:0 6px 6px 0;padding:6px 10px;max-width:760px}
.nrn-state::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;
  background:#59dffc;margin-right:7px;vertical-align:middle;animation:nrn-pulse 1.1s ease-in-out infinite}
@keyframes nrn-pulse{0%,100%{opacity:.25}50%{opacity:1}}
.nrn-state b{color:#cfe6f5;font-weight:500;font-variant-numeric:tabular-nums}
html[data-theme="light"] .nrn-state{color:#31556f !important;background:#fff !important;
  border-color:#dbe6f1 !important;border-left-color:#2a7fb8 !important}
html[data-theme="light"] .nrn-state::before{background:#2a7fb8}
html[data-theme="light"] .nrn-metrics b{color:#0f3550 !important}
html[data-theme="light"] .nrn-metrics span{color:#5b7a92 !important}
html[data-theme="light"] .nrn-metrics .m{border-left-color:#dbe6f1 !important}
html[data-theme="light"] .nrn-metrics .m.warn b{color:#8a5a00 !important}
html[data-theme="light"] .nrn-metrics .m.bad b{color:#a8321f !important}
html[data-theme="light"] .nrn-state b{color:#14567d !important}
html[data-theme="light"] .ev-llm{color:#0f7a52 !important;border-color:#8ecbb0 !important;background:#e6f6ee !important}
html[data-theme="light"] .ev-llm.off{color:#7a5200 !important;border-color:#e6cf9c !important;background:#fdf6e7 !important}
html[data-theme="light"] .ev-note{color:#7a5200 !important}
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
  .nrn-detail p,.nrn-detail p>b{font-size:11px}
  .nrn-detail header b{font-size:12.5px}
  .nrn-side h3{font-size:11.5px}
  .tag{font-size:10.5px}
  .nrn-table td small{font-size:10.5px}
  .ev-step p{font-size:10.5px}
}
/* 768 高的屏：把详情区限高并允许内部滚动，别让地图被压没 */
@media(max-height:820px){
  /* 1366×768 是最常见的答辩投影分辨率。这一档下地图必须优先：
     画布保底 300px，详情卡限到 32vh 并自己滚 —— 之前 44vh 会把地图压成一条缝，
     图例与监视条几乎盖满整幅图。 */
  .nrn-canvas{min-height:300px}
  .nrn-detail{max-height:26vh;overflow:auto}
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
