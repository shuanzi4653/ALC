<script setup>
import {computed,onBeforeUnmount,onMounted,ref} from 'vue'
import ScrollList from './ScrollList.vue'
import SituationBrief from './SituationBrief.vue'
import CityTrafficMap from '../CityTrafficMap.vue'
import WeatherSourceSwitch from './WeatherSourceSwitch.vue'
import {requestJson} from '../../api.js'
import {workspaceLabel,resetWorkspace} from '../../workspace.js'
import {isCaseMode,withCase,caseMeta} from '../../traffic/caseMode.js'
import {stageKpis,briefingTicker,clearanceReport,stageBox,wallClockText,wallDateText,releaseQueue,reasonNames,actionNames,modeNames,relativeClock,operationalTime,nonWeatherRouteRows,dispatchSummaryRows,drillable,drillTarget,SECTION_NAMES,MAP_LAYERS,FOG_SIGN_NOTE} from '../../traffic/runtime.js'

const props=defineProps({
  plan:Object,network:Object,flights:Array,weather:Object,minute:Number,playing:Boolean,
  mapFlights:{type:Array,default:null},
  city:String,selected:Object,mapStatus:String,weatherMode:String,weatherModeStatus:Object,
  layers:{type:Object,default:()=>({})},
  effective:{type:Object,default:()=>({})},
  speed:{type:Number,default:1},ready:Boolean,fullscreen:Boolean,
  radarLabel:String,
  alertFlights:{type:Array,default:()=>[]},
  aiReviewed:{type:Object,default:()=>({})},
  disposition:String,
})
const caseMode=isCaseMode()
const emit=defineEmits(['select-flight','select-city','map-status','weather-mode-change','toggle-play','toggle-layer','open-settings','export','toggle-fullscreen','update:minute','update:speed','drill','select-event','open-corridor'])
function onOpenCorridor(routeId){
  if(!routeId)return
  emit('open-corridor',routeId)
}
const sectionNames=SECTION_NAMES
const HOME_HIDDEN_LAYERS = new Set([])
const stationVisibility = computed(() => props.weather?.stationVisibility || [])

const layerDefs = computed(() => MAP_LAYERS.filter((layer) => !HOME_HIDDEN_LAYERS.has(layer.key)).map((layer) => ({
  ...layer,
  label: layer.key === 'radar' ? (props.radarLabel || layer.label)
    : (layer.key === 'fog' && stationVisibility.value.length) ? `${layer.label}·示意`
      : layer.label,
  title: (layer.key === 'radar' || layer.key === 'weather')
    ? `${layer.title}。来自气象通道，与「走廊概率」是两套读法；同时打开时以判据表为准。`
    : (layer.key === 'fog' && stationVisibility.value.length)
      ? `${layer.title}。${FOG_SIGN_NOTE}`
      : layer.title,
})))

const box=ref({width:0,height:1080,scale:0})
const wrap=ref(null)
let observer=null
function fit(){
  const el=wrap.value
  const w=el?.clientWidth||0
  const h=el?.clientHeight||0
  box.value=stageBox(w,h)
}
onMounted(()=>{
  fit()
  window.addEventListener('resize',fit)
  if(typeof ResizeObserver!=='undefined'&&wrap.value){observer=new ResizeObserver(fit);observer.observe(wrap.value)}
})

const now=ref(new Date())
let wallTimer=null
const wallTime=computed(()=>wallClockText(now.value))
const wallDate=computed(()=>wallDateText(now.value))

onMounted(()=>{wallTimer=setInterval(()=>{now.value=new Date()},1000)})
onBeforeUnmount(()=>{
  window.removeEventListener('resize',fit)
  observer?.disconnect()
  clearInterval(wallTimer)
})

const kpis=computed(()=>stageKpis(props.flights,props.weather,props.plan,{reviewed:props.aiReviewed}))
const ticker=computed(()=>briefingTicker(props.weather,props.flights))
const detourTicker=computed(()=>ticker.value.filter(item=>item.kind==='改航'))
const weatherTicker=computed(()=>ticker.value.filter(item=>item.kind!=='改航'))
const ribbon=ref([])
const ribbonTotal=ref(0)
const ribbonError=ref('')
async function loadRibbon(){
  try{
    const payload=await requestJson(withCase('/api/traffic/v2/corridors?limit=24'),{timeoutMs:15000})
    const items=payload?.items||[]
    const flyable=items.filter(row=>row.verdict!=='不可飞')
      .sort((a,b)=>(b.pMax||0)-(a.pMax||0))
    ribbon.value=flyable.slice(0,12).map(row=>({
      id:row.corridorId,name:row.name,p:row.pMax,sigma:row.sigmaMean,verdict:row.verdict,
      points:(row.samples||[]).map(s=>({lng:s.lng,lat:s.lat,p:s.p})),
    })).filter(line=>line.points.length>1)
    ribbonTotal.value=Number(payload?.total)||items.length
    ribbonError.value=''
  }catch(e){ribbonError.value=e.message||'可飞性带不可用';ribbon.value=[]}
}
onMounted(()=>{loadRibbon();loadCityWeather()})

