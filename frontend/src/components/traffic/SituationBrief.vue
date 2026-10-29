<script setup>
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'
import {pct,riskTone} from '../../traffic/runtime.js'
import {activeCase,caseQuery,caseMeta} from '../../traffic/caseMode.js'

const props=defineProps({
  cityName:{type:String,default:'全域'},
  planScenario:{type:String,default:'live'},
  planReady:{type:Boolean,default:false},
  planId:{type:String,default:''},
  planClosed:{type:Number,default:null},
  planStats:{type:Object,default:null},
  minute:{type:Number,default:0},
})
const emit=defineEmits(['open-corridor','open-review','drill'])
const data=ref(null),error=ref(''),loading=ref(true),expanded=ref(false)
let timer=null,disposed=false

function minuteQuery(){
  if(!activeCase()||!Number.isFinite(props.minute))return ''
  return `&minute=${Math.round(props.minute)}`
}

async function load(){
  try{
    const scenario=props.planScenario||'live'
    const payload=await requestJson(`/api/traffic/v2/overview?seed=42&scenario=${encodeURIComponent(scenario)}${caseQuery()}${minuteQuery()}`,{timeoutMs:12000})
    if(disposed)return
    data.value=payload
    error.value=''
  }catch(e){
    if(!disposed)error.value=e.message||'态势数据加载失败'
  }finally{
    if(!disposed)loading.value=false
  }
}
watch(()=>props.planScenario,()=>{loading.value=true;load()})
watch(()=>props.planId,(value,prev)=>{
  if(!prev||!value||value===prev)return
  loading.value=true;load()
})
let minuteTimer=null
watch(()=>props.minute,(value,prev)=>{
  if(!activeCase()||Math.round(value)===Math.round(prev||0))return
  clearTimeout(minuteTimer)
  minuteTimer=setTimeout(load,300)
})
onMounted(()=>{load();timer=setInterval(load,300000)})
onBeforeUnmount(()=>{disposed=true;clearInterval(timer);clearTimeout(minuteTimer)})

const conclusion=computed(()=>data.value?.conclusion||null)
const tone=computed(()=>conclusion.value?.tone||'unknown')
const caseLabel=computed(()=>caseMeta()?.label||'')
const caseNote=computed(()=>caseMeta()?.note||'')
const caseFrames=computed(()=>data.value?.case?.frames??null)
const pendingCount=computed(()=>{
  const kpi=(data.value?.kpis||[]).find(k=>k.key==='pending')
  const value=kpi?.value
  return typeof value==='number'&&value>0?value:0
})
const scenarioLabel=computed(()=>({clear:'无气象声明',live:'公开天气驱动',unknown:'气象中断'})[props.planScenario]||'—')
const pendingMode=computed(()=>{
  if(loading.value||error.value)return false
  if(props.planId&&!props.planReady)return true
  if(data.value&&(data.value.scenario||'live')!==(props.planScenario||'live'))return true
  return false
})
const kpis=computed(()=>(data.value?.kpis||[]).filter(k=>k.key!=='ai'))
const pendingNote=computed(()=>{
  const detail=data.value?.kpiDetail||{}
  const text=String(detail.definitionPending||'').trim()
  return text
})

const coverageText=computed(()=>{
  const kpi=(data.value?.kpis||[]).find(k=>k.key==='ai')
  if(!kpi||typeof kpi.value!=='number')return ''
  return `${kpi.value}${kpi.unit||'%'}`
})
const scopeNote=computed(()=>{
  if(caseLabel.value||!data.value)return ''
  const s=props.planStats
  if(!s||typeof s.flights!=='number')return ''
  const closed=Number(s.closed)||0
  const weather=Number(s.closedByWeather)||0
  const tail=closed?`停止放行 ${closed} 班（气象 ${weather}）`:'无停止放行'
  const mech=weather>0?' · 走廊概率不参与排程':''
  return `走廊判据（三站 METAR）· 班次处置（全量 ${s.flights} 班，${tail}）`+mech
})
const obsClock=computed(()=>{
  const raw=String(observation.value?.observedAt||'')
  const m=raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m?`${m[2]}-${m[3]} ${m[4]}:${m[5]}Z`:raw||'—'
})

const observation=computed(()=>data.value?.observation||null)
const stations=computed(()=>observation.value?.stations||[])
const availableCount=computed(()=>stations.value.filter(s=>s.available).length)
const stationCount=computed(()=>stations.value.length)
const stationStampGap=computed(()=>{
  const list=(observation.value?.stations||[]).filter(s=>s.available&&s.observedAt)
  if(list.length<2)return ''
  if(new Set(list.map(s=>String(s.observedAt))).size===1)return ''
  return list.map(s=>`${s.station} ${String(s.observedAt).slice(11,16)}Z`).join(' · ')
})
const observationDown=computed(()=>data.value&&observation.value&&observation.value.available===false)

function kpiText(kpi){
  if(kpi.value===null||kpi.value===undefined)return '—'
  return kpi.value
}
function directionMark(kpi){
  if(kpi.direction==='up')return '▲'
  if(kpi.direction==='down')return '▼'
  return ''
}
function directionNote(kpi){
  if(kpi.baseline)return kpi.baseline
  return kpi.baselineReason||''
}
</script>

