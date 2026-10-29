<script setup>
import {computed,defineAsyncComponent,ref,watch,onUnmounted,onBeforeUnmount,nextTick} from 'vue'
import {postAction,requestJson,operatorRole} from '../api.js'
import RegionalObservations from './RegionalObservations.vue'
import WeatherSourceSwitch from './traffic/WeatherSourceSwitch.vue'
import WeatherSupplements from './traffic/WeatherSupplements.vue'
import Track1Panel from './traffic/Track1Panel.vue'
import MlEffectBoard from './traffic/MlEffectBoard.vue'
import CorridorPanel from './traffic/CorridorPanel.vue'
import {isCaseMode} from '../traffic/caseMode.js'
const DeductionPanel = defineAsyncComponent(() => import('./traffic/DeductionPanel.vue'))
const CounterfactualPanel = defineAsyncComponent(() => import('./traffic/CounterfactualPanel.vue'))
const DivergencePanel = defineAsyncComponent(() => import('./traffic/DivergencePanel.vue'))
import {metarLines,metarOrder,sigmetRows,clearanceReport,operationalTime,detourMinutesShort,routeBasisNames,isWeatherDetour,radarRuleBlock,routeBasisCensus,mechanismChain,mechanismPickerRows,groupAlerts,
  caliberBlocks,glossaryGroups,airspaceIntel,timelineIntel,replayBuckets,replaySlice,receiptText,densityPolicy,SOURCE_BADGES,
  DISPOSAL_FLOW,disposalStateLabel,disposalNextActions,disposalAction,
  observationRows,sortObservationRows,observationCsv,OBSERVATION_COLUMNS,observationImpact,
  batchClearanceRows,severityBands,radarTierStats,weatherImpact,weatherEvolution,replayWeatherFrame,
  verdictMark,aiMark,AI_MARKS,aiCoverage,EVENT_TONE_LABELS,eventTone,CALIBER_LEDGER,
  closureShortNames} from '../traffic/runtime.js'
const detourShort=detourMinutesShort
const props=defineProps({
  maxMinute:{type:Number,default:480},view:String,session:Object,network:Object,flights:Array,weather:Object,selected:Object,minute:Number,cityName:String,operations:Array,weatherMode:{type:String,default:'measured'},weatherModeStatus:{type:Object,default:null},density:{type:String,default:'duty'},focus:{type:Object,default:null},
  alertFlights:{type:Array,default:()=>[]},
  eventFocus:{type:Object,default:null},
  corridorFocus:{type:String,default:''},
  corridorPair:{type:Object,default:null},
  aiReviewed:{type:Object,default:()=>({})}})
const emit=defineEmits(['select-flight','weather-mode-change','locate-event','ai-reviewed','open-section','seek'])
const caseMode=isCaseMode()
const stationRows=computed(()=>{
  const rows=props.weather?.stationVisibility||[]
  return rows.map(r=>({
    station:r.station,
    vis:r.visM, cloud:r.cloudBaseM, gust:r.gustMs,
    observedAt:r.observedAt||'',
    level:r.visLevel||'',
    levelLabel:r.visLevel==='BAN'?'停飞档':(r.visLevel==='CAUTION'?'需谨慎':'可飞'),
    tone:r.visLevel==='BAN'?'danger':(r.visLevel==='CAUTION'?'watch':'ok'),
  }))
})
const casePanels=ref(null)
const activeCaseId=(()=>{try{return new URLSearchParams(window.location.search).get('case')||''}catch(_){return ''}})()
watch(()=>[caseMode,activeCaseId,props.session?.status],async()=>{
  if(!caseMode||!activeCaseId||props.session?.status!=='READY'){casePanels.value=null;return}
  try{
    const query=`seed=${props.session.seed||42}&scenario=${props.session.scenario||'live'}&case=${encodeURIComponent(activeCaseId)}&minute=${Math.round(props.minute||0)}`
    const [cf,ov]=await Promise.all([
      requestJson(`/api/traffic/v2/counterfactual?${query}&policy=balanced`,{timeoutMs:45000}),
      requestJson(`/api/traffic/v2/overview?${query}`,{timeoutMs:30000}),
    ])
    const panels=cf?.casePanels
    const high=(ov?.kpis||[]).find(k=>k.key==='high')?.value
    casePanels.value=panels?{...panels,corridorsAtBan:typeof high==='number'?high:null}:null
  }catch(_){casePanels.value=null}
},{immediate:true})
const question=ref('当前运行有哪些风险，为什么需要绕行或暂停？'),answer=ref(null),asking=ref(false),error=ref('')
const lastGlobal=ref(false)
let token=0
const alertGroups=computed(()=>groupAlerts(props.flights))
const alertCauseFilter=ref('weather')
watch(()=>props.focus,value=>{
  if(!value||value.section!=='alerts')return
  alertCauseFilter.value=value.cause==='weather'?'weather':(value.cause==='nonWeather'?'nonWeather':'')
},{immediate:true})
const shownAlerts=computed(()=>{
  if(alertCauseFilter.value==='weather')return alertGroups.value.rows.filter(row=>row.weather)
  if(alertCauseFilter.value==='nonWeather')return alertGroups.value.rows.filter(row=>!row.weather)
  return alertGroups.value.rows
})
const causeVerdict=computed(()=>{
  const g=alertGroups.value
  if(!g.total)return '本轮无调度事件'
  if(!g.closedFlights)return `${g.total} 个事件全部是时隙重排或改航，本轮无停止放行班次`
  if(!g.weatherClosedFlights)
    return `停止放行 ${g.closedFlights} 班，其中气象成因 0 班 —— 不要把这一屏读成天气造成的`
  return `停止放行 ${g.closedFlights} 班，其中气象成因 ${g.weatherClosedFlights} 班（${Math.round(g.weatherClosedFlights/g.closedFlights*100)}%）`
})
const DISPOSAL_LABELS=Object.fromEntries(DISPOSAL_FLOW.map(item=>[item.key,item.label]))
const disposalStates=computed(()=>{
  const map=new Map()
  for(const row of journal.value){
    if(row.kind!=='DISPOSAL'||!row.eventKey)continue
    map.set(row.eventKey,{state:row.action,label:disposalStateLabel(row.action),
      at:row.at,actor:row.actor,action:row.disposalAction||null,
      actionLabel:row.disposalActionLabel||null})
  }
  return map
})
const disposalOf=key=>disposalStates.value.get(key)||{state:'PENDING',label:'待确认',at:null,actor:null}
const disposalBusy=ref(''),disposalError=ref(''),disposalRefusal=ref(null)
const disposalActionsFor=row=>disposalNextActions(disposalOf(row.key).state)
async function setDisposal(row,state){
  const sessionId=props.session?.sessionId
  if(!sessionId||disposalBusy.value)return
  disposalBusy.value=row.key;disposalError.value=''
  try{
    await postAction('/api/traffic/operations/disposal',
      {sessionId,eventKey:row.key,state,actor:operatorRole()})
    await loadJournal()
  }catch(e){disposalError.value=e.message}
  finally{disposalBusy.value=''}
}
async function dispose(row,action){
  const session=props.session
  if(!session?.sessionId||disposalBusy.value)return
  disposalBusy.value=row.key;disposalError.value='';disposalRefusal.value=null
  try{
    const result=await postAction('/api/traffic/operations/dispose',{
      seed:session.seed,scenario:session.scenario,eventKey:row.key,action,
      flightId:action==='SUSPEND'?(row.sample?.id||null):null,
      minute:props.minute,planRevision:session.planRevision})
    if(!result||result.applied!==true){
      disposalRefusal.value={key:row.key,label:result?.label||action,
        text:result?.reason||result?.detail||'本系统不支持对该事件执行该动作。'}
    }
    await loadJournal()
  }catch(e){disposalError.value=e.message}
  finally{disposalBusy.value=''}
}
function locateEvent(row){emit('locate-event',row.key,row.sample||null)}
const alertCards=ref([])
watch(()=>props.eventFocus,async value=>{
  if(!value||props.view!=='alerts')return
  await nextTick()
  const node=alertCards.value.find(item=>item&&item.dataset&&item.dataset.alertKey===value.key)
  if(node&&typeof node.scrollIntoView==='function')node.scrollIntoView({block:'center',behavior:'smooth'})
})
const eventFocused=key=>!!props.eventFocus&&props.eventFocus.key===key
const wind=computed(()=>{
  const values=(props.weather?.winds||[]).map(w=>Math.hypot(w.u,w.v)).sort((a,b)=>a-b)
  return values.length?values[Math.floor(values.length/2)].toFixed(1):'—'
})
const metarRows=computed(()=>metarOrder(props.weather?.observations).map(o=>({id:o.cityId||o.cityName||o.station,lines:metarLines(o)})))
const obsRows=computed(()=>observationRows(props.weather))
const obsSortKey=ref('')
const obsDir=ref('asc')
const obsSorted=computed(()=>obsSortKey.value
  ?sortObservationRows(obsRows.value,obsSortKey.value,obsDir.value)
  :obsRows.value)
function sortObs(key){
  if(obsSortKey.value===key){obsDir.value=obsDir.value==='asc'?'desc':'asc';return}
  obsSortKey.value=key
  obsDir.value=(OBSERVATION_COLUMNS.find(column=>column.key===key)?.numeric)?'desc':'asc'
}
const obsSortMark=key=>obsSortKey.value!==key?'':(obsDir.value==='asc'?'▲':'▼')
function exportObservations(){
  if(!obsRows.value.length)return
  const blob=new Blob(['\ufeff'+observationCsv(obsSorted.value)],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob),link=document.createElement('a')
  link.href=url;link.download=`逐站观测-${(props.session?.sessionId||'session').slice(0,12)}.csv`
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url)
}
const impacts=computed(()=>observationImpact(props.weather,props.flights,props.network))
const batchClearance=computed(()=>batchClearanceRows(props.flights,{limit:24}))
const situation=computed(()=>radarTierStats(props.weather,props.session))
const situationBands=computed(()=>severityBands(props.weather,props.network))
const weatherImpacts=computed(()=>weatherImpact(props.session,props.flights,props.network))
const evolution=computed(()=>weatherEvolution(props.session,props.flights))
const selectedMark=computed(()=>verdictMark(props.selected?.id,props.aiReviewed))
const markOf=flight=>verdictMark(flight?.id,props.aiReviewed)
const coverage=computed(()=>aiCoverage(props.flights,props.aiReviewed))
const MARK_ROWS=Object.freeze(Object.values(AI_MARKS))
const replayWeather=computed(()=>replayWeatherFrame(props.weather,replayMinute.value))
const sigmet=computed(()=>sigmetRows(props.weather))
const clearance=computed(()=>clearanceReport(props.selected?.atcClearance))
const detourRows=computed(()=>(props.flights||[])
  .filter(f=>(Number(f?.detourMinutes)||0)>0.01)
  .sort((a,b)=>(Number(b.detourMinutes)||0)-(Number(a.detourMinutes)||0))
  .map(f=>({id:f.id,name:f.name||f.id,detour:Math.round(Number(f.detourMinutes)||0),
    basis:f.atcClearance?.weatherBasis||'航路受气象影响推移',
    route:`${f.fromPad||'—'} → ${f.toPad||'—'}`,
    distance:Number.isFinite(Number(f.distanceKm))?Number(f.distanceKm):null})))
const PICKER_LIMIT=12
const pickerQuery=ref('')
const pickerRows=computed(()=>{
  const query=pickerQuery.value.trim().toLowerCase()
  const scored=(props.flights||[]).map(f=>({
    f,
    rank:(Number(f?.detourMinutes)||0)>0.01?2:(f?.status==='CLOSED'?1:0),
    detour:Number(f?.detourMinutes)||0,
  }))
  const matched=query
    ?scored.filter(({f})=>[f.id,f.name,f.fromCity,f.toCity,f.fromPad,f.toPad]
        .filter(Boolean).some(value=>String(value).toLowerCase().includes(query)))
    :scored
  matched.sort((a,b)=>b.rank-a.rank||b.detour-a.detour
    ||(a.f.departureMinute??1e9)-(b.f.departureMinute??1e9)
    ||String(a.f.id).localeCompare(String(b.f.id)))
  return matched.slice(0,PICKER_LIMIT).map(item=>item.f)
})
const pickerTotal=computed(()=>Number(props.session?.flightStats?.total)||(props.flights||[]).length)

async function ask(){
  if(asking.value||!props.session||!question.value.trim())return
  const current=++token;asking.value=true;error.value='';answer.value=null
  const askedFor=props.selected?.id||''
  lastGlobal.value=!askedFor
  try{
    const result=await postAction('/api/traffic/explain',{seed:props.session.seed,scenario:props.session.scenario,flightId:props.selected?.id||null,minute:props.minute,question:question.value},28000)
    if(current===token){
      answer.value=result
      if(askedFor&&result?.ai?.outcome){
        emit('ai-reviewed',{flightId:askedFor,outcome:result.ai.outcome})
      }
    }
  }
  catch(e){if(current===token)error.value=e.message}
  finally{if(current===token)asking.value=false}
}
watch(()=>[props.session?.sessionId,props.selected?.id],()=>{++token;answer.value=null;asking.value=false})
onUnmounted(()=>++token)

const rule=computed(()=>radarRuleBlock(props.session))
const ruleRows=computed(()=>{
  const r=rule.value
  if(!r)return []
  const dbz=value=>value===null?'未发布':`${value} dBZ`
  const metres=value=>value===null?'未发布':`${value} m`
  return [
    {key:'bands',label:'回波分级',value:`无回波 < ${dbz(r.bandFloorDbz)} · 对流 ${dbz(r.convectiveDbz)} · 强对流 ${dbz(r.strongDbz)}`,
     note:'层状降水（下界到对流阈值之间）只展示，不构成限制，也不进入避让几何。'},
    {key:'core',label:'内核 · 禁止进入',value:`外场向内收缩 ${metres(r.coreInsetM)}`,
     note:'内核由外场收缩得到，而不是强对流原轮廓：原轮廓在真实回波上是一圈碎点，画出来看不见。'},
    {key:'field',label:'外场 · 须绕飞',value:`擦入深度上限 ${metres(r.penetrationM)}`,
     note:'擦入深度与水平间隔同源——本项目不为强回波另立第二套标准。两级两规则：内核不可触碰，外场可有界擦边。'},
    {key:'layers',label:'高度层',value:props.session?.stats?.noAltitudeStacking===true?'只使用已声明高度层':'本计划未声明',
     note:'冲突用已声明高度层、时隙或地面等待解决，不叠加高度。'},
  ]
})
const census=computed(()=>routeBasisCensus(props.flights))
const basisFilter=ref(''),chainQuery=ref(''),chainId=ref('')
const picker=computed(()=>mechanismPickerRows(props.flights,{basis:basisFilter.value,query:chainQuery.value}))
const chainFlight=computed(()=>(props.flights||[]).find(f=>f.id===chainId.value)||null)
const chain=computed(()=>mechanismChain(chainFlight.value,props.session))
watch(()=>picker.value.rows.map(f=>f.id),ids=>{if(!ids.includes(chainId.value))chainId.value=ids[0]||''},{immediate:true})

