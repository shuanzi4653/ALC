<script setup>
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {requestJson,postAction} from '../../api.js'
import {pct,riskTone,verdictTone,hourLabel,criterionValueText,visibilityText} from '../../traffic/runtime.js'
import {withCase,activeCase} from '../../traffic/caseMode.js'

const props=defineProps({initialId:{type:String,default:''},
  minute:{type:Number,default:0},
  focusPair:{type:Object,default:null}})
const list=ref(null),detail=ref(null),selected=ref(props.initialId||''),error=ref(''),loading=ref(false)
const note=ref(''),recorded=ref(''),busy=ref(false)

function withMinute(url){
  const base=withCase(url)
  if(!activeCase()||!Number.isFinite(props.minute))return base
  return `${base}${base.includes('?')?'&':'?'}minute=${Math.round(props.minute)}`
}

async function loadList(){
  try{
    list.value=await requestJson(withMinute('/api/traffic/v2/corridors?limit=53'),{timeoutMs:15000})
    if(!selected.value&&list.value?.items?.length)selected.value=list.value.items[0].corridorId
    error.value=''
  }catch(e){error.value=e.message}
}
async function loadDetail(){
  if(!selected.value)return
  loading.value=true
  try{
    detail.value=await requestJson(withMinute(`/api/traffic/v2/corridor/${encodeURIComponent(selected.value)}`),{timeoutMs:15000})
    recorded.value=''
    error.value=''
  }catch(e){error.value=e.message}
  finally{loading.value=false}
}
async function reload(){await loadList();await loadDetail()}
const reading=ref(null),readingBusy=ref(false),readingError=ref('')
async function explain(){
  if(!selected.value)return
  readingBusy.value=true;readingError.value=''
  try{
    reading.value=await requestJson('/api/traffic/v2/explain?corridorId='+encodeURIComponent(selected.value),{timeoutMs:25000})
  }catch(e){readingError.value=e.message||'解读生成失败';reading.value=null}
  finally{readingBusy.value=false}
}
let minuteTimer=null
watch(()=>props.focusPair,(pair)=>{
  if(!pair||!list.value.length)return
  const match=list.value.filter(row=>{
    const same=(row.fromCity===pair.from&&row.toCity===pair.to)
      ||(row.fromCity===pair.to&&row.toCity===pair.from)
    return same&&(!pair.mode||row.mode===pair.mode)
  })
  if(!match.length)return
  const worst=match.reduce((a,b)=>((b.pMax||0)>(a.pMax||0)?b:a),match[0])
  if(worst.corridorId!==selected.value){selected.value=worst.corridorId;loadDetail()}
},{immediate:true})

watch(()=>props.minute,(value,prev)=>{
  if(!activeCase()||Math.round(value)===Math.round(prev||0))return
  clearTimeout(minuteTimer)
  minuteTimer=setTimeout(()=>{loadList();if(selected.value)loadDetail()},300)
})
onBeforeUnmount(()=>{clearTimeout(minuteTimer)})

onMounted(reload)
watch(selected,loadDetail)
defineExpose({open:id=>{selected.value=id}})