<template>
<section class="brief" data-brief>
  <p class="brief-case" v-if="caseLabel" data-case-banner>
    <b>历史回放 · 非实时</b>
    <span>{{ caseLabel }}</span>
    <span class="brief-case-note">{{ caseNote }}</span>
    <span class="brief-case-note" v-if="caseFrames">{{ caseFrames }} 帧 · 逐时</span>
    <span class="brief-case-bound" data-case-boundary>只回放观测与判据，<b>不重跑调度</b>；航班状态仍为实时推演</span>
    <a class="brief-case-exit" href="./">回到实时</a>
  </p>
  <div class="brief-conclusion" :class="'tone-'+tone" role="status" aria-live="polite">
    <span class="brief-bar" aria-hidden="true"></span>
    <div class="brief-text">
      <p v-if="loading" class="brief-loading">正在读取机场站 METAR 观测…</p>
      <p v-else-if="error" class="brief-error">态势数据加载失败 · {{ error }}
        <button @click="load">重试</button>
      </p>
      <p v-else-if="pendingMode" class="brief-pending">
        <span aria-hidden="true" class="brief-spinner"></span>
        正在按「{{ scenarioLabel }}」重算 · 约 20 秒
        <span class="brief-bar-track" aria-hidden="true"><i></i></span>
      </p>
      <p v-else-if="observationDown" class="brief-error">
        METAR 观测暂不可用，本次不出结论。
        <button @click="load">重试</button>
      </p>
      <p v-else-if="conclusion" class="brief-sentence">{{ conclusion.text }}</p>
      <p v-else class="brief-loading">暂无结论</p>
      <p class="brief-sub" v-if="!loading&&!error">
        <span v-if="pendingMode">正在按当前情景重算 · 约 40 秒后自动替换</span>
        <template v-else>
          <span v-if="observation">观测 {{ obsClock }} · {{ availableCount }}/{{ stationCount }} 站</span>
          <span v-if="stationStampGap" class="brief-caveat" data-station-stamp-gap
                :title="`各站报文时刻不一致：${stationStampGap}。帧时刻取最新一站，其余站仍是上一期报文`">· 逐站时刻 {{ stationStampGap }}</span>
          <span v-if="coverageText" class="brief-caveat" data-kpi-coverage
                :title="'模型覆盖：本帧每一条载客走廊都有概率输出'">· 覆盖 {{ coverageText }}</span>
          <span v-if="observation?.dataType">· {{ observation.dataType==='STATION_OBSERVATION_METAR'?'METAR 实测':'来源未声明' }}</span>
          <span v-if="data?.weatherChannel?.mode==='virtual'" class="brief-channel" :title="data.weatherChannel.note">· 模拟通道</span>
          <span v-if="planScenario!=='live'&&planClosed!==null" class="brief-marker">· 本情景停止放行 {{ planClosed }} 班</span>
          <span class="brief-caveat" :title="`仅 ${stationCount} 个机场站；站距越远误差越大，走廊值由插值得到`">· 插值误差带已标注</span>
        </template>
      </p>
    </div>
    <div class="brief-actions">
      <button v-if="pendingCount" class="primary" data-act-alerts @click="emit('drill','alerts')">
        处置这 {{ pendingCount }} 条 →
      </button>
      <button v-else-if="conclusion?.corridorId" class="primary" @click="emit('open-corridor',conclusion.corridorId)">
        查看 {{ conclusion.corridorId }} →
      </button>
      <button class="ghost" @click="emit('open-review')">逐条推演 →</button>
    </div>
  </div>

  <div class="brief-kpis" v-if="kpis.length">
    <article v-for="kpi in kpis" :key="kpi.key" class="brief-kpi" :class="'tone-'+kpi.tone"
             :title="directionNote(kpi) || '无基线'">
      <div class="brief-kpi-top">
        <button type="button" class="brief-kpi-value alc-num" data-kpi-drill
                :data-drill-key="kpi.key" :title="'下钻到承载这个数的分节'"
                @click="emit('drill',kpi.key)">{{ kpiText(kpi) }}<i v-if="kpi.value!==null">{{ kpi.unit }}</i></button>
        <span class="brief-kpi-mark" v-if="directionMark(kpi)">{{ directionMark(kpi) }}</span>
      </div>
      <div class="brief-kpi-label">{{ kpi.label }}<em v-if="kpi.scope==='offline'" class="brief-kpi-scope">离线</em></div>
      <span class="sr-only">{{ directionNote(kpi) || '无基线' }}</span>
    </article>
  </div>
  <p class="brief-kpi-note" v-if="pendingNote" data-kpi-note>{{ pendingNote }}</p>
  <p class="brief-kpi-note brief-scope-note" v-if="scopeNote" data-brief-scope>{{ scopeNote }}</p>
</section>
</template>

<style scoped>
.brief-kpi-note{margin:6px 0 0;padding-left:2px;font-size:11px;line-height:1.5;
  color:var(--alc-text-dim);letter-spacing:.1px}

