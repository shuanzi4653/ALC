<script setup>
import {computed,onBeforeUnmount,onMounted,onUnmounted,ref,watch,nextTick} from 'vue'
import {requestJson,postAction,operatorRole,setOperatorRole} from '../api.js'
import OperationsConsole from './OperationsConsole.vue'
import {isCaseMode, caseQuery, caseMeta} from '../traffic/caseMode.js'
import WeatherSourceSwitch from './traffic/WeatherSourceSwitch.vue'
import NationPanel from './traffic/NationPanel.vue'
import NationBriefing from './traffic/NationBriefing.vue'
import CommandPalette from './traffic/CommandPalette.vue'
import {relayRadarTiles} from '../traffic/radarRelay.js'
import {theme,toggleTheme} from '../theme.js'
import {store} from '../store.js'
import {readScopeFromUrl,writeScopeToUrl,scopeKey} from '../traffic/scope.js'
import {atTime,trajectoryOf,flightState,flightPhase,profile,effectiveFlights,filterLedgerRows,reasonNames,actionNames,modeNames,relativeClock,operationalTime,executionTimes,staticCrossingSummary,staticZoneSummary,closureBreakdown,dispositionSummary,delaySpread,clearanceLines,clearanceStatusName,weatherChannelState,weatherChannelLabel,WEATHER_MODE_MEASURED,normalizeWeatherMode,weatherModeIsVirtual,planChannelMismatch,weatherBucket,buildNote,algorithmIdentity,algorithmIdentityTitle,SECTION_NAMES,DENSITY_TIERS,NAV_GROUPS,visibleSubs,entryOf,entryTabs,isOfflineMode,navGroup,groupOfSection,defaultSub,densityTier,densityPolicy,drillTarget,MAP_LAYERS,lowVisibilityRuleBlock,buildProgressView,radarRelayReady,SECTION_CAN_DO,sectionHash,sectionFromHash,SECTION_HASHES,isDemoMode} from '../traffic/runtime.js'
// 全局作用域：初值从地址栏还原，之后由 NationPanel 的 scope-change 事件写回。
// 这样评委点一个带 scope 的链接、或刷新页面，都停在同一级。
store.scope=readScopeFromUrl()
const nationScopeKey=computed(()=>scopeKey(store.scope.level,store.scope.id))
// 导航入口 → 全国台视图。处置看事件、取证看台账（选中班次后能取证）、
// 气象与走廊都用态势图（右栏的气象实况与点航线出的剖面就是它们的内容）。
// 这些页面共用一张图/一张表，不给一句"该做什么"，用户看到的只是空地图。
const NATION_HINTS={
  weather:'逐市实况按「低能见概率」排序，概率来自 ml-v3；点地图任意城市可下钻，右上「空域视角」可切到净空边界',
  profile:'点地图上任意一条航线，下方会给出逐公里回波剖面与绕飞段',
  card:'先选城市或班次，再看这一班从实况、判据到裁决的完整链路',
  assistant:'在表里点一行班次选中它，再在下方详情里点「取证」，得到逐行带来源的证据链',
}
function nationViewOf(section){
  if(section==='alerts') return 'alerts'
  if(section==='assistant') return 'ledger'
  // 气象监测 = 情报：左侧班次/空域两张表，右侧保留逐市实况与回波/雾统计。
  // 以前这一页是"地图 + 宽气象栏"，和首页那张图重复；地图只在态势页出现一次。
  if(section==='weather') return 'intel'
  return 'map'
}
function onScopeChange(next){
  store.scope={level:next.level,id:next.id,label:next.label}
  writeScopeToUrl(next)
}
const activeSection=ref('home'),scope=ref('nation')
// 运行情报的两个视图：班次情报（默认，看飞行汽车）| 空域情报（机场与净空）。
// 原来的「民航情报」名不副实——它展示的是机场城市气象，而情报的对象该是飞行汽车。
// 走廊/推演页的定位目标。处置事件与日志行都跳这里：
// 点一条事件 → 直接落到那条走廊上，而不是"切到城市让用户自己找"。
const corridorFocusId=ref('')
function openCorridor(payload){
  const corridorId=(payload&&payload.corridor)||String((payload&&payload.flightId)||'').split('#')[0]
  if(!corridorId) return
  corridorFocusId.value=''
  // 先清空再赋值：同一条走廊连续点两次，子组件也要能再收到一次
  nextTick(()=>{ corridorFocusId.value=corridorId })
  activeSection.value='profile'
}

const intelTab=ref('flight'),settings=ref(false),operations=ref([]),operationsReady=ref(false),commandBusy=ref(false),mapExpanded=ref(false)
const demoMode=isDemoMode()
const workbench=ref(null)
const sections=SECTION_NAMES
const activeGroup=computed(()=>navGroup(groupOfSection(activeSection.value)))
function gotoGroup(key){
  const next=defaultSub(key)
  if(next)activeSection.value=next
}
function keyGuard(event){
  const tag=(event.target?.tagName||'').toLowerCase()
  return tag==='input'||tag==='textarea'||tag==='select'||event.target?.isContentEditable
}
function onGlobalKey(event){
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
    event.preventDefault();paletteOpen.value=!paletteOpen.value;return
  }
  if(event.key==='Escape'&&paletteOpen.value){paletteOpen.value=false;return}
  // 投影模式已下线（2026-11-11），P 键不再绑定任何动作
}
const paletteOpen=ref(false)
const paletteRoutes=computed(()=>(network.value?.routes||[]).map(r=>({id:r.id,name:r.name,fromCity:r.fromCity,toCity:r.toCity})))
const paletteFlights=computed(()=>flights.value.map(f=>({id:f.id,name:f.name,fromCity:f.fromCity,toCity:f.toCity})))
function onPaletteRun(item){
  paletteOpen.value=false
  if(!item)return
  if(item.kind==='section')activeSection.value=item.key
  else if(item.kind==='corridor')activeSection.value='profile'
  else if(item.kind==='flight'&&item.id){activeSection.value='schedule';selectedId.value=item.id}
}
const network=ref(null),session=ref(null),weather=ref(null),error=ref(''),busy=ref(false)
const weatherMode=ref(WEATHER_MODE_MEASURED),weatherModeStatus=ref(null)
const seed=ref(42),scenario=ref('live'),city=ref(''),minute=ref(60),playing=ref(false),speed=ref(1)
const showCar=ref(true),showDelivery=ref(true),showWeather=ref(true),showWind=ref(true),showFixedZones=ref(true),showRadar=ref(true)
const showFog=ref(true)
const showEvents=ref(true),showObservations=ref(true),search=ref(''),status=ref('ALL'),page=ref(1),selectedId=ref(''),scene=ref(null)
let generation=0,weatherGeneration=0,poll=null,timer=null,disposed=false
const stateNames={AIRBORNE:'飞行中',HOLD:'等待放行',PENDING:'待执行',ARRIVED:'已到达',CLOSED:'已关闭'}
const phaseNames={CLIMB:'爬升',CRUISE:'巡航',DESCENT:'下降',AIRBORNE:'飞行中',HOLD:'待放行',PENDING:'待执行',ARRIVED:'已到达',CLOSED:'已关闭'}
const provinces=['辽宁省','吉林省','黑龙江省']
const appliedOperationKey=computed(()=>operations.value.flatMap((op,i)=>op.minute<=minute.value?[i]:[]).join(','))
const flights=computed(()=>session.value?.status==='READY'&&operationsReady.value?effectiveFlights(session.value.flights,appliedOperationKey.value?appliedOperationKey.value.split(',').map(i=>operations.value[Number(i)]):[],Infinity):[])
const filtered=computed(()=>filterLedgerRows(flights.value,{showCar:showCar.value,showDelivery:showDelivery.value,city:city.value,search:search.value,status:status.value,minute:minute.value}))
const rows=computed(()=>filtered.value.slice((page.value-1)*20,page.value*20))
const fullFlights=ref({})
const fullRequested=new Set()
async function ensureFullFlight(id){
  if(!id||fullRequested.has(id))return
  const row=(session.value?.flights||[]).find(f=>f.id===id)
  if(!row||!row.slim)return
  fullRequested.add(id)
  try{
    const full=await requestJson(`/api/traffic/flight/${encodeURIComponent(id)}?seed=${session.value.seed}&scenario=${session.value.scenario}`,{timeoutMs:15000})
    if(full&&full.id===id)fullFlights.value={...fullFlights.value,[id]:full}
  }catch(_){fullRequested.delete(id)}
}
const selected=computed(()=>{
  const row=flights.value.find(f=>f.id===selectedId.value)
  if(!row)return null
  const extra=fullFlights.value[row.id]
  const merged=extra?{...row,...extra}:row
  if(!Array.isArray(merged.points)){
    const mapRow=(session.value?.mapFlights||[]).find(r=>r.id===row.id)
    if(mapRow&&Array.isArray(mapRow.points))return {...merged,points:mapRow.points}
    return {...merged,points:[]}
  }
  return merged
})
const scoped=computed(()=>flights.value.filter(f=>(f.mode==='CAR'?showCar.value:showDelivery.value)&&(!city.value||[f.fromCity,f.toCity].includes(city.value))))
const mapFlights=computed(()=>{
  const base=session.value?.status==='READY'?session.value.mapFlights||[]:[]
  if(!base.length)return []
  const live=new Map(flights.value.map(f=>[f.id,f]))
  return base.map(row=>{
    const now=live.get(row.id)
    if(!now)return row
    return {...row,status:now.status,departureMinute:now.departureMinute,arrivalMinute:now.arrivalMinute}
  })
})
const boardFlights=computed(()=>flights.value.filter(f=>!city.value||[f.fromCity,f.toCity].includes(city.value)))
const counts=computed(()=>{const c={AIRBORNE:0,HOLD:0,PENDING:0,ARRIVED:0,CLOSED:0};for(const f of scoped.value)c[flightState(f,minute.value)]++;return c})
const cityName=computed(()=>network.value?.cities.find(c=>c.id===city.value)?.name||'全域')
const location=computed(()=>{const pts=trajectoryOf(selected.value);return pts.length?atTime(pts,minute.value):null})
const actualTimes=computed(()=>executionTimes(selected.value,minute.value))
const selectedPhase=computed(()=>selected.value?flightPhase(selected.value,minute.value):'')
const trajectoryPoints=computed(()=>selected.value?.plannedPoints||selected.value?.points||[])
const clearanceRows=computed(()=>clearanceLines(selected.value?.atcClearance))
const ready=computed(()=>session.value?.status==='READY'&&operationsReady.value)
function locateDelivery(){
  const withPath=new Set((session.value?.mapFlights||[]).filter(r=>Array.isArray(r.points)&&r.points.length).map(r=>r.id))
  const candidates=flights.value.filter(f=>f.fromCity===city.value&&f.mode==='DELIVERY'&&withPath.has(f.id))
  const f=candidates.find(f=>f.separationAction==='CROSSING_RAMP')||candidates[0]
  if(f){selectedId.value=f.id;minute.value=(f.departureMinute+f.arrivalMinute)/2;playing.value=false}
}
const selectedState=computed(()=>selected.value?flightState(selected.value,minute.value):'')
const sessionLabel=computed(()=>({clear:'无气象声明',live:'公开天气驱动',unknown:'气象中断'})[session.value?.scenario]||'准备模拟')
const caseMode=isCaseMode()
const entryKey=computed(()=>(entryOf(activeSection.value)||{}).key||'')
const entryTabList=computed(()=>entryTabs(activeSection.value))
const algorithmIdentityLabel=computed(()=>algorithmIdentity(session.value))
const algorithmIdentityNote=computed(()=>algorithmIdentityTitle(session.value))

const DENSITY_KEY='alc.traffic.density'
function readDensity(){
  try{
    const raw=localStorage.getItem(DENSITY_KEY)
    if(DENSITY_TIERS.some(tier=>tier.key===raw))return raw
    if(raw!==null)localStorage.removeItem(DENSITY_KEY)
    return 'duty'
  }catch(_){return 'duty'}
}
const density=ref(readDensity())
watch(density,value=>{try{localStorage.setItem(DENSITY_KEY,value)}catch(_){}})
const densityNote=computed(()=>densityTier(density.value).note)