const rows=computed(()=>list.value?.items||[])
const probabilityRow=computed(()=>(detail.value?.criteria||[]).find(c=>c.kind==='PROBABILITY')||null)
const observationCount=computed(()=>(detail.value?.criteria||[]).filter(c=>c.kind!=='PROBABILITY').length)
const observationAllPassed=computed(()=>{
  const rows=(detail.value?.criteria||[]).filter(c=>c.kind!=='PROBABILITY')
  return rows.length>0&&rows.every(c=>c.passed===true)
})
const hourly=computed(()=>detail.value?.hourly||[])
const baseIso=computed(()=>detail.value?.observation?.observedAt||'')
const hasExtension=computed(()=>hourly.value.some(h=>h.source==='MODEL_EXTENSION'))
const windowText=computed(()=>{
  const w=detail.value?.window||[]
  if(!w.length)return '未来 6 小时内没有连续可飞窗口'
  return w.map(([a,b])=>`${hourLabel(baseIso.value,a)||('T+'+a)}–${hourLabel(baseIso.value,b+1)||('T+'+(b+1))}`).join('、')
})
const curve=computed(()=>{
  const items=hourly.value
  if(!items.length)return ''
  const step=320/Math.max(1,items.length-1)
  return items.map((h,i)=>{
    if(h.p===null||h.p===undefined)return null
    const x=20+i*step,y=100-h.p*80
    return {x,y,p:h.p,source:h.source,i}
  }).filter(Boolean)
})
const bars=computed(()=>{
  const step=320/Math.max(1,hourly.value.length)
  return hourly.value.map((h,i)=>{
    const p=h.p===null||h.p===undefined?null:h.p
    return {i,x:20+i*step,w:Math.max(6,step-6),h:p===null?0:p*80,y:100-(p===null?0:p*80),p,source:h.source}
  })
})
const windowBands=computed(()=>{
  const step=320/Math.max(1,hourly.value.length)
  return (detail.value?.window||[]).map(([a,b])=>({x:20+a*step,w:(b-a+1)*step,label:'可飞窗口'}))
})

async function record(verdict){
  if(!note.value.trim()){recorded.value='请先填写理由（否决与回滚必须留痕）';return}
  busy.value=true
  try{
    await postAction('/api/traffic/v2/decision',{
      corridorId:detail.value.corridorId,ruleLevel:0,p:detail.value.pMax,
      confidence:Math.abs(detail.value.pMax-.5)*2,verdict,note:note.value,
    })
    recorded.value='已记录：'+verdict
    note.value=''
  }catch(e){recorded.value='记录失败：'+e.message}
  finally{busy.value=false}
}
function exportCsv(){
  if(!detail.value)return
  const head='km,p_unsafe,sigma\n'
  const body=(detail.value.samples||[]).map(s=>`${s.km},${s.p},${s.sigma}`).join('\n')
  const blob=new Blob([head+body],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob),a=document.createElement('a')
  a.href=url;a.download=`${detail.value.corridorId}-profile.csv`;a.click()
  setTimeout(()=>URL.revokeObjectURL(url),1000)
}
</script>