.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.brief{display:flex;flex-direction:column;gap:12px;margin:12px 0 0}
.brief-case{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding:8px 14px;border-radius:6px;background:rgba(194,65,12,.10);border:1px solid rgba(194,65,12,.35);font-size:12px;color:var(--alc-text)}
.brief-case b{font-size:12px;color:#C2410C;letter-spacing:.5px}
.brief-case-note{color:var(--alc-text-dim)}
.brief-channel{color:#C2410C;border-bottom:1px dashed rgba(194,65,12,.55)}
.brief-case-bound{flex-basis:100%;font-size:11px;color:var(--alc-text-dim);border-top:1px dashed rgba(194,65,12,.30);padding-top:6px;margin-top:2px}
.brief-case-bound b{color:#C2410C;font-size:11px}
.brief-case-exit{margin-left:auto;color:var(--alc-info);text-decoration:none;border-bottom:1px dashed var(--alc-info)}
.brief-case-exit:hover{color:var(--alc-text)}
.brief-conclusion{position:relative;display:flex;align-items:center;gap:16px;min-height:64px;padding:12px 20px 12px 24px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius)}
.brief-bar{position:absolute;left:0;top:0;bottom:0;width:4px;border-radius:6px 0 0 6px;background:var(--alc-neutral)}
.tone-danger .brief-bar{background:var(--alc-danger)}
.tone-watch .brief-bar{background:var(--alc-watch)}
.tone-ok .brief-bar{background:var(--alc-ok)}
.tone-info .brief-bar{background:var(--alc-info)}
.tone-unknown .brief-bar{background:var(--alc-neutral)}
.brief-text{flex:1;min-width:0;overflow:visible}
.brief-sentence{font-size:16px;line-height:1.5;color:var(--alc-text);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  overflow-wrap:anywhere}
.brief-sub{margin-top:4px;font-size:12px;color:var(--alc-text-dim);display:flex;gap:8px;flex-wrap:wrap}
.brief-caveat{color:var(--alc-text-mute)}
.brief-loading,.brief-error{font-size:13px;color:var(--alc-text-dim)}
.brief-pending{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--alc-text-dim)}
.brief-spinner{width:10px;height:10px;border-radius:50%;border:2px solid var(--alc-line);border-top-color:var(--alc-info);animation:brief-spin .9s linear infinite;flex:0 0 auto}
@keyframes brief-spin{to{transform:rotate(360deg)}}
.brief-bar-track{position:relative;display:inline-block;width:96px;height:3px;border-radius:2px;background:var(--alc-line);overflow:hidden}
.brief-bar-track i{position:absolute;inset:0;width:38%;border-radius:2px;background:var(--alc-info);animation:brief-slide 1.4s var(--alc-ease) infinite}
@keyframes brief-slide{0%{transform:translateX(-100%)}100%{transform:translateX(320%)}}
.brief-marker{color:var(--alc-text)}
.brief-error{color:var(--alc-watch)}
.brief-error button{margin-left:8px;padding:2px 8px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text);border-radius:4px;font-size:12px;cursor:pointer}
.brief-actions{display:flex;gap:8px;flex:0 0 auto}
.brief-actions button{font-size:12px;padding:7px 12px;border-radius:6px;cursor:pointer;border:1px solid var(--alc-line)}
.brief-actions .primary{background:var(--alc-info);border-color:var(--alc-info);color:#fff}
.brief-actions .ghost{background:transparent;color:var(--alc-text-dim)}
.brief-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.brief-kpi{padding:10px 16px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);min-width:0;text-align:center}
.brief-kpi-top{display:flex;align-items:baseline;gap:6px;justify-content:center}
.brief-kpi-value{font-size:44px;font-weight:700;line-height:1.1;color:var(--alc-text)}
.brief-kpi-value i{font-size:14px;font-style:normal;font-weight:400;color:var(--alc-text-dim);margin-left:4px}
.tone-danger .brief-kpi-value{color:var(--alc-danger)}
.tone-watch .brief-kpi-value{color:var(--alc-watch)}
.brief-kpi-mark{font-size:12px;color:var(--alc-text-dim)}
.brief-kpi-label{margin-top:6px;font-size:14px;color:var(--alc-text)}
.brief-kpi-scope{display:inline-block;margin-left:6px;padding:0 5px;border-radius:3px;
  font-size:11px;font-style:normal;line-height:16px;vertical-align:1px;
  color:var(--alc-text-dim);border:1px solid var(--alc-line);background:var(--alc-bg-2)}
.brief-scope-note{color:var(--alc-text-dim);opacity:.92}
.brief-kpi-base{margin-top:2px;font-size:12px;color:var(--alc-text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:1100px){.brief-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}

.brief-kpi-value{background:none;border:0;padding:0;cursor:pointer;font-family:inherit;text-align:center;transition:color .2s var(--alc-ease)}
.brief-kpi-value:hover{color:var(--alc-info)}
.brief-kpi-value:focus-visible{outline:2px solid var(--alc-info);outline-offset:3px;border-radius:4px}
</style>