const cityWeather=ref(null)
const cityWeatherError=ref('')
async function loadCityWeather(){
  try{
    cityWeather.value=await requestJson('/api/traffic/weather/cities',{timeoutMs:15000})
    cityWeatherError.value=''
  }catch(e){cityWeatherError.value=e.message||'城市气象不可用'}
}
const wxRows=computed(()=>{
  const rows=cityWeather.value?.cities||[]
  return rows.length?[...rows,...rows]:[]
})

const wxBox=ref(null)
const wxHeld=ref(false)
const wxHover=ref(false)
const wxSpeed=52
let wxTimer=null, wxAcc=0, wxHoverTimer=null
function wxAdvance(){
  const el=wxBox.value
  if(!el||wxHeld.value)return
  const half=el.scrollHeight/2
  if(!half)return
  const step=wxSpeed*(wxHover.value?0.15:1)/1000*32
  wxAcc+=step
  if(wxAcc<1)return
  const whole=Math.floor(wxAcc)
  wxAcc-=whole
  el.scrollTop+=whole
  if(el.scrollTop>=half)el.scrollTop-=half
}
function wxEnter(){wxHover.value=true}
function wxLeave(){wxHover.value=false}
function wxNudge(){wxHover.value=true;clearTimeout(wxHoverTimer);wxHoverTimer=setTimeout(()=>{wxHover.value=false},1600)}
onMounted(()=>{wxTimer=window.setInterval(wxAdvance,32)})
onBeforeUnmount(()=>{clearInterval(wxTimer);clearTimeout(wxHoverTimer)})

const weatherQuiet=computed(()=>{
  const rows=weatherTicker.value
  return rows.length>0&&rows.every(item=>item.tone==='calm'||item.tone==='normal'||item.tone==='muted')
})
const detourEmptyText=computed(()=>{
  const other=nonWeatherRouteRows(props.flights).length
  if(!other)return '本场景没有因气象影响改航的班次（航路未被气象推移）'
  return `本场景没有因气象影响改航的班次；另有 ${other} 班航路被作业区边界等非气象约束逼弯（不属于气象改航）`
})
const queueTicker=computed(()=>releaseQueue(props.flights,props.minute??0,30).slice(0,40).map(f=>({
  id:'Q-'+f.id,kind:'队列',tone:'normal',
  title:f.name||f.id,
  meta:relativeClock(f.departureMinute),
  body:`${modeNames[f.mode]||f.mode} · ${f.fromPad||'—'} → ${f.toPad||'—'}`,
  foot:`计划放行 ${operationalTime(f.plannedReleaseAt,f.departureMinute)}`
    +(Number(f.delayMinutes)>0?` · 延迟 ${f.delayMinutes} 分`:'')
    +(Number(f.detourMinutes)>0.01?` · 绕行 ${f.detourMinutes} 分`:''),
})))
const planFleet=computed(()=>{
  const n=Number((props.plan&&props.plan.stats&&props.plan.stats.flights)||0)
  return n||'—'
})
const clearance=computed(()=>clearanceReport(props.selected?.atcClearance))
const dispatchSummary=computed(()=>dispatchSummaryRows(props.flights,props.minute??0))
const sampleRatio=computed(()=>{
  const stats=(props.plan&&props.plan.stats)||{}
  const total=Number(stats.flights||0)
  const shown=Number(dispatchSummary.value.total||0)
  if(!total||!shown)return null
  return { total, percent: Math.round((shown/total)*1000)/10 }
})
const cityName=computed(()=>props.city?((props.network?.cities||[]).find(c=>c.id===props.city)?.name||props.city):'东北三省 · 全域')
const playbackMax=computed(()=>{
  const meta=caseMeta()
  if(meta&&Number.isFinite(meta.durationMinutes))return meta.durationMinutes
  const own=Number(props.plan?.timelineMinutes)
  if(Number.isFinite(own)&&own>0)return own
  return 480
})
const playbackMaxLabel=computed(()=>{
  const total=playbackMax.value
  return `T+${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`
})

const clockText=computed(()=>relativeClock(props.minute??0))

const toneClass=computed(()=>({good:'k-good',warn:'k-warn',cyan:'k-cyan',muted:'k-muted',normal:'k-normal'}))
const playable=computed(()=>props.ready&&props.plan?.scenario!=='unknown')

const wsLabel=ref(workspaceLabel())
const wsArmed=ref(false)
let wsTimer=null
onBeforeUnmount(()=>clearTimeout(wsTimer))
function changeWorkspace(){
  if(!wsArmed.value){
    wsArmed.value=true
    clearTimeout(wsTimer)
    wsTimer=setTimeout(()=>{wsArmed.value=false},4000)
    return
  }
  clearTimeout(wsTimer)
  resetWorkspace()
  location.reload()
}
</script>