<template>
<div class="corr">
  <aside class="corr-list">
    <div class="corr-list-hd">
      <b>城际走廊</b><span>{{ list?.total ?? '—' }} 条</span>
    </div>
    <p class="corr-list-note" v-if="list?.observation">观测 {{ list.observation.observedAt || '—' }}</p>
    <button v-for="row in rows" :key="row.corridorId" class="corr-row" :class="['tone-'+verdictTone(row.verdict),{active:row.corridorId===selected}]" @click="selected=row.corridorId">
      <span class="corr-row-name">{{ row.name }}</span>
      <span class="corr-row-meta">{{ row.corridorId }} · {{ row.lengthKm }} km</span>
      <span class="corr-row-p alc-num" :title="`不可飞概率 ${pct(row.pMax)}`">{{ pct(row.pMax) }}</span>
      <span class="corr-row-verdict">{{ row.verdict }}</span>
      <span class="corr-row-vis" v-if="row.visM != null"
            :class="{lower:!!row.visLowerBound}"
            :title="`最近站 ${row.visNearestStation || '—'}（${row.visNearestKm ?? '—'} km）实测 ${row.visLowerBound ? '≥ ' : ''}${Math.round(row.visM)} m${row.visLowerBound && row.visRaw ? '（报文 ' + row.visRaw + ' 为下界）' : ''}；中点插值 ${row.visMidpointM != null ? Math.round(row.visMidpointM) + ' m' : '—'}（仅参考）`">
        {{ visibilityText(row.visM, row.visLowerBound) }}
      </span>
    </button>
    <p class="corr-empty" v-if="!rows.length&&!error">暂无可读走廊（三站观测不可用时不编数据）</p>
  </aside>

  <section class="corr-detail" v-if="detail&&detail.status==='OK'">
    <header class="corr-hd">
      <div>
        <h2>{{ detail.name }} <small>{{ detail.corridorId }} · {{ detail.lengthKm }} km</small></h2>
        <p>
          不可飞概率 <b class="alc-num">{{ pct(detail.pMax) }}</b> ·
          <span :class="'v-'+riskTone(detail.pMax)">{{ detail.verdict }}</span>
          <span class="corr-source" :class="'src-'+(detail.verdictExplain?.source||'NONE').toLowerCase()"
                :title="detail.verdictExplain?.text||''">
            {{ {OBSERVATION:'观测判定',PROBABILITY:'概率档判定',BOTH:'两档一致',NONE:'—'}[detail.verdictExplain?.source] || '—' }}
          </span> ·
          插值不确定度 σ≈{{ detail.sigmaMean }} · 最近站距 {{ detail.nearestStationKm }} km
        </p>
      </div>
      <div class="corr-hd-actions">
        <button class="primary" data-explain @click="explain" :disabled="readingBusy">{{ readingBusy?'正在翻译…':'生成一句解读' }}</button>
        <button @click="exportCsv">导出 CSV</button>
        <button @click="reload">刷新</button>
      </div>
    </header>

    <section class="corr-reading" v-if="reading||readingError" data-reading>
      <p class="corr-reading-text" v-if="reading&&reading.text">{{ reading.text }}</p>
      <p class="corr-reading-error" v-else-if="readingError">解读生成失败 · {{ readingError }}</p>
      <p class="corr-reading-meta" v-if="reading">
        <span class="src" :class="'src-'+String(reading.source||'').toLowerCase()">{{ reading.source==='MODEL'?'大模型翻译':'模板生成' }}</span>
        <span v-if="reading.guard&&reading.guard.violations&&reading.guard.violations.length">已拦下越界数字：{{ reading.guard.violations.join('、') }}</span>
        <span v-else-if="reading.source==='MODEL'">数字校验通过（只用了证据里的数）</span>
        <span v-if="reading.note">· {{ reading.note }}</span>
      </p>
    </section>

    <div class="corr-alert" v-if="detail.confidence==='LOW'">
      最近观测站距超过 250 km，本走廊的概率是插值外推 —— <b>默认降级为建议人工复核</b>，不给"可飞"。
    </div>

    <section class="corr-chart">
      <div class="corr-chart-hd">
        <b>可飞性（0–6 h）</b>
        <span v-if="hasExtension">0–3 h＝模型（METAR 驱动） · 3–6 h＝模式延伸（Open-Meteo 校准）</span>
        <span v-else>0–3 h＝模型（METAR 驱动） · 3–6 h 模式延伸不可用</span>
      </div>
      <svg viewBox="0 0 360 130" role="img" aria-label="未来六小时不可飞概率">
        <line x1="20" y1="100" x2="350" y2="100" stroke="rgba(255,255,255,.14)"/>
        <line x1="20" y1="60" x2="350" y2="60" stroke="rgba(255,255,255,.06)" stroke-dasharray="3 4"/>
        <line x1="20" y1="20" x2="350" y2="20" stroke="rgba(255,255,255,.06)" stroke-dasharray="3 4"/>
        <text x="2" y="104" class="axis">0%</text><text x="2" y="64" class="axis">50%</text><text x="2" y="24" class="axis">100%</text>
        <rect v-for="band in windowBands" :key="band.x" :x="band.x" y="18" :width="band.w" height="84" fill="rgba(82,196,26,.10)"/>
        <rect v-for="bar in bars" :key="'b'+bar.i" :x="bar.x" :y="bar.y" :width="bar.w" :height="100-bar.y"
              :fill="bar.source==='MODEL_EXTENSION'?'rgba(76,141,255,.35)':'rgba(76,141,255,.75)'"/>
        <polyline :points="curve.map(c=>c.x+','+c.y).join(' ')" fill="none" stroke="#9ad0ff" stroke-width="1.6" stroke-linejoin="round"/>
        <circle v-for="c in curve" :key="'c'+c.i" :cx="c.x" :cy="c.y" r="2.4" :fill="c.source==='MODEL_EXTENSION'?'#4c8dff':'#dce6f5'"/>
        <text v-for="(h,i) in hourly" :key="'t'+i" :x="20+i*(320/Math.max(1,hourly.length))" y="118" class="axis">{{ hourLabel(baseIso,i)||('T+'+i) }}</text>
      </svg>
      <p class="corr-window">建议窗口：<b>{{ windowText }}</b>（可飞性 &gt;50%）</p>
      <p class="corr-window-note" v-if="probabilityRow && detail.verdict && detail.verdict !== '可飞'"
         data-threshold-scales>
        与停飞判据<b>不是同一把尺</b>：建议窗口按「可飞性 &gt;50%」的选班偏好取，回答"哪个时段更好"；
        本条当前不可飞概率 <b>{{ pct(detail.pMax) }}</b> 已触发停飞判据（概率 ≥ 25%），回答"能不能放行"。
        窗口里列出的时段只是概率相对更低的时段，<b>不是免复核的时段</b>。
      </p>
      <p class="corr-window-note" v-if="hasExtension">3–6 h 一段来自模式逐时值按历史频率校准，<b>不是本模型</b>；引用时请写清。</p>
    </section>

    <section class="corr-criteria">
      <b>判据（{{ detail.criteria?.length||0 }} 条）
        <small class="corr-criteria-note">
          观测 {{ observationCount }} 条{{ observationAllPassed?' · 全部满足':' · 有未满足' }} ·
          概率档 {{ probabilityRow ? (probabilityRow.passed?'未触发':'已触发') : '未取得' }}
        </small>
      </b>
      <ul>
        <li v-for="c in detail.criteria||[]" :key="c.metric" :class="c.passed===false?'fail':c.passed===true?'pass':'unknown'">
          <span class="c-metric">{{ c.metric }}</span>
          <span class="c-value alc-num" :class="{lower:!!c.lowerBound}" :title="c.lowerBound ? '报文 ' + (c.display || '') + '：该值取自报文下界（如 6+），不是一次精确观测' : ''">{{ criterionValueText(c).text }}</span>
          <span class="c-thr" v-if="c.tierText">（{{ c.tierText }}）</span>
          <span class="c-thr" v-else-if="!c.display">（阈值 {{ c.operator }} {{ c.threshold }} {{ c.unit }}）</span>
          <span class="c-ok" :class="{watch:c.hitTier==='WATCH', block:c.hitTier==='BLOCK'}">{{ c.hitTier==='BLOCK'?'命中停飞档':(c.hitTier==='WATCH'?'命中谨慎档':(c.hitTier==='NONE'?'未达判据':'无法判定')) }}</span>
          <span class="c-src">{{ c.source }}</span>
        </li>
      </ul>
      <p class="corr-explain" v-if="detail.verdictExplain" :class="{divergent:detail.verdictExplain.divergent}"
         data-verdict-explain>{{ detail.verdictExplain.text }}</p>
    </section>

    <section class="corr-actions">
      <b>处置</b>
      <div class="corr-action-row">
        <button class="primary" :disabled="busy" @click="record('ACCEPT')">采纳模型判断</button>
        <button :disabled="busy" @click="record('REJECT')">否决（填理由）</button>
        <button :disabled="busy" @click="record('MANUAL')">转人工复核</button>
        <input v-model="note" placeholder="理由（否决与回滚必填）" aria-label="裁决理由">
      </div>
      <p class="corr-recorded" v-if="recorded">{{ recorded }}</p>
      <div class="corr-alts" v-if="detail.alternatives?.length">
        <b>备选走廊</b>
        <button v-for="alt in detail.alternatives" :key="alt.corridorId" @click="selected=alt.corridorId">
          {{ alt.name }} · {{ pct(alt.pMax) }}
        </button>
      </div>
    </section>

    <footer class="corr-foot">
      <span>插值：{{ detail.assumptions?.interpolation }}</span>
      <span>误差带：{{ detail.assumptions?.sigma }}</span>
      <span>地形修正：{{ detail.terrainCorrection==='APPLIED'?'已应用（DEM）':'未应用（缺 DEM）' }}</span>
    </footer>
  </section>

  <section class="corr-detail" v-else-if="loading">正在读取走廊剖面…</section>
  <section class="corr-detail" v-else-if="error">走廊数据加载失败 · {{ error }}</section>
  <section class="corr-detail" v-else>选择左侧一条走廊。</section>