const JOURNAL_KINDS=[
  {key:'',label:'全部'},
  {key:'MANUAL',label:'人工干预'},
  {key:'SYSTEM',label:'系统决策'},
  {key:'SOURCE',label:'数据源变更'},
  {key:'EXPORT',label:'导出'},
]
const journal=ref([]),journalLoading=ref(false),journalError=ref(''),journalKind=ref(''),journalQuery=ref('')
async function loadJournal(){
  const id=props.session?.sessionId
  if(!id){journal.value=[];return}
  journalLoading.value=true;journalError.value=''
  try{journal.value=await requestJson('/api/traffic/journal?sessionId='+id)}
  catch(e){journalError.value=e.message;journal.value=[]}
  finally{journalLoading.value=false}
}
watch(()=>[props.view,props.session?.sessionId],()=>{
  if(props.view==='history'||props.view==='alerts')loadJournal()
},{immediate:true})
const journalRows=computed(()=>{
  const query=journalQuery.value.trim().toLowerCase()
  return journal.value.filter(row=>{
    if(journalKind.value&&row.kind!==journalKind.value)return false
    if(!query)return true
    return [row.kindLabel,row.actionLabel,row.name,row.flightId,row.detail]
      .filter(Boolean).some(value=>String(value).toLowerCase().includes(query))
  })
})
const journalCounts=computed(()=>{
  const counts={MANUAL:0,SYSTEM:0,SOURCE:0,EXPORT:0}
  for(const row of journal.value)counts[row.kind]=(counts[row.kind]||0)+1
  return counts
})
const journalTime=row=>row.at?new Date(row.at).toLocaleString('zh-CN',{hour12:false}):'—'
const journalMinute=row=>Number.isFinite(Number(row.minute))?Number(row.minute).toFixed(1):'—'
const journalTarget=row=>row.name?(row.name+(row.flightId?' · '+row.flightId:'')):(row.flightId||'—')

function journalCsv(rows){
  const head=['时刻','类型','推演分钟','对象','内容','明细']
  const cell=value=>`"${String(value??'').replace(/"/g,'""')}"`
  return [head,...rows.map(row=>[journalTime(row),row.kindLabel,row.minute??'',
    journalTarget(row),row.actionLabel,row.detail])]
    .map(line=>line.map(cell).join(',')).join('\r\n')
}
const AI_OUTCOMES={
  ACCEPTED:{key:'accepted',label:'外部模型选取已采用'},
  VETOED:{key:'vetoed',label:'外部模型被规则否决'},
  UNAVAILABLE:{key:'unavailable',label:'外部模型不可用（已降级）'},
  NOT_CONFIGURED:{key:'off',label:'未配置外部模型（仅规则证据）'},
}
const aiStatus=computed(()=>{
  const ai=answer.value?.ai
  if(!ai)return null
  return {...(AI_OUTCOMES[ai.outcome]||{key:'off',label:ai.outcome}),...ai}
})

async function exportJournal(){
  const rows=[...journalRows.value].reverse()
  if(!rows.length)return
  const blob=new Blob(['\ufeff'+journalCsv(rows)],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob),link=document.createElement('a')
  link.href=url;link.download=`运行日志-${(props.session?.sessionId||'session').slice(0,12)}.csv`
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url)
  try{
    await postAction('/api/traffic/operations/note',{sessionId:props.session.sessionId,format:'csv',rows:rows.length})
    await loadJournal()
  }catch(_){
  }
}

const policy=computed(()=>densityPolicy(props.density))

const caliber=computed(()=>caliberBlocks(props.session,props.weather,props.network))
const sourceRows=computed(()=>caliber.value.flatMap(block=>block.rows.map(row=>({...row,block:block.title}))))
const glossaryQuery=ref('')
const glossary=computed(()=>{
  const query=glossaryQuery.value.trim().toLowerCase()
  const groups=glossaryGroups()
  if(!query)return groups
  return groups.map(group=>({...group,
    terms:group.terms.filter(entry=>[entry.term,entry.plain,entry.full]
      .some(value=>String(value).toLowerCase().includes(query)))}))
    .filter(group=>group.terms.length)
})
const glossaryTotal=glossaryGroups().reduce((sum,group)=>sum+group.terms.length,0)

const timeline=computed(()=>timelineIntel(props.session,props.weather,journal.value))
const airspace=computed(()=>airspaceIntel(props.session,props.flights,props.weather,props.network))
const intelTone=row=>'k-'+(row.tone||'normal')

const closedReasons=computed(()=>{
  const rows=(props.alertFlights||[]).filter(f=>f.status==='CLOSED')
  const tally={}
  for(const row of rows){const key=row.reason||'UNKNOWN';tally[key]=(tally[key]||0)+1}
  return Object.entries(tally).sort((a,b)=>b[1]-a[1])
    .map(([key,count])=>({key,count,label:closureShortNames[key]||key}))
})

const replay=computed(()=>replayBuckets(journal.value))
const replayMinute=computed(()=>Number(props.minute)||0)
const replayMax=computed(()=>Number(props.maxMinute)||480)
const replayView=computed(()=>replaySlice(journal.value,replayMinute.value))
function jumpReplay(minute){emit('seek',Math.max(0,Math.min(replayMax.value,minute)))}
const replayPlaying=ref(false)
let replayTimer=null
function stopReplay(){replayPlaying.value=false;if(replayTimer)clearInterval(replayTimer);replayTimer=null}
function replayStep(){
  const next=Math.min(replayMax.value,replayMinute.value+2)
  emit('seek',next)
  if(next>=replayMax.value)stopReplay()
}
function toggleReplay(){
  if(replayPlaying.value){stopReplay();return}
  if(replayMinute.value>=replayMax.value)emit('seek',0)
  replayPlaying.value=true
  replayTimer=setInterval(replayStep,180)
}
onBeforeUnmount(stopReplay)
const replaySpan=computed(()=>{
  const minutes=journal.value.map(row=>Number(row.minute)).filter(Number.isFinite)
  if(!minutes.length)return null
  return {count:minutes.length,from:Math.min(...minutes),to:Math.max(...minutes)}
})