<template>
<div ref="wrap" class="hstage-wrap">
  <div class="hstage" :style="{width:box.width+'px',height:box.height+'px',transform:`translate(-50%,-50%) scale(${box.scale})`}">
    <div class="hs-brief hs-brief-band">
    <h1 class="hs-title" data-stage-title>
      <b>运行态势</b>
      <span>{{ cityName || '东北三省 · 全域' }}</span>
      <em>{{ (minute||0)>=0 ? 'T+'+String(Math.floor((minute||0)/60)).padStart(2,'0')+':'+String(Math.round((minute||0)%60)).padStart(2,'0') : '' }}</em>
    </h1>
    <SituationBrief :city-name="cityName" :minute="minute"
                    :plan-scenario="plan?.scenario||'live'" :plan-ready="!!ready"
                    :plan-id="plan?.sessionId||''"
                    :plan-closed="typeof plan?.stats?.closed==='number'?plan.stats.closed:null"
                    :plan-stats="plan?.stats||null"
                    @open-corridor="onOpenCorridor" @open-review="emit('drill','model')" @drill="emit('drill',$event)"/>
    </div>

    <div class="hs-main">

      <div class="hs-col hs-center">
        <section class="hs-panel hs-map fam-flight">
          <div class="hs-panel-hd"><b>航路与风险区</b>
            <span class="hs-ribbon-count" v-if="ribbon.length" data-ribbon-count>
              走廊带 {{ ribbon.length }} / {{ ribbonTotal }}
            </span>
            <span>{{ mapStatus || '—' }}</span>
          </div>
          <div class="hs-layers">
            <label v-for="l in layerDefs" :key="l.key" :title="l.title">
              <input type="checkbox" :checked="!!layers[l.key]" @change="emit('toggle-layer',l.key)">
              <i :class="l.dot"></i>{{ l.label }}
            </label>
            <span class="hs-legend">走廊带 <b>蓝＝可飞 · 橙＝需谨慎</b> · 航迹 青＝车 / 紫＝机 / <b>橙＝绕行</b> · 深橙＝禁入 · 冷色＝管制 · 事件 深橙＝停止放行</span>
          </div>
          <div class="hs-panel-bd hs-map-bd">
            <CityTrafficMap :network="network" :flights="mapFlights||flights" :minute="minute" :city="city"
              :station-visibility="stationVisibility"
                            :selected="selected" :weather="weather" :playing="playing"
                            :show-car="!!layers.car" :show-delivery="!!layers.delivery"
                            :show-weather="!!layers.weather"
                            :show-wind="!!layers.wind" :show-fixed-zones="!!layers.zones"
                            :show-radar="!!layers.radar"
                            :show-fog="!!layers.fog"
                            :show-events="!!layers.events"
                            :show-observations="false"
                            :alert-flights="alertFlights" :ribbon="ribbon"
                            @select-city="emit('select-city',$event)"
                            @select-flight="emit('select-flight',$event)"
                            @select-event="emit('select-event',$event)"
                            @open-corridor="emit('open-corridor',$event)"
                            @map-status="emit('map-status',$event)"/>
          </div>
        </section>
        <section class="hs-playback">
          <button class="hs-btn primary" :disabled="!playable" @click="emit('toggle-play')">{{ playing?'Ⅱ 暂停':'▶ 推演' }}</button>
          <span class="hs-chip" data-plan-status>{{ plan?.status==='READY'?'计划就绪':(plan?.status||'等待计算') }}</span>
          <strong>{{ clockText }}</strong>
          <input aria-label="运行推演时间" type="range" min="0" :max="playbackMax" step="0.1"
                 :value="minute" :disabled="!ready" @input="emit('update:minute',Number($event.target.value))">
          <span class="hs-tp">{{ playbackMaxLabel }}</span>
          <select aria-label="推演速度" :value="speed" @change="emit('update:speed',Number($event.target.value))">
            <option :value=".25">15 倍速</option><option :value="1">60 倍速</option><option :value="5">300 倍速</option>
          </select>
        </section>
      </div>

      <div class="hs-col hs-col-right">
        <section class="hs-panel fam-flight">
          <div class="hs-panel-hd"><b>放行许可</b><span>{{ selected?(selected.name||selected.id):'全网络调度总结' }}</span></div>
          <div class="hs-panel-bd">
            <template v-if="clearance.length">
              <pre class="hs-report"><code>{{ clearance.join('\n') }}</code></pre>
              <p class="hs-hint hs-hint-inline">取自计划字段，不重算；「未指派」＝计划中确无该项。</p>
            </template>
            <template v-else>
              <div class="hs-sum" role="status" aria-label="本页抽样视图调度总结">
                <div v-for="r in dispatchSummary.rows" :key="r.key" class="hs-sum-row" :class="'k-'+r.tone">
                  <span class="hs-sum-lab">{{ r.label }}</span>
                  <b class="hs-sum-val">{{ r.value }}<i>{{ r.unit }}</i></b>
                  <span class="hs-sum-note">{{ r.note }}</span>
                </div>
                <p class="hs-sum-total">四态合计 {{ dispatchSummary.total }} 班 · {{ clockText }}<template v-if="sampleRatio"> · 抽样 {{ dispatchSummary.total }} / 全量 {{ sampleRatio.total }}（{{ sampleRatio.percent }}%）</template></p>
              </div>
              <p class="hs-hint hs-hint-inline">{{ dispatchSummary.note }}</p>
            </template>
          </div>
        </section>

      <section class="hs-panel fam-wx" v-if="cityWeather?.available!==false" data-city-weather>
        <div class="hs-panel-hd">
          <b>城市气象</b>
          <span>{{ cityWeather?.cities?.length || 0 }} 城 · {{ cityWeather?.provider || '公开来源' }}</span>
          <button class="wx-toggle" type="button" data-wx-toggle
                  :aria-pressed="wxHeld" @click="wxHeld=!wxHeld"
                  :title="wxHeld?'继续自动滚动':'暂停自动滚动（也可以直接滚轮翻看）'">
            {{ wxHeld ? '▶ 继续滚动' : 'Ⅱ 暂停' }}
          </button>
        </div>
        <div class="wx-ticker" ref="wxBox" @mouseenter="wxEnter" @mouseleave="wxLeave"
             @wheel.passive="wxNudge" @touchmove.passive="wxNudge">
          <div class="wx-track">
            <div v-for="(row,index) in wxRows" :key="row.id+'-'+index" class="wx-row"
                 :title="`${row.name} · ${row.condition} · 气温 ${row.tempC} ℃ · 体感 ${row.feelsC ?? '—'} ℃ · ${row.windDirText || '风向 —'} ${row.windMs ?? '—'} m/s · 湿度 ${row.humidity ?? '—'}%`">
              <span class="wx-ico" aria-hidden="true">{{ row.icon }}</span>
              <span class="wx-city">{{ row.name }}</span>
              <span class="wx-cond">{{ row.condition }}</span>
              <b class="wx-temp">{{ row.tempC }}<i>℃</i></b>
              <span class="wx-wind">
                <b>{{ row.windDirText || '—' }}</b>{{ row.windMs == null ? '' : row.windMs }}<i>m/s</i>
              </span>
            </div>
          </div>
        </div>
        <p class="hs-hint hs-hint-inline wx-note">
          公开模式当前值（{{ cityWeather?.retrievedAt ? cityWeather.retrievedAt.slice(11,16)+'Z' : '—' }}）· <b>不参与走廊判据</b>
        </p>
      </section>
      </div>
    </div>

    <footer class="hs-foot">
      <template v-if="selected">
        <span class="hs-f-chip">{{ modeNames[selected.mode]||selected.mode }} · {{ selected.id }}</span>
        <span class="hs-f-item"><small>处置</small><b>{{ actionNames[selected.separationAction]||'—' }}</b></span>
        <span class="hs-f-item"><small>原因</small><b>{{ reasonNames[selected.reason]||selected.reason||'—' }}</b></span>
        <span class="hs-f-item"><small>申请 → 计划</small><b>{{ operationalTime(selected.requestedDepartureAt,selected.requestedDepartureMinute) }} → {{ operationalTime(selected.plannedReleaseAt,selected.departureMinute) }}</b></span>
        <span class="hs-f-item"><small>延误 / 绕行</small><b>{{ selected.delayMinutes??0 }} / {{ selected.detourMinutes??0 }} 分</b></span>
      </template>
      <span v-else class="hs-f-idle">交通为模拟运行；城市底图来自开放地图数据。系统派生的飞行风险区不等同于官方空域管制命令，均不构成飞行许可结论。</span>
      <span class="hs-f-tail">
        <span class="hs-f-item hs-f-right" v-if="disposition && !caseMode"><small>本轮处置（延迟优先 · 全量 {{ planFleet }} 班）</small><b>{{ disposition }}</b></span>
        <span class="hs-f-item hs-f-right" v-else-if="caseMode" data-case-disposition><small>本轮处置</small><b>回放不重跑调度 · 无处置数字</b></span>
      <span class="hs-f-item hs-f-right" v-if="caseMode" data-case-live-badge>
        <small>本页时间轴与班次</small><b>实时推演 · 与左侧回放观测无关</b></span>
        <span class="hs-f-beian">
          <a class="hs-beian-link" href="https://beian.miit.gov.cn/" target="_blank"
             rel="noopener noreferrer"
             title="工业和信息化部政务服务平台 · ICP 备案查询">蜀ICP备2026061491号-1</a>
          <span class="hs-beian-sep" aria-hidden="true"></span>
          <a class="hs-beian-link hs-beian-police"
             href="https://beian.mps.gov.cn/#/query/webSearch?code=51010602003735"
             target="_blank" rel="noreferrer"
             title="全国互联网安全管理服务平台 · 公安联网备案查询"><img
               src="/assets/beian.png" alt="" width="14" height="14"
               loading="lazy" decoding="async">川公网安备51010602003735号</a>
        </span>
      </span>
    </footer>
  </div>