</div>
</template>

<style scoped>
.corr{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;padding:16px 0}
.corr-list{background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:12px;max-height:calc(100vh - 260px);overflow:auto}
.corr-list-hd{display:flex;justify-content:space-between;align-items:baseline;font-size:14px;color:var(--alc-text);margin-bottom:4px}
.corr-list-hd span{font-size:12px;color:var(--alc-text-dim)}
.corr-list-note{font-size:12px;color:var(--alc-text-dim);margin-bottom:8px}
.corr-row{display:grid;grid-template-columns:1fr auto;gap:2px 8px;width:100%;text-align:left;padding:8px 10px;margin-bottom:6px;background:transparent;border:1px solid transparent;border-radius:6px;cursor:pointer;color:var(--alc-text)}
.corr-row:hover{background:var(--alc-bg-2)}
.corr-row.active{border-color:var(--alc-info);background:rgba(76,141,255,.12)}
.corr-row-name{font-size:13px}
.corr-row-meta{grid-column:1;font-size:12px;color:var(--alc-text-dim)}
.corr-row-p{grid-row:1;grid-column:2;font-size:16px;font-weight:700}
.corr-row-vis{font-size:11px;color:var(--alc-text-dim);font-variant-numeric:tabular-nums;margin-left:6px}
.corr-row-verdict{grid-row:2;grid-column:2;font-size:12px;color:var(--alc-text-dim);text-align:right}
.tone-danger .corr-row-p{color:var(--alc-danger)}
.tone-watch .corr-row-p{color:var(--alc-watch)}
.tone-ok .corr-row-p{color:var(--alc-ok)}
.tone-info .corr-row-p{color:var(--alc-info)}
.corr-empty{font-size:12px;color:var(--alc-text-dim);padding:12px 4px}
.corr-detail{background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:16px 20px;min-height:200px}
.corr-hd{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.corr-hd h2{font-size:20px;color:var(--alc-text)}
.corr-hd h2 small{font-size:12px;color:var(--alc-text-dim);font-weight:400;margin-left:8px}
.corr-hd p{margin-top:4px;font-size:13px;color:var(--alc-text-dim)}
.corr-hd p b{font-size:20px;color:var(--alc-text)}
.v-danger{color:var(--alc-danger)}.v-watch{color:var(--alc-watch)}.v-ok{color:var(--alc-ok)}.v-info{color:var(--alc-info)}
.corr-hd-actions{display:flex;gap:8px}
.corr-hd-actions button{font-size:12px;padding:6px 10px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text);border-radius:6px;cursor:pointer}
.corr-alert{margin-top:10px;padding:8px 12px;border-left:3px solid var(--alc-watch);background:rgba(250,173,20,.08);font-size:12px;color:var(--alc-text)}
.corr-chart{margin-top:16px}
.corr-chart-hd{display:flex;justify-content:space-between;align-items:baseline;font-size:13px;color:var(--alc-text)}
.corr-chart-hd span{font-size:12px;color:var(--alc-text-dim)}
.corr-chart svg{width:100%;max-width:720px;margin-top:6px}
.axis{font-size:7px;fill:#93a4bc}
.corr-window{margin-top:6px;font-size:13px;color:var(--alc-text)}
.corr-window-note{font-size:12px;color:var(--alc-text-dim);margin-top:2px}
.corr-row-vis .vis-lower{margin-right:1px;color:var(--alc-text-mute, #8c9bab);font-weight:600}
.corr-criteria .c-value.lower{color:var(--alc-text)}
.corr-source{font-size:11px;padding:1px 6px;border-radius:9px;border:1px solid var(--alc-line);color:var(--alc-text-dim)}
.corr-source.src-probability{border-color:#8a5a2a;color:#ffce8a;background:#241a0d}
.corr-source.src-observation{border-color:#2f6f4f;color:#8ff0bb;background:#0f2318}
.corr-criteria-note{font-weight:400;font-size:11px;color:var(--alc-text-mute);margin-left:8px}
.corr-explain{margin-top:10px;padding:8px 10px;border-left:3px solid var(--alc-line);
  background:rgba(255,255,255,.03);font-size:12px;line-height:1.6;color:var(--alc-text-dim)}
.corr-explain.divergent{border-left-color:#d98a2b;color:#ffd9a8}
.corr-criteria{margin-top:16px}
.corr-criteria>b,.corr-actions>b{font-size:14px;color:var(--alc-text)}
.corr-criteria ul{list-style:none;margin-top:6px}
.corr-criteria li{display:flex;gap:10px;align-items:baseline;padding:6px 0;border-bottom:1px dashed var(--alc-line);font-size:13px}
.c-metric{width:64px;color:var(--alc-text-dim)}
.c-value{font-weight:700;color:var(--alc-text)}
.c-thr{color:var(--alc-text-dim);font-size:12px}
.c-ok{font-size:12px}
.c-ok.watch{color:var(--alc-watch)}
.c-ok.block{color:var(--alc-danger)}
.corr-criteria li.pass .c-ok{color:var(--alc-ok)}
.corr-criteria li.fail .c-ok{color:var(--alc-danger)}
.corr-criteria li.unknown .c-ok{color:var(--alc-text-mute)}
.c-src{margin-left:auto;font-size:11px;color:var(--alc-text-mute)}
.corr-actions{margin-top:16px}
.corr-action-row{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.corr-action-row button{font-size:12px;padding:7px 12px;border-radius:6px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text);cursor:pointer}
.corr-action-row .primary{background:var(--alc-info);border-color:var(--alc-info);color:#fff}
.corr-action-row input{flex:1;min-width:180px;padding:7px 10px;border-radius:6px;border:1px solid var(--alc-line);background:var(--alc-bg-0);color:var(--alc-text);font-size:12px}
.corr-recorded{margin-top:6px;font-size:12px;color:var(--alc-watch)}
.corr-alts{margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}
.corr-alts button{font-size:12px;padding:5px 10px;border-radius:6px;border:1px solid var(--alc-line);background:transparent;color:var(--alc-text-dim);cursor:pointer}
.corr-foot{margin-top:16px;display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--alc-text-mute)}

.corr-reading{margin:10px 0;padding:10px 14px;background:var(--alc-bg-2);border:1px solid var(--alc-line);border-radius:var(--alc-radius)}
.corr-reading-text{margin:0;font-size:14px;line-height:1.55;color:var(--alc-text)}
.corr-reading-error{margin:0;font-size:13px;color:var(--alc-watch)}
.corr-reading-meta{margin:6px 0 0;font-size:12px;color:var(--alc-text-dim);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.corr-reading-meta .src{padding:1px 6px;border-radius:4px;border:1px solid var(--alc-line)}
.corr-reading-meta .src-model{color:var(--alc-info);border-color:var(--alc-info)}
.corr-reading-meta .src-template{color:var(--alc-watch);border-color:var(--alc-watch)}
</style>