const receiptCopied=ref('')
function disposalRow(key){
  const rows=journal.value.filter(row=>row.kind==='DISPOSAL'&&row.eventKey===key)
  return rows.length?rows[rows.length-1]:null
}
function receiptOf(row){return receiptText(disposalRow(row.key),{sessionId:props.session?.sessionId||''})}
async function copyReceipt(row){
  const text=receiptOf(row)
  if(!text)return
  try{
    await navigator.clipboard.writeText(text)
    receiptCopied.value=row.key
  }catch(_){
    receiptCopied.value=''
  }
  finally{setTimeout(()=>{if(receiptCopied.value===row.key)receiptCopied.value=''},2400)}
}
</script>
<template>
<section class="operations-console" :data-view="view">
  <p class="drill-banner" v-if="focus&&focus.hint" data-drill-banner>
    <b>从首页指标下钻</b>{{focus.hint}}。本页只做导航与呈现，数值仍由本页唯一的产出点算一次。
  </p>
  <template v-if="view==='alerts'">
      <section class="case-panels" v-if="casePanels" data-case-panels>
        <header>
          <b>本案例判据</b>
          <span>{{ casePanels.caseLabel || '历史回放' }}</span>
          <small>数据来自「推演 · 第 6 步 对照」的同一次计算</small>
        </header>
        <div class="case-panels-grid">
          <div><small>观测已达不可飞</small><b>{{ casePanels.corridorsAtBan == null ? '—' : casePanels.corridorsAtBan + ' 条走廊' }}</b></div>
          <div><small>涉及班次</small><b>{{ casePanels.flightsHandled }} 班</b></div>
          <div><small>按观测档应当</small><b>改航 {{ casePanels.rerouted }} · 延误 {{ casePanels.delayed }}</b></div>
          <div><small>暴露变化</small><b>{{ casePanels.exposureA }} → {{ casePanels.exposureB }} 架次</b></div>
        </div>
        <p class="case-panels-foot">
          这是判据层的结论：观测已越过禁飞阈值，按观测档应当处置 {{ casePanels.flightsHandled }} 班。
          <b>下方是实时推演的事件，与这段判据不同源</b> —— 本案例只回放观测，不重跑调度。
        </p>
      </section>

  <div class="operations-heading">
    <h2>预警中心 · 事件处置台 <small>{{cityName}} · {{alertGroups.total}} 个合并事件</small></h2>
    <p>同一走廊与原因合并为一个事件。处置次序恒为：先改时隙（延迟起飞）、再改航绕飞，两者都不可行才停止放行。<b>但哪一类成因占多数，由下面对比条给出 —— 不由导语暗示。</b></p>
  </div>
  <div class="cause-bar" v-if="alertGroups.total">
    <div class="cause-head">
      <b>{{alertGroups.total}} 个事件</b>
      <span>涉及 {{alertGroups.totalFlights}} 班 · 停止放行 {{alertGroups.closedFlights}} 班</span>
      <span class="cause-verdict">{{causeVerdict}}</span>
    </div>
    <div class="cause-split">
      <span class="weather" :style="{flex:alertGroups.weatherEvents||0}"></span>
      <span class="nonweather" :style="{flex:alertGroups.nonWeatherEvents||0}"></span>
    </div>
    <div class="cause-legend">
      <button class="cause-chip weather" :class="{on:alertCauseFilter==='weather'}"
              @click="alertCauseFilter=alertCauseFilter==='weather'?'':'weather'">
        气象成因 <em>{{alertGroups.weatherEvents}}</em>
      </button>
      <button class="cause-chip nonweather" :class="{on:alertCauseFilter==='nonWeather'}"
              @click="alertCauseFilter=alertCauseFilter==='nonWeather'?'':'nonWeather'">
        非气象成因 <em>{{alertGroups.nonWeatherEvents}}</em>
      </button>
      <span class="cause-note">停止放行中气象成因 {{alertGroups.weatherClosedFlights}} 班 · 非气象成因 {{alertGroups.closedFlights-alertGroups.weatherClosedFlights}} 班</span>
    </div>
  </div>
  <p class="operations-error" v-if="disposalError">{{disposalError}}</p>
  <p class="disposal-refusal" v-if="disposalRefusal" role="status" data-disposal-refusal>
    <b>本系统不支持对该事件执行「{{disposalRefusal.label}}」</b>{{disposalRefusal.text}}
    <button @click="disposalRefusal=null">知道了</button>
  </p>
  <div class="alert-grid">
    <article class="disposal-card" v-for="row in shownAlerts" :key="row.key"
             ref="alertCards" :data-alert-key="row.key"
             :class="{closed:row.closed,weather:row.weather,focused:eventFocused(row.key)}">
      <header>
        <span class="cause-tag" :class="row.weather?'weather':'nonweather'">{{row.weather?'气象成因':'排程冲突'}}</span>
        <span class="disposal-state" :class="disposalOf(row.key).state.toLowerCase()">{{disposalOf(row.key).label}}</span>
      </header>
      <h3>{{row.short}}</h3>
      <p class="cause-phrase">{{row.name}}</p>
      <dl class="impact">
        <dt>影响班次</dt>
        <dd>{{row.count}} 班<template v-if="row.closedCount"> · 停止放行 {{row.closedCount}}</template><template v-if="row.detoured"> · 改航 {{row.detoured}}</template><template v-if="row.delayed"> · 时隙重排 {{row.delayed}}</template></dd>
        <dt>走廊</dt>
        <dd>{{row.corridors.length?row.corridors.join(' · '):'—'}}</dd>
        <dt>地图档位</dt>
        <dd><span class="event-tone" :class="eventTone(row)" :data-event-tone="eventTone(row)">{{EVENT_TONE_LABELS[eventTone(row)]}}</span> · 与地图「运行事件」图层同一档颜色</dd>
      </dl>
      <p class="advice" :class="{plain:!row.weather}" v-if="row.advice">{{row.advice}}</p>
      <div class="disposal-actions">
        <button class="locate" @click="locateEvent(row)">在地图上定位</button>
        <button @click="emit('select-flight',row.sample)">查看航班</button>
        <button :disabled="disposalBusy===row.key||disposalOf(row.key).state!=='PENDING'"
                @click="setDisposal(row,'ACKNOWLEDGED')">确认</button>
        <button v-for="action in disposalActionsFor(row)" :key="action.key"
                class="disposal-action" :disabled="disposalBusy===row.key"
                :data-disposal-action="action.key"
                :title="action.why" @click="dispose(row,action.key)">
          {{action.label}}
        </button>
        <button class="disposal-evidence" data-disposal-evidence @click="locateEvent(row)">查看依据</button>
        <button v-if="disposalOf(row.key).state!=='PENDING'"
                class="receipt" :class="{done:receiptCopied===row.key}"
                @click="copyReceipt(row)">{{receiptCopied===row.key?'已复制回执':'复制回执'}}</button>
      </div>
      <p class="receipt-text" v-if="disposalOf(row.key).state!=='PENDING'">{{receiptOf(row)}}</p>
    </article>
    <p v-if="!shownAlerts.length" class="alerts-empty" data-alerts-empty>
      <template v-if="alertCauseFilter==='weather'&&alertGroups.closedFlights">
        <template v-if="caseMode">
          本案例只回放观测与判据，<b>不重跑调度</b>。下方 {{alertGroups.closedFlights}} 班的停止放行来自实时推演（超出规划视界），与本次回放的气象无关 ——
          要看气象进入决策后的差别，<button type="button" class="inline-link" data-go-deduce @click="emit('open-section','card')">见「推演 · 第 6 步 对照」</button>。
        </template>
        <template v-else>
          当前窗口内没有气象成因事件。停止放行的 {{alertGroups.closedFlights}} 班<b>不是天气造成的</b>，
          原因构成：
          <template v-for="(row,index) in closedReasons" :key="row.key">
            <template v-if="index"> · </template><b>{{row.label}}</b> {{row.count}} 班
          </template>
          —— 要看规则与概率各自处置了什么，<button type="button" class="inline-link" data-go-deduce @click="emit('open-section','card')">见「推演 · 第 6 步 对照」</button>。
        </template>
      </template>
      <template v-else-if="alertCauseFilter==='weather'">当前窗口内没有气象成因事件，也没有调度事件。</template>
      <template v-else-if="alertCauseFilter==='nonWeather'">当前窗口内没有排程冲突类事件。</template>
      <template v-else>当前筛选范围暂无调度事件。</template>
    </p>
  </div>
  </template>
  <template v-else-if="view==='weather'"><div class="operations-heading"><h2>气象监测 <small>{{cityName}}</small><small v-if="caseMode" class="case-scope-hint" data-case-scope>本页气象来自实时通道；回放案例的三站实测见首页横幅</small></h2><p>公开天气、合成气象和历史观测分别展示。系统派生的飞行风险区不等同于官方空域管制命令。</p><p class="operations-muted" v-if="weather?.dataType==='MODEL_ESTIMATE'" data-weather-source-split><template v-if="weatherMode==='measured'">通道是「实测气象」：<b>走廊的不可飞概率</b>由沈阳 / 长春 / 哈尔滨三站 METAR 实测推算；而本页这张<b>天气场</b>（风场点与派生风险区）来自 Open-Meteo 模式估算 —— 两者来源不同：走廊概率不看模式值，天气场也不冒充观测。</template><template v-else>通道是「虚拟气象」：<b>地图上的雷达回波与天气场走模拟通道（程序生成，不是观测）</b>；<b>走廊的不可飞概率仍按沈阳 / 长春 / 哈尔滨三站 METAR 实测推算</b>，不受本开关影响。两者来源不同 —— 回波不冒充观测，走廊概率也不看模式值。仅供演示。</template></p><WeatherSourceSwitch class="heading-switch" :mode="weatherMode" :status="weatherModeStatus" @change="emit('weather-mode-change',$event)"/></div><div class="weather-metrics"><article><small>当前数据类型</small><strong>{{weather?.dataType==='MODEL_ESTIMATE'?'公开模型估算':weather?.dataType==='SYNTHETIC_REPLAYABLE'?'合成回放':(caseMode?'历史回放 · 仅机场站观测':'数据不可用')}}</strong></article><article><small>来源 / 有效时刻</small><strong>{{weather?.provider||weather?.source||'—'}}</strong><small>{{weather?.validAt||weather?.retrievedAt||'—'}}</small></article><article><small>显示风场点</small><strong>{{weather?.winds?.length??0}}</strong></article><article><small>派生风险区域（已合并）</small><strong>{{weather?.cells?.length??0}}</strong></article></div>    <p class="operations-muted" v-if="caseMode" data-case-weather-boundary>历史回放只有机场站 METAR，<b>无雷达网格</b>；网格分档与派生风险区不可用。</p>
    <p class="operations-muted" v-if="weather?.qualityFlags?.length">数据质量：{{weather.qualityFlags.join(' · ')}}；航路覆盖：{{weather?.coverage?.routeCoverage||'模拟全域场'}}</p><div class="weather-cells"><article v-for="cell in weather?.cells||[]" :key="cell.id"><b>{{{RAIN:'降水',STORM:'合成雷暴',WIND:'强风',LOW_VISIBILITY:'低能见度'}[cell.kind]||cell.kind}}</b><span>{{cell.id}}</span><p>{{cell.source==='OPEN_METEO_DERIVED_RISK'?'按公开天气快照及项目阈值派生':'场区 / 谨慎外环 / 禁止进入核心分别计算后合并'}}<template v-if="cell.memberCount>1">；本区域由 {{cell.memberCount}} 个单体合并，成员：{{(cell.sources||[]).map(s=>s.split('::')[0]).join('、')}}</template></p></article></div>
  <section class="briefing" data-weather-situation>
    <div class="briefing-head">
      <h3>气象态势 · 分档统计</h3>
      <small>{{situation.source==='regions'?'面积取自本帧雷达区域自身发布的分档':(situation.source==='summary'?'面积取自雷达通道摘要':'本帧无可用分档')}} · 通道 {{situation.mode||'—'}}</small>
    </div>
    <p class="briefing-note">{{situation.note}}</p>
    <div class="tier-grid" v-if="situation.rows.length">
      <article v-for="row in situation.rows" :key="row.key" :class="'tier-'+row.state.toLowerCase()"
               :data-tier="row.key" :data-tier-state="row.state">
        <header><b>{{row.label}}</b><span>{{row.transferable?'可飞越':'须避让'}}</span></header>
        <strong v-if="row.state==='PRESENT'">{{row.areaKm2}} <i>km²</i></strong>
        <strong v-else-if="row.state==='EMPTY'">本帧无 <i>已判定 · 面积为 0</i></strong>
        <strong v-else-if="row.state==='INVALID'">值非法 <i>发布了该档但面积不可用</i></strong>
        <strong v-else>本帧未发布该档 <i>不是"面积 0"</i></strong>
        <p>{{row.note}}</p>
        <small v-if="row.components!==null">{{row.components}} 个单体</small>
      </article>
    </div>
    <p class="operations-muted" v-if="situation.avoidance">
      本计划的避让几何：{{situation.avoidance.mode==='virtual'
        ?'虚拟通道沿时间轴逐帧取并集，因此<b>没有</b>"某一帧的三档"可报'
        :`并集 ${situation.avoidance.unionKm2??'—'} km²（内核 ${situation.avoidance.coreKm2??'—'} · 谨慎 ${situation.avoidance.cautionKm2??'—'} · 层状 ${situation.avoidance.watchKm2??'—'}）`}}
    </p>
  </section>

  <section class="briefing" data-weather-bands>
    <template v-if="caseMode && stationRows.length">
      <div class="briefing-head" data-case-stations>
        <h3>案例机场站实测</h3>
        <small>{{stationRows.length}} 站 METAR · {{stationRows[0].observedAt}}</small>
      </div>
      <table class="case-station-table">
        <thead><tr><th>站</th><th>能见度</th><th>云底</th><th>阵风</th><th>档位</th></tr></thead>
        <tbody>
          <tr v-for="row in stationRows" :key="row.station" :data-station="row.station" :data-level="row.level">
            <td><b>{{row.station}}</b></td>
            <td class="alc-num">{{row.vis==null?'—':row.vis+' m'}}</td>
            <td class="alc-num">{{row.cloud==null?'—':row.cloud+' m'}}</td>
            <td class="alc-num">{{row.gust==null?'—':row.gust+' m/s'}}</td>
            <td><span class="station-level" :class="row.tone">{{row.levelLabel}}</span></td>
          </tr>
        </tbody>
      </table>
      <p class="briefing-note" data-case-weather-boundary-stations>
        {{stationRows.length}} 站 METAR 实测；<b>本案例无雷达网格</b>，网格分档与派生风险区不可用。
      </p>
    </template>
    <template v-else>
    <div class="briefing-head">
      <h3>分区严重度色带</h3>
      <small>{{situationBands.total}} 个地级行政区代表中心 · 高影响 {{situationBands.counts.SEVERE}} · 需谨慎 {{situationBands.counts.CAUTION}}</small>
    </div>
    <p class="briefing-note">{{situationBands.note}}按严重度降序排列：差天气在最前。</p>
    <ol class="severity-band" v-if="situationBands.rows.length">
      <li v-for="row in situationBands.rows" :key="row.key" :data-band-city="row.key"
          :data-band-level="row.level" :style="{borderLeftColor:row.color}">
        <b>{{row.label}}</b><span>{{row.levelLabel}}</span><small>{{row.reading}}</small>
      </li>
    </ol>
    <p class="operations-muted" v-else>本帧没有可用的点观测。</p>
    <p class="operations-muted" v-if="situationBands.missingLocation">
      另有 {{situationBands.missingLocation}} 条观测取不到行政区坐标，已跳过 —— 不把它们落到 (0,0)，
      一个落在几内亚湾的点比少一个点更糟：它看起来像那里有雷暴。
    </p>
    </template>
  </section>

  <section class="briefing" data-weather-impact>
    <div class="briefing-head">
      <h3>气象影响面</h3>
      <small>气象成因 {{weatherImpacts.weatherFlights}} 班 · 非气象成因 {{weatherImpacts.otherFlights}} 班</small>
    </div>
    <p class="briefing-note">{{weatherImpacts.note}}</p>
    <div class="impact-grid" v-if="weatherImpacts.rows.length">
      <article v-for="row in weatherImpacts.rows" :key="row.basis" :class="{weather:row.weather}">
        <header><b>{{row.label}}</b><span>{{row.weather?'气象成因':'非气象成因'}}</span></header>
        <strong>{{row.count}} <i>班</i></strong>
        <p>走廊 {{row.corridorCount}} 条<template v-if="row.corridors.length">：{{row.corridors.join(' · ')}}</template></p>
        <small>最大绕行 {{row.maxDetourMinutes}} 分<template v-if="row.closedCount"> · 其中 {{row.closedCount}} 班停止放行</template></small>
      </article>
    </div>
    <p class="operations-muted" v-else>{{weatherImpacts.note}}</p>
  </section>

  <section class="briefing" data-weather-evolution>
    <div class="briefing-head"><h3>时间演变</h3><small>两个轴分开 · 每桶 {{evolution.stepMinutes}} 分钟</small></div>
    <p class="briefing-note">{{evolution.note}}</p>
    <div class="tier-grid">
      <article data-evolution-axis="result">
        <header><b>运行结果轴</b><span>与推演指针无关</span></header>
        <strong>{{evolution.peak?(evolution.peak.detoured+' 班'):'0 班'}} <i>受气象影响改航最多的时段</i></strong>
        <p v-if="evolution.peak">峰值时段 {{evolution.peak.from}}—{{evolution.peak.to}} 分</p>
      </article>
      <article data-evolution-axis="geometry" :data-evolution-state="evolution.evolution.state">
        <header><b>避让几何轴</b><span>{{evolution.evolution.state==='PER_SLOT'?'逐帧采样':(evolution.evolution.state==='SINGLE_OBSERVATION'?'单次观测':'未纳入')}}</span></header>
        <strong v-if="evolution.evolution.state==='PER_SLOT'">{{evolution.evolution.slots}} <i>帧 · 步长 {{evolution.evolution.strideMinutes}} 分钟</i></strong>
        <strong v-else-if="evolution.evolution.state==='SINGLE_OBSERVATION'">1 <i>次观测 · 覆盖整个计划窗口</i></strong>
        <strong v-else>未纳入避让几何</strong>
        <p>{{evolution.evolution.note}}</p>
      </article>
    </div>
    <table class="evolution-table" v-if="evolution.buckets.length">
      <thead><tr><th>时段</th><th>起飞</th><th>受气象影响改航</th><th>关闭</th><th>其中天气成因</th><th>最大绕行</th></tr></thead>
      <tbody><tr v-for="bucket in evolution.buckets" :key="bucket.key">
        <td>T+{{bucket.from}}—{{bucket.to}}</td>
        <td>{{bucket.departures}}</td>
        <td :class="{hit:bucket.detoured}">{{bucket.detoured}}</td>
        <td>{{bucket.closed}}</td>
        <td>{{bucket.weatherClosed}}</td>
        <td>{{bucket.maxDetourMinutes}} 分</td>
      </tr></tbody>
    </table>
  </section>
  <RegionalObservations/></template>
  <template v-else-if="view==='briefing'">
  <div class="operations-heading"><h2>民航运行情报 <small>{{cityName}}</small></h2><p>班次选择、放行许可、逐站观测与危险天气合成一屏——选班次就在本页，不必绕调度台账。许可要素由该班次已写定的计划字段组装，不在此处重新计算；派生情报用于演示与核对，不作为真实放行依据。</p><WeatherSourceSwitch class="heading-switch" :mode="weatherMode" :status="weatherModeStatus" @change="emit('weather-mode-change',$event)"/></div>
  <div class="briefing-block picker">
    <div class="briefing-head"><h3>选择班次</h3><small>共 {{pickerTotal}} 班 · 按与气象情报的相关度排序，此处列最相关的 {{pickerRows.length}} 班</small></div>
    <div class="picker-bar">
      <input v-model="pickerQuery" type="search" aria-label="搜索班次" placeholder="搜索呼号 / 起降点 / 城市">
      <span class="picker-note">受气象影响改航的排在前面，其次是被关闭的班次</span>
    </div>
    <div class="picker-chips" v-if="pickerRows.length">
      <button v-for="f in pickerRows" :key="f.id" class="picker-chip"
              :class="{on:f.id===selected?.id,hit:(Number(f.detourMinutes)||0)>0.01,off:f.status==='CLOSED'}"
              @click="emit('select-flight',f)">
        <b>{{f.name||f.id}}</b>
        <em v-if="(Number(f.detourMinutes)||0)>0.01">改航 +{{detourShort(f.detourMinutes)}}</em>
        <em v-else-if="f.status==='CLOSED'">已关闭</em>
        <em v-else>{{f.fromCity}}→{{f.toCity}}</em>
      </button>
    </div>
    <p class="briefing-note" v-else>没有匹配的班次。要按城市与运行状态筛全量班次，用「调度台账」。</p>
  </div>

  <div class="clearance-card">
    <div class="briefing-head"><h3>放行许可</h3><small v-if="selected">{{selected.name||selected.id}} · 计划放行 {{operationalTime(selected.plannedReleaseAt,selected.departureMinute)}}</small><small v-else>未选中班次</small></div>
    <p class="verdict-mark" v-if="selected" :class="selectedMark.tone" data-verdict-mark>
      <b>{{selectedMark.label}}</b>{{selectedMark.note}}
    </p>
    <pre class="clearance-report" v-if="clearance.length"><code>{{clearance.join('\n')}}</code></pre>
    <p class="briefing-note" v-else>在上面那一条里点一个班次，这里就给出它的放行许可——不必再去调度台账。缺报的要素写「未指派 / 未取得」：许可报文里没有留白，一个空值会被读成可以自行决定。</p>
  </div>
  <div class="briefing-block" data-batch-clearance>
    <div class="briefing-head"><h3>批量放行许可复核</h3><small>{{batchClearance.note}}</small></div>
    <table class="observation-table">
      <thead><tr><th>呼号</th><th>航路</th><th>高度层</th><th>放行界限</th><th>CTOT</th><th>气象判据</th><th>状态</th><th>AI 标记</th></tr></thead>
      <tbody><tr v-for="row in batchClearance.rows" :key="row.id" :data-clearance-row="row.id">
        <td><button class="link" @click="emit('select-flight',row.flight)">{{row.callsign}}</button></td>
        <td>{{row.route}}</td><td>{{row.level}}</td><td>{{row.limit}}</td><td>{{row.ctot}}</td>
        <td class="journal-detail">{{row.basis}}</td><td>{{row.status}}</td>
        <td><span class="verdict-chip" :class="markOf(row.flight).tone">{{markOf(row.flight).label}}</span></td>
      </tr></tbody>
    </table>
  </div>
  <section class="briefing">
    <div class="briefing-head"><h3>报文情报（METAR / SIGMET 式）</h3><small>报文读法 · 用于演示与核对，不作为真实放行依据</small></div>
    <details class="briefing-block density-fold" :open="policy.raw" data-density="raw">
      <summary>观测报文 <span>{{metarRows.length?metarRows.length+' 站':'本站帧无逐站观测'}}</span></summary>
      <p class="briefing-note">逐站观测的报文读法。缺报的要素写 <code>//</code>——观测未报出能见度，与报出能见度 0 km 是两件事，不填补默认值。表格按严重程度排序：能见度低者在前，其次风速大者。</p>
      <div class="metar-grid" v-if="metarRows.length">
        <article v-for="row in metarRows" :key="row.id">
          <dl><template v-for="line in row.lines" :key="line.label"><dt>{{line.label}}</dt><dd>{{line.value}}</dd></template></dl>
        </article>
      </div>
      <WeatherSupplements/>
    </details>
    <div class="briefing-block" data-observation-table>
      <div class="briefing-head">
        <h4>逐站观测 · 可排序表格 <span>{{obsRows.length?obsRows.length+' 站':'本站帧无逐站观测'}}</span></h4>
        <button class="journal-export" :disabled="!obsRows.length" data-obs-export @click="exportObservations">导出 CSV</button>
      </div>
      <p class="briefing-note">点列头排序。数值列默认降序（点「阵风」要的是最大的那一站排最前），文字列默认升序。缺值永远排在最后，升序降序都一样 —— 一个没报阵风的站既不是"阵风 0"，也不该在降序时顶到最前面冒充最大值。</p>
      <div class="table-scroll" v-if="obsSorted.length">
      <table class="observation-table">
        <thead><tr>
          <th v-for="column in OBSERVATION_COLUMNS" :key="column.key" :data-obs-col="column.key">
            <button class="obs-sort" :class="{on:obsSortKey===column.key,numeric:column.numeric}" :data-obs-sort="column.key" @click="sortObs(column.key)">{{column.label}}<em>{{obsSortMark(column.key)}}</em></button>
          </th>
        </tr></thead>
        <tbody>
          <tr v-for="row in obsSorted" :key="row.id" :class="row.level.toLowerCase()" :data-obs-row="row.id">
            <td>{{row.station}}</td>
            <td class="num">{{row.temperatureC==null?'—':row.temperatureC}}</td>
            <td class="num">{{row.windSpeed==null?'—':row.windSpeed}}</td>
            <td class="num">{{row.gust==null?'—':row.gust}}</td>
            <td class="num">{{row.visibilityM==null?'—':row.visibilityM}}</td>
            <td class="num">{{row.precipitationMm==null?'—':row.precipitationMm}}</td>
            <td>{{row.phenomenon||'—'}}</td>
            <td><span class="severity-chip" :data-obs-level="row.level">{{row.levelLabel}}</span></td>
          </tr>
        </tbody>
      </table>
      </div>
      <p class="operations-muted" v-else>本帧没有逐站观测。不显示一张空表：一张没有行的表会被读成"观测都是空的"。</p>
    </div>
    <div class="briefing-block" data-observation-impact>
      <div class="briefing-head"><h4>观测影响面</h4><small>{{impacts.length}} 站达到需谨慎以上等级</small></div>
      <p class="briefing-note">只有高影响与需谨慎两级的观测进入这里；正常与未定级的观测不列出——把正常站也列上，需要盯的那几站就被淹掉了。</p>
      <div class="impact-grid" v-if="impacts.length">
        <article v-for="row in impacts" :key="row.cityId" :class="row.level.toLowerCase()" :data-impact-city="row.cityId">
          <header><b>{{row.station}}</b><span>{{row.levelLabel}}</span></header>
          <strong>{{row.flightCount}} <i>班经此</i></strong>
          <p>{{row.reading}}</p>
          <p>走廊 {{row.corridorCount}} 条<template v-if="row.corridors.length">：{{row.corridors.join(' · ')}}</template></p>
          <small v-if="row.closedCount||row.detouredCount||row.delayedCount">已关闭 {{row.closedCount}} · 已改航 {{row.detouredCount}} · 地面等待 {{row.delayedCount}}</small>
          <small v-else>尚无班次因此关闭、改航或等待</small>
          <p class="impact-advice">{{row.advice}}</p>
        </article>
      </div>
      <p class="operations-muted" v-else>本帧没有达到需谨慎以上等级的观测。</p>
    </div>
    <div class="briefing-block">
      <h4>{{sigmet.heading}}</h4>
      <p class="briefing-note">{{sigmet.note}}</p>
      <p class="briefing-rule" v-if="sigmet.rules">{{sigmet.rules}}</p>
      <div class="sigmet-list" v-if="sigmet.entries.length">
        <article v-for="e in sigmet.entries" :key="e.id">
          <header><b :class="e.kind">{{e.kind}}</b><code>{{e.id}}</code><span :class="e.status">{{e.status==='MERGED'?'已合并':'有效'}}</span></header>
          <p>{{e.body}}</p>
          <small>派生方式：{{e.basis}}</small>
        </article>
      </div>
      <p class="briefing-note" v-else>{{sigmet.note}}</p>
    </div>
  </section>
  <div class="briefing-block detour-card" data-detour-block>
    <div class="briefing-head"><h3>改航依据 · 逐班复诵</h3><small>{{detourRows.length}} 个班次因气象推移航路</small></div>
    <p class="briefing-note">一个总数（例如"12 班改航"）无法核对；逐班带上各自的天气判据才可以。这正是本项目要讲的那件事——航道是被气象推着改的，不是排班排出来的。</p>
    <div class="detour-list" v-if="detourRows.length">
      <article v-for="row in detourRows" :key="row.id" :data-detour-row="row.id">
        <header><code>{{row.id}}</code><b>{{row.name}}</b><span>+{{row.detour}} 分</span></header>
        <p>{{row.basis}}</p>
        <small>{{row.route}}<template v-if="row.distance!=null"> · 航程 {{row.distance}} km</template></small>
      </article>
    </div>
    <p class="briefing-note" v-else>本场景没有受气象影响改航的班次——航路未被气象推移。</p>
  </div>
  <section class="briefing" data-intel-timeline>
    <div class="briefing-head">
      <h3>时间轴情报</h3>
      <small>本场景的关键时刻，按先后排列 · 相对场景基准时刻的分钟偏移</small>
    </div>
    <div class="intel-grid">
      <article v-for="row in timeline" :key="row.key" :class="intelTone(row)">
        <header><b>{{row.label}}</b><span class="source-badge" :class="row.source.tone">{{row.source.label}}</span></header>
        <strong>{{row.value==='absent'?'未取得':row.value}}</strong>
        <p>{{row.note}}</p>
      </article>
    </div>
  </section>
  <section class="briefing" data-intel-airspace>
    <div class="briefing-head">
      <h3>空域与资源情报</h3>
      <small>官方固定管制区与气象派生风险区<b>分开报</b>，不合并成一个总数</small>
    </div>
    <div class="intel-grid">
      <article v-for="row in airspace" :key="row.key" :class="intelTone(row)">
        <header><b>{{row.label}}</b><span class="source-badge" :class="row.source.tone">{{row.source.label}}</span></header>
        <strong>{{row.value==='absent'?'未取得':row.value}}</strong>
        <p>{{row.note}}</p>
      </article>
    </div>
    <p class="briefing-note">登记数与已有几何数<b>不相等是正常的</b>：未取得公开定量范围的类别只登记、不生成几何。把两者合成一句"共 N 个管制区"会把这个差额抹掉，而差额正是"哪一类还不能用"的答案。</p>
  </section>
  </template>
  <template v-else-if="view==='profile'">
    <div class="operations-heading"><h2>走廊剖面 <small>这条走廊几点能飞，凭什么</small></h2>
      <p>概率来自三站 METAR 实测的 1/d² 插值；0–3 h 是本模型，3–6 h 是模式延伸，两段不合并成一条曲线。低置信（最近站距 &gt;250 km）一律降级为建议人工复核。</p></div>
    <CorridorPanel :initial-id="corridorFocus" :minute="minute" :focus-pair="corridorPair"/>
  </template>
  <template v-else-if="view==='card'">
    <div class="operations-heading">
      <h2>推演 <small>一条走廊从观测到裁决</small></h2>
      <p>四站 METAR → 1/d² 插值 → 概率合成 → 四条判据 → 四种处置的期望损失 → 与规则裁决对照。
        每一步的数都由后端算，这一页只按算法顺序摆出来；换一条走廊、拖时间轴，整条链跟着变。</p>
    </div>
    <DeductionPanel :initial-id="corridorFocus" :minute="minute"/>
    <p class="card-archive" data-card-archive>
      <button @click="emit('open-section','mechanism')">历史版本 0.10.1 · 算法机理（学的是判据，不是天气）</button>
      <span>这一页描述的模型不是当前在跑的那个；它的 0.977 属于"复现判据"口径，与上面的数字不可比较。</span>
    </p>
  </template>
  <template v-else-if="view==='counterfactual'">
    <div class="operations-heading"><h2>反事实对照 <small>用 AI 和不用，差多少</small></h2>
      <p>同一份运行计划、同一份气象快照，只换最后一层裁决规则 —— 差异只可能来自裁决，不来自"两次抽样恰好不同"。</p></div>
    <CounterfactualPanel/>
  </template>
  <template v-else-if="view==='ledger'">
    <div class="operations-heading"><h2>分歧台账 <small>AI 与规则不一致时，人怎么判的</small></h2>
      <p>每条记录带时间、走廊、当时的概率与理由；否决与回滚必须填理由（后端对空理由直接 422）。空台账如实说空，不塞占位内容。</p></div>
    <DivergencePanel/>
  </template>
  <template v-else-if="view==='mechanism'">
  <div class="operations-heading"><h2>算法机理 <small>{{cityName}} · {{census.total}} 班</small></h2><p>把「这条走廊为什么不是直线」摊成一条因果链：气象判据 → 几何 → 时间窗。三要素全部取自当前计划自己的班次记录，本页不重算任何一个量；判据说这条走廊被挡住，与航路因此变了多少，是两句话，分开写。</p><WeatherSourceSwitch class="heading-switch" :mode="weatherMode" :status="weatherModeStatus" @change="emit('weather-mode-change',$event)"/></div>

  <MlEffectBoard />

  <div class="briefing-block" data-mechanism-rule>
    <div class="briefing-head"><h3>分级规则与几何构造</h3><small>取自本计划载荷</small></div>    <p class="briefing-note">这些阈值不是在页面上写死的：它们随计划一起下发，并由后端从各自唯一的常量读出。界面再写一份，等于让"页面引用的阈值"和"分类器实际使用的阈值"各有一份，改掉其中一处不会有任何东西变红。</p>
    <div class="mechanism-rule" v-if="rule">
      <article v-for="row in ruleRows" :key="row.key"><small>{{row.label}}</small><strong>{{row.value}}</strong><span>{{row.note}}</span></article>
    </div>
    <p class="briefing-rule" v-else>本计划未发布分级规则——此处不引用任何阈值。缺失时唯一正确的写法是不写数，而不是退回一组看起来像规则的默认值：一个默认值会让人以为已经核对过。</p>
  </div>

  <div class="briefing-block" data-mechanism-census>
    <div class="briefing-head"><h3>判据分布</h3><small>{{census.rows.length}} 条判据 · {{census.unevaluated}} 班未进入成因判定</small></div>
    <p class="briefing-note">每条判据后面写的是"这个判断是在哪块几何上做出来的"。点一条判据可以把下面的班次收窄到它；再点一次取消。固定管制区与作业区边界都不是气象——把它们算进"受气象影响改航"就是把非气象的成因记到气象账上。</p>
    <div class="mechanism-census" v-if="census.rows.length">
      <button v-for="row in census.rows" :key="row.key" class="mechanism-cause" :class="{on:basisFilter===row.key,weather:row.weather}" @click="basisFilter=basisFilter===row.key?'':row.key">
        <header><b>{{row.name}}</b><em>{{row.total}} 班</em><span v-if="row.weather">气象成因</span></header>
        <p>{{row.construction}}</p>
        <small>{{row.detoured}} 班航程增加 · {{row.delayed}} 班地面等待</small>
      </button>
    </div>
    <p class="briefing-note" v-else>本帧没有班次带成因判据。</p>
    <p class="briefing-note" v-if="census.unevaluated">另有 {{census.unevaluated}} 班没有成因判据：它们在成因判定之前的判据处就结束了，不计入上面任何一条。这个数不能并进"直飞段可用"——那会把"没有被判定过"说成"判定为可用"。</p>
  </div>

  <div class="briefing-block" data-mechanism-chain>
    <div class="briefing-head"><h3>逐班三要素</h3><small>匹配 {{picker.matched}} 班 · 此处列 {{picker.rows.length}} 班</small></div>
    <p class="briefing-note">在这里选一个班次，下面展开它的判据、几何与时间窗。这是入口不是台账——要按城市与状态筛全量班次，用「调度台账」。</p>
    <div class="picker-bar">
      <input v-model="chainQuery" type="search" aria-label="搜索班次" placeholder="搜索呼号 / 起降点 / 城市">
      <span class="picker-note">{{basisFilter?`已按「${routeBasisNames[basisFilter]||basisFilter}」收窄`:'未收窄判据：气象成因的班次排在前面'}}</span>
    </div>
    <div class="picker-chips" v-if="picker.rows.length">
      <button v-for="f in picker.rows" :key="f.id" class="picker-chip"
              :class="{on:f.id===chainId,hit:isWeatherDetour(f)}" @click="chainId=f.id">
        <b>{{f.name||f.id}}</b>
        <em>{{routeBasisNames[f.routeBasis]||f.routeBasis}}</em>
      </button>
    </div>
    <p class="briefing-note" v-else>没有匹配的班次。</p>

    <article class="mechanism-chain" v-if="chain" data-mechanism-detail>
      <header>
        <code>{{chain.id}}</code><b>{{chain.name}}</b>
        <span :class="{weather:chain.basisIsWeather}">{{chain.basisIsWeather?'受气象影响改航':(chain.ok?'非气象成因':'未进入成因判定')}}</span>
        <button class="mechanism-jump" @click="emit('select-flight',chainFlight)">在运行总览中查看</button>
      </header>
      <p class="briefing-note" v-if="!chain.ok">本班次没有完整的因果链：{{chain.missing.length}} 个要素缺席。下面逐项写出记录里还剩什么，缺的部分不填补默认值。</p>
      <ol class="mechanism-steps">
        <li v-for="step in chain.steps" :key="step.key" :data-mechanism-step="step.key">
          <h4>{{step.label}}</h4>
          <p class="mechanism-headline" v-if="step.headline">{{step.headline}}</p>
          <p class="mechanism-absent" v-if="step.absent">{{step.absent}}</p>
          <p class="mechanism-line" v-for="(line,index) in step.lines" :key="index">{{line}}</p>
        </li>
      </ol>
    </article>
    <p class="briefing-note" v-else>在上面选一个班次，这里就展开它的三要素。</p>
  </div>
  </template>
  <template v-else-if="view==='assistant'">
  <div class="operations-heading"><h2>大模型取证</h2><p>{{selected?'当前班次：'+selected.name:'取证范围：全网调度计划'}} · 数值由概率模型算（覆盖全部班次），本页只做证据检索 · 共享同一场景与数据快照</p></div>
  <div class="assistant-context"><span>计划 {{session?.sessionId?.slice(0,12)||'未就绪'}}</span><span>第 {{minute.toFixed(1)}} 分钟</span><span>{{selected?.id||'全域运行'}}</span></div>
  <Track1Panel :weather="weather" :minute="minute" :session="session" />
  <section class="mark-panel" data-ai-mark-row>
    <div class="briefing-head"><h3>结论在 AI 与规则之间的位置</h3><small>共 {{MARK_ROWS.length}} 种结局 · 当前：{{selectedMark.label}}</small></div>
    <p class="briefing-note">数值判定由概率模型完成（覆盖全部班次）；规则负责硬阈值兜底，冲突进「推演 · 第 8 步 复核」、可回滚。本页是大模型的<b>证据检索</b>：它只改变"这次引用了哪些证据"，不改判定。</p>
    <ol class="verdict-marks">
      <li v-for="mark in MARK_ROWS" :key="mark.key" :class="mark.tone" :data-ai-mark="mark.key">
        <b>{{mark.label}}</b>
        <small>{{mark.note}}</small>
        <em v-if="selectedMark.key===mark.key" data-ai-mark-current>当前</em>
      </li>
    </ol>
  </section>
  <section class="coverage-card" data-ai-coverage>
    <div class="briefing-head"><h3>研判覆盖</h3><small>{{coverage.reviewed}} / {{coverage.total}} 班</small></div>
    <strong>{{coverage.total?(coverage.ratio*100).toFixed(0):'—'}}<i>%</i></strong>
    <p>分母是全部 <b>{{coverage.total}}</b> 班；<b>全域提问不计入</b>。已对 <b>{{coverage.reviewed}}</b> 个班次发起过研判，尚有 <b>{{coverage.uncovered}}</b> 个未研判<template v-if="coverage.vetoed">，其中 <b>{{coverage.vetoed}}</b> 个的外模作答被规则整条否决</template>。</p>
    <p class="briefing-note" v-if="!coverage.total">当前没有班次可供研判。不显示 0%：一个没有分母的百分比会被读成"覆盖得很差"，而实际是"还没有对象"。</p>
  </section>
  <div class="operations-question"><textarea v-model="question" aria-label="运行研判问题" rows="3" maxlength="1200" placeholder="询问当前城市、班次的风险、绕行或等待原因"></textarea><button @click="ask" :disabled="asking||!session||session.status!=='READY'||!question.trim()">{{asking?'正在查证…':(selected?'查证并研判':'查证并研判（全域）')}}</button></div>
  <p class="operations-error" v-if="error">{{error}}</p>
  <p v-if="answer&&lastGlobal" class="operations-muted" data-global-note><b>本次为全域提问</b>：没有挂在具体班次上，因此<b>不计入</b>下方「研判覆盖」。要让它进入覆盖统计，先在列表里选一个班次再问。这不是失败 —— 全域问答的结论无法归属到某一班，登记它等于给一个不存在的结论盖标记。</p>
  <p v-if="!answer" class="operations-muted">研判只引用当前计划已有的证据：外部模型从证据集合里挑选编号，<b>越出集合即整条回答退回规则证据</b> —— 模型不能生成新事实，也不能绕过气象与冲突约束放行班次。</p>
  <div v-else>
    <div class="ai-status" :class="aiStatus.key" v-if="aiStatus">
      <header>
        <span class="ai-badge">{{aiStatus.label}}</span>
        <small v-if="aiStatus.model">模型 {{aiStatus.model}}</small>
        <small v-if="aiStatus.errorCode">状态码 {{aiStatus.errorCode}}</small>
        <small>证据集合 {{aiStatus.available?.length??0}} 条 · 模型选取 {{aiStatus.selected?.length??0}} 条</small>
      </header>
      <p v-if="aiStatus.key==='vetoed'"><b>整条退回</b>：{{aiStatus.vetoed}}。越界的编号不会被静默丢弃 —— 丢掉它、其余照常作答，界面会显示"检索成功"而回答里全是没核对过的引用。</p>
      <p>{{aiStatus.note}}</p>
    </div>
    <p class="operations-muted">证据时刻：第 {{answer.minute.toFixed(1)}} 分钟 · {{answer.source==='deepseek'?'外部模型选取证据':'本地规则证据'}}</p>
    <div class="answer-cards">
      <article v-for="e in answer.citations" :key="e.id">
        <header><h3>{{e.title}}</h3><span class="origin" :class="e.origin.toLowerCase()">{{e.originLabel}}</span></header>
        <p>{{e.text}}</p>
        <small>证据 {{e.id}}</small>
      </article>
    </div>
  </div>
  </template>
  <template v-else-if="view==='reference'">
  <div class="operations-heading">
    <h2>数据口径与边界 <small>{{cityName}}</small></h2>
    <p>本系统里每一块内容都带一枚来源角标，含义只在这里定义一次。<b>「边界」一项说的是它不意味着什么</b>——前两项（谁产的、覆盖什么）在别的页面已经零散说过，唯独边界从来没有集中的、可引用的出处。</p>
  </div>
  <section class="caliber-ledger" data-caliber-ledger>
    <div class="ledger-hd">
      <h3>口径总账</h3>
      <p>每个数字都在这里能查到定义、分子分母、出处与更新节奏。<b>分母写"—"表示它不是一个比值</b>，不是"还没填"。</p>
    </div>
    <div class="ledger-scroll">
      <table>
        <thead><tr><th>指标</th><th>定义</th><th>分子</th><th>分母</th><th>来源</th><th>更新</th><th>负责人</th></tr></thead>
        <tbody>
          <tr v-for="row in CALIBER_LEDGER" :key="row.key" :data-ledge="row.key">
            <td><b>{{ row.name }}</b></td>
            <td>{{ row.definition }}</td>
            <td>{{ row.numerator || '—' }}</td>
            <td>{{ row.denominator || '—' }}</td>
            <td><code>{{ row.source }}</code></td>
            <td>{{ row.refresh }}</td>
            <td>{{ row.owner }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <div class="badge-legend">
    <article v-for="badge in Object.values(SOURCE_BADGES)" :key="badge.key">
      <span class="source-badge" :class="badge.tone">{{badge.label}}</span>
      <p>{{badge.note}}</p>
    </article>
  </div>
  <div class="caliber-grid">
    <section class="caliber-card" v-for="block in caliber" :key="block.key">
      <header>
        <h3>{{block.title}}</h3>
        <span class="source-badge" :class="block.source.tone">{{block.source.label}}</span>
      </header>
      <p class="caliber-intro">{{block.intro}}</p>
      <dl class="caliber-rows">
        <template v-for="row in block.rows" :key="row.label">
          <dt>{{row.label}}</dt>
          <dd>
            <b :class="{absent:row.value==='absent'}">{{row.value==='absent'?'未取得':row.value}}</b>
            <small>{{row.note}}</small>
          </dd>
        </template>
      </dl>
      <p class="caliber-boundary"><b>边界</b>{{block.boundary}}</p>
    </section>
  </div>

  <div class="briefing-head glossary-head">
    <h3>术语表 · 专业与通俗两读</h3>
    <small>共 {{glossaryTotal}} 条 · 术语本身（dBZ、内核、指纹…）不换词——它是接口、是文档、也是日志里的字段；这里只补一句给人看的话。</small>
  </div>
  <div class="glossary-bar">
    <input v-model="glossaryQuery" type="search" aria-label="搜索术语" placeholder="搜索术语或释义">
    <span>{{glossary.reduce((sum,g)=>sum+g.terms.length,0)}} 条</span>
  </div>
  <div class="glossary-grid">
    <section v-for="group in glossary" :key="group.group">
      <h4>{{group.group}}</h4>
      <dl>
        <template v-for="entry in group.terms" :key="entry.term">
          <dt>{{entry.term}}</dt>
          <dd>
            <span class="plain">{{entry.plain}}</span>
            <details :open="policy.glossary"><summary>专业表述</summary><p>{{entry.full}}</p></details>
          </dd>
        </template>
      </dl>
    </section>
    <p v-if="!glossary.length">没有匹配的术语。这一页只收本系统真正在用、并且会在界面上出现的词——收一个界面上没有的词没有意义。</p>
  </div>
  </template>
  <template v-else-if="view==='history'">
  <div class="operations-heading"><h2>运行操作与决策日志 <small>{{cityName}} · {{journal.length}} 条</small></h2><p>人工干预、系统决策、数据源变更与导出记在同一本日志里，可按类型筛选、按关键词搜索、整表导出 CSV。<b>只有「人工干预」会改变班次状态</b>——其余三类只记录事实，不参与时间轴回放。</p></div>
  <div class="assistant-context"><span>计划 {{session?.sessionId}}</span><span>算法 {{session?.version}}</span><span>指纹 {{session?.fingerprint}}</span></div>
  <div class="journal-bar">
    <div class="journal-filters">
      <button v-for="k in JOURNAL_KINDS" :key="k.key||'all'" class="journal-chip" :class="{on:journalKind===k.key}" @click="journalKind=k.key">
        {{k.label}}<em>{{k.key?(journalCounts[k.key]||0):journal.length}}</em>
      </button>
    </div>
    <input v-model="journalQuery" type="search" aria-label="搜索运行日志" placeholder="搜索班次 / 内容 / 明细">
    <button class="journal-export" :disabled="!journalRows.length" @click="exportJournal">导出 CSV</button>
  </div>
  <p class="operations-error" v-if="journalError">{{journalError}}</p>
  <details class="replay density-fold" :open="policy.replay" data-density="replay">
    <summary>复盘回放 <span>按推演分钟重放全站时钟 · 另有 {{journal.length}} 条操作记录</span></summary>
    <p class="replay-span" v-if="!journal.length" data-replay-empty>
      本计划<b>还没有操作记录</b>（没人点过处置）—— 但时间轴照样能放：
      它驱动的是全站时钟，地图上的航班、气象帧与走廊判据都会跟着走。
      点「开始回放」后切到「态势」即可看画面。
    </p>
    <p class="replay-span" v-else-if="replaySpan" data-replay-span>
      回放的是<b>全站时间轴</b>（0–T+{{ replayMax }} 分）：地图、气象帧、走廊判据会跟着一起走。
      本计划另有 <b>{{ replaySpan.count }}</b> 条操作记录，落在
      <b>T+{{ replaySpan.from.toFixed(0) }}–T+{{ replaySpan.to.toFixed(0) }}</b> 分，
      <template v-if="replaySpan.to<=replaySpan.from">这一段没有第二条记录 —— 表示「这段时间没有人工干预」，不是回放没做完。</template>
      <template v-else>拖过那一段时下表会逐条点亮。</template>
    </p>
    <div class="replay-bar">
      <input aria-label="复盘时间轴" type="range" min="0" :max="replayMax" step="1"
             :value="replayMinute" @input="jumpReplay(Number($event.target.value))">
      <strong>T+{{replayMinute.toFixed(0)}} 分</strong>
      <button class="replay-play primary" data-replay-play @click="toggleReplay">
        {{ replayPlaying ? 'Ⅱ 暂停回放' : '▶ 开始回放' }}
      </button>
      <button @click="jumpReplay(0)">回到开头</button>
      <button @click="jumpReplay(replayMax)">跳到末尾</button>
    </div>
    <div class="replay-marks">
      <button v-for="bucket in replay.buckets" :key="bucket.index"
              class="replay-slot" :class="{on:replayMinute>=bucket.from&&replayMinute<bucket.to,empty:!bucket.count}"
              :title="`T+${bucket.from}—T+${bucket.to} 分`"
              @click="jumpReplay(bucket.from)">
        <em>{{bucket.count}}</em>
        <span>T+{{bucket.from}}</span>
      </button>
    </div>
    <div class="replay-state">
      <span>已发生 <b>{{replayView.past.length}}</b></span>
      <span>就在这一刻 <b>{{replayView.here.length}}</b></span>
      <span>还没发生 <b>{{replayView.upcoming.length}}</b></span>
      <span>全程有效 <b>{{replayView.always.length}}</b></span>
    </div>
    <ul class="replay-now" v-if="replayView.here.length">
      <li v-for="row in replayView.here" :key="row.id">
        <span class="journal-kind" :class="row.kind.toLowerCase()">{{row.kindLabel}}</span>
        {{row.actionLabel}} · {{journalTarget(row)}}<template v-if="row.detail"> · {{row.detail}}</template>
      </li>
    </ul>
    <p class="operations-muted" v-else>这一刻没有发生任何记录。时间轴上的 <b>四态合计</b>始终等于带分钟的条目总数——分段计数与这一步的读数来自同一个切分。</p>
    <div class="replay-weather" :data-replay-weather="replayWeather.state">
      <header><b>当时气象帧</b><span>{{replayWeather.label}}</span></header>
      <div class="replay-weather-grid">
        <article><small>帧分钟</small><strong>{{replayWeather.minute==null?'未取得':'T+'+replayWeather.minute}}</strong></article>
        <article><small>回放指针</small><strong>{{replayWeather.requested==null?'未取得':'T+'+replayWeather.requested}}</strong></article>
        <article><small>网格单元</small><strong>{{replayWeather.cells}}</strong></article>
        <article><small>逐站观测</small><strong>{{replayWeather.observations}}<i> 站</i></strong></article>
        <article><small>雷达槽号</small><strong>{{replayWeather.radarSlot||'未取得'}}</strong></article>
        <article><small>数据源</small><strong>{{replayWeather.provider||'未取得'}}</strong></article>
      </div>
      <ol class="replay-tiers">
        <li><small>层状云 15–35 dBZ</small><b>{{replayWeather.tiers?.stratiform==null?'未发布':replayWeather.tiers.stratiform+' km²'}}</b></li>
        <li><small>对流云 35–45 dBZ</small><b>{{replayWeather.tiers?.convective==null?'未发布':replayWeather.tiers.convective+' km²'}}</b></li>
        <li><small>强回波 ≥45 dBZ</small><b>{{replayWeather.tiers?.strong==null?'未发布':replayWeather.tiers.strong+' km²'}}</b></li>
      </ol>
      <p class="briefing-note">{{replayWeather.note}}</p>
    </div>
  </details>
  <details class="density-fold journal-fold" v-if="journalRows.length" :open="policy.audit" data-density="audit">
  <summary>运行日志明细 <span>{{journalRows.length}} 条</span></summary>
  <table class="operation-journal">
    <thead><tr><th>时刻</th><th>类型</th><th>推演分钟</th><th>对象</th><th>内容</th><th>明细</th></tr></thead>
    <tbody><tr v-for="row in [...journalRows].reverse()" :key="row.id">
      <td>{{journalTime(row)}}</td>
      <td><span class="journal-kind" :class="row.kind.toLowerCase()">{{row.kindLabel}}</span></td>
      <td>{{journalMinute(row)}}</td>
      <td>{{journalTarget(row)}}</td>
      <td>{{row.actionLabel}}</td>
      <td class="journal-detail">{{row.detail||'—'}}</td>
    </tr></tbody>
  </table>
  </details>
  <p class="operations-muted" v-else-if="journalLoading">正在读取运行日志…</p>
  <p class="operations-muted" v-else>这份计划的日志里还没有记录。系统会在 <b>计划构建完成</b>、<b>气象通道切换</b>、<b>人工暂停/恢复</b> 与 <b>导出</b> 时各写一行；若此页为空，请确认后端已按本版本启动（旧版后端不写这三类事件）。</p>
  </template>
</section>
</template>
<style scoped>
.card-archive{margin-top:16px;padding-top:12px;border-top:1px solid var(--alc-line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;font-size:12px;color:var(--alc-text-mute)}
.card-archive button{background:none;border:0;padding:0;color:var(--alc-text-dim);font-size:12px;cursor:pointer;border-bottom:1px dashed var(--alc-line)}
.card-archive button:hover{color:var(--alc-info);border-bottom-color:var(--alc-info)}
.operations-console{background:#0e1c2b;border:1px solid #294355;border-radius:12px;padding:22px;min-height:480px}.operations-heading{margin-bottom:22px}.operations-heading h2{font-size:20px;font-weight:500}.operations-heading h2 small{font-size:12px;color:#7198ad;margin-left:12px}.operations-heading p{font-size:12px;color:#849fb1;line-height:1.8;margin-top:10px}.alert-legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 14px}.alert-legend .tag{font-size:12px;letter-spacing:1px;padding:3px 8px;border-radius:4px;border:1px solid}.alert-legend .tag.delay{color:#f1c77f;border-color:#675636;background:#241f10}.alert-legend .tag.detour{color:#8fd8ea;border-color:#2f5f70;background:#102530}.alert-legend .tag.closed{color:#ffd9a8;border-color:#8a5a2a;background:#3a2712}.heading-switch{margin-top:14px}.alert-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}.operational-alert{text-align:left;background:#152b3c!important;color:#d3e3ee;padding:18px!important;border:1px solid #315168!important;display:block}.operational-alert:hover{background:#1b374b!important;border-color:#65cce5!important}.operational-alert>span{display:inline-block;font-size:12px;letter-spacing:1px;padding:3px 7px;border-radius:4px;background:#3d3320;color:#f1c77f}.operational-alert>span.danger{background:#4a2a12;color:#ffd9a8}.operational-alert h3{font-size:15px;margin:11px 0 7px;color:#e2f1fa;font-weight:500}.operational-alert p{font-size:12px;margin-bottom:14px;color:#a9c6d8;line-height:1.7}.operational-alert small{font-size:12px;color:#7fa3b8}.operational-alert.delay{border-left:3px solid #e8bd72!important}.operational-alert.closed{border-left:3px solid #e08a45!important}.weather-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}.weather-metrics article{padding:18px;background:#152b3c;border-radius:9px;min-width:0;overflow:hidden}.weather-metrics small{display:block;color:#82a4b7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.weather-metrics strong{display:block;font-size:25px;margin-top:12px;color:#a8e9e7;font-weight:500;overflow-wrap:anywhere}.weather-metrics em{font-size:12px;font-style:normal}.weather-cells{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:20px 0}.weather-cells article{padding:14px;border:1px solid #284859;border-radius:6px;min-width:0}.weather-cells article b{overflow-wrap:anywhere}.weather-cells span{font-size:12px;color:#7597ac;margin-left:12px}.weather-cells p{font-size:12px;color:#8aa8b9;margin-top:9px;overflow-wrap:anywhere}.assistant-context{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:#7aa6bd;margin-bottom:18px}.assistant-context span{padding:6px 10px;background:#142e40;border-radius:5px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.operations-question{display:flex;gap:12px}.operations-question textarea{flex:1;resize:vertical;min-width:0;color:#dcebf7;background:#0a1b29;border:1px solid #31526a;border-radius:8px;padding:14px;font:14px 'Microsoft YaHei',sans-serif;line-height:1.8}.operations-question button{align-self:flex-end;background:#236580!important;color:#ecfaff!important}.operations-muted{font-size:12px;color:#8aabbf;line-height:1.9;margin:20px 0}.answer-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.answer-cards article{padding:18px;border-left:3px solid #63c5cb;background:#142b3b;line-height:1.9}.answer-cards h3{font-size:14px;color:#94deda;margin-bottom:12px}.answer-cards p{font-size:13px}.answer-cards small{font-size:12px;color:#688ca2}.operations-error{color:#ffd9a8;padding:16px}.operation-journal{width:100%;border-collapse:collapse;font-size:12px;text-align:left}.operation-journal th,.operation-journal td{padding:16px 12px;border-bottom:1px solid #294353}.operation-journal th{color:#7095ac}.operation-journal small{display:block;color:#6b8aa0;font-size:12px;margin-top:5px}
.briefing{margin:26px 0 0;border-top:1px solid #294353;padding-top:22px}
.briefing-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.briefing-head h3{font-size:16px;font-weight:500;color:#d5e7f1}
.briefing-head small{font-size:12px;color:#6f92a8}
.briefing-block{margin-bottom:24px;min-width:0}
.table-scroll{overflow-x:auto;scrollbar-width:thin;max-width:100%}
.table-scroll::-webkit-scrollbar{height:8px}
.table-scroll::-webkit-scrollbar-thumb{background:rgba(120,180,220,.28);border-radius:4px}
.table-scroll::-webkit-scrollbar-track{background:rgba(255,255,255,.03)}
.briefing-block h4{font-size:13px;color:#9fd9e2;margin-bottom:9px;font-weight:500}
.briefing-block h4 span{font-size:12px;color:#6f92a8;margin-left:9px}
.density-fold>summary{font-size:13px;color:#9fd9e2;font-weight:500;cursor:pointer;
  margin-bottom:9px;list-style-position:outside}
.density-fold>summary span{font-size:12px;color:#6f92a8;margin-left:9px;font-weight:400}
.density-fold>summary:hover{color:#c6eef5}
.density-fold.journal-fold>summary{font-size:13px;color:#d5e7f1;margin:18px 0 10px}
.replay>summary{font-size:14px;color:#d5e7f1;margin-bottom:13px;cursor:pointer}
.replay>summary span{font-size:12px;color:#7b9cb1;margin-left:14px;font-weight:400}
.replay>summary:hover{color:#c6eef5}
.briefing-note{font-size:12px;color:#7d9cb0;line-height:1.85;margin-bottom:13px;max-width:900px}
.briefing-note code{background:#12293a;padding:1px 5px;border-radius:3px;color:#a8cfe0}
.briefing-rule{font-size:12px;color:#c8a86a;line-height:1.85;margin-bottom:14px;padding:9px 12px;background:#251f10;border-left:3px solid #8a6f3a;border-radius:0 5px 5px 0;max-width:900px}
.metar-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.metar-grid article{padding:14px 16px;background:#14293a;border:1px solid #274355;border-radius:8px;min-width:0}
.metar-grid dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px;margin:0}
.metar-grid dt{font-size:12px;color:#7b9cb1;white-space:nowrap}
.metar-grid dd{margin:0;font-size:12px;color:#d2e5f0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.sigmet-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.sigmet-list article{padding:14px 16px;background:#1a2334;border:1px solid #33415c;border-left:3px solid #7d6fc6;border-radius:0 8px 8px 0;min-width:0}
.sigmet-list header{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:9px}
.sigmet-list header b{font-size:12px;font-weight:500}
.sigmet-list header b.降水{color:#8fd0ea}.sigmet-list header b.雷暴{color:#ffc98a}.sigmet-list header b.强风{color:#8bd8be}.sigmet-list header b.低能见度{color:#b3b0dd}
.sigmet-list header code{font-size:12px;color:#7e9cb2;overflow-wrap:anywhere}
.sigmet-list header span{font-size:12px;letter-spacing:1px;padding:2px 6px;border-radius:3px;background:#2b3f2f;color:#93d0a5}
.sigmet-list header span.MERGED{background:#3b3420;color:#e0c489}
.sigmet-list p{font-size:12px;color:#a8c3d4;line-height:1.8;margin-bottom:8px}
.sigmet-list small{font-size:12px;color:#7593a8;line-height:1.7;display:block}
.picker{margin-bottom:6px}
.picker-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.picker-bar input{flex:0 1 300px;min-width:180px;background:#12293a!important;border:1px solid #2b4a5e!important;
  color:#d3e6f0;border-radius:7px;padding:8px 11px;font:inherit;font-size:12px}
.picker-bar input::placeholder{color:#5f8098}
.picker-note{font-size:12px;color:#6f92a8}
.picker-chips{display:flex;flex-wrap:wrap;gap:8px;max-height:124px;overflow-y:auto;padding-right:4px}
.picker-chip{display:flex;flex-direction:column;align-items:flex-start;gap:2px;text-align:left;
  background:#14293a!important;border:1px solid #274355!important;border-left:3px solid #3d8bff!important;
  border-radius:0 7px 7px 0;color:#cfe3ef;padding:7px 11px;cursor:pointer;font:inherit;min-width:0}
.picker-chip b{font-size:11.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}
.picker-chip em{font-size:9.5px;font-style:normal;color:#7fa3b8;white-space:nowrap}
.picker-chip.hit{border-left-color:#27e0ff!important}
.picker-chip.hit em{color:#8fe6f7}
.picker-chip.off{border-left-color:#e08a45!important}
.picker-chip.off em{color:#e8c69a}
.picker-chip:hover{border-color:#65cce5!important;background:#1b374b!important}
.picker-chip.on{background:#204658!important;border-color:#398098!important;color:#eaf7ff}
.clearance-card{margin-bottom:24px}
.clearance-report{margin:0;padding:16px 20px;background:#0b1b30;border:1px solid #274355;
  border-left:3px solid #27e0ff;border-radius:0 9px 9px 0;overflow:auto;
  font-family:"Cascadia Mono","Consolas","Courier New",monospace}
.clearance-report code{font-size:12px;line-height:2;color:#d3ecf7;white-space:pre;display:block}
.detour-card{margin-top:26px;border-top:1px solid #294353;padding-top:22px;margin-bottom:0}
.detour-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.detour-list article{padding:14px 16px;background:#122a3a;border:1px solid #2b5f70;
  border-left:3px solid #27e0ff;border-radius:0 8px 8px 0;min-width:0}
.detour-list header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.detour-list header code{font-size:12px;color:#7ea6bd;overflow-wrap:anywhere}
.detour-list header b{font-size:12px;font-weight:500;color:#e2f1fa;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.detour-list header span{font-size:12px;color:#a9f0ff;font-variant-numeric:tabular-nums;flex:none}
.detour-list p{font-size:12px;color:#a8c3d4;line-height:1.8;margin-bottom:8px}
.detour-list small{font-size:12px;color:#7593a8;line-height:1.7;display:block}
.mechanism-rule{display:grid;grid-template-columns:repeat(auto-fit,minmax(238px,1fr));gap:12px}
.mechanism-rule article{padding:14px 16px;background:#14293a;border:1px solid #274355;border-radius:8px;min-width:0}
.mechanism-rule small{display:block;font-size:12px;color:#7b9cb1;letter-spacing:1px;margin-bottom:7px}
.mechanism-rule strong{display:block;font-size:13px;color:#bfeaf6;font-weight:500;font-variant-numeric:tabular-nums;margin-bottom:8px;overflow-wrap:anywhere}
.mechanism-rule span{font-size:10.5px;color:#82a0b4;line-height:1.75;display:block}
.mechanism-census{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:12px}
.mechanism-cause{text-align:left;background:#14293a!important;color:#cfe3ef;padding:14px 16px!important;
  border:1px solid #274355!important;border-left:3px solid #3d8bff!important;border-radius:0 8px 8px 0;display:block;min-width:0;cursor:pointer;font:inherit}
.mechanism-cause:hover{border-color:#65cce5!important;background:#1b374b!important}
.mechanism-cause.weather{border-left-color:#27e0ff!important}
.mechanism-cause.on{background:#204658!important;border-color:#398098!important}
.mechanism-cause header{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:8px}
.mechanism-cause header b{font-size:12.5px;font-weight:600;color:#e2f1fa}
.mechanism-cause header em{font-size:12px;font-style:normal;color:#a9f0ff;font-variant-numeric:tabular-nums}
.mechanism-cause header span{font-size:12px;letter-spacing:1px;padding:2px 6px;border-radius:3px;background:#10333f;color:#8fe6f7}
.mechanism-cause p{font-size:12px;color:#a8c3d4;line-height:1.8;margin-bottom:7px;overflow-wrap:anywhere}
.mechanism-cause small{font-size:12px;color:#7593a8}
.mechanism-chain{margin-top:18px;padding:16px 18px;background:#0b1b30;border:1px solid #274355;
  border-left:3px solid #27e0ff;border-radius:0 9px 9px 0}
.mechanism-chain>header{display:flex;align-items:baseline;gap:11px;flex-wrap:wrap;margin-bottom:12px}
.mechanism-chain>header code{font-size:12px;color:#7ea6bd;overflow-wrap:anywhere}
.mechanism-chain>header b{font-size:13px;font-weight:500;color:#e2f1fa}
.mechanism-chain>header span{font-size:12px;letter-spacing:1px;padding:2px 7px;border-radius:3px;background:#3b3420;color:#e0c489}
.mechanism-chain>header span.weather{background:#10333f;color:#8fe6f7}
.mechanism-jump{margin-left:auto;font-size:12px!important;padding:5px 10px!important;
  background:#16323f!important;border:1px solid #2b5f70!important;color:#bfeaf6!important;border-radius:6px}
.mechanism-steps{list-style:none;counter-reset:mechanism;margin:0;padding:0;display:grid;gap:14px}
.mechanism-steps li{counter-increment:mechanism;position:relative;padding-left:34px;min-width:0}
.mechanism-steps li::before{content:counter(mechanism);position:absolute;left:0;top:0;width:22px;height:22px;
  display:flex;align-items:center;justify-content:center;border-radius:50%;background:#16323f;color:#8fe6f7;
  font-size:12px;font-variant-numeric:tabular-nums}
.mechanism-steps h4{font-size:12px;font-weight:500;color:#9fd9e2;margin:2px 0 7px}
.mechanism-headline{font-size:11.5px;color:#d3ecf7;line-height:1.8;margin-bottom:6px;overflow-wrap:anywhere}
.mechanism-absent{font-size:12px;color:#c8a86a;line-height:1.85;padding:8px 11px;background:#251f10;
  border-left:3px solid #8a6f3a;border-radius:0 5px 5px 0;margin-bottom:6px}
.mechanism-line{font-size:12px;color:#a8c3d4;line-height:1.85;margin-bottom:4px;overflow-wrap:anywhere}
.mechanism-line:last-child{margin-bottom:0}
@media(max-width:800px){.mechanism-rule,.mechanism-census{grid-template-columns:minmax(0,1fr)}.mechanism-chain>header .mechanism-jump{margin-left:0}}
.journal-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.journal-filters{display:flex;gap:7px;flex-wrap:wrap}
.journal-chip{display:inline-flex;align-items:center;gap:6px;font:inherit;font-size:12px;padding:6px 11px;
  background:#14293a!important;border:1px solid #274355!important;border-radius:999px;
  color:#bcd4e2;cursor:pointer}
.journal-chip em{font-style:normal;font-size:12px;color:#8fb3c6;font-variant-numeric:tabular-nums}
.journal-chip:hover{border-color:#65cce5!important}
.journal-chip.on{background:#204658!important;border-color:#398098!important;color:#eaf7ff}
.journal-chip.on em{color:#a9f0ff}
.journal-bar input{flex:0 1 260px;min-width:160px;background:#12293a!important;border:1px solid #2b4a5e!important;
  color:#d3e6f0;border-radius:7px;padding:8px 11px;font:inherit;font-size:12px}
.journal-bar input::placeholder{color:#5f8098}
.journal-export{margin-left:auto;font:inherit;font-size:12px;padding:7px 13px;background:#16323f!important;
  border:1px solid #2b5f70!important;color:#bfeaf6!important;border-radius:7px;cursor:pointer}
.journal-export:hover:not(:disabled){border-color:#65cce5!important}
.journal-export:disabled{opacity:.45;cursor:not-allowed}
.journal-kind{display:inline-block;font-size:12px;letter-spacing:.5px;padding:3px 7px;border-radius:4px;
  white-space:nowrap;background:#1b3145;color:#9fc4d8}
.journal-kind.manual{background:#10333f;color:#8fe6f7}
.journal-kind.system{background:#1a2a44;color:#a8c6f0}
.journal-kind.source{background:#2b2a3f;color:#c3b6ee}
.journal-kind.export{background:#233040;color:#93a9bd}
.journal-detail{color:#9ab6c8;line-height:1.7;overflow-wrap:anywhere;max-width:420px}
.cause-bar{margin:0 0 20px;padding:14px 16px;background:#14293a;border:1px solid #274355;border-radius:9px}
.cause-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:11px}
.cause-head b{font-size:14px;color:#e2f1fa;font-weight:500}
.cause-head span{font-size:12px;color:#82a4b7}
.cause-verdict{color:#c8a86a!important}
.cause-split{display:flex;height:12px;border-radius:6px;overflow:hidden;background:#0e1c2b;margin-bottom:11px}
.cause-split span{display:block;min-width:0}
.cause-split .weather{background:#d98a2b}
.cause-split .nonweather{background:#3d8bff}
.cause-legend{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.cause-chip{display:inline-flex;align-items:center;gap:6px;font:inherit;font-size:12px;padding:5px 11px;
  background:#14293a!important;border:1px solid #274355!important;border-radius:999px;color:#bcd4e2;cursor:pointer}
.cause-chip em{font-style:normal;font-size:12px;font-variant-numeric:tabular-nums;color:#8fb3c6}
.cause-chip.weather:hover{border-color:#d98a2b!important}
.cause-chip.nonweather:hover{border-color:#3d8bff!important}
.cause-chip.weather.on{background:#3b2c14!important;border-color:#8a6f3a!important;color:#e8cf9a}
.cause-chip.nonweather.on{background:#16323f!important;border-color:#398098!important;color:#bfeaf6}
.cause-note{font-size:12px;color:#6f92a8}
.disposal-card{padding:16px 18px;background:#152b3c;border:1px solid #315168;border-left:3px solid #475569;border-radius:0 9px 9px 0;display:flex;flex-direction:column;min-width:0}
.disposal-card.weather{border-left-color:#C2410C}
.disposal-card.closed{background:#1b2733}
.disposal-card>header{display:flex;align-items:center;justify-content:space-between;gap:9px;flex-wrap:wrap;margin-bottom:9px}
.cause-tag{font-size:12px;letter-spacing:.5px;padding:3px 8px;border-radius:4px;background:#16323f;color:#bfeaf6}
.case-panels{margin:0 0 14px;padding:12px 14px;border:1px solid rgba(194,65,12,.42);
  border-radius:8px;background:rgba(194,65,12,.06)}
.case-panels header{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}
.case-panels header b{font-size:13px;color:#F0B27A}
.case-panels header span{font-size:12px;color:var(--alc-text)}
.case-panels header small{margin-left:auto;font-size:11px;color:var(--alc-text-dim)}
.case-panels-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.case-panels-grid div{display:flex;flex-direction:column;gap:2px}
.case-panels-grid small{font-size:11px;color:var(--alc-text-dim)}
.case-panels-grid b{font-size:14px;color:var(--alc-text);font-variant-numeric:tabular-nums}
.case-panels-foot{margin:10px 0 0;font-size:12px;color:var(--alc-text-dim);line-height:1.6}
.case-panels-foot b{color:#F0B27A}
.inline-link{padding:0;border:0;background:none;color:#6fb3ff;font:inherit;
  text-decoration:underline;cursor:pointer}
.inline-link:hover{color:#a6d0ff}
.cause-tag.weather{background:#3b2c14;color:#e8cf9a}
.disposal-state{font-size:12px;letter-spacing:.5px;padding:3px 8px;border-radius:4px;background:#1b3145;color:#9fc4d8}
.disposal-state.acknowledged{background:#2b2a3f;color:#c3b6ee}
.disposal-state.handled{background:#12321f;color:#8fd6a8}
.disposal-card h3{font-size:15px;margin:0 0 7px;color:#e2f1fa;font-weight:500}
.cause-phrase{font-size:12px;color:#a9c6d8;line-height:1.7;margin-bottom:11px}
.impact{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 12px;margin:0 0 11px}
.impact dt{font-size:12px;color:#7b9cb1;white-space:nowrap}
.impact dd{margin:0;font-size:12px;color:#cfe3ef;line-height:1.6;overflow-wrap:anywhere}
.advice{font-size:12px;color:#e8cf9a;line-height:1.85;padding:9px 11px;background:#251f10;
  border-left:3px solid #8a6f3a;border-radius:0 5px 5px 0;margin:0 0 12px}
.advice.plain{color:#9fc4d8;background:#132434;border-left-color:#2b5f70}
.disposal-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:auto}
.disposal-actions button{font:inherit;font-size:10.5px;padding:6px 11px;background:#16323f!important;
  border:1px solid #2b5f70!important;color:#bfeaf6!important;border-radius:6px;cursor:pointer}
.disposal-actions button:hover:not(:disabled){border-color:#65cce5!important}
.disposal-actions button:disabled{opacity:.4;cursor:not-allowed}
.ai-status{margin:0 0 18px;padding:14px 16px;background:#14293a;border:1px solid #274355;
  border-left:3px solid #3d8bff;border-radius:0 9px 9px 0}
.ai-status header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.ai-badge{font-size:12px;letter-spacing:.5px;padding:4px 10px;border-radius:999px;background:#16323f;color:#bfeaf6}
.ai-status small{font-size:12px;color:#7fa3b8;font-variant-numeric:tabular-nums}
.ai-status p{font-size:12px;color:#a8c3d4;line-height:1.85;margin:0 0 6px;max-width:900px}
.ai-status p:last-child{margin-bottom:0}
.ai-status.accepted{border-left-color:#27e0ff}
.ai-status.vetoed{border-left-color:#c8a86a;background:#221d12}
.ai-status.vetoed .ai-badge{background:#3b3420;color:#e0c489}
.ai-status.vetoed p b{color:#e0c489}
.ai-status.unavailable,.ai-status.off{border-left-color:#3d6b8b}
.ai-status.unavailable .ai-badge,.ai-status.off .ai-badge{background:#1b3145;color:#9fc4d8}
.answer-cards article>header{display:flex;align-items:baseline;justify-content:space-between;gap:10px;flex-wrap:wrap}
.answer-cards article>header h3{margin-bottom:8px}
.origin{font-size:9.5px;letter-spacing:.5px;padding:3px 7px;border-radius:4px;white-space:nowrap;
  background:#1b3145;color:#9fc4d8}
.origin.ai{background:#10333f;color:#8fe6f7}
@media(max-width:800px){.weather-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.operations-question{flex-direction:column}.operation-journal{font-size:12px}.operations-console{padding:14px}.metar-grid,.sigmet-list{grid-template-columns:minmax(0,1fr)}.journal-export{margin-left:0}.journal-detail{max-width:none}
  .replay-marks{grid-template-columns:repeat(4,minmax(0,1fr))}
  .intel-grid,.badge-legend,.caliber-grid,.glossary-grid{grid-template-columns:minmax(0,1fr)}}

.drill-banner{margin-bottom:18px;padding:10px 13px;font-size:11.5px;line-height:1.8;color:#9fd0e0;
  background:#122a3a;border-left:3px solid #59dffc;border-radius:0 6px 6px 0}
.drill-banner b{color:#c9f0fb;margin-right:10px}

.source-badge{font-size:9.5px;letter-spacing:.6px;padding:3px 8px;border-radius:4px;white-space:nowrap;
  border:1px solid transparent;font-weight:500}
.source-badge.sim{background:#152a3d;color:#8fb6d0;border-color:#2b4a63}
.source-badge.public{background:#102b30;color:#7fd9cd;border-color:#265249}
.source-badge.derived{background:#2a2413;color:#e8c477;border-color:#5c4c22}
.source-badge.official{background:#1a2438;color:#9fb0dd;border-color:#37456b}
.source-badge.manual{background:#2a1e30;color:#d9a8e4;border-color:#543d5e}
.source-badge.absent{background:#242a30;color:#9aa6b2;border-color:#4b5560}
.badge-legend{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:26px}
.badge-legend article{padding:13px 15px;background:#14293a;border:1px solid #274355;border-radius:8px}
.badge-legend p{font-size:12px;color:#8aa8ba;line-height:1.75;margin-top:9px}

.caliber-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(390px,1fr));gap:14px;margin-bottom:30px}
.caliber-card{padding:16px 18px;background:#14293a;border:1px solid #274355;border-radius:9px;min-width:0}
.caliber-card header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.caliber-card h3{font-size:14px;font-weight:500;color:#d5e7f1}
.caliber-intro{font-size:12px;color:#7d9cb0;line-height:1.75;margin-bottom:13px}
.caliber-rows{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px 14px;margin:0}
.caliber-rows dt{font-size:12px;color:#7b9cb1;white-space:nowrap;padding-top:3px}
.caliber-rows dd{margin:0;min-width:0}
.caliber-rows dd b{display:block;font-size:12px;color:#d2e5f0;overflow-wrap:anywhere;font-weight:500}
.caliber-rows dd b.absent{color:#9aa6b2;font-style:italic;font-weight:400}
.caliber-rows dd small{display:block;font-size:12px;color:#7593a6;line-height:1.65;margin-top:4px}
.caliber-boundary{margin-top:14px;padding:10px 12px;font-size:12px;line-height:1.8;color:#c9b183;
  background:#231e11;border-left:3px solid #8a6f3a;border-radius:0 5px 5px 0}
.caliber-boundary b{color:#e8c477;margin-right:8px}

.glossary-head{margin-top:6px;margin-bottom:14px}
.glossary-bar{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.glossary-bar input{flex:1 1 auto;min-width:0}
.glossary-bar span{font-size:12px;color:#7b9cb1;white-space:nowrap}
.glossary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.glossary-grid>section{background:#14293a;border:1px solid #274355;border-radius:9px;padding:15px 17px;min-width:0}
.glossary-grid h4{font-size:12px;letter-spacing:1.2px;color:#7fb6c8;text-transform:none;margin-bottom:12px;font-weight:500}
.glossary-grid dl{margin:0}
.glossary-grid dt{font-size:12.5px;color:#9fe4f2;font-weight:500;margin-bottom:5px}
.glossary-grid dd{margin:0 0 15px;padding-left:11px;border-left:2px solid #24455a}
.glossary-grid dd:last-child{margin-bottom:0}
.glossary-grid .plain{display:block;font-size:11.5px;color:#c3dae6;line-height:1.8}
.glossary-grid details{margin-top:7px}
.glossary-grid summary{font-size:12px;color:#7fa3b8;cursor:pointer;list-style:none}
.glossary-grid summary::before{content:"▸ ";color:#4d7f97}
.glossary-grid details[open] summary::before{content:"▾ "}
.glossary-grid details p{font-size:10.5px;color:#8fabbd;line-height:1.8;margin-top:6px;
  padding:8px 10px;background:#112434;border-radius:5px}

.intel-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.intel-grid article{padding:13px 15px;background:#14293a;border:1px solid #274355;
  border-left:3px solid #35516b;border-radius:8px;min-width:0}
.intel-grid article header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}
.intel-grid article header b{font-size:11.5px;color:#a9c6d8;font-weight:500}
.intel-grid article strong{display:block;font-size:14px;color:#d9ecf5;font-variant-numeric:tabular-nums;
  overflow-wrap:anywhere;margin-bottom:8px}
.intel-grid article p{font-size:10.5px;color:#7d9cb0;line-height:1.7}
.intel-grid article.k-good{border-left-color:#4fbf9a}
.intel-grid article.k-warn{border-left-color:#d98a4a}
.intel-grid article.k-muted{border-left-color:#3a5568;opacity:.82}
.intel-grid article.k-cyan{border-left-color:#59dffc}

.disposal-actions button.receipt{border-color:#3d5f7a;color:#a8cfe0}
.disposal-actions button.receipt.done{border-color:#4fbf9a;color:#8fe0c2}
.receipt-text{margin-top:10px;padding:9px 11px;font-size:10.5px;line-height:1.8;color:#9dbdd0;
  background:#112434;border-radius:6px;overflow-wrap:anywhere}

.replay{margin:0 0 22px;padding:15px 17px;background:#122636;border:1px solid #274355;border-radius:9px}
.replay-span{margin:10px 0 4px;padding:7px 10px;border-radius:6px;font-size:12px;line-height:1.6;
  color:#a9c3d3;background:rgba(120,170,220,.07);border-left:2px solid rgba(120,170,220,.35)}
.replay-span b{color:#dff1fb;font-weight:600}
.replay-bar .replay-play{background:#1f6b86!important;border-color:#3f93b0!important;color:#eefbff!important}
.replay-bar .replay-play:hover{border-color:#65cce5!important}
.replay-bar{display:flex;align-items:center;gap:12px;margin-bottom:13px}
.replay-bar input[type=range]{flex:1 1 auto;min-width:0}
.replay-bar strong{font-size:13px;color:#9fe4f2;font-variant-numeric:tabular-nums;white-space:nowrap}
.replay-marks{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:6px;margin-bottom:14px}
.replay-slot{border:1px solid #274355!important;background:#132a3b!important;padding:7px 4px!important;
  display:flex;flex-direction:column;align-items:center;gap:3px;line-height:1.25}
.replay-slot em{font-style:normal;font-size:13px;color:#9fe4f2;font-variant-numeric:tabular-nums}
.replay-slot span{font-size:12px;color:#6f92a8}
.replay-slot.empty em{color:#4d6c80}
.replay-slot.on{border-color:#59dffc!important;background:#17384b!important}
.replay-state{display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:#8aa8ba;margin-bottom:11px}
.replay-state b{color:#d2e5f0;font-variant-numeric:tabular-nums;margin-left:5px}
.replay-now{list-style:none;margin:0;padding:0}
.replay-now li{font-size:12px;color:#b6d1e0;line-height:1.9;padding:7px 0;border-top:1px solid #1e3849}
.replay-now li:first-child{border-top:0}
.replay-now .journal-kind{margin-right:8px}
.observation-table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}
.observation-table th,.observation-table td{padding:11px 10px;border-bottom:1px solid #243d4f;vertical-align:middle}
.observation-table thead th{color:#7095ac;font-weight:400;padding:0;white-space:nowrap}
.observation-table thead th:first-child{padding-left:10px}
.obs-sort{font:inherit;color:#7095ac;background:transparent!important;border:0!important;padding:11px 10px!important;
  cursor:pointer;display:inline-flex;align-items:center;gap:5px;width:100%;text-align:left;border-radius:0}
.obs-sort.numeric{justify-content:flex-end}
.obs-sort em{font-style:normal;font-size:12px;color:#4d6c80;min-width:9px}
.obs-sort:hover,.obs-sort.on{color:#9fe4f2}
.obs-sort.on em{color:#9fe4f2}
.observation-table td.num{text-align:right;font-variant-numeric:tabular-nums;color:#d2e5f0}
.observation-table tbody tr:hover{background:#14293a}
.observation-table tbody tr.SEVERE td:first-child{box-shadow:inset 3px 0 0 #e08a45}
.observation-table tbody tr.CAUTION td:first-child{box-shadow:inset 3px 0 0 #d98a2b}
.severity-chip{display:inline-block;font-size:12px;padding:2px 7px;border-radius:3px;
  background:#22333f;color:#9fbccd;white-space:nowrap}
.severity-chip[data-obs-level="SEVERE"]{background:#4a2a12;color:#ffd9a8}
.severity-chip[data-obs-level="CAUTION"]{background:#3b3420;color:#e0c489}
.severity-chip[data-obs-level="UNKNOWN"]{background:#1e2b35;color:#7d95a5}
.impact-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.impact-grid article{padding:16px;background:#152b3c;border:1px solid #315168;border-left:3px solid #3d8bff;border-radius:0 9px 9px 0;min-width:0}
.impact-grid article.severe{border-left-color:#e08a45}
.impact-grid article.caution,.impact-grid article.weather{border-left-color:#d98a2b}
.impact-grid header{display:flex;align-items:baseline;justify-content:space-between;gap:9px;flex-wrap:wrap;margin-bottom:9px}
.impact-grid header b{font-size:14px;color:#e2f1fa;font-weight:500}
.impact-grid header span{font-size:12px;color:#8aa8ba}
.impact-grid strong{display:block;font-size:24px;color:#a8e9e7;font-weight:500;font-variant-numeric:tabular-nums}
.impact-grid strong i{font-size:12px;font-style:normal;color:#82a4b7;margin-left:5px}
.impact-grid p{font-size:12px;color:#a8c3d4;line-height:1.8;margin-top:9px}
.impact-grid small{font-size:12px;color:#7d9cb0;line-height:1.7;display:block;margin-top:6px}
.impact-advice{color:#c8a86a!important;border-top:1px dashed #3a4653;padding-top:8px}
.mark-panel{margin:22px 0;border-top:1px solid #294353;padding-top:20px}
.verdict-marks{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.verdict-marks li{position:relative;padding:13px 14px;background:#14293a;border:1px solid #274355;
  border-left:3px solid #4d6c80;border-radius:0 7px 7px 0;min-width:0}
.verdict-marks li b{display:block;font-size:12px;color:#cfe3ee;font-weight:500;margin-bottom:6px}
.verdict-marks li small{font-size:12px;color:#7d9cb0;line-height:1.75;display:block}
.verdict-marks li.cyan{border-left-color:#3d8bff}
.verdict-marks li.warn{border-left-color:#d98a2b}
.verdict-marks li em{font-style:normal;position:absolute;top:11px;right:12px;font-size:12px;letter-spacing:1px;
  padding:2px 6px;border-radius:3px;background:#17384b;color:#9fe4f2}
.coverage-card{margin:22px 0;padding:16px 18px;background:#152b3c;border:1px solid #315168;border-radius:9px}
.coverage-card strong{display:block;font-size:30px;color:#a8e9e7;font-weight:500;font-variant-numeric:tabular-nums}
.coverage-card strong i{font-size:14px;font-style:normal;color:#82a4b7;margin-left:3px}
.coverage-card p{font-size:12px;color:#a8c3d4;line-height:1.85;margin-top:9px}
.verdict-mark{font-size:11.5px;line-height:1.85;margin-bottom:13px;padding:10px 13px;border-radius:0 6px 6px 0;
  background:#16232e;border-left:3px solid #4d6c80;color:#93aec0}
.verdict-mark b{display:inline-block;margin-right:9px;padding:2px 8px;border-radius:3px;
  background:#22333f;color:#cfe3ee;font-size:10.5px;font-weight:500}
.verdict-mark.cyan{border-left-color:#3d8bff;background:#132434}
.verdict-mark.warn{border-left-color:#d98a2b;background:#241f10;color:#c8b48a}
.verdict-mark.warn b{background:#3b3420;color:#e0c489}
.verdict-chip{display:inline-block;font-size:12px;padding:2px 7px;border-radius:3px;background:#22333f;color:#9fbccd;white-space:nowrap}
.verdict-chip.muted{background:#1e2b35;color:#7d95a5}
.verdict-chip.cyan{background:#12293a;color:#8fd8ea}
.verdict-chip.warn{background:#3b3420;color:#e0c489}
.event-tone{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:2px 8px;border-radius:3px;
  background:#16323f;color:#9fbccd;white-space:nowrap}
.event-tone::before{content:'';width:8px;height:8px;border-radius:50%;background:#3d8bff}
.event-tone.alert{color:#ffd9a8}
.event-tone.alert::before{background:#e08a45}
.event-tone.warn{color:#e0c489}
.event-tone.warn::before{background:#d98a2b}
.disposal-actions button.unsupported{color:#8aa8ba;border-color:#33475a;border-style:dashed}
.disposal-actions button.unsupported:hover{color:#a8c3d4;border-color:#4d6c80}
.disposal-refusal{font-size:12px;color:#e8c69a;line-height:1.8;margin-bottom:11px;padding:9px 12px;
  background:#3a2712;border-left:3px solid #8a5a2a;border-radius:0 6px 6px 0}
.disposal-refusal b{display:block;margin-bottom:4px;color:#ffd9a8}
.disposal-card.focused{box-shadow:0 0 0 2px #59dffc,0 0 22px -6px rgba(89,223,252,.53)}
.tier-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-bottom:14px}
.tier-grid article{padding:15px 17px;background:#152b3c;border:1px solid #315168;border-radius:8px;min-width:0}
.tier-grid article[data-evolution-state="NOT_INCLUDED"]{border-style:dashed;background:#132330}
.tier-grid header{display:flex;align-items:baseline;justify-content:space-between;gap:9px;flex-wrap:wrap;margin-bottom:8px}
.tier-grid header b{font-size:13px;color:#d5e7f1;font-weight:500}
.tier-grid header span{font-size:12px;color:#7d9cb0}
.tier-grid strong{display:block;font-size:24px;color:#a8e9e7;font-weight:500;font-variant-numeric:tabular-nums}
.tier-grid strong i{font-size:12px;font-style:normal;color:#82a4b7;margin-left:5px}
.tier-grid p{font-size:12px;color:#8aa8ba;line-height:1.8;margin-top:8px}
.tier-grid article[data-tier-state="ABSENT"]{border-style:dashed;background:#132330;border-left:3px solid #4d6c80}
.tier-grid article[data-tier-state="EMPTY"]{border-left:3px solid #4fbf9a}
.tier-grid article[data-tier-state="INVALID"]{border-left:3px solid #e08a45}
.tier-grid article[data-tier-state="PRESENT"]{border-left:3px solid #3d8bff}
.case-station-table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:8px}
.case-station-table th{text-align:left;padding:4px 8px;font-weight:500;color:var(--alc-text-dim);
  border-bottom:1px solid rgba(255,255,255,.12);white-space:nowrap}
.case-station-table td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.06);white-space:nowrap}
.case-station-table td b{font-weight:500;color:#e2f1fa;letter-spacing:.4px}
.station-level{font-size:11.5px;padding:1px 6px;border-radius:3px;background:rgba(255,255,255,.06)}
.station-level.danger{color:var(--alc-danger);background:rgba(224,71,71,.12)}
.station-level.watch{color:var(--alc-watch);background:rgba(255,181,71,.12)}
.station-level.ok{color:var(--alc-ok)}
.severity-band{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px}
.severity-band li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 10px;align-items:baseline;
  padding:10px 13px;background:#14293a;border-left:3px solid #3d8bff;border-radius:0 7px 7px 0;min-width:0}
.severity-band li b{font-size:12.5px;color:#e2f1fa;font-weight:500}
.severity-band li span{font-size:12px;color:#8aa8ba;text-align:right}
.severity-band li small{grid-column:1/-1;font-size:12px;color:#7d9cb0;line-height:1.7}
.evolution-table{width:100%;border-collapse:collapse;font-size:12px;text-align:left;margin-top:6px}
.evolution-table th,.evolution-table td{padding:10px;border-bottom:1px solid #243d4f;font-variant-numeric:tabular-nums}
.evolution-table th{color:#7095ac;font-weight:400}
.evolution-table td.hit{color:#e0c489}
.replay-weather{margin-top:16px;padding:15px 17px;background:#132330;border:1px solid #274355;border-radius:8px}
.replay-weather[data-replay-weather="ALIGNED"]{border-left:3px solid #4fbf9a}
.replay-weather[data-replay-weather="MISALIGNED"]{border-left:3px solid #d98a2b}
.replay-weather[data-replay-weather="ABSENT"]{border-left:3px solid #6d3a46}
.replay-weather>header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.replay-weather>header b{font-size:13px;color:#d5e7f1;font-weight:500}
.replay-weather>header span{font-size:10.5px;color:#8aa8ba}
.replay-weather-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:12px}
.replay-weather-grid article{padding:11px 12px;background:#152b3c;border:1px solid #274355;border-radius:6px;min-width:0}
.replay-weather-grid small{display:block;font-size:9.5px;color:#7597ac;margin-bottom:5px}
.replay-weather-grid strong{font-size:16px;color:#d2e5f0;font-weight:500;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.replay-weather-grid strong i{font-size:12px;font-style:normal;color:#82a4b7;margin-left:3px}
.replay-tiers{list-style:none;margin:0 0 10px;padding:0;display:flex;gap:10px;flex-wrap:wrap}
.replay-tiers li{display:flex;align-items:baseline;gap:8px;padding:7px 12px;background:#14293a;border-radius:5px}
.replay-tiers small{font-size:12px;color:#7597ac}
.replay-tiers b{font-size:12px;color:#d2e5f0;font-weight:500;font-variant-numeric:tabular-nums}
.link{font:inherit;font-size:12px;color:#8fd8ea;background:transparent!important;border:0!important;
  padding:0!important;cursor:pointer;text-align:left;text-decoration:underline;text-underline-offset:3px}
.link:hover{color:#b8ecfb}

.caliber-ledger{margin:12px 0 16px;border:1px solid var(--alc-line);border-radius:var(--alc-radius);background:var(--alc-bg-1);overflow:hidden}
.ledger-hd{padding:12px 16px;border-bottom:1px solid var(--alc-line)}
.ledger-hd h3{margin:0;font-size:18px;font-weight:600;color:var(--alc-text)}
.ledger-hd p{margin:6px 0 0;font-size:12px;line-height:1.6;color:var(--alc-text-dim)}
.ledger-scroll{overflow-x:auto;scrollbar-width:thin}
.ledger-scroll::-webkit-scrollbar{height:8px}
.ledger-scroll::-webkit-scrollbar-thumb{background:rgba(120,180,220,.28);border-radius:4px}
.ledger-scroll::-webkit-scrollbar-track{background:rgba(255,255,255,.03)}
.caliber-ledger table{width:100%;min-width:1080px;border-collapse:collapse;font-size:12px}
.caliber-ledger td code{white-space:nowrap}
.caliber-ledger th,.caliber-ledger td{padding:8px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--alc-line)}
.caliber-ledger th{font-weight:600;color:var(--alc-text-dim);white-space:nowrap}
.caliber-ledger td{color:var(--alc-text)}
.caliber-ledger td code{font-size:12px;color:var(--alc-info);word-break:break-all}
.caliber-ledger tbody tr:last-child td{border-bottom:0}
</style>