</div>
</template>

<style scoped>
.hs-brief-band{display:flex;flex-direction:column;gap:6px;min-height:0}
.hs-title{display:flex;align-items:baseline;gap:10px;margin:0;padding:0 2px 6px;
  font-size:22px;font-weight:600;color:#dcebff;letter-spacing:1px}
.hs-title b{font-weight:700;color:#eaf5ff}
.hs-title span{font-size:15px;font-weight:400;color:#8fb4de}
.hs-title em{font-size:12px;font-style:normal;color:#6f95c4;margin-left:auto;letter-spacing:1px}
.hstage-wrap{position:relative;flex:1;min-height:0;width:100%;overflow:hidden;background:#050b16}
.hstage{position:absolute;left:50%;top:50%;transform-origin:center center;
  display:grid;gap:10px;padding:10px;grid-template-rows:auto minmax(0,1fr) 46px}
.hs-top{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;min-width:0}
.hs-top-l,.hs-top-r{display:flex;align-items:center;gap:9px;min-width:0}
.hs-top-r{justify-content:flex-end}
.hs-top-c{text-align:center;min-width:0}
.hs-top-c h1{font-size:23px;font-weight:800;letter-spacing:5px;white-space:nowrap;
  background:linear-gradient(180deg,#fff 20%,#8ec4ff 90%);-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;filter:drop-shadow(0 0 12px rgba(61,139,255,.5))}
.hs-top-c p{font-size:12px;color:#6f95c4;letter-spacing:2px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-when{display:flex;flex-direction:column;align-items:flex-start;gap:1px;flex:none;
  padding:2px 10px;border-radius:7px;border:1px solid rgba(64,140,230,.24);
  background:linear-gradient(165deg,rgba(17,38,72,.7),rgba(9,22,44,.7))}
.hs-when i{font-size:12px;font-style:normal;color:#6f95c4;letter-spacing:2px}
.hs-when b{font-size:18px;font-weight:700;line-height:1.1;color:#cfe6f2;font-variant-numeric:tabular-nums}
.hs-when em{font-size:12px;font-style:normal;color:#6f95c4;white-space:nowrap}
.hs-when.sim{border-color:rgba(39,224,255,.34)}
.hs-when.sim b{color:#a9f0ff}
.hs-chip{font-size:12px;color:#8fb4de;border:1px solid rgba(64,140,230,.28);border-radius:11px;padding:2px 9px;white-space:nowrap}
.hs-chip.live{color:#7ee2a8;border-color:rgba(46,139,87,.5)}
.hs-chip.ws{border-style:dashed;font-variant-numeric:tabular-nums}
.hs-btn{background:rgba(61,139,255,.16);border:1px solid rgba(80,158,255,.45);color:#cfe6ff;border-radius:6px;
  padding:6px 13px;cursor:pointer;font-size:12px;white-space:nowrap}
.hs-btn:hover{background:rgba(61,139,255,.38);box-shadow:0 0 10px rgba(61,139,255,.35)}
.hs-btn:disabled{opacity:.45;cursor:not-allowed}
.hs-btn.primary{background:linear-gradient(180deg,#3d84e0,#2b5fa8);border-color:#5aa4ff;color:#fff}
.hs-acts{display:flex;gap:5px;flex:none}
.hs-btn.sm{padding:4px 8px;font-size:12px}
.hs-btn.sm.armed{background:linear-gradient(180deg,#3d84e0,#2b5fa8);border-color:#5aa4ff;color:#fff}

.hs-kpis{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px}.hs-kpi-band{display:grid;grid-template-rows:minmax(0,1fr) auto;min-height:0}
.hs-kpi{position:relative;display:flex;flex-direction:column;justify-content:center;gap:3px;
  padding:10px 12px;border-radius:9px;min-width:0;
  background:linear-gradient(165deg,rgba(17,38,72,.9),rgba(9,22,44,.9));
  border:1px solid rgba(64,140,230,.26);border-left-width:3px;overflow:hidden}
.hs-kpi-lab{font-size:10.5px;color:#87afd9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-kpi-val{font-size:32px;font-weight:800;line-height:1.05;color:#eaf5ff;font-variant-numeric:tabular-nums}
.hs-kpi-val i{font-size:12px;font-weight:400;color:#7ba0cc;margin-left:3px;font-style:normal}
.hs-kpi-note{font-size:11px;color:#6f95c4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-kpi.k-normal{border-left-color:#3d8bff}.hs-kpi.k-good{border-left-color:#2e8b57}
.hs-kpi.k-good .hs-kpi-val{color:#8ff0bb}
.hs-kpi.k-warn{border-left-color:#d98a2b}.hs-kpi.k-warn .hs-kpi-val{color:#ffce8a}
.hs-kpi.k-cyan{border-left-color:#27e0ff}.hs-kpi.k-cyan .hs-kpi-val{color:#a9f0ff}
.hs-kpi.k-bad{border-left-color:#e08a45}.hs-kpi.k-bad .hs-kpi-val{color:#ffc98a}
.hs-kpi.k-muted{border-left-color:#3b5068}.hs-kpi.k-muted .hs-kpi-val{color:#8ea8c4}

.hs-kpi-val.hs-kpi-drill{font:inherit;font-size:32px;font-weight:800;line-height:1.05;
  font-variant-numeric:tabular-nums;text-align:left;padding:0;margin:0;border:0;
  background:transparent;color:inherit;cursor:pointer;
  border-bottom:1px dashed rgba(120,180,255,.42);align-self:flex-start}
.hs-kpi-val.hs-kpi-drill:hover{border-bottom-color:#59dffc;text-shadow:0 0 10px rgba(89,223,252,.55)}
.hs-kpi-val.hs-kpi-drill:focus-visible{outline:1px solid #59dffc;outline-offset:3px}
.hs-drill-note{margin-top:0;font-size:9.5px;color:#5f83ad;line-height:1.6;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-drill-note b{color:#8fb6d0;font-weight:500}

.hs-main{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:10px;min-height:0}
.hs-col{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,1fr);gap:10px;min-height:0}
.hs-col-right{grid-template-rows:auto minmax(0,1fr)}
.hs-center{grid-template-rows:minmax(0,1fr) 44px}
.hs-panel{position:relative;display:flex;flex-direction:column;min-height:0;overflow:hidden;border-radius:10px;
  background:linear-gradient(165deg,rgba(17,38,72,.9) 0%,rgba(9,22,44,.9) 55%,rgba(8,18,38,.92) 100%);
  border:1px solid rgba(64,140,230,.26);
  box-shadow:inset 0 1px 0 rgba(120,180,255,.1),0 4px 18px rgba(0,0,0,.35)}
.hs-panel-hd{display:flex;align-items:center;justify-content:space-between;gap:10px;flex:none;
  padding:8px 13px;font-size:13px;color:#bfe0ff;letter-spacing:1px;
  background:linear-gradient(90deg,rgba(61,139,255,.1),transparent 55%);
  border-bottom:1px solid rgba(61,139,255,.22)}
.hs-panel-hd b{font-weight:700;display:flex;align-items:center;gap:7px}
.hs-panel-hd b::before{content:"";width:4px;height:14px;border-radius:2px;
  background:linear-gradient(180deg,#3d8bff,#27e0ff);box-shadow:0 0 8px rgba(61,170,255,.9)}
.hs-panel.fam-flight .hs-panel-hd b::before{background:linear-gradient(180deg,#3d8bff,#27e0ff);box-shadow:0 0 8px rgba(61,170,255,.9)}
.hs-panel.fam-wx .hs-panel-hd b::before{background:linear-gradient(180deg,#f0b357,#e08a45);box-shadow:0 0 8px rgba(224,140,60,.9)}
.hs-panel.fam-wx .hs-panel-hd{background:linear-gradient(90deg,rgba(224,140,60,.10),transparent 55%);border-bottom-color:rgba(224,140,60,.24)}
.hs-panel-hd span{font-size:12px;color:#6f95c4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-panel-bd{flex:1;min-height:0;display:flex;flex-direction:column;padding:10px 13px;overflow:hidden}

.hs-hint{font-size:12px;color:#7fa6d2;line-height:1.5;margin-top:auto;padding-top:6px}
.hs-hint-inline{margin-top:9px;padding-top:0}
.hs-sum{display:grid;gap:4px}
.hs-sum-row{display:grid;grid-template-columns:54px 80px minmax(0,1fr);align-items:baseline;gap:8px;
  padding:4px 9px;border-radius:6px;border-left:3px solid #3b5068;background:rgba(9,22,44,.5)}
.hs-sum-row.k-cyan{border-left-color:#27e0ff}
.hs-sum-row.k-good{border-left-color:#2e8b57}
.hs-sum-row.k-normal{border-left-color:#3d8bff}
.hs-sum-lab{font-size:10.5px;color:#87afd9;white-space:nowrap}
.hs-sum-val{font-size:17px;font-weight:700;line-height:1.15;color:#eaf5ff;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.hs-sum-val i{font-size:9.5px;font-weight:400;color:#7ba0cc;font-style:normal;margin-left:3px}
.hs-sum-row.k-cyan .hs-sum-val{color:#a9f0ff}
.hs-sum-row.k-good .hs-sum-val{color:#8ff0bb}
.hs-sum-note{font-size:9.5px;color:#6f95c4;line-height:1.5;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.hs-sum-total{margin:5px 0 0;font-size:12px;color:#7ba0cc;font-variant-numeric:tabular-nums}

.hs-report{margin:0;font-size:12px;line-height:1.75;color:#cfe6f2;white-space:pre-wrap;overflow-wrap:anywhere;
  background:#0b1b30;border:1px solid rgba(64,140,230,.24);border-left:3px solid #27e0ff;border-radius:0 6px 6px 0;
  padding:8px 11px;font-family:"Cascadia Mono","Consolas","Courier New",monospace;
  max-height:240px;overflow:auto}
.hs-map{min-height:0}
.hs-map-bd{padding:0;min-height:0}
.hs-layers{display:flex;align-items:center;gap:12px;flex-wrap:nowrap;flex:none;
  overflow-x:auto;overflow-y:hidden;scrollbar-width:thin;
  scrollbar-color:rgba(255,255,255,.22) transparent;
  padding:6px 13px;border-bottom:1px solid rgba(61,139,255,.16);background:rgba(9,22,44,.5)}
.hs-layers::-webkit-scrollbar{height:4px}
.hs-layers::-webkit-scrollbar-thumb{background:rgba(255,255,255,.22);border-radius:2px}
.hs-layers::-webkit-scrollbar-track{background:transparent}
.hs-layers label{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:#a9c8ea;cursor:pointer;white-space:nowrap}
.hs-layers input{accent-color:#3d8bff;cursor:pointer;margin:0}
.hs-layers i{width:7px;height:7px;border-radius:50%;display:inline-block;flex:none}
.hs-layers .d-car{background:#27e0ff;box-shadow:0 0 6px rgba(39,224,255,.8)}
.hs-layers .d-del{background:#f0b357;box-shadow:0 0 6px rgba(240,179,87,.8)}
.hs-layers .d-wx{background:#e08a45;box-shadow:0 0 6px rgba(224,138,69,.8)}
.hs-layers .d-wind{background:#7fb2e8}
.hs-layers .d-radar{background:#e08a45;box-shadow:0 0 6px rgba(224,138,69,.8)}
.hs-layers .d-fog{background:#8d94a3;box-shadow:0 0 6px rgba(141,148,163,.75)}
.hs-layers .d-zone{background:#8f7fd6}
.hs-layers .d-event{background:transparent;border:1.5px solid #e08a45;box-shadow:0 0 6px rgba(224,138,69,.9)}
.hs-layers .d-obs{background:#bfeaf6;box-shadow:0 0 6px rgba(191,234,246,.75)}
.hs-ribbon-count{font-size:11.5px;color:#9fc4dd;white-space:nowrap;
  padding:1px 7px;border-radius:3px;background:rgba(76,141,255,.12);border:1px solid rgba(76,141,255,.28)}
.hs-legend{font-size:11px;color:#6f95c4;margin-left:auto;white-space:normal;overflow:visible;
  text-overflow:clip;line-height:1.5;flex:1 1 auto;min-width:0}
.hs-playback{display:flex;align-items:center;gap:11px;padding:0 14px;border-radius:9px;flex:none;
  background:linear-gradient(165deg,rgba(17,38,72,.9),rgba(9,22,44,.9));border:1px solid rgba(64,140,230,.26)}
.hs-playback strong{font-size:14px;color:#bfe0ff;font-variant-numeric:tabular-nums;flex:none}
.hs-playback input[type=range]{flex:1;min-width:0;accent-color:#3d8bff}
.hs-playback .hs-tp{font-size:12px;color:#6f95c4;flex:none}
.hs-playback select{background:rgba(10,25,48,.85);border:1px solid rgba(64,140,230,.35);color:#cfe6ff;
  border-radius:5px;padding:4px 6px;font-size:12px;outline:none}

.hs-tick{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;
  padding:6px 9px;margin-bottom:5px;border-radius:0 6px 6px 0;border-left:3px solid #3d8bff;
  background:linear-gradient(90deg,rgba(28,58,104,.5),rgba(16,36,68,.28))}
.hs-tick b{font-size:11.5px;color:#e6f2fd;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hs-tick em{font-size:12px;font-style:normal;color:#8fb4de;white-space:nowrap}
.hs-tick span{grid-column:1/3;font-size:10.5px;color:#a9c8ea;line-height:1.6;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hs-tick small{grid-column:1/3;font-size:12px;color:#6f95c4}
.hs-tick.t-alert{border-left-color:#e08a45}
.hs-tick.t-warn{border-left-color:#d98a2b}
.hs-tick.t-cyan{border-left-color:#27e0ff}
.hs-tick.t-normal{border-left-color:#3d8bff}
.hs-tick.t-calm{border-left-color:#8a6f3a}

.hs-foot{display:flex;align-items:center;gap:16px;padding:0 14px;border-radius:9px;overflow:hidden;
  background:linear-gradient(165deg,rgba(17,38,72,.9),rgba(9,22,44,.9));border:1px solid rgba(64,140,230,.26)}
.hs-f-chip{font-size:12px;color:#a9f0ff;border:1px solid rgba(39,224,255,.4);border-radius:5px;padding:2px 9px;flex:none}
.hs-f-item{display:flex;flex-direction:column;gap:1px;min-width:0}
.hs-f-item small{font-size:12px;color:#6f95c4}
.hs-f-item b{font-size:12px;color:#dbeaf8;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-f-tail{margin-left:auto;display:flex;align-items:center;gap:16px;flex:none;min-width:0}
.hs-f-right{text-align:right;align-items:flex-end;flex:0 1 auto}
.hs-f-idle{font-size:12px;color:#6f95c4;line-height:1.6;min-width:0}
.hs-f-beian{display:flex;align-items:center;gap:7px;flex:none;font-size:12px;line-height:1}
.hs-beian-link{display:inline-flex;align-items:center;gap:4px;color:#7fa3cc;text-decoration:none;
  white-space:nowrap;transition:color .15s}
.hs-beian-link:hover{color:#cfe3f8}
.hs-beian-link img{display:block;width:14px;height:14px;flex:none}
.hs-beian-sep{width:1px;height:11px;background:rgba(120,160,210,.35);flex:none;margin:0 1px}
.hs-model-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.hs-model-links button{display:flex;align-items:baseline;gap:8px;font-size:10.5px;color:#9dc0d4;
  background:#122636;border:1px solid #2c4a5e;border-radius:5px;padding:6px 10px;cursor:pointer;
  transition:border-color .15s,color .15s}
.hs-model-links button:hover{border-color:#65cce5;color:#e9fbff}
.hs-model-links button small{font-size:9.5px;color:#6b8aa0}

.hs-brief{min-height:0;overflow:hidden}
.hs-brief :deep(.brief-conclusion){min-height:64px}
.hs-brief :deep(.brief){margin:0}

.hs-quiet{font-size:12px;line-height:1.6;color:var(--alc-text-dim);padding:8px 2px;margin:0}
.hs-quiet small{display:block;font-size:12px;color:var(--alc-text-mute);margin-top:2px}

.hs-panel.fam-wx{padding:0;min-height:0;align-self:stretch;height:100%}
.hs-panel.fam-wx>.hs-panel-hd{flex:none}
.wx-toggle{flex:none;margin-left:auto;font-size:10.5px;padding:1px 7px;border-radius:4px;cursor:pointer;
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.16);color:#a9c3d3}
.wx-toggle:hover{background:rgba(89,223,252,.14);border-color:rgba(89,223,252,.4);color:#e6f7ff}
.wx-ticker{position:relative;flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;
  scrollbar-width:thin;overscroll-behavior:contain;
  -webkit-mask-image:linear-gradient(180deg,transparent 0,#000 8%,#000 92%,transparent 100%);
  mask-image:linear-gradient(180deg,transparent 0,#000 8%,#000 92%,transparent 100%)}
.wx-ticker::-webkit-scrollbar{width:6px}
.wx-ticker::-webkit-scrollbar-thumb{background:rgba(120,180,220,.26);border-radius:3px}
.wx-track{display:flex;flex-direction:column}
.wx-row{display:grid;grid-template-columns:18px minmax(0,1fr) auto 52px 84px;gap:8px;align-items:baseline;
  padding:6px 12px;border-bottom:1px solid rgba(255,255,255,.045);font-size:13px;line-height:1.5}
.wx-row:nth-child(odd){background:rgba(255,255,255,.016)}
.wx-ico{font-size:12px;text-align:center;filter:saturate(.8)}
.wx-city{color:#d6e9f7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wx-cond{color:#96b9cf;font-size:12px;white-space:nowrap}
.wx-temp{color:#eaf8ff;font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.wx-temp i{font-style:normal;font-size:10.5px;color:#7fa5bd;margin-left:1px}
.wx-wind{color:#8fb3c9;font-size:11.5px;white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}
.wx-wind b{color:#b7d3e4;font-weight:500;margin-right:4px}
.wx-wind i{font-style:normal;font-size:10px;color:#6f92a8;margin-left:1px}
.wx-note{padding:5px 12px 7px;margin:0;font-size:10.5px;line-height:1.5;color:#6f92a8;
  border-top:1px solid rgba(255,255,255,.05);flex:none}

@media (min-width:1800px){
  .hs-main{grid-template-columns:minmax(0,1fr) 420px}
  .hs-col-right{grid-template-rows:auto minmax(0,1fr)}
}
@media (max-width:1500px){
  .hs-main{grid-template-columns:minmax(0,1fr) 340px}
}
@media (max-width:1280px){
  .hs-main{grid-template-columns:minmax(0,1fr) 300px}
  .hs-kpis{grid-template-columns:repeat(4,minmax(0,1fr))}
  .hs-kpis>:nth-child(5){grid-column:span 2}
}
@media (max-width:1080px){
  .hs-main{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(320px,1fr) auto}
  .hs-col-right{grid-template-rows:auto auto;max-height:none}
  .hs-map-bd{min-height:340px}
  .hs-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
  .hs-kpis>:nth-child(5){grid-column:span 1}
  .wx-ticker{max-height:260px}
}
@media (max-width:820px){
  .hs-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .hs-top{grid-template-columns:1fr;justify-items:start;gap:6px}
}
</style>