const drillFocus=ref(null)
const corridorFocus=ref('')
const corridorPair=ref(null)
const firstVisit=ref(false)
onBeforeUnmount(()=>{
  window.removeEventListener('hashchange',applyHash)
  window.removeEventListener('popstate',onPopState)
})
const playbackMax=computed(()=>{
  const meta=caseMeta()
  if(meta&&Number.isFinite(meta.durationMinutes))return meta.durationMinutes
  const own=session.value?.timelineMinutes
  if(Number.isFinite(own)&&own>0)return own
  return 480
})
const playbackMaxLabel=computed(()=>{
  const total=playbackMax.value
  return `T+${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`
})

const canDo=computed(()=>SECTION_CAN_DO[activeSection.value]||[])

onMounted(()=>{
  applyHash()
  window.addEventListener('hashchange',applyHash)
  window.addEventListener('popstate',onPopState)
  try{ firstVisit.value=!localStorage.getItem('alc.visited') }catch(e){ firstVisit.value=false }
  if(firstVisit.value)startTour(false)
  if(firstVisit.value)window.setTimeout(()=>dismissFirstVisit(),4000)
})
function dismissFirstVisit(){
  firstVisit.value=false
  try{ localStorage.setItem('alc.visited','1') }catch(e){}
}

function onOpenCorridor(payload){
  if(!payload)return
  if(typeof payload==='string'){
    corridorPair.value=null
    corridorFocus.value=payload
  }else{
    corridorFocus.value=''
    corridorPair.value={from:payload.from,to:payload.to,mode:payload.mode||''}
  }
  activeSection.value='profile'
}
function onDrill(key){
  const target=drillTarget(key)
  drillFocus.value={key,section:target.section,cause:target.cause||'',hint:target.hint,at:Date.now()}
  if(target.status)status.value=target.status
  activeSection.value=target.section
}

const eventFocusKey=ref('')
const eventFocus=computed(()=>eventFocusKey.value
  ?{key:eventFocusKey.value,at:Date.now()}:null)
function onSelectEvent(key){
  if(!key)return
  eventFocusKey.value=key
  activeSection.value='alerts'
}
function locateEvent(key,flight){
  if(!key)return
  eventFocusKey.value=key
  activeSection.value='overview'
  if(flight&&flight.id){
    selectedId.value=flight.id
    if(flight.fromCity)city.value=flight.fromCity
    ensureFullFlight(flight.id)
  }
  nextTick(()=>scene.value?.focusEvent(key))
}

const aiReviewed=ref({})
function onAiReviewed(payload){
  const id=payload&&payload.flightId
  if(!id)return
  aiReviewed.value={...aiReviewed.value,[String(id)]:String(payload.outcome||'')}
}

const closedBreakdown=computed(()=>closureBreakdown(session.value?.stats))
const dispositionBreakdown=computed(()=>dispositionSummary(session.value?.stats))
const delayStats=computed(()=>delaySpread(flights.value))
const delayNote=computed(()=>{
  const s=delayStats.value
  const span = playbackMax.value > 480
    ? `窗口 T+${playbackMaxLabel.value.replace('T+','')}（按最晚到达） · `
    : ''
  if(!s.count)return `${span}本轮无延迟起飞`
  return `${span}延迟 ${s.count} 班 · 中位 ${Math.round(s.median)} 分 · 九成在 ${Math.round(s.p90)} 分内 · 最长 ${Math.round(s.max)} 分`
})
const channel=computed(()=>weatherChannelState({showWeather:showWeather.value,showRadar:showRadar.value}))
const radarLabel=computed(()=>weatherChannelLabel(weatherMode.value))
const layerRefs={car:showCar,delivery:showDelivery,weather:showWeather,wind:showWind,radar:showRadar,zones:showFixedZones,events:showEvents,observations:showObservations,fog:showFog}
const homeLayers=computed(()=>Object.fromEntries(MAP_LAYERS.map(layer=>[layer.key,!!(layerRefs[layer.key]&&layerRefs[layer.key].value)])))
const homeEffective=computed(()=>({weather:channel.value.modelVisible,radar:channel.value.radarVisible}))
function toggleHomeLayer(key){const target=layerRefs[key];if(target)target.value=!target.value}
function toggleLayerRow(key){toggleHomeLayer(key)}
const layerRows=computed(()=>MAP_LAYERS.map(layer=>({
  ...layer,
  label:layer.key==='radar'?radarLabel.value:layer.label,
  title:{weather:riskLegend.value,radar:radarLegend.value,zones:fixedZoneNote.value,fog:fogLegend.value}[layer.key]||layer.title,
})))
const channelMismatch=computed(()=>planChannelMismatch(session.value?.weatherMode,weatherMode.value))
const radarLegend=computed(()=>{
  const channelNote=weatherModeIsVirtual(weatherMode.value)
    ?'当前为虚拟气象：回波由程序按仿主流气象产品的形态生成，非观测数据'
    :'中国气象数据网组网组合反射率实测值；读取失败时不产出任何几何，非本系统估算'
  return '风险区＝实测雷达回波（≥35 dBZ）：橙黄＝对流回波，航线须绕飞；深橙＝对流内核，禁止进入。'
    +'35 dBZ 以下层状降水以淡紫画出，可穿越、不构成限制。'
    +`航线已按 35 dBZ 以上回波避让。${channelNote}。`
})
const riskLegend=computed(()=>'极端气象派生风险区：城市观测达到暴雨 / 雷暴（WMO 65、82、95、96、99）、'
  +'阵风 ≥17 m/s（8 级）或小时雨量 ≥8 mm 时，在该点生成半径 6 km 的紧凑禁止进入内核。'
  +'轻度不利天气只作观测记录，不生成任何几何，也不拦航路。'
  +'与雷达回波是两套来源，可同时显示。')
const fogLegend=computed(()=>{
  const block=lowVisibilityRuleBlock(session.value)
  if(!block||block.banVisibilityM===null){
    return '低能见度（雾）：站点能见度读数派生的两档缓冲圆（灰阶）；'
      +'深灰＝低于禁飞阈值、禁止进入；浅灰＝能见度偏低、须绕飞。'
      +'本计划未发布两档规则数字，因此此处不引用任何具体阈值。'
  }
  const km=r=>r===null?null:Math.round(r/1000)
  return `低能见度（雾）：按站点能见度读数派生，两档缓冲圆。`
    +`深灰＝能见度 <${block.banVisibilityM} m（低于禁飞阈值）、禁止进入、半径 ${km(block.banRadiusM)} km；`
    +`浅灰＝能见度偏低、须绕飞、半径 ${km(block.cautionRadiusM)} km。`
    +`浅灰档**不拒绝起降**：起降点落在某个浅灰圆内时，该圆对本班次不构成约束`
    +`（本计划豁免 ${block.padExemptFlights??'—'} 班次）。`
    +`阈值来源 ${block.thresholdSource||'—'}。`
    +'范围由单点读数派生，是近似值、不是实测雾区边界。'
})

const deliverySettings=computed(()=>network.value?.deliveryConfig||{})
const fixedZoneSummary=computed(()=>staticZoneSummary(network.value?.staticAirspace))
const fixedZoneNote=computed(()=>network.value?.staticAirspace?.rules?.enforcementNote||'')
const selectedCrossings=computed(()=>staticCrossingSummary(selected.value))
function chooseCity(id){city.value=id||'';selectedId.value='';page.value=1}
function chooseFlight(f){
  selectedId.value=f.id;activeSection.value='overview';if(f.mode==='DELIVERY')city.value=f.fromCity
  ensureFullFlight(f.id)
}
async function loadOperations(){
  const id=session.value?.sessionId;if(!id)return
  const data=await requestJson('/api/traffic/operations?sessionId='+id)
  if(session.value?.sessionId===id){operations.value=data;operationsReady.value=true}
}
async function commandFlight(target){
  const flight=target&&target.id&&target.requestedDepartureMinute!=null?target:selected.value
  if(!flight||commandBusy.value||!ready.value)return
  playing.value=false;commandBusy.value=true;error.value=''
  const commandId=globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random()}`
  try{await postAction('/api/traffic/command',{seed:session.value.seed,scenario:session.value.scenario,flightId:flight.id,minute:minute.value,action:flight.manuallySuspended?'RESUME':'SUSPEND',planRevision:session.value.planRevision,commandId});await loadOperations()}
  catch(e){error.value=e.message}
  finally{commandBusy.value=false}
}
function followFlight(flight){
  selectedId.value=flight.id;activeSection.value='overview'
  nextTick(()=>scene.value?.follow())
}
function clock(m){return relativeClock(m)}
function rowActual(f){return executionTimes(f,minute.value)}
function rowPhase(f){return phaseNames[flightPhase(f,minute.value)]}
async function loadWeather(){
  if(!ready.value)return
  const token=++weatherGeneration,key=session.value.sessionId,t=minute.value
    try{const value=await requestJson(`/api/traffic/weather?seed=${session.value.seed}&scenario=${session.value.scenario}&minute=${t}${city.value?'&cityId='+encodeURIComponent(city.value):''}${caseQuery()}`);if(!disposed&&token===weatherGeneration&&key===session.value?.sessionId){weather.value=value;maybeRelayRadar(value)}}
  catch(e){
    if(token===weatherGeneration){weather.value=null;error.value='气象图层读取失败，本帧已作废（推演继续）：'+e.message}
  }
}
const radarRelay=ref({status:'idle',slot:null,detail:''})
let relayBusy=false,relayNextAllowedAt=0
function relayFailureText(result){
  if(result.reason==='NO_SLOT_AVAILABLE')return `本机浏览器也没取到可用的雷达时次（已试 ${result.tried} 档）。源站可能对本网络同样拒绝。`
  if(result.reason==='POST_FAILED')return `瓦片已取到但后端未接受：${result.message}`
  if(result.reason==='NO_INSTRUCTIONS')return '服务端未下发取图说明，未发起中继。'
  // 源站没开 CORS 时浏览器连第一张都读不到，这不是"时次不对"，重试也没用
  if(result.reason==='CORS_BLOCKED')return '瓦片源未开放 CORS，本机浏览器无法代取（已停止重试，不影响后端直取）'
  return `中继失败：${result.reason}`
}
let relayRetryTimer=null
function scheduleRelayRetry(){
  if(relayRetryTimer)clearTimeout(relayRetryTimer)
  const delay=Math.max(30_000,relayNextAllowedAt-Date.now()+1_000)
  relayRetryTimer=setTimeout(()=>{
    relayRetryTimer=null
    const radar=weather.value&&weather.value.radar
    if(radar&&radar.available===false)maybeRelayRadar(weather.value)
  },delay)
}

async function maybeRelayRadar(value){
  const relay=value&&value.radar&&value.radar.relay
  if(!radarRelayReady(relay))return
  if(relayBusy||Date.now()<relayNextAllowedAt)return
  relayBusy=true
  if(isOfflineMode()){
    radarRelay.value={status:'failed',slot:null,detail:'离线演示模式：未取回波瓦片'}
    return
  }
  radarRelay.value={status:'running',slot:null,detail:'正在由本机浏览器代取瓦片…'}
  try{
    const result=await relayRadarTiles(relay)
    if(result.ok){
      const ttl=Number(result.stored&&result.stored.ttlSeconds)||600
      relayNextAllowedAt=Date.now()+Math.max(60_000,ttl*1000-60_000)
      radarRelay.value={status:'ok',slot:result.slot,detail:`由本机浏览器代取：${result.slot}（北京时）`}
      scheduleRelayRetry()
      await loadWeather()
    }else{
      relayNextAllowedAt=Date.now()+60_000
      radarRelay.value={status:'failed',slot:null,detail:relayFailureText(result)}
    }
  }catch(e){
    relayNextAllowedAt=Date.now()+60_000
    radarRelay.value={status:'failed',slot:null,detail:'代取失败：'+(e&&e.message||e)}
    scheduleRelayRetry()
  }finally{relayBusy=false}
}
const operator=ref(operatorRole())
function applyOperator(e){
  const value=e&&e.target?e.target.value:''
  setOperatorRole(value)
  operator.value=operatorRole()
  loadWeatherMode()
}

async function loadWeatherMode(){
  try{const state=await requestJson('/api/traffic/weather/mode',{timeoutMs:8000});if(disposed)return;weatherMode.value=normalizeWeatherMode(state?.mode);weatherModeStatus.value=state}
  catch(e){if(!disposed)weatherModeStatus.value={...(weatherModeStatus.value||{}),available:false,error:e.message}}
}
async function onWeatherModeChange(result){
  weatherMode.value=normalizeWeatherMode(result?.mode)
  weatherModeStatus.value={...(weatherModeStatus.value||{}),...result}
  await loadWeatherMode()
  ++weatherGeneration;weather.value=null
  if(network.value&&!busy.value)await generate()
  else{
    session.value=null
    operations.value=[];operationsReady.value=false
    await loadWeather()
  }
}
const mapStatus=ref(null)
function onMapStatus(payload){mapStatus.value=payload||null}
const mapStatusText=computed(()=>{
  const status=mapStatus.value
  if(!status)return ''
  if(status.status==='ERROR')return '地图：资源异常'
  if(status.status==='OFFLINE')return '地图：离线底图'
  return status.buildings?`地图：已载入 · ${status.buildings} 个建筑要素`:'地图：已载入'
})
const progressView=computed(()=>buildProgressView(session.value))
// 全国范围的三个视图（全国台、全国情报、全国台账）都不参与东北建场
// 全国台覆盖的视图：这些页面里不显示东北的「建场进度条」。
// 全国网是 SIM，不参与东北建场，挂一条 0% 的进度条只会让人以为卡死了。
const NATION_VIEWS=['home','national','overview','weather','profile','alerts','assistant','card']
const nationScopeView=computed(()=>{
  if(NATION_VIEWS.includes(activeSection.value)) return true
  return scope.value==='nation'&&(activeSection.value==='briefing'||activeSection.value==='schedule')
})
const buildProgress=computed(()=>progressView.value.percent)
// 建场进度条只出现在"会用到这份计划"的页面上。
// 之前判据只有 `busy && !nationScopeView`，于是日志页顶上压着一条 86% 的蓝条 ——
// 既盖住了正文，又和这一页的内容（操作留痕）毫无关系。
const BUILD_STRIP_SECTIONS=new Set(['home','overview','national','weather','profile','alerts','assistant','card','briefing','schedule'])
const showBuildStrip=computed(()=>busy.value&&!nationScopeView.value&&BUILD_STRIP_SECTIONS.has(activeSection.value))
const buildLabel=computed(()=>{
  if(buildProgress.value===null)return '正在调度 · 排队中'
  const s=session.value||{}
  const channel=s.buildChannel==='virtual'?'虚拟':'实测'
  const parts=[`正在按${channel}气象重建`,`${buildProgress.value}%`]
  if(typeof s.elapsedSeconds==='number')parts.push(`已用 ${Math.round(s.elapsedSeconds)} 秒`)
  if(typeof s.etaSeconds==='number'&&s.etaSeconds>0)parts.push(`约剩 ${Math.round(s.etaSeconds)} 秒`)
  if(s.stage)parts.push(s.stage)
  return parts.join(' · ')
})
const buildStage=computed(()=>progressView.value.stage)
const buildElapsed=ref(0)
let buildClock=null
watch(busy,value=>{
  clearInterval(buildClock);buildClock=null;buildElapsed.value=0
  if(!value)return
  buildClock=setInterval(()=>{buildElapsed.value+=1},1000)
})
const buildElapsedText=computed(()=>{
  const seconds=buildElapsed.value
  if(seconds<60)return `已用 ${seconds} 秒`
  return `已用 ${Math.floor(seconds/60)} 分 ${String(seconds%60).padStart(2,'0')} 秒`
})
const buildTip=computed(()=>buildNote(buildElapsed.value))
async function preflightRadar(){
  if(disposed)return
  try{
    const value=await requestJson(`/api/traffic/weather?seed=${seed.value}&scenario=${scenario.value}&minute=${minute.value}${caseQuery()}`)
    if(disposed)return
    await maybeRelayRadar(value)
  }catch{
  }
}
async function generate(){
  if(busy.value)return
  const input=Number(seed.value)
  if(!Number.isInteger(input)||input<0||input>99999){error.value='数据快照编号需为 0—99999 的整数';return}
  const run=++generation;clearTimeout(poll);++weatherGeneration
  busy.value=true;playing.value=false;error.value='';session.value=null;weather.value=null;selectedId.value='';operations.value=[];operationsReady.value=false
  await preflightRadar()
  if(disposed||generation!==run)return
  const params=`seed=${input}&scenario=${scenario.value}&fields=slim&mode=${weatherMode.value}`
  async function check(){
    try{
      const data=await requestJson(`/api/traffic/session?${params}`,{cache:'no-store'})
      if(disposed||generation!==run)return
      session.value=data
      if(data.status==='READY'){
        busy.value=false;minute.value=60;page.value=1;await loadOperations();await loadWeather()
      }
      else if(data.status==='ERROR'){busy.value=false;error.value=data.message}
      else poll=setTimeout(check,1500)
    }catch(e){if(generation===run){busy.value=false;error.value=e.message}}
  }
  await check()
}
async function initialize(){
  loadWeatherMode()
  try{network.value=await requestJson('/api/traffic/network');if(!disposed)await generate()}
  catch(e){error.value=e.message}
}

const HASH_GUARD=ref(true)
function writeHash(section){
  const next=sectionHash(section)
  if(window.location.hash===next)return
  try{ history.pushState({section},'',next) }catch(_){ window.location.hash=next }
}
function onPopState(){
  HASH_GUARD.value=false
  applyHash()
  nextTick(()=>{HASH_GUARD.value=true})
}
function applyHash(){
  const raw=String(window.location.hash||'').replace(/^#\/?/,'').replace(/\/+$/,'')
  let section=sectionFromHash(window.location.hash)
  // 旧地址静默归到现有页面，不能让同学点到"导航里不存在的一页"：
  // `#/situation/national` → home；`#/corridor/briefing` → weather（V1.0.5 情报并入气象监测）。
  if(section==='national') section='home'
  if(section==='briefing') section='weather'
  const known = raw === '' || Object.values(SECTION_HASHES).includes(raw)
  if(!known){ try{ window.location.hash = sectionHash('home') }catch(_){} }
  if(section&&section!==activeSection.value)activeSection.value=section
}

const TOUR_STEPS=[
  {key:'brief',label:'结论条',text:'页首是当前作用域的一句话结论：多少条航线、几架在飞、几架绕飞或暂缓。下面的地图和右栏是它的明细。'},
  {key:'nav',label:'五个功能区',text:'态势 / 走廊 / 处置 / 推演 / 日志。点一次换页，没有先后顺序；每一页都能下钻到省和市。'},
]
const RAIL_KEY='alc.railCollapsed'
const railCollapsed=ref(false)
try{railCollapsed.value=localStorage.getItem(RAIL_KEY)==='1'}catch(_){}
function toggleRail(){
  railCollapsed.value=!railCollapsed.value
  try{localStorage.setItem(RAIL_KEY,railCollapsed.value?'1':'0')}catch(_){}
}
const tourStep=ref(-1)
const tourForced=ref(false)
function startTour(force=false){tourForced.value=force;tourStep.value=0}
function nextTour(){
  if(tourStep.value>=TOUR_STEPS.length-1){endTour();return}
  tourStep.value+=1
}
function endTour(){
  tourStep.value=-1
  if(!tourForced.value){try{localStorage.setItem('alc.visited','1')}catch(e){}}
  tourForced.value=false
}
function download(){
  if(!ready.value)return
  const blob=new Blob([JSON.stringify({simulation:session.value,network:network.value,viewMinute:minute.value,weather:weather.value,operations:operations.value},null,2)],{type:'application/json'})
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`traffic-${session.value.sessionId}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
watch([city,search,status,showCar,showDelivery],()=>page.value=1)
const overviewRibbon=ref([])
let ribbonTimer=null
function ribbonMinuteQuery(){
  if(!isCaseMode()||!Number.isFinite(minute.value))return ''
  return `&minute=${Math.round(minute.value)}`
}
async function loadOverviewRibbon(){
  if(activeSection.value!=='overview'||!ready.value)return
  clearTimeout(ribbonTimer)
  ribbonTimer=setTimeout(async()=>{
    try{
      const payload=await requestJson(
        `/api/traffic/v2/overview?seed=42&scenario=${encodeURIComponent(scenario.value)}`+
        `${caseQuery()}${ribbonMinuteQuery()}`,{timeoutMs:20000})
      const rows=(payload?.corridors?.ribbon||[]).filter(row=>Array.isArray(row.samples)&&row.samples.length>1)
      overviewRibbon.value=rows.map(row=>({
        id:row.id,name:row.name,verdict:row.verdict,p:row.p,sigma:row.sigma,
        points:row.samples.map(sample=>({lng:sample.lng,lat:sample.lat,p:sample.p})),
      }))
    }catch(_){}
  },600)
}
watch([activeSection,ready,minute,scenario],loadOverviewRibbon)

watch(activeSection,value=>{
  if(HASH_GUARD.value)writeHash(value)
  playing.value=false
})

watch([activeSection,mapExpanded],async()=>{await nextTick();if(workbench.value)workbench.value.scrollTop=0})
watch(()=>weatherBucket(minute.value),loadWeather)
watch(city,()=>{weather.value=null;loadWeather()})
watch(()=>filtered.value.length,()=>{page.value=Math.min(page.value,Math.max(1,Math.ceil(filtered.value.length/20)))})
// 顶栏的推演时刻：全国台自己报（它有自己的 0–1440 分钟），东北台用本组件的 minute。
const nationMinute=ref(0), nationPlaying=ref(true)
const topMinute=computed(()=>nationScopeView.value?nationMinute.value:minute.value)
const topPlaying=computed(()=>nationScopeView.value?nationPlaying.value:playing.value)
function onNationTick(payload){
  nationMinute.value=Number(payload?.minute)||0
  nationPlaying.value=!!payload?.playing
}

// 真实北京时间：每秒刷一次。只驱动顶栏这一个数字，不参与任何推演计算。
const wallClock=ref('')
let wallTimer=0
function tickWallClock(){
  const d=new Date()
  const p=n=>String(n).padStart(2,'0')
  wallClock.value=`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

onMounted(()=>{initialize();window.addEventListener('keydown',onGlobalKey);timer=setInterval(()=>{
  if(!playing.value||!ready.value)return
  const step=Number(speed.value)*.2
  minute.value=Math.min(480,minute.value+step)
  if(minute.value===480)playing.value=false
},200)})
onMounted(()=>{ tickWallClock(); wallTimer=setInterval(tickWallClock,1000) })
onUnmounted(()=>{
  clearInterval(wallTimer)
  if(relayRetryTimer)clearTimeout(relayRetryTimer);disposed=true;++generation;++weatherGeneration;window.removeEventListener('keydown',onGlobalKey);clearTimeout(poll);clearInterval(timer);clearInterval(buildClock)})
</script>
<template>
<main ref="workbench" class="traffic-workbench" :class="{'map-expanded':mapExpanded&&activeSection==='overview','overview-mode':activeSection==='overview','page-mode':activeSection!=='overview'}">
  <p class="wb-demo-bar" v-if="demoMode" data-demo-bar>
    演示模式（<code>?demo=1</code>）：底图与雷达瓦片不再外取，气象以本帧快照为准；页面上的“实时”字样本次不成立。
  </p>
  <header class="wb-top" data-workbench-top>
    <span class="wb-brand"><b>天窗智巡</b><em>低空航路气象风险裁决</em></span>
    <span class="wb-scope" data-scope-label>{{ cityName }}</span>
    <!-- 两个时间分开写：右边那个是**真实的北京时间**，每秒走；
         左边那个是**推演时刻**，暂停时会停住。以前只有一个"时间基准"，
         用户暂停后看到它也停了，会以为整站卡死。 -->
    <span class="nav-clock" data-wall-clock :title="'本机时区的当前时间，与推演无关，暂停时照常走'">北京时间 {{ wallClock }}</span>
    <span class="nav-timebase" data-time-basis :class="{paused:!topPlaying}" :title="`推演时刻：运行第 ${Math.round(topMinute)} 分钟${topPlaying?'（播放中）':'（已暂停）'}`">推演 {{ clock(topMinute) }}<template v-if="!topPlaying"> · 已暂停</template></span>
    <span class="relay-pill" v-if="radarRelay.status!=='idle'" role="status" data-radar-relay
          :class="radarRelay.status" :title="'实测雷达' + radarRelay.detail">
      雷达 {{ radarRelay.status==='ok' ? (radarRelay.slot||'').slice(11,16) : radarRelay.status==='running' ? '代取中' : '代取失败' }}
    </span>
    <span class="wb-spacer"></span>
    <!-- 深浅色：答辩现场投影仪普遍偏亮，讲解人要能一键切浅色，
         所以这个开关放顶栏，不藏在"设置"里。 -->
    <button class="wb-theme" data-theme-toggle :aria-pressed="theme==='light'"
            :title="theme==='light'?'切到深色（当前浅色）':'切到浅色（当前深色）'"
            @click="toggleTheme">{{ theme==='light' ? '深色' : '浅色' }}</button>
    <button class="wb-rail-toggle" data-rail-toggle :aria-pressed="railCollapsed"
            :title="railCollapsed?'展开左侧导航':'收起左侧导航，把宽度让给地图'"
            @click="toggleRail">{{ railCollapsed ? '展开导航' : '收起导航' }}</button>
  </header>
  <div class="wb-shell">
  <nav class="operations-nav" :class="{'rail-collapsed':railCollapsed}" data-nav-groups>
    <div class="nav-groups"><button v-for="group in NAV_GROUPS" :key="group.key" :data-group="group.key" class="nav-group" :class="{active:activeGroup?.key===group.key}" @click="gotoGroup(group.key)"><em>{{ group.no }}</em>{{ group.label }}</button></div>
    <!-- 点亮规则只有一条：**当前页是谁就亮谁**（V1.0.4）。
         以前用 `entryKey===sub.key` —— 那是"入口"，不是"当前页"，
         于是「推演」和页内「口径与来源」同时亮、点完也不灭。
         合并入口在"当前页是它的兄弟 tab"时只保留"你在这个入口里"的弱标识（entry-context）。 -->
    <div class="nav-subs" v-if="activeGroup" :data-group="activeGroup.key"><template v-for="group in NAV_GROUPS" :key="group.key"><button v-for="sub in visibleSubs(group)" :key="sub.key" :data-section="sub.key" v-show="group.key===activeGroup?.key" :class="{active:activeSection===sub.key, 'entry-context':sub.merged&&entryKey===sub.key&&activeSection!==sub.key}" @click="activeSection=sub.key">{{ sub.label }}</button></template><template v-if="entryTabList.length"><span class="nav-tab-sep" aria-hidden="true">|</span><button v-for="tab in entryTabList" :key="tab.key" class="nav-entry-tab" :data-entry-tab="tab.key" :class="{active:activeSection===tab.key}" @click="activeSection=tab.key">{{ tab.label }}</button></template></div>
    <div class="nav-fill">
      <!-- 这个下拉只对东北那套（session/network）有效；全国台用 scope 下钻，
         把它挂在首页会显示"东北三省 · 全域"，让人以为全国页还是东北的。 -->
      <label class="nav-region" v-if="!nationScopeView" title="运行区域"><select aria-label="运行区域" v-model="city" @change="selectedId='';page=1"><option value="">东北三省 · 全域</option><optgroup v-for="p in provinces" :label="p" :key="p"><option v-for="c in network?.cities.filter(c=>c.province===p)||[]" :key="c.id" :value="c.id">{{c.capital?'省会 · ':''}}{{c.name}}</option></optgroup></select></label>

      <button class="nav-toggle" data-settings-toggle :class="{on:settings}" :aria-pressed="settings" title="运行设置：情景、重新调度、信息密度、本页可做" @click="settings=!settings">设置</button>
    </div>
  </nav>
  <div class="wb-body">
  <section class="traffic-toolbar" v-show="settings">
    <div class="toolbar-cando" data-can-do>
      <b>本页可做</b>
      <span v-for="item in canDo" :key="item">{{ item }}</span>
    </div><label>运行情景 <select v-model="scenario" :disabled="busy"><option value="live">公开天气驱动 / 模拟交通</option><option value="clear">无气象声明 / 交通交汇</option><option value="unknown">气象中断 / 暂停放行</option></select></label><button class="primary" @click="generate" :disabled="busy||!network">{{busy?buildLabel:'重新调度'}}</button><label class="settings-density" data-density-switch><span>信息密度</span><select aria-label="信息密度" v-model="density" :title="densityNote"><option v-for="tier in DENSITY_TIERS" :key="tier.key" :value="tier.key">{{tier.label}}</option></select></label><label class="settings-density" data-operator-switch><span>操作员角色</span><select aria-label="操作员角色" v-model="operator" title="决定你能做哪些写操作：观察员只读；值班员可暂停/恢复/处置；管理员可切换气象通道" @change="applyOperator"><option value="observer">观察员（只读）</option><option value="duty">值班员（处置）</option><option value="admin">管理员（切通道）</option></select></label><span class="traffic-session">{{sessionLabel}} · {{ready?'运行计划已就绪':'等待计算'}} · {{session?.weatherSnapshot?.dataType==='MODEL_ESTIMATE'||session?.weatherSnapshot?.dataType==='PROVIDER_CURRENT_ESTIMATE_OR_OBSERVATION_UNVERIFIED'?'天气为公开来源（非本系统合成）':'本场景未声明气象'}}</span><details class="traffic-repro" data-repro-params :open="densityPolicy(density).engineering"><summary>工程信息 · 复现参数</summary><dl><div><dt>数据快照编号</dt><dd>{{ready?session.seed:'—'}}</dd></div><div><dt>计划标识</dt><dd>{{session?.sessionId?.slice(0,12)||'—'}}</dd></div><div><dt>计划修订</dt><dd>{{session?.planRevision??'—'}}</dd></div><div><dt>算法版本</dt><dd>{{session?.version||'—'}}</dd></div><div><dt>算法标识</dt><dd data-algorithm-identity :title="algorithmIdentityNote">{{algorithmIdentityLabel||'—'}}</dd></div><div><dt>算法指纹</dt><dd>{{session?.fingerprint||'—'}}</dd></div><div><dt>气象通道</dt><dd>{{weatherModeIsVirtual(weatherMode)?'虚拟气象':'实测气象'}}</dd></div></dl><p>数据快照编号 + 算法指纹 + 气象通道三者相同，重跑即得到逐字节相同的运行计划。本区只读，不参与业务操作。</p></details></section>
  <div class="traffic-error" v-if="error" role="alert">{{error}} <button @click="network?generate():initialize()" :disabled="busy">重试</button></div>
  <div class="traffic-channel-warning" v-if="!error&&channelMismatch&&ready" role="status"><span>{{channelMismatch}}</span><button @click="generate" :disabled="busy">{{busy?'正在重建':`按${weatherModeIsVirtual(weatherMode)?'虚拟':'实测'}通道重新调度`}}</button></div>

  <!-- V1.0.2：首页就是全国四级态势（全国 → 大区 → 省 → 市）。
       `national` 是旧地址，applyHash 已把它归到 home，这里一并渲染同一组件，
       所以不存在"两套全国页"。旧的首屏组件 `HomeStage.vue`（东北 maplibre 运行图）
       在 9aafd7f 之后**已经没有任何地方引用**，只剩测试还在读它的源码；
       三维能力以 NationGlobe.vue 的形式回来了。是否删除 HomeStage 取决于要不要
       保留那批只针对它的用例（删了用例数会从 506 掉下来，材料里的数字要跟着改）。 -->
  <section class="traffic-page national-page" v-if="activeSection==='home'||activeSection==='national'">
    <!-- 首页这一份也要接 open-corridor：处置事件在首页的「处置」页签里点开，
         没有这个监听就只会原地不动（实测点了没反应）。 -->
    <NationPanel :scope-key="nationScopeKey" :focus-corridor="corridorFocusId"
                 @scope-change="onScopeChange" @open-corridor="openCorridor" @tick="onNationTick"/>
  </section>
  <!-- 运行总览同样四级：全国走全国台，切到东北才用 V1.0.0 那张 maplibre 运行图。
       两者共用同一个 scope 变量，避免"总览是东北、情报是全国"的错位。 -->
  <!-- 运行总览默认落「台账」视图：首页已经是地图态势，两个入口看同一张图没有意义。
       总览给的是逐班次数据，首屏看地图、要看数就点这里。 -->
  <section class="traffic-page national-page" v-if="activeSection==='overview'&&scope==='nation'">
    <NationPanel :scope-key="nationScopeKey" initial-view="ledger" @scope-change="onScopeChange" @tick="onNationTick"/>
  </section>
  <!-- V1.0.5：一个分节只放一个视图。气象监测=情报（左表右气象统计）、
       运行总览=台账、处置=处置，各自由左侧导航进入；页内不再有 tab 条，
       也不再提供"全国/东北"作用域切换（东北那套已从界面下线）。 -->
  <section class="traffic-page national-page"
           v-if="['weather','profile','alerts','assistant','card'].includes(activeSection)">
    <NationPanel :scope-key="nationScopeKey" :initial-view="nationViewOf(activeSection)"
                 :mode="activeSection==='weather'?'weather':(activeSection==='card'?'card':(activeSection==='profile'?'corridor':(activeSection==='assistant'?'evidence':'')))"
                 :hint="NATION_HINTS[activeSection]||''"
                 :focus-corridor="corridorFocusId"
                 :hide-tabs="false" @scope-change="onScopeChange"
                 @open-corridor="openCorridor" @tick="onNationTick"/>
  </section>
  <OperationsConsole v-if="!['home','overview','schedule','national'].includes(activeSection)&&!['briefing','weather','profile','alerts','assistant','card'].includes(activeSection)" :corridor-focus="corridorFocus" :corridor-pair="corridorPair" :view="activeSection" :session="session" :network="network" :flights="scoped" :weather="weather" :selected="selected" :minute="minute" :city-name="cityName" :operations="operations" :density="density" :focus="drillFocus" :weather-mode="weatherMode" :weather-mode-status="weatherModeStatus" :alert-flights="scoped" :event-focus="eventFocus" :ai-reviewed="aiReviewed" @select-flight="chooseFlight" @weather-mode-change="onWeatherModeChange" @locate-event="locateEvent" @ai-reviewed="onAiReviewed" @open-section="activeSection=$event" @seek="minute=$event" @open-corridor="openCorridor" :max-minute="playbackMax"/>
  <!-- 调度台账：处置大类下的第二个页签。情报已经并到「气象监测」，这里只剩台账。 -->
  <section class="traffic-page scope-page" v-if="activeSection==='schedule'">
    <div class="scope-bar" data-scope-bar>
      <b>调度台账</b>
      <span class="scope-note">气象与雷达为公开源实况；交通为模拟（SIM），不参与运行计划</span>
    </div>
    <!-- 密度档在这里生效：值班员/指挥默认展开口径说明，演示档收起。
        （`DENSITY_POLICY.ledger` 必须有界面消费点，否则切档位屏幕上什么都不变 ——
        以前这条开关的消费点在东北那张已下线的台账表里。） -->
    <details class="ledger-note density-fold" :open="densityPolicy(density).ledger" data-density="ledger">
      <summary>这一页的数怎么来的</summary>
      <p>台账按当前分钟的快照重算：起降时刻是计划值，绕飞 / 停飞是<b>此刻</b>的裁决结果。
        交通为模拟派生（SIM），气象与雷达来自公开源；两者不合并成"综合风险"一个数。</p>
    </details>
    <!-- 给组件一个确定高度的槽位：它内部靠 flex:1 让表体滚动，父级不给高度就不滚 -->
    <div class="scope-body">
      <NationBriefing view="ledger" variant="ledger" self-fetch/>
    </div>
  </section>
  </div>
  </div>
  <div class="nav-tour" v-if="tourStep>=0&&activeSection!=='national'" role="dialog" aria-modal="false" data-nav-tour
       :data-step="tourStep+1">
    <div class="nav-tour-card">
      <b>第 {{ tourStep+1 }} / {{ TOUR_STEPS.length }} 步 · {{ TOUR_STEPS[tourStep].label }}</b>
      <p>{{ TOUR_STEPS[tourStep].text }}</p>
      <div class="nav-tour-actions">
        <button class="primary" @click="nextTour">{{ tourStep>=TOUR_STEPS.length-1?'知道了':'下一步' }}</button>
        <button @click="endTour">{{ tourForced?'关闭':'跳过并不再提示' }}</button>
      </div>
    </div>
  </div>
  <div class="first-visit" v-if="firstVisit&&tourStep<0" role="status" data-first-visit @click="dismissFirstVisit">
    提示：按 <b>Ctrl+K</b> 可直接搜索走廊号或班次号。
    <button class="first-visit-again" @click.stop="startTour(true)">再看一遍引导</button>
  </div>
  <CommandPalette :open="paletteOpen" :groups="NAV_GROUPS" :routes="paletteRoutes" :flights="paletteFlights"
                  @close="paletteOpen=false" @run="onPaletteRun"/>
</main>
<!-- 建场进度条只属于东北那套（会按气象重建计划）；全国网是 SIM，不参与建场，
     全国页上挂着一条 0% 的进度条只会让人以为卡死了。 -->
<div class="traffic-build-strip" v-if="showBuildStrip" role="status" aria-live="polite" data-build-strip>
  <div class="tbs-track" :class="{pending:buildProgress===null}" role="progressbar"
       :aria-valuenow="buildProgress===null?undefined:buildProgress"
       :aria-valuetext="buildProgress===null?'暂无数值进度，等待前面的计划完成':undefined"
       aria-valuemin="0" aria-valuemax="100" :aria-label="buildStage">
    <div class="tbs-fill" :class="{pending:buildProgress===null}" :style="buildProgress===null?{}:{width:buildProgress+'%'}"></div>
  </div>
  <p class="tbs-text">
    <strong class="tbs-num">{{buildProgress===null?'—':buildProgress+'%'}}</strong>
    <span class="tbs-stage">{{buildStage}}</span>
    <span class="tbs-note">{{buildElapsedText}} · 之后同一情景与快照编号直接命中缓存</span>
  </p>
</div>
</template>
<style scoped>
.traffic-page{display:flex;flex-direction:column;padding:14px 20px 16px;min-height:0}
/* 全国台是一屏运行台，不是一段可滚的长文：占满可视高度，内部各自滚动。
   以前写死 `calc(100vh - 168px)` —— 168 是旧版"顶部栏 + 二级 tab"两层的估计值，
   现在二级 tab 并进了左侧导航，实际只剩顶部栏（约 70px），于是每屏底部空出 80–100px，
   1366×768 下地图被白压一圈。改成 flex 填满：父级 .wb-body 已是 flex 列，不需要再估高度。 */
.traffic-page.national-page,
.traffic-page.scope-page{padding:10px 16px 12px;min-height:0;
  flex:1 1 auto;height:auto;min-height:min(560px,calc(100vh - 96px))}
.scope-body{flex:1;min-height:0;display:flex;flex-direction:column}
.scope-bar{display:flex;align-items:center;gap:8px;padding:0 2px 8px;font-size:12px;color:#82a6bd}
.scope-bar b{font-size:13px;color:#eaf6ff;font-weight:600}
.scope-bar button{background:#10283a;border:1px solid #2b4c62;color:#a9cde2;border-radius:5px;padding:3px 11px;font-size:11.5px;cursor:pointer}
.scope-bar button.on{background:#1d5670;border-color:#3f8ba8;color:#c8f0ff}
.scope-bar .scope-note{margin-left:auto;font-size:11px;color:#6f92a8}
.scope-bar.floating{position:fixed;left:50%;transform:translateX(-50%);top:64px;z-index:40;
  background:rgba(10,26,38,.92);border:1px solid rgba(70,110,140,.5);border-radius:8px;
  padding:5px 10px;box-shadow:0 6px 18px rgba(0,0,0,.35)}
.wb-demo-bar{margin:0;padding:6px 12px;font-size:var(--alc-fs-aux);color:var(--alc-watch);
  background:rgba(250,173,20,.10);border-bottom:1px solid rgba(250,173,20,.35);line-height:1.5}
.wb-demo-bar code{font-family:ui-monospace,Consolas,monospace;color:var(--alc-text)}
.operations-nav{display:flex;align-items:center;gap:6px;padding:8px;background:#0e2131;border:1px solid #294354;border-radius:9px;margin:12px 0}.operations-nav button{border:0!important;background:transparent!important;padding:10px 15px!important;font-size:13px!important}.operations-nav button.active{background:#24566e!important;color:#c6f4ff!important}.operations-nav select{max-width:210px;min-width:0;flex:0 1 auto}.traffic-workbench .traffic-header{margin-bottom:12px}.traffic-workbench .traffic-summary{margin-bottom:9px}.traffic-workbench .traffic-summary>div{padding:6px 14px}.traffic-workbench .traffic-summary strong{font-size:21px;line-height:1.35}.traffic-workbench .traffic-summary span{font-size:12px}.traffic-workbench .traffic-main{grid-template-columns:minmax(0,1fr) 300px}.traffic-workbench .traffic-table-scroll{max-height:calc(100vh - 390px);min-height:300px}.traffic-workbench .traffic-map-heading{padding:12px 14px}@media(max-width:1000px){.operations-nav{flex-wrap:wrap}.operations-nav .nav-fill{margin-left:0;width:100%;order:3}.operations-nav select{margin-left:0}.operations-nav .nav-map-status{max-width:none}.traffic-workbench .traffic-main{grid-template-columns:minmax(0,1fr)}}@media(max-width:700px){.traffic-workbench .traffic-main{grid-template-columns:1fr}.operations-nav button{font-size:12px!important;padding:8px!important}}
.traffic-workbench{display:flex;flex-direction:column;height:100%;overflow-y:auto;overflow-x:hidden;padding:14px 20px 18px;background:
  radial-gradient(1400px 620px at 50% -14%,rgba(38,108,205,.20),transparent 62%),
  radial-gradient(1000px 460px at 90% 108%,rgba(24,84,168,.13),transparent 60%),
  linear-gradient(rgba(64,140,230,.038) 1px,transparent 1px),
  linear-gradient(90deg,rgba(64,140,230,.038) 1px,transparent 1px),
  radial-gradient(ellipse at 50% -10%,#17314b 0,transparent 45%),
  #080f19;
  background-size:auto,auto,44px 44px,44px 44px,auto,auto;
  color:#d6e5ef;font-size:13px}
.traffic-detail,.traffic-map-panel{
  background:linear-gradient(165deg,rgba(17,38,72,.90) 0%,rgba(9,22,44,.90) 55%,rgba(8,18,38,.92) 100%)!important;
  border-color:rgba(64,140,230,.26)!important;
  box-shadow:inset 0 1px 0 rgba(120,180,255,.10),inset 0 0 30px rgba(28,92,180,.07),0 4px 18px rgba(0,0,0,.35);
  position:relative;
}
.traffic-detail::before,.traffic-map-panel::before,
.traffic-detail::after,.traffic-map-panel::after{
  content:"";position:absolute;width:14px;height:14px;pointer-events:none;z-index:4;
  filter:drop-shadow(0 0 4px rgba(61,139,255,.8))}
.traffic-detail::before,.traffic-map-panel::before{
  left:-1px;top:-1px;border-left:2px solid #3d8bff;border-top:2px solid #3d8bff;border-top-left-radius:10px}
.traffic-detail::after,.traffic-map-panel::after{
  right:-1px;bottom:-1px;border-right:2px solid #3d8bff;border-bottom:2px solid #3d8bff;border-bottom-right-radius:10px}
.traffic-panel-title{position:relative;background:linear-gradient(90deg,rgba(61,139,255,.10),transparent 55%)}
.traffic-panel-title::before{
  content:"";position:absolute;left:6px;top:50%;transform:translateY(-50%);
  width:4px;height:15px;border-radius:2px;
  background:linear-gradient(180deg,#3d8bff,#27e0ff);box-shadow:0 0 8px rgba(61,170,255,.9)}
.traffic-panel-title::after{
  content:"";position:absolute;left:0;right:0;bottom:0;height:1px;
  background:linear-gradient(90deg,rgba(61,139,255,.55),rgba(61,139,255,.08))}
.traffic-panel-title{text-indent:14px}
.traffic-header h1{background:linear-gradient(180deg,#ffffff 20%,#8ec4ff 90%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;filter:drop-shadow(0 0 14px rgba(61,139,255,.55))}
.traffic-eyebrow{text-shadow:0 0 8px rgba(61,139,255,.5)}
.traffic-summary{overflow:hidden;box-shadow:inset 0 1px 0 rgba(120,180,255,.10),0 4px 18px rgba(0,0,0,.28)}
.traffic-summary>div{background:linear-gradient(180deg,rgba(61,139,255,.055),transparent 42%)}
.traffic-playback{background:linear-gradient(180deg,rgba(17,38,72,.92),rgba(9,22,44,.92))!important;box-shadow:inset 0 1px 0 rgba(120,180,255,.09)}
.operations-nav{box-shadow:inset 0 1px 0 rgba(120,180,255,.09)}
.wb-theme{border:1px solid #2c4a60;background:rgba(18,38,54,.7);color:#bcd7e8;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer;white-space:nowrap}.wb-theme:hover{background:rgba(40,86,112,.7);color:#e6f6ff}.wb-theme[aria-pressed="true"]{background:#e3f0fb;border-color:#7fb3d8;color:#0d4f74}.traffic-workbench.page-mode{overflow-y:auto}.traffic-workbench.page-mode .traffic-main,.traffic-workbench.page-mode .traffic-playback,.traffic-workbench.page-mode .traffic-overview-playback,.traffic-workbench.page-mode .traffic-secondary-head,.traffic-workbench.page-mode .traffic-overview-pointer{display:none}
.traffic-workbench button,.traffic-workbench select,.traffic-workbench input:not([type=checkbox]):not([type=range]){background:#122334;color:#bcd3e2;border:1px solid #294153;border-radius:6px;padding:8px 11px;font:inherit}.traffic-workbench button{cursor:pointer}.traffic-workbench button:hover{border-color:#65cce5;color:white}.traffic-workbench button:disabled{opacity:.45;cursor:default}.traffic-workbench button.primary{background:#246279;color:#effcff;border-color:#398098}.traffic-workbench input[type=checkbox]{accent-color:#59dffc}.traffic-workbench input[type=range]{accent-color:#59dffc;min-width:100px}
.traffic-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,auto) minmax(0,1fr);gap:20px;align-items:center;margin-bottom:14px}
.traffic-header>.traffic-brand{grid-column:2;display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;min-width:0;max-width:100%;justify-self:center}
.traffic-eyebrow{font-size:12px;letter-spacing:3px;color:#688a9e;white-space:nowrap}
.traffic-header h1{font-size:25px;letter-spacing:1px;line-height:1.35;white-space:nowrap}
.traffic-badge{font-size:12px;padding:4px 8px;color:#f7ce89;border:1px solid #675636;border-radius:4px;letter-spacing:0;flex:none;white-space:nowrap}
.traffic-header p{color:#7895a8;font-size:12px;white-space:nowrap}
.traffic-header-actions{grid-column:3;justify-self:end;display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
@media(max-width:1180px){
  .traffic-header{grid-template-columns:minmax(0,1fr) minmax(0,auto) minmax(0,1fr)}
  .traffic-header>.traffic-brand{gap:10px 12px}
  .traffic-header h1{font-size:21px}
}
@media(max-width:900px){
  .traffic-header{grid-template-columns:minmax(0,1fr)}
  .traffic-header>.traffic-brand{grid-column:1}
  .traffic-header-actions{grid-column:1;justify-self:center}
  .traffic-eyebrow,.traffic-header h1,.traffic-header p{white-space:normal}
  .traffic-header h1{font-size:19px}
}
.traffic-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border:1px solid #263949;border-radius:10px;background:#101e2c;margin-bottom:16px}
.traffic-summary>div{padding:16px 20px;border-right:1px solid #263949;min-width:0;overflow:hidden}
.traffic-summary>div:last-child{border:0}
.traffic-summary small{color:#8ea7b8;font-size:12px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.traffic-summary strong{display:block;font-size:27px;font-weight:500;line-height:1.8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.traffic-summary strong em{font-style:normal;font-size:12px;color:#809bac}
.traffic-summary span{color:#6d899d;font-size:12px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cyan{color:#64ddf6}.amber{color:#e8bd72}
.traffic-toolbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:15px;color:#89a3b4}.traffic-toolbar label{display:flex;align-items:center;gap:8px;font-size:12px}.traffic-toolbar input{width:100px}.traffic-session{margin-left:auto;font-size:12px;flex:none;white-space:nowrap;min-width:0;overflow:hidden;text-overflow:ellipsis}
.traffic-repro{width:100%;font-size:12px;color:#86a6bd;border-top:1px solid #23414f;padding-top:9px}
.traffic-repro>summary{cursor:pointer;letter-spacing:.5px;color:#7fa5bd;list-style:none}
.traffic-repro>summary::-webkit-details-marker{display:none}
.traffic-repro>summary::before{content:'▸ ';color:#4d7f96}
.traffic-repro[open]>summary::before{content:'▾ '}
.traffic-repro dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:6px 18px;margin:10px 0 0}
.traffic-repro dl>div{display:flex;align-items:baseline;gap:8px;min-width:0}
.traffic-repro dt{color:#6d8ea6;font-size:12px;letter-spacing:.5px;flex:0 0 auto}
.traffic-repro dd{margin:0;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:#b6dcec;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.traffic-repro>p{margin:9px 0 0;font-size:12px;color:#65859c;line-height:1.6}.traffic-error{background:#5a2c10;border:1px solid #a8622a;color:#ffd9a8;padding:12px;margin-bottom:12px;border-radius:8px;display:flex;justify-content:space-between;align-items:center}
.traffic-channel-warning{background:#4a3a1e;border:1px solid #94703f;color:#ffe6b8;padding:10px 12px;margin-bottom:12px;border-radius:8px;display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:12px;line-height:1.6}
.traffic-channel-warning button{flex:none}
.traffic-main{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;align-items:stretch}.traffic-detail,.traffic-map-panel{border:1px solid #22394a;border-radius:12px;background:#0e1b29;min-width:0}.traffic-panel-title{padding:15px;border-bottom:1px solid #233848;display:flex;justify-content:space-between;align-items:center;font-size:13px;font-weight:600}.traffic-panel-title button{padding:3px 8px}
.traffic-map-panel{display:flex;flex-direction:column;position:relative;overflow:hidden}
.traffic-map-heading{padding:12px 14px;display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.traffic-map-heading>div:first-child{min-width:0}
.traffic-map-heading>div:last-child{display:flex;gap:6px;flex:none;flex-wrap:wrap;justify-content:flex-end}
.traffic-map-heading h2{font-size:17px;font-weight:500;margin-bottom:5px}
.traffic-map-heading h2 small{font-size:12px;color:#668da3;margin-left:10px}
.traffic-map-heading span{font-size:12px;color:#718fa3}
.traffic-layer-row{display:flex;flex-direction:column;gap:6px;padding:0 14px 8px;border-bottom:1px solid #233848}
.traffic-layer-toggles{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:#8babbf;line-height:1.5;align-items:center}
.traffic-layer-toggles label{display:flex;gap:5px;align-items:center;white-space:nowrap}
.traffic-layer-toggles i{height:5px;width:5px;border-radius:50%;display:inline-block;flex:none}
.car-dot{background:#55dcff}.delivery-dot{background:#ffcf75}.fixed-zone-dot{background:#a5b4fc}
.radar-dot{background:linear-gradient(135deg,#ffc107,#e7b268 62%,#e08a45)}
.risk-dot{background:#e08a45;box-shadow:0 0 0 1px #e5b98f}
.fog-dot{background:linear-gradient(135deg,#c8cedb,#5c6472 62%,#3f4653);box-shadow:0 0 0 1px #8d94a3}
.wind-dot{background:#45c4a5}
.event-dot{background:transparent;border:1.5px solid #e08a45;box-sizing:border-box}
.obs-dot{background:#bfeaf6;box-shadow:0 0 0 1px #7fb2c8}
.traffic-map-panel :deep(.city-map-stack){flex:1;min-height:0}.traffic-map-panel :deep(.city-map-shell){flex:1;min-height:0;border-radius:0}
.operations-nav .nav-fill{margin-left:auto;display:flex;align-items:center;gap:12px;row-gap:8px;flex-wrap:wrap;min-width:0;padding-right:4px}
.operations-nav .nav-map-status{font-size:12px;color:#7fa5bd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px}
.operations-nav .nav-algorithm{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;letter-spacing:.3px;color:#8fd6e8;border:1px solid #2d5d72;background:rgba(38,97,117,.18);border-radius:5px;padding:3px 7px;white-space:nowrap;cursor:help;flex:0 0 auto}
@media(max-width:1200px){.operations-nav .nav-algorithm{display:none}}
.operations-nav .nav-density{display:flex;align-items:center;gap:6px;flex:0 1 auto;min-width:0}
.operations-nav .nav-density>span{font-size:12px;color:#6f92a8;white-space:nowrap}
.operations-nav .nav-density select{padding:5px 8px!important;font-size:12px!important;max-width:120px}
.traffic-table-panel .density-fold>summary{font-size:12px;color:#9fd9e2;cursor:pointer;
  padding:10px 18px;background:#142536;border-top:1px solid #1c3041;list-style-position:inside}
.traffic-table-panel .density-fold>summary span{font-size:12px;color:#6f92a8;margin-left:9px}
.traffic-table-panel .density-fold>summary:hover{color:#c6eef5}
@media(max-width:1800px){
  .operations-nav{flex-wrap:wrap;row-gap:8px}
  .operations-nav>button{order:1;flex:0 0 auto}
  .operations-nav .nav-fill{margin-left:0;width:100%;order:3;padding-right:0}
  .operations-nav .nav-map-status{max-width:none;flex:1 1 auto}
  .operations-nav .nav-region{margin-left:auto;order:2}
}
.nav-region{display:flex;align-items:center;gap:7px;flex:0 1 auto;min-width:0}
.nav-region>span{font-size:12px;letter-spacing:1px;color:#7fa5bd;white-space:nowrap}
.nav-region select{max-width:250px;min-width:0;flex:0 1 auto}
.detail-scope{font-size:12px;font-weight:400;color:#6d899d;text-indent:0;white-space:nowrap}
.traffic-legend{position:relative;margin-left:auto;font-size:12px;color:#7794a8}
.traffic-legend summary{cursor:pointer;list-style:none;padding:2px 8px;border:1px solid var(--alc-line);
  border-radius:5px;user-select:none}
.traffic-legend summary::-webkit-details-marker{display:none}
.traffic-legend summary:hover{color:#c6d3e5}
.traffic-legend[open] summary{color:#c6d3e5;border-color:rgba(76,141,255,.45)}
.traffic-legend span{position:absolute;right:0;top:130%;z-index:20;display:block;
  width:min(560px,60vw);padding:8px 10px;border-radius:6px;line-height:1.6;
  background:rgba(17,26,43,.97);border:1px solid var(--alc-line);
  box-shadow:0 8px 24px rgba(0,0,0,.35)}
.traffic-detail{display:flex;flex-direction:column}.traffic-flight-title{padding:18px 16px 10px}.traffic-flight-title small{color:#8dc1ce;font-size:12px}.traffic-flight-title h2{font-size:17px;line-height:1.5;margin:9px 0}.traffic-flight-title code{font-size:12px;color:#64869b;overflow-wrap:anywhere}.detail-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px 8px;padding:15px}.detail-grid small{display:block;color:#6e90a6;font-size:12px;margin-bottom:5px}.detail-grid b{font-size:12px;font-weight:500}.traffic-profile{padding:15px;background:#0a1722;margin:0 12px;border-radius:7px}.traffic-profile span{font-size:12px;color:#94b3c4}.traffic-profile svg{width:100%;display:block;margin:12px 0 4px}.traffic-profile small{color:#7f9cb5;font-size:12px}.traffic-reason{padding:16px;font-size:12px;color:#84a4ba;line-height:1.8}.traffic-reason h3{font-size:12px;color:#83d3de;margin-bottom:7px}.traffic-static-crossing{padding:0 16px 16px;font-size:12px;color:#9d94c6;line-height:1.9;border-top:1px solid #2a2440;margin-top:2px;padding-top:14px}
.traffic-clearance{padding:14px 16px;margin:10px 12px 0;border:1px solid #2c4a5e;border-radius:8px;background:#0c2431}
.traffic-clearance h3{font-size:12px;color:#7fdce8;margin-bottom:10px;letter-spacing:1px}
.traffic-clearance dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:7px 12px;margin:0}
.traffic-clearance dt{font-size:12px;color:#7c9db2;white-space:nowrap}
.traffic-clearance dd{font-size:12px;color:#cfe6f2;margin:0;overflow-wrap:anywhere;line-height:1.6}
.traffic-clearance small{display:block;font-size:12px;color:#6d8ba0;line-height:1.7;margin-top:11px;padding-top:9px;border-top:1px dashed #24404f}.traffic-static-crossing h3{font-size:12px;color:#c4b5fd;margin-bottom:7px}.traffic-static-crossing small{display:block;font-size:12px;color:#7c7398;line-height:1.8;margin-top:8px}.traffic-reason code{font-size:12px;overflow-wrap:anywhere}.traffic-detail>button{margin:0 15px 15px}.traffic-disclaimer{font-size:12px;color:#7f9cb5;line-height:1.8;padding:15px;margin-top:auto;border-top:1px solid #213446}.traffic-empty{padding:25px 20px;color:#6b8ba1;line-height:1.9}.traffic-empty>span{font-size:40px;color:#32596f}.traffic-empty h3{color:#a3becd;font-size:15px;margin:10px 0}.traffic-empty p{font-size:12px}.traffic-rules{padding:0 18px 20px;font-size:12px;color:#7391a5;line-height:1.8}.traffic-rules h3{font-size:12px;color:#9cbaca;margin-bottom:9px}.traffic-rules p{margin-bottom:10px}
.traffic-playback{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:14px 0;padding:12px 16px;border:1px solid #22394a;background:#0e1b29;border-radius:10px;font-size:12px;color:#819fb2}.traffic-playback input{flex:1}.traffic-playback strong{font-size:14px;color:#c1eaf6;font-variant-numeric:tabular-nums;min-width:68px}.playback-note{font-size:12px}
.traffic-overview-playback{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:14px 0 0;padding:10px 14px;border:1px solid #2b4658;border-radius:9px;background:#0d1a26;color:#819fb2}.traffic-overview-playback input{flex:1;min-width:160px}.traffic-overview-playback strong{min-width:68px;color:#c1eaf6;font-variant-numeric:tabular-nums}.traffic-secondary-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin:14px 0;padding:16px 18px;border:1px solid #22394a;border-radius:10px;background:#101e2c}.traffic-secondary-head h2{font-size:16px;font-weight:500}.traffic-secondary-head h2 small{font-size:12px;color:#698ea6;margin-left:10px}.traffic-secondary-head p{font-size:12px;color:#678597;margin-top:7px;line-height:1.7;max-width:760px}.traffic-overview-pointer{display:flex;align-items:center;gap:10px;margin:14px 0 0;padding:10px 16px;border:1px dashed #2b4658;border-radius:9px;background:#0d1a26;font-size:12px;color:#7b99ad}
.traffic-table-panel{border:1px solid #22394a;border-radius:12px;background:#0e1b29;overflow:hidden}.traffic-table-heading{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:18px}.traffic-table-heading h2{font-size:15px;font-weight:500}.traffic-table-heading small{font-size:12px;color:#698ea6;margin-left:10px}.traffic-table-heading p{font-size:12px;color:#678597;margin-top:7px}.traffic-table-heading>div:last-child{display:flex;gap:8px}.traffic-table-scroll{overflow:auto;max-height:460px}.traffic-table-panel table{width:100%;border-collapse:collapse;text-align:left;font-size:12px;white-space:nowrap}.traffic-table-panel th{background:#142536;color:#7297ae;font-weight:400;padding:12px 16px;position:sticky;top:0}.traffic-table-panel td{padding:10px 16px;border-top:1px solid #1c3041;color:#b1c8d8}.traffic-table-panel td small{display:block;font-size:12px;color:#7f9cb5;margin-top:4px}.traffic-table-panel tr{cursor:pointer}.traffic-table-panel tr:hover,.traffic-table-panel tr.selected{background:#19384a}.traffic-table-panel .flight-link{border:0;background:transparent;padding:0;text-align:left}.flight-state{font-size:12px;padding:4px 6px;border-radius:4px;background:#203447;color:#7f9caf}.flight-state.AIRBORNE{background:#173e45;color:#6ad6c9}.flight-state.HOLD{background:#493b23;color:#e5bd72}.flight-state.CLOSED{background:#4a2a12;color:#ffd9a8}.traffic-pagination{display:flex;gap:14px;align-items:center;padding:12px 18px;color:#7797ac;font-size:12px}.traffic-pagination span{margin-right:auto}.traffic-no-results{text-align:center;padding:30px!important}
@media(min-width:1700px){.traffic-main{grid-template-columns:minmax(0,1fr) 340px}.traffic-map-panel :deep(.traffic-scene){min-height:620px}}
@media(max-width:1100px){.traffic-workbench{padding:14px}.traffic-main{grid-template-columns:minmax(0,1fr)}.traffic-detail{grid-column:1/-1;display:block}.traffic-empty,.traffic-rules{display:inline-block;width:48%;vertical-align:top}.detail-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.traffic-profile{max-width:500px}.traffic-summary{grid-template-columns:repeat(3,minmax(0,1fr))}.traffic-summary>div{border-bottom:1px solid #263949}.traffic-summary strong{font-size:23px}.traffic-header h1{font-size:19px}.traffic-session{margin-left:0}.playback-note{display:none}}
@media(max-width:700px){.traffic-main{grid-template-columns:1fr}.traffic-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.traffic-summary>div{padding:12px}.traffic-table-heading{align-items:flex-start;flex-direction:column}.traffic-toolbar label{flex-wrap:wrap}.traffic-map-heading h2 small{display:none}.traffic-layer-toggles{gap:10px}.traffic-empty,.traffic-rules{display:block;width:100%}.traffic-eyebrow{letter-spacing:1px}}

.traffic-workbench>*{flex:none}
.traffic-workbench.home-mode{padding:10px 12px 12px}
.traffic-workbench.home-mode .traffic-header,.traffic-workbench.home-mode .traffic-summary{display:none}
.traffic-workbench .traffic-main{flex:1 1 auto;grid-template-rows:minmax(0,1fr);min-height:620px}
.traffic-workbench.map-expanded .traffic-main{grid-template-columns:minmax(0,1fr)!important;min-height:460px}
.traffic-workbench.map-expanded .traffic-detail{display:none}
.traffic-workbench.map-expanded .traffic-layer-row{display:none}.traffic-workbench .traffic-map-panel{min-height:520px}.traffic-workbench :deep(.city-map-shell){min-height:0}.traffic-workbench .traffic-detail{overflow:auto;min-height:0}.traffic-playback{position:sticky;bottom:0;z-index:3;background:#0e2131}.traffic-workbench.map-expanded .traffic-header,.traffic-workbench.map-expanded .traffic-summary,.traffic-workbench.map-expanded .traffic-detail{display:none}.traffic-build-strip{position:fixed;left:0;right:0;top:0;z-index:60;pointer-events:none;
  background:linear-gradient(180deg,rgba(6,15,25,.96),rgba(6,15,25,.86));
  border-bottom:1px solid rgba(64,140,230,.34)}
.traffic-build-strip .tbs-track{position:relative;height:3px;background:#0d1c2b;overflow:hidden}
.traffic-build-strip .tbs-fill{position:absolute;left:0;top:0;bottom:0;
  background:linear-gradient(90deg,#2f7fd0,#59dffc);box-shadow:0 0 10px rgba(89,223,252,.55);
  transition:width .6s cubic-bezier(.4,0,.2,1)}
.traffic-build-strip .tbs-fill::after{content:"";position:absolute;inset:0;
  background-image:linear-gradient(115deg,rgba(255,255,255,.30) 0 10px,transparent 10px 22px);
  background-size:22px 100%;animation:traffic-build-shimmer .9s linear infinite}
@keyframes traffic-build-shimmer{from{background-position:0 0}to{background-position:22px 0}}
.traffic-build-strip .tbs-fill.pending{width:34%;animation:traffic-build-slide 1.6s ease-in-out infinite}
@keyframes traffic-build-slide{0%{left:-34%}100%{left:100%}}
.tbs-text{display:flex;align-items:baseline;gap:10px;margin:0;padding:7px 16px 8px;
  font-size:12px;color:#a9c9da;line-height:1.5;flex-wrap:wrap}
.tbs-num{font-size:14px;font-weight:600;color:#7fe3ff;font-variant-numeric:tabular-nums}
.tbs-stage{color:#cfe6f2}
.tbs-note{color:#7d9cb0}
@media(prefers-reduced-motion:reduce){.traffic-build-strip .tbs-fill{transition:none}
  .traffic-build-strip .tbs-fill::after{animation:none}.traffic-build-strip .tbs-fill.pending{animation:none}}
.traffic-workbench.map-expanded .traffic-main{grid-template-columns:1fr}.traffic-workbench.map-expanded .operations-nav{margin-top:0}@media(max-width:1000px){.traffic-workbench .traffic-main{grid-template-columns:1fr;min-height:520px}.traffic-workbench .traffic-map-panel{min-height:460px}}

/* 调度台账的口径说明：密度档控制默认开合，样式与其它 density-fold 一致 */
.ledger-note{margin:0 0 8px;font-size:12px;color:#8aa2b6}
.ledger-note summary{cursor:pointer;padding:4px 0;list-style:none}
.ledger-note summary::-webkit-details-marker{display:none}
.ledger-note summary::before{content:'▸ ';color:#5f7f96}
.ledger-note[open] summary::before{content:'▾ '}
.ledger-note p{margin:2px 0 0;line-height:1.65;color:#7d9cb0;max-width:900px}
html[data-theme="light"] .ledger-note{color:#4a6a85 !important}
html[data-theme="light"] .ledger-note p{color:#5b7a92 !important}
</style>

<style scoped>
.operations-nav{gap:10px}
.nav-groups{display:flex;gap:4px;flex:0 0 auto}
.nav-group{display:flex;align-items:center;gap:6px;padding:8px 12px;border:0;border-bottom:2px solid transparent;background:transparent;color:#93a4bc;font-size:14px;cursor:pointer}
.nav-group em{font-style:normal;font-size:12px;color:#6f92a8}
.nav-group:hover{color:#dce6f5}
.nav-group.active{color:#ffffff;border-bottom-color:var(--alc-info)}
.nav-group.active em{color:var(--alc-info)}
.nav-timebase{font-size:12px;color:#93a4bc;white-space:nowrap;padding:3px 8px;border:1px solid rgba(147,164,188,.28);border-radius:999px}
.nav-timebase.paused{color:#ffc857;border-color:rgba(220,170,60,.45)}
.nav-clock{font-size:12px;color:#cfe6f5;white-space:nowrap;padding:3px 8px;
  border:1px solid rgba(147,164,188,.28);border-radius:999px;font-variant-numeric:tabular-nums}
.nav-tour{position:fixed;right:16px;bottom:56px;z-index:120;max-width:360px}
.nav-tour-card{padding:14px 16px;border-radius:10px;background:#0e2038;border:1px solid #2f5f97;
  box-shadow:0 10px 30px rgba(0,0,0,.45);color:#dce9f7}
.nav-tour-card b{font-size:13px;color:#8fd2ff}
.nav-tour-card p{margin:8px 0 12px;font-size:13px;line-height:1.6}
.nav-tour-actions{display:flex;gap:8px}
.nav-tour-actions button{font-size:12px;padding:6px 12px;border-radius:6px;cursor:pointer;
  border:1px solid #2f5f97;background:transparent;color:#cfe3f7}
.nav-tour-actions .primary{background:#2f7fd4;border-color:#2f7fd4;color:#fff}
.first-visit-again{margin-left:10px;border:none;background:none;color:#8fd2ff;
  text-decoration:underline;cursor:pointer;font-size:12px}
.nav-toggle{padding:6px 10px;border:1px solid rgba(147,164,188,.28);background:transparent;color:#93a4bc;font-size:12px;border-radius:6px;cursor:pointer;white-space:nowrap}
.nav-toggle.on{border-color:var(--alc-info);color:#ffffff;background:rgba(76,141,255,.18)}
.nav-subs{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 20px;border-bottom:1px solid rgba(147,164,188,.16);background:rgba(11,18,32,.6)}
.nav-subs-hint{font-size:12px;color:#6f92a8;margin-right:4px}
.nav-subs button{padding:5px 12px;border-radius:6px;border:1px solid transparent;background:transparent;color:#93a4bc;font-size:13px;cursor:pointer}
.nav-subs button:hover{background:rgba(147,164,188,.10);color:#dce6f5}
.nav-subs button.active{background:rgba(76,141,255,.16);border-color:rgba(76,141,255,.5);color:#ffffff}
/* 多成员入口（处置/推演/运行总览）的按钮在"当前页是它的兄弟 tab"时只表示
   「你在这个分组里」，不是「当前页面」——真正的当前视图由页内 tab 表达。
   V1.0.4：这条规则以前叫 group-active，且被后面 `.nav-subs button.active` 覆盖，
   于是入口和 tab 一起亮、点完不灭。现在改成独立的 entry-context 类，
   与 active 互斥，不再靠"同特异性抢顺序"。 */
.nav-subs button.entry-context{background:transparent;border-color:transparent;
  color:#a8bdd0;box-shadow:inset 2px 0 0 rgba(76,141,255,.55);border-radius:4px 6px 6px 4px}

.nav-tab-sep{color:#2f4257;margin:0 2px;font-size:12px;user-select:none}
.nav-entry-tab{padding:4px 10px;border-radius:5px;border:1px solid transparent;
  background:transparent;color:#7c8fa6;font-size:12px;cursor:pointer}
.nav-entry-tab:hover{background:rgba(147,164,188,.08);color:#c6d3e5}
.nav-entry-tab.active{background:rgba(76,141,255,.10);border-color:rgba(76,141,255,.32);
  color:#cfe0ff}
.nav-subs-tip{margin-left:auto;font-size:12px;color:#5d6f86}
.settings-density{display:flex;align-items:center;gap:6px}
.settings-density>span{font-size:12px;color:#6f92a8}

.nav-help{position:relative}
.nav-help-body{position:absolute;right:0;top:34px;z-index:60;width:300px;padding:12px 14px;border-radius:8px;background:var(--alc-bg-2);border:1px solid #294354;box-shadow:0 14px 30px rgba(0,0,0,.5)}
.nav-help-body b{font-size:14px;color:var(--alc-text)}
.nav-help-body ul{margin:8px 0 6px;padding-left:18px}
.nav-help-body li{font-size:13px;line-height:1.7;color:var(--alc-text)}
.nav-help-body small{font-size:12px;color:var(--alc-text-mute)}
.first-visit{position:fixed;right:20px;bottom:18px;z-index:70;padding:10px 14px;border-radius:8px;background:rgba(17,26,43,.96);border:1px solid var(--alc-info);color:var(--alc-text);font-size:13px;cursor:pointer;box-shadow:0 10px 26px rgba(0,0,0,.45)}
.first-visit b{color:var(--alc-info)}

.operations-nav{display:flex;align-items:center;flex-wrap:nowrap;gap:6px;padding:4px 10px;min-height:40px;margin:6px 0 8px;border-radius:8px}
.nav-brand{display:flex;flex-direction:column;line-height:1.05;padding-right:8px;border-right:1px solid var(--alc-line);flex:none}
.nav-brand b{font-size:14px;letter-spacing:.3px;color:#e8f2ff}
.nav-brand em{font-size:12px;color:var(--alc-text-mute);font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px}
.nav-groups{display:flex;gap:1px;flex:none}
.operations-nav .nav-group{padding:5px 8px!important;font-size:13px!important;border-radius:6px;white-space:nowrap}
.operations-nav .nav-group em{font-size:12px;opacity:.7;margin-right:3px;font-style:normal}
.nav-subs{display:flex;gap:1px;align-items:center;flex:1 0 100%;order:9;padding:0 2px 2px}
.operations-nav{flex-wrap:wrap;row-gap:0}
.nav-subs::-webkit-scrollbar{display:none}
.nav-subs button{padding:4px 8px!important;font-size:12px!important;border-radius:6px;white-space:nowrap}
.nav-fill{margin-left:auto;display:flex;align-items:center;gap:6px;flex:0 1 auto;min-width:0;overflow:hidden}
.nav-region select{max-width:150px;font-size:12px!important;padding:3px 4px!important}
.nav-algorithm{max-width:210px;font-size:12px;color:var(--alc-text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nav-timebase{font-size:12px;color:var(--alc-text-dim);white-space:nowrap;flex-shrink:0}
.operations-nav .nav-toggle{padding:4px 8px!important;font-size:12px!important}

.relay-pill{margin-left:10px;padding:2px 9px;border-radius:10px;font-size:11px;line-height:1.6;
  background:rgba(17,26,43,.9);border:1px solid var(--alc-line);color:var(--alc-text-dim);
  cursor:help;white-space:nowrap;font-variant-numeric:tabular-nums}
.relay-pill.ok{border-color:rgba(82,196,26,.45);color:#9fd88a}
.relay-pill.failed{border-color:rgba(214,72,54,.55);color:#f0a99e}
.traffic-relay-note.failed,.traffic-relay-note.error{border-color:var(--alc-watch);color:var(--alc-watch)}

.toolbar-cando{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;padding:6px 2px 8px;border-bottom:1px dashed var(--alc-line);margin-bottom:6px}
.toolbar-cando b{font-size:13px;color:var(--alc-text)}
.toolbar-cando span{font-size:12px;color:var(--alc-text-dim)}
@media(max-width:1600px){.nav-algorithm{display:none}}
@media(max-width:1280px){
  .operations-nav{flex-wrap:wrap;row-gap:2px}
  .nav-subs{order:9;flex:1 0 100%;overflow:visible;padding-bottom:2px}
  .nav-sub-hint{display:none}
}
@media(max-width:980px){.operations-nav{flex-wrap:wrap;row-gap:4px}.nav-fill{margin-left:0;width:100%;order:3}}

.traffic-workbench{display:flex;flex-direction:column;height:100%;overflow:hidden;padding:0;gap:0}
.wb-top{flex:0 0 auto;display:flex;align-items:center;gap:14px;padding:8px 16px;min-height:46px;
  border-bottom:1px solid #1e3648;background:linear-gradient(180deg,#0f2233 0%,#0b1a27 100%)}
.wb-brand{display:flex;align-items:baseline;gap:9px;min-width:0}
.wb-brand b{font-size:16px;letter-spacing:1.2px;color:#e2f3fd;font-weight:600;white-space:nowrap}
.wb-brand em{font-style:normal;font-size:11.5px;color:#6f92a8;letter-spacing:.4px;white-space:nowrap}
.wb-scope{font-size:12px;color:#9fc4dd;border:1px solid #26445a;border-radius:4px;padding:2px 8px;white-space:nowrap}
.wb-spacer{flex:1 1 auto}
.traffic-workbench .wb-rail-toggle{font-size:12px!important;padding:5px 10px!important}
.wb-shell{flex:1 1 auto;display:flex;min-height:0;min-width:0}
.traffic-workbench .operations-nav{flex:0 0 176px;width:176px;display:flex;flex-direction:column;
  align-items:stretch;gap:3px;padding:10px 8px 8px;margin:0!important;background:#0a1825;
  border:0;border-right:1px solid #1e3648;border-radius:0;box-shadow:none;
  overflow-y:auto;overflow-x:hidden;flex-wrap:nowrap}
.traffic-workbench .operations-nav .nav-groups{display:flex;flex-direction:column;gap:2px}
.traffic-workbench .operations-nav .nav-group{justify-content:flex-start!important;text-align:left!important;
  padding:9px 10px!important;border-radius:6px!important;gap:8px;width:100%;font-size:13px!important}
.traffic-workbench .operations-nav .nav-group em{font-style:normal;font-size:11px;color:#5f8298;min-width:12px}
.traffic-workbench .operations-nav .nav-group.active em{color:#8fe4ff}
.traffic-workbench .operations-nav .nav-subs{display:flex;flex-direction:column;gap:2px;
  margin:1px 0 7px 12px;padding-left:8px;border-left:2px solid #1d384a}
.traffic-workbench .operations-nav .nav-subs button{justify-content:flex-start!important;text-align:left!important;
  padding:6px 9px!important;font-size:12.5px!important;width:100%}
.traffic-workbench .operations-nav .nav-tab-sep{display:none}
.traffic-workbench .operations-nav .nav-fill{margin:auto 0 0;display:flex;flex-direction:column;
  align-items:stretch;gap:6px;padding:9px 0 0;border-top:1px solid #1d384a;width:auto;order:0}
.traffic-workbench .operations-nav .nav-region{margin:0}
.traffic-workbench .operations-nav .nav-region select{width:100%;max-width:none;min-width:0}
.traffic-workbench .operations-nav .nav-fill .nav-toggle{width:100%;justify-content:flex-start!important;
  text-align:left!important;font-size:12px!important}
.wb-body{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;
  overflow-y:auto;overflow-x:hidden;padding:14px 18px 18px}
.traffic-workbench .operations-nav.rail-collapsed{flex-basis:56px;width:56px;padding:10px 6px 8px}
.traffic-workbench .operations-nav.rail-collapsed .nav-group{justify-content:center!important;
  font-size:0!important;padding:10px 0!important}
.traffic-workbench .operations-nav.rail-collapsed .nav-group em{font-size:13px}
.traffic-workbench .operations-nav.rail-collapsed .nav-subs{display:none}
.traffic-workbench .operations-nav.rail-collapsed .nav-region,
.traffic-workbench .operations-nav.rail-collapsed .nav-toggle{display:none}
.traffic-workbench.home-mode{padding:0}
.traffic-workbench.home-mode .wb-body{padding:10px 12px 12px}
.traffic-workbench.page-mode{overflow:hidden}
@media(max-width:1180px){.wb-brand em{display:none}}
@media(max-width:1000px){
  .traffic-workbench .operations-nav{flex-basis:56px;width:56px;padding:10px 6px 8px}
  .traffic-workbench .operations-nav .nav-group{justify-content:center!important;font-size:0!important}
  .traffic-workbench .operations-nav .nav-group em{font-size:13px}
  .traffic-workbench .operations-nav .nav-subs{display:none}
  .traffic-workbench .operations-nav .nav-region,
  .traffic-workbench .operations-nav .nav-toggle{display:none}
}

.traffic-workbench .operations-nav{
  background:linear-gradient(180deg,#0b1b2a 0%,#081420 100%);
  padding:12px 10px 10px;gap:4px;
}
.traffic-workbench .operations-nav::-webkit-scrollbar{width:6px}
.traffic-workbench .operations-nav::-webkit-scrollbar-thumb{background:rgba(255,255,255,.14);border-radius:3px}
.traffic-workbench .operations-nav .nav-groups{gap:4px}

.traffic-workbench .operations-nav .nav-group{
  position:relative;display:flex;align-items:center;gap:9px;width:100%;
  padding:9px 12px!important;border-radius:9px!important;
  background:rgba(255,255,255,.035)!important;border:1px solid rgba(255,255,255,.05)!important;
  color:#9db6c7!important;font-size:13px!important;letter-spacing:.2px;
  transition:background .16s ease,border-color .16s ease,color .16s ease;
}
.traffic-workbench .operations-nav .nav-group:hover{
  background:rgba(89,223,252,.10);border-color:rgba(89,223,252,.26)!important;color:#d8eefb!important}
.traffic-workbench .operations-nav .nav-group.active{
  background:linear-gradient(90deg,rgba(32,104,136,.58),rgba(32,104,136,.16))!important;
  border-color:rgba(89,223,252,.42)!important;color:#eaf8ff!important;
  box-shadow:0 2px 12px -8px rgba(89,223,252,.9)}
.traffic-workbench .operations-nav .nav-group.active::before{
  content:'';position:absolute;left:0;top:9px;bottom:9px;width:3px;border-radius:0 2px 2px 0;
  background:#59dffc;box-shadow:0 0 8px rgba(89,223,252,.8)}
.traffic-workbench .operations-nav .nav-group em{
  font-style:normal;font-size:10.5px;min-width:15px;height:15px;line-height:15px;text-align:center;
  border-radius:4px;background:rgba(255,255,255,.07);color:#7f9db0}
.traffic-workbench .operations-nav .nav-group.active em{background:rgba(89,223,252,.22);color:#d6f6ff}

.traffic-workbench .operations-nav .nav-subs{
  margin:2px 0 10px 20px;padding-left:13px;border-left:1px solid rgba(255,255,255,.10);
  display:flex;flex-direction:column;gap:1px}
.traffic-workbench .operations-nav .nav-subs button{
  position:relative;width:100%;text-align:left!important;justify-content:flex-start!important;
  padding:7px 10px!important;border:1px solid transparent!important;border-radius:7px!important;
  background:transparent!important;color:#8ea9bb!important;font-size:12.5px!important;
  transition:background .15s ease,color .15s ease}
.traffic-workbench .operations-nav .nav-subs button::before{
  content:'';position:absolute;left:-16px;top:50%;width:5px;height:5px;margin-top:-2.5px;
  border-radius:50%;background:rgba(255,255,255,.22);transition:background .15s ease,box-shadow .15s ease}
.traffic-workbench .operations-nav .nav-subs button:hover{background:rgba(255,255,255,.055)!important;color:#d6ecf8!important}
.traffic-workbench .operations-nav .nav-subs button:hover::before{background:rgba(89,223,252,.6)}
.traffic-workbench .operations-nav .nav-subs button.active{
  background:rgba(89,223,252,.13)!important;border-color:rgba(89,223,252,.26)!important;color:#eaf8ff!important}
.traffic-workbench .operations-nav .nav-subs button.active::before{
  background:#59dffc;box-shadow:0 0 7px rgba(89,223,252,.85)}
/* 入口上下文：不点亮，只让那个圆点比常态亮一点（连左侧竖条也不给，
   否则看起来仍像"第二盏灯"）。 */
.traffic-workbench .operations-nav .nav-subs button.entry-context{
  background:transparent!important;border-color:transparent!important;box-shadow:none!important;
  color:#93aebf!important}
.traffic-workbench .operations-nav .nav-subs button.entry-context::before{
  background:rgba(89,223,252,.55)}

.traffic-workbench .operations-nav .nav-fill{
  border-top:1px solid rgba(255,255,255,.08);padding-top:10px;gap:5px}
.traffic-workbench .operations-nav .nav-fill .nav-toggle{
  width:100%;justify-content:center!important;text-align:center!important;
  background:rgba(255,255,255,.045)!important;border:1px solid rgba(255,255,255,.07)!important;
  border-radius:7px!important;padding:7px 10px!important;color:#a9c3d3!important;font-size:12px!important;
  transition:background .15s ease,color .15s ease,border-color .15s ease}
.traffic-workbench .operations-nav .nav-fill .nav-toggle:hover{
  background:rgba(89,223,252,.12)!important;border-color:rgba(89,223,252,.30)!important;color:#e6f7ff!important}
.traffic-workbench .operations-nav .nav-fill .nav-toggle.on{
  background:rgba(89,223,252,.20)!important;border-color:rgba(89,223,252,.45)!important;color:#eaf8ff!important}
.traffic-workbench .operations-nav .nav-region select{
  background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.07);border-radius:7px;
  padding:6px 8px;font-size:12px;color:#bcd3e2}

.traffic-workbench .operations-nav.rail-collapsed .nav-group{
  justify-content:center!important;padding:10px 0!important;border-radius:8px!important}
.traffic-workbench .operations-nav.rail-collapsed .nav-group em{
  min-width:0;width:100%;background:transparent;font-size:13px;color:inherit}
.traffic-workbench .operations-nav.rail-collapsed .nav-group.active::before{top:6px;bottom:6px}

@media (min-width:1900px){
  .traffic-workbench .wb-body{padding:16px 28px 22px}
  .operations-heading p,.briefing-note,.traffic-secondary-head p{max-width:1180px}
}
@media (max-width:1360px){
  .traffic-workbench .operations-nav{flex-basis:56px;width:56px;padding:10px 6px 8px}
  .traffic-workbench .operations-nav .nav-group{justify-content:center!important;font-size:0!important;padding:10px 0!important}
  .traffic-workbench .operations-nav .nav-group em{font-size:13px;min-width:0;width:100%;background:transparent}
  .traffic-workbench .operations-nav .nav-subs{display:none}
  .traffic-workbench .operations-nav .nav-region,
  .traffic-workbench .operations-nav .nav-toggle{display:none}
  .traffic-workbench .wb-body{padding:12px 14px 16px}
}
@media (max-width:1100px){
  .traffic-workbench .wb-body{padding:10px 12px 14px}
  .operations-heading{gap:10px}
}

.traffic-workbench .wb-body>.operations-console{flex:0 0 auto}
.operations-console{display:flow-root}
.traffic-ribbon-count{display:inline-flex;align-items:center;padding:2px 8px;margin-right:8px;
  border-radius:4px;font-size:11.5px;color:#9fc4dd;background:rgba(76,141,255,.12);
  border:1px solid rgba(76,141,255,.28);white-space:nowrap}
/* 1366 级笔记本断点：导航与品牌后缀原本 11–11.5px，抬到 12px 地板。 */
@media (max-width:1440px){
  .operations-nav .nav-group em,.wb-brand em,.traffic-ribbon-count{font-size:12px}
  .traffic-workbench .operations-nav .nav-group em{font-size:12px;min-width:17px;height:17px;line-height:17px}
}
</style>
