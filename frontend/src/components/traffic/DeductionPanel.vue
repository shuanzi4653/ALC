<script setup>
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'
import {activeCase,withCase} from '../../traffic/caseMode.js'
import {pct} from '../../traffic/runtime.js'
import DivergencePanel from './DivergencePanel.vue'

const props=defineProps({
  initialId:{type:String,default:''},
  minute:{type:Number,default:0},
})

const list=ref([])
const detail=ref(null)
const cf=ref(null)
const error=ref('')
const loading=ref(false)
const picked=ref(props.initialId||'')

function minuteQuery(){
  if(!activeCase()||!Number.isFinite(props.minute))return ''
  return `&minute=${Math.round(props.minute)}`
}
function url(path){
  const base=withCase(path)
  if(!minuteQuery())return base
  return `${base}${base.includes('?')?'&':'?'}minute=${Math.round(props.minute)}`
}

let timer=null,disposed=false
async function loadList(){
  try{
    const payload=await requestJson(url('/api/traffic/v2/corridors?limit=53'),{timeoutMs:15000})
    const items=payload?.items||[]
    list.value=items
    if(!picked.value&&items.length){
      const worst=items.reduce((a,b)=>((b.pMax||0)>(a.pMax||0)?b:a),items[0])
      picked.value=worst.corridorId
    }
  }catch(e){error.value=e.message}
}
async function loadDetail(){
  if(!picked.value)return
  loading.value=true
  try{
    detail.value=await requestJson(url(`/api/traffic/v2/corridor/${encodeURIComponent(picked.value)}`),{timeoutMs:20000})
    error.value=''
  }catch(e){error.value=e.message}
  finally{loading.value=false}
}
async function loadCounterfactual(){
  if(disposed)return
  try{
    const payload=await requestJson(withCase('/api/traffic/v2/counterfactual?seed=42&scenario=live&policy=balanced'),{timeoutMs:30000})
    cf.value=payload
    if(payload?.status==='BUILDING'&&!timer){
      timer=setTimeout(()=>{timer=null;loadCounterfactual()},4000)
    }
  }catch(_){}
}
watch(picked,()=>{loadDetail()})
watch(()=>props.initialId,(id)=>{if(id&&id!==picked.value){picked.value=id}})
let minuteTimer=null
watch(()=>props.minute,(value,prev)=>{
  if(!activeCase()||Math.round(value)===Math.round(prev||0))return
  clearTimeout(minuteTimer)
  minuteTimer=setTimeout(()=>{loadList();loadDetail()},300)
})
onMounted(async()=>{await loadList();await loadDetail();loadCounterfactual()})
onBeforeUnmount(()=>{disposed=true;clearTimeout(timer);clearTimeout(minuteTimer)})

const STEP_TITLES=['数据','插值','概率','判据','裁决','对照','七帧','复核']
const LAST=STEP_TITLES.length
const step=ref(1)
const allOpen=ref(false)
function goto(n){allOpen.value=false;step.value=Math.min(LAST,Math.max(1,n))}
function nextStep(){if(step.value<LAST)step.value+=1}
function toggleAll(){allOpen.value=!allOpen.value}
function prevStep(){
  if(allOpen.value){allOpen.value=false;step.value=Math.max(1,LAST-1);return}
  step.value=Math.max(1,step.value-1)
}
function show(n){return allOpen.value||n<=step.value}
function folded(n){return !allOpen.value&&n<step.value}
function restart(){step.value=1;allOpen.value=false}
watch(picked,restart)
watch(()=>props.minute,restart)

const d=computed(()=>detail.value||{})
const ded=computed(()=>d.value.deduction||{})
const stations=computed(()=>ded.value.stations||[])
const allStations=computed(()=>d.value.observation?.stations||[])
const probs=computed(()=>ded.value.midpointProbs||{})
const decision=computed(()=>ded.value.decision||{})
const criteria=computed(()=>d.value.criteria||[])
const hourly=computed(()=>d.value.hourly||[])
const visCriterion=computed(()=>criteria.value.find(c=>c.metric==='能见度')||null)

const LEVEL_TEXT={BAN:'停飞档',CAUTION:'需谨慎',CLEAR:'可飞',NONE:'可飞'}
function levelText(level){return LEVEL_TEXT[level]||'—'}
function levelTone(level){return level==='BAN'?'danger':(level==='CAUTION'?'watch':'ok')}

const rawRows=computed(()=>{
  const byStation=new Map(stations.value.map(s=>[s.station,s]))
  return allStations.value.map(s=>{
    const extra=byStation.get(s.station)||{}
    return {...s,distanceKm:extra.distanceKm??null,weight:extra.weight??null}
  })
})

const GEO={w:560,h:250,left:118,right:500,axisY:150,spanKm:400}
const geo=computed(()=>{
  const shown=stations.value.filter(s=>s.lng!=null&&s.lat!=null)
    .slice().sort((a,b)=>(b.weight||0)-(a.weight||0)).slice(0,3)
  if(!shown.length)return null
  const {w,left,right,axisY,spanKm}=GEO
  const step=shown.length>1?(right-left)/(shown.length-1):0
  return {
    corridor:{x1:left-26,x2:right+26,y:axisY},
    spanKm,
    ticks:[0,100,200,300].map(km=>({km,y:axisY-km/spanKm*100})),
    stations:shown.map((s,i)=>{
      const y=axisY-Math.min(96,(s.distanceKm||0)/spanKm*100)
      const below=y>axisY-24
      return {
        ...s,
        x:shown.length>1?left+i*step:(left+right)/2,
        y,
        labelNameY:below?y+20:y-15,
        labelMetaY:below?y+32:y-3,
      }
    }),
  }
})

const judgeRows=computed(()=>criteria.value.map(c=>({
  metric:c.metric,
  value:c.value,
  unit:c.unit,
  tierText:c.tierText,
  hitTier:c.hitTier,
  ratio:(()=>{
    if(c.kind==='PROBABILITY')return Math.min(1,Math.max(0,Number(c.value)||0))
    const v=Number(c.value); if(!Number.isFinite(v))return 0
    if(c.metric==='能见度')return Math.min(1,Math.max(0,v/6000))
    if(c.metric==='阵风')return Math.min(1,Math.max(0,v/20))
    if(c.metric==='云底高')return Math.min(1,Math.max(0,v/1500))
    return 0
  })(),
  hit:c.hitTier==='BLOCK'||c.hitTier==='WATCH',
})))

const lossRows=computed(()=>{
  const losses=decision.value.losses||{}
  const excluded=decision.value.excluded||{}
  const chosen=decision.value.chosen
  const max=Math.max(1,...Object.values(losses).map(Number))
  const LABEL={DIRECT:'直飞',DELAY:'延误',REROUTE:'绕飞',CANCEL:'取消'}
  return ['DIRECT','DELAY','REROUTE','CANCEL'].filter(k=>losses[k]!=null).map((k,index)=>{
    const excludedReason=excluded[k]
    return {
      key:k,label:LABEL[k],value:Number(losses[k]),
      ratio:Math.min(1,Number(losses[k])/max),
      chosen:k===chosen,
      excluded:!!excludedReason,
      reason:excludedReason||'',
      y:14+index*30,
    }
  })
})

const verdictPair=computed(()=>({
  rule:d.value.verdictObservation||'—',
  fused:d.value.verdict||'—',
  probability:d.value.verdictProbability||'—',
  source:d.value.verdictSource||'',
}))
const cfReady=computed(()=>cf.value?.status==='OK')
const cfA=computed(()=>cf.value?.a||null)
const cfB=computed(()=>cf.value?.b||null)

const CURVE={w:560,h:96}
const curve=computed(()=>{
  const items=hourly.value.filter(h=>h.p!=null)
  if(items.length<2)return {line:'',dots:[]}
  const stepX=(CURVE.w-40)/Math.max(1,hourly.value.length-1)
  const dots=hourly.value.map((h,i)=>{
    if(h.p==null)return null
    return {i,x:20+i*stepX,y:80-h.p*72,p:h.p,ext:h.source==='MODEL_EXTENSION'}
  }).filter(Boolean)
  return {line:dots.map(d=>`${d.x},${d.y}`).join(' '),dots}
})
const summaries=computed(()=>{
  const worstVis=allStations.value.reduce((min,s)=>{
    const v=s.observed?.visM
    return v==null?min:(min==null?v:Math.min(min,v))
  },null)
  const hitCount=criteria.value.filter(c=>c.hitTier==='BLOCK'||c.hitTier==='WATCH').length
  const topWeight=stations.value.reduce((m,s)=>Math.max(m,s.weight||0),0)
  const ACTION={DIRECT:'直飞',DELAY:'延误',REROUTE:'绕飞',CANCEL:'取消'}
  const ps=hourly.value.filter(h=>h.p!=null).map(h=>h.p)
  return {
    1: allStations.value.length?`${allStations.value.length} 站读数，最低能见度 ${worstVis==null?'—':Math.round(worstVis)+' m'}`:'无观测',
    2: stations.value.length?`最近站 ${probs.value.nearestKm??'—'} km，最高权重 ${(topWeight*100).toFixed(1)}%`:'—',
    3: `不可飞概率 ${pct(probs.value.pMax)}（最差采样点）`,
    4: `${hitCount} 条命中，结论 ${verdictPair.value.fused}`,
    5: `选中 ${ACTION[decision.value.chosen]||'—'}，损失 ${Math.round(decision.value.losses?.[decision.value.chosen]||0)}`,
    6: verdictPair.value.rule===verdictPair.value.fused
      ? `规则与 AI 一致：${verdictPair.value.fused}`
      : `规则 ${verdictPair.value.rule} → AI ${verdictPair.value.fused}`,
    7: ps.length?`${pct(Math.min(...ps))} – ${pct(Math.max(...ps))}：雾在散`:'—',
    8: 'AI 与规则不一致时，人的最终判断',
  }
})
const ACTION_LABEL={DIRECT:'直飞',DELAY:'延误',REROUTE:'绕飞',CANCEL:'取消'}

function clockOf(iso){
  const m=String(iso||'').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m?`${m[2]}-${m[3]} ${m[4]}:${m[5]}Z`:(iso||'—')
}
</script>

<template>
<section class="ded" data-deduction>
  <header class="ded-hd">
    <div>
      <p class="ded-sub">
        <b>{{ d.name || '—' }}</b> · {{ d.lengthKm ?? '—' }} km
        · 观测 {{ clockOf(d.observation?.observedAt) }}
        <span v-if="d.verdict" class="ded-verdict" :class="'tone-'+(d.verdict==='不可飞'?'danger':(d.verdict==='需谨慎'?'watch':'ok'))">{{ d.verdict }}</span>
      </p>
    </div>
    <div class="ded-pick">
      <label for="ded-corridor">走廊</label>
      <select id="ded-corridor" v-model="picked" data-ded-pick>
        <option v-for="item in list" :key="item.corridorId" :value="item.corridorId">
          {{ item.name }} · {{ pct(item.pMax) }}
        </option>
      </select>
      <span class="ded-hint">{{ list.length }} 条载客走廊</span>
    </div>
  </header>

  <p class="ded-state" v-if="loading&&!d.corridorId">正在读取走廊…</p>
  <p class="ded-state bad" v-else-if="error">走廊推演不可用 · {{ error }}</p>

  <template v-else-if="d.corridorId">
    <div class="ded-track" data-ded-track>
      <ol class="ded-track-list">
        <li v-for="(label,i) in STEP_TITLES" :key="label">
          <button type="button" :data-step-goto="i+1" :data-step-done="step>i+1||allOpen"
                  :class="{on:!allOpen&&step===i+1,done:step>i+1||allOpen}" @click="goto(i+1)">
            <em>{{ i+1 }}</em><span>{{ label }}</span>
          </button>
        </li>
      </ol>
      <div class="ded-track-actions">
        <b class="ded-track-pos" data-step-pos>{{ allOpen?'全部':(step+' / '+LAST) }}</b>
        <button type="button" data-step-prev @click="prevStep" :disabled="!allOpen&&step<=1">上一步</button>
        <button type="button" class="primary" data-step-next @click="nextStep" :disabled="allOpen||step>=LAST">下一步</button>
        <button type="button" data-step-expand :aria-pressed="allOpen" @click="toggleAll">
          {{ allOpen?'收拢':'展开全部' }}
        </button>
      </div>
    </div>

    <article class="ded-step" data-step="1" :data-step-state="folded(1)?'folded':'open'" v-show="show(1)">
      <header>
        <span class="ded-no">1</span>
        <h3>数据</h3>
        <p class="ded-lead">{{ allStations.length }} 个机场站 METAR，{{ clockOf(d.observation?.observedAt) }} —— 这一步只读，不判断</p>
      </header>
      <p class="ded-fold-line" v-if="folded(1)">{{ summaries[1] }}</p>
      <div class="ded-body wide" v-else>
        <table class="ded-table ded-raw" data-raw-table>
          <thead><tr><th>站</th><th>距走廊中点</th><th>能见度</th><th>阵风</th><th>云底</th><th>档位</th></tr></thead>
          <tbody>
            <tr v-for="st in rawRows" :key="st.station" :data-station="st.station">
              <td><b>{{ st.station }}</b><small>{{ st.name }}</small></td>
              <td class="ded-num">{{ st.distanceKm==null?'—':st.distanceKm+' km' }}</td>
              <td class="ded-num">
                {{ st.observed?.visM==null?'—':Math.round(st.observed.visM)+' m' }}
                <i class="ded-mini" v-if="st.observed?.visM!=null" aria-hidden="true">
                  <b :class="levelTone(st.level)" :style="{width: Math.min(100,st.observed.visM/6000*100)+'%'}"></b>
                </i>
              </td>
              <td class="ded-num">{{ st.observed?.gustMs==null?'—':st.observed.gustMs+' m/s' }}</td>
              <td class="ded-num">{{ st.observed?.cloudBaseM==null?'—':Math.round(st.observed.cloudBaseM)+' m' }}</td>
              <td><span class="ded-hit" :class="levelTone(st.level)">{{ levelText(st.level) }}</span></td>
            </tr>
          </tbody>
        </table>
        <aside class="ded-facts">
          <dl class="ded-io">
            <dt>本步输入</dt>
            <dd>{{ allStations.length }} 站 METAR 实测，观测时刻 {{ clockOf(d.observation?.observedAt) }}</dd>
            <dt>本步输出</dt>
            <dd>每站的能见度与档位 —— 走廊本身还没有结论</dd>
          </dl>
          <p class="ded-note">档位是<b>单站</b>判的：能见度低于阈值即停飞档。走廊的档位要等第 2、3 步把站点插值到走廊上。</p>
        </aside>
      </div>
    </article>

    <article class="ded-step" data-step="2" :data-step-state="folded(2)?'folded':'open'" v-show="show(2)">
      <header>
        <span class="ded-no">2</span>
        <h3>插值</h3>
        <p class="ded-lead">把四站读数搬到走廊上：最近 3 站按 1/d² 加权</p>
      </header>
      <p class="ded-fold-line" v-if="folded(2)">{{ summaries[2] }}</p>
      <div class="ded-body" v-else>
        <svg class="ded-svg" :viewBox="`0 0 ${GEO.w} ${GEO.h}`" role="img"
             aria-label="三站到走廊的距离与权重（横轴按权重排序，纵轴为真实距离）" v-if="geo">
          <g v-for="t in geo.ticks" :key="'t'+t.km">
            <line :x1="GEO.left-26" :y1="t.y" :x2="GEO.right+26" :y2="t.y"
                  stroke="rgba(255,255,255,.07)" stroke-dasharray="3 5"/>
            <text :x="GEO.left-40" :y="t.y+3.5" class="ded-tag" text-anchor="end">{{ t.km }} km</text>
          </g>
          <line :x1="geo.corridor.x1" :y1="geo.corridor.y" :x2="geo.corridor.x2" :y2="geo.corridor.y"
                stroke="rgba(4,14,22,.85)" stroke-width="12" stroke-linecap="round"/>
          <line :x1="geo.corridor.x1" :y1="geo.corridor.y" :x2="geo.corridor.x2" :y2="geo.corridor.y"
                stroke="#9ad0ff" stroke-width="6" stroke-linecap="round"/>
          <text :x="(geo.corridor.x1+geo.corridor.x2)/2" :y="geo.corridor.y+22" class="ded-tag"
                text-anchor="middle">走廊 {{ d.lengthKm }} km</text>
          <g v-for="st in geo.stations" :key="'st'+st.station">
            <line :x1="st.x" :y1="st.y" :x2="st.x" :y2="geo.corridor.y"
                  stroke="rgba(255,255,255,.22)" :stroke-width="1+st.weight*5" stroke-dasharray="4 4"/>
            <circle :cx="st.x" :cy="st.y" r="5.5"
                    :fill="st.level==='BAN'?'#ff4d4f':(st.level==='CAUTION'?'#faad14':'#52c41a')"/>
            <text :x="st.x" :y="st.labelNameY" class="ded-label" text-anchor="middle">{{ st.station }}</text>
            <text :x="st.x" :y="st.labelMetaY" class="ded-tag" text-anchor="middle">{{ st.distanceKm }} km · {{ (st.weight*100).toFixed(1) }}%</text>
          </g>
        </svg>
        <aside class="ded-facts">
          <dl class="ded-io">
            <dt>本步输入</dt>
            <dd>走廊两端坐标 + {{ stations.length }} 个站的坐标与距离</dd>
            <dt>本步输出</dt>
            <dd>权重（线上数字）与中点插值值 {{ visCriterion?('能见度 '+visCriterion.value+' m'):'—' }}</dd>
          </dl>
          <p v-for="st in stations" :key="st.station">
            <b>{{ st.name }}</b>{{ st.station }} · {{ st.distanceKm }} km · 权重 {{ (st.weight*100).toFixed(1) }}%
          </p>
          <p><b>最近站距</b>{{ probs.nearestKm ?? '—' }} km<span v-if="probs.confidence==='LOW'"> · 超 250 km，置信降级</span></p>
          <p class="ded-note">权重 = 1/d²，取最近 3 站后归一化，连线粗细表示权重。
            纵轴是<b>真实距离</b>（每 100 km 一格），横轴按权重排序、间距均分 —— 不是地理方位。</p>
        </aside>
      </div>
    </article>

    <article class="ded-step" data-step="3" :data-step-state="folded(3)?'folded':'open'" v-show="show(3)">
      <header>
        <span class="ded-no">3</span>
        <h3>概率</h3>
        <p class="ded-lead">插值后的能见度与阵风各自出概率，取并集</p>
      </header>
      <p class="ded-fold-line" v-if="folded(3)">{{ summaries[3] }}</p>
      <div class="ded-body" v-else>
        <svg class="ded-svg" viewBox="0 0 560 150" role="img" aria-label="概率合成">
          <g v-for="(row,index) in [{k:'pVis',label:'低能见度',v:probs.pVis,color:'rgba(76,141,255,.75)'},{k:'pGust',label:'阵风',v:probs.pGust,color:'rgba(0,196,204,.75)'}]" :key="row.k">
            <text x="0" :y="18+index*30" class="ded-label">{{ row.label }}</text>
            <rect x="86" :y="6+index*30" width="330" height="16" rx="2" fill="rgba(255,255,255,.06)"/>
            <rect x="86" :y="6+index*30" :width="Math.min(330,(row.v||0)*330)" height="16" rx="2" :fill="row.color"/>
            <text x="424" :y="19+index*30" class="ded-num">{{ pct(row.v) }}</text>
          </g>
          <text x="0" y="96" class="ded-label">不可飞概率</text>
          <rect x="86" y="84" width="330" height="16" rx="2" fill="rgba(255,255,255,.06)"/>
          <rect x="86" y="84" :width="Math.min(330,(probs.pUnsafe||0)*330)" height="16" rx="2" fill="rgba(250,173,20,.6)"/>
          <text x="424" y="97" class="ded-num">{{ pct(probs.pUnsafe) }}</text>
          <text x="0" y="128" class="ded-label">最差采样点</text>
          <rect x="86" y="116" width="330" height="16" rx="2" fill="rgba(255,255,255,.06)"/>
          <rect x="86" y="116" :width="Math.min(330,(probs.pMax||0)*330)" height="16" rx="2" fill="rgba(255,77,79,.5)"/>
          <text x="424" y="129" class="ded-num">{{ pct(probs.pMax) }}</text>
        </svg>
        <aside class="ded-facts">
          <dl class="ded-io">
            <dt>本步输入</dt>
            <dd>低能见度 p = {{ (probs.pVis??0).toFixed(3) }} · 阵风 p = {{ (probs.pGust??0).toFixed(3) }}</dd>
            <dt>本步输出</dt>
            <dd>p = 1 − (1 − p₁)(1 − p₂) = {{ (probs.pUnsafe??0).toFixed(3) }}；沿走廊取最差段 {{ pct(probs.pMax) }}</dd>
          </dl>
          <p><b>σ</b>{{ probs.sigma ?? '—' }} · 置信 {{ probs.confidence==='OK'?'正常':'降级' }}</p>
          <p><b>判据取值</b>用<b>最差采样点</b> {{ pct(probs.pMax) }}，不用中点 {{ pct(probs.pUnsafe) }}</p>
          <p class="ded-note">沿走廊每 5 km 采样一次，取最差的一段 —— 保守取法：只要有一段不可飞，整条都按不可飞看。</p>
        </aside>
      </div>
    </article>

    <article class="ded-step" data-step="4" :data-step-state="folded(4)?'folded':'open'" v-show="show(4)">
      <header>
        <span class="ded-no">4</span>
        <h3>判据</h3>
        <p class="ded-lead">{{ judgeRows.length }} 条判据逐条对照阈值，命中即定档</p>
      </header>
      <p class="ded-fold-line" v-if="folded(4)">{{ summaries[4] }}</p>
      <div class="ded-body wide" v-else>
        <table class="ded-table">
          <thead><tr><th>判据</th><th>当前值</th><th>阈值</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-for="row in judgeRows" :key="row.metric" :data-criterion="row.metric">
              <td>{{ row.metric }}</td>
              <td class="ded-num">{{ row.metric==='概率档'?pct(row.value):row.value }}{{ row.metric==='概率档'?'':(row.unit||'') }}</td>
              <td class="ded-thresh">{{ row.tierText }}</td>
              <td><span class="ded-hit" :class="row.hitTier==='BLOCK'?'block':(row.hitTier==='WATCH'?'watch':'none')">
                {{ row.hitTier==='BLOCK'?'命中停飞档':(row.hitTier==='WATCH'?'命中谨慎档':'未达判据') }}</span></td>
            </tr>
          </tbody>
        </table>
        <aside class="ded-facts">
          <dl class="ded-io">
            <dt>本步输入</dt>
            <dd>{{ judgeRows.length }} 条判据值（观测 3 条 + 概率档 1 条）</dd>
            <dt>本步输出</dt>
            <dd>{{ verdictPair.fused }} · 来源 {{ verdictPair.source==='BOTH'?'观测与概率同时命中':(verdictPair.source==='OBSERVATION'?'观测命中':(verdictPair.source==='PROBABILITY'?'概率档命中':'均未命中')) }}</dd>
          </dl>
          <p><b>观测档</b>{{ verdictPair.rule }}</p>
          <p><b>概率档</b>{{ verdictPair.probability }}</p>
          <p class="ded-note">两档取更严者为结论。判据与结论用同一个数：第 3 步的最差采样点。</p>
        </aside>
      </div>
    </article>

    <article class="ded-step" data-step="5" :data-step-state="folded(5)?'folded':'open'" v-show="show(5)">
      <header>
        <span class="ded-no">5</span>
        <h3>裁决</h3>
        <p class="ded-lead">四种处置各算一次期望损失，取可执行里最小的</p>
      </header>
      <p class="ded-fold-line" v-if="folded(5)">{{ summaries[5] }}</p>
      <div class="ded-body" v-else>
        <svg class="ded-svg" :viewBox="`0 0 560 ${16+lossRows.length*30}`" role="img" aria-label="期望损失">
          <g v-for="row in lossRows" :key="row.key" :data-action="row.key">
            <text x="0" :y="row.y+12" class="ded-label">{{ row.label }}</text>
            <rect x="52" :y="row.y" width="360" height="16" rx="2" fill="rgba(255,255,255,.06)"/>
            <rect x="52" :y="row.y" :width="Math.max(2,row.ratio*360)" height="16" rx="2"
                  :fill="row.excluded?'rgba(255,255,255,.14)':(row.chosen?'rgba(82,196,26,.65)':'rgba(76,141,255,.45)')"/>
            <text x="420" :y="row.y+12" class="ded-num">{{ Math.round(row.value) }}</text>
            <text x="470" :y="row.y+12" class="ded-tag" :class="row.chosen?'ok':''">{{ row.chosen?'选中':(row.excluded?'不可执行':'备选') }}</text>
          </g>
        </svg>
        <aside class="ded-facts">
          <dl class="ded-io">
            <dt>本步输入</dt>
            <dd>不可飞概率 {{ pct(probs.pMax) }} + 四个门限（事故 {{ decision.params?.incident }} · 绕飞 {{ decision.params?.reroute }} · 取消 {{ decision.params?.cancel }} · 延误 {{ decision.params?.delay }}）</dd>
            <dt>本步输出</dt>
            <dd>选中 <b>{{ ACTION_LABEL[decision.chosen]||'—' }}</b>，期望损失 {{ Math.round(decision.losses?.[decision.chosen]||0) }}</dd>
          </dl>
          <p v-if="decision.excluded && decision.excluded.CANCEL" class="ded-note">
            取消的损失只有 {{ Math.round(decision.losses?.CANCEL||0) }}，数字上最便宜，但<b>不可执行</b>：{{ decision.excluded.CANCEL }}。
          </p>
          <p class="ded-note">期望损失 = 概率 × 代价。取消是兜底项，不参与"谁最便宜"的比较。</p>
        </aside>
      </div>
    </article>

    <article class="ded-step" data-step="6" :data-step-state="folded(6)?'folded':'open'" v-show="show(6)">
      <header>
        <span class="ded-no">6</span>
        <h3>对照</h3>
        <p class="ded-lead">同一条走廊，只按观测判 vs 观测加概率</p>
      </header>
      <p class="ded-fold-line" v-if="folded(6)">{{ summaries[6] }}</p>
      <div class="ded-body" v-else>
        <div class="ded-cf">
          <div class="ded-cf-row">
            <span>只按观测判据（关掉 AI）</span>
            <b :class="'tone-'+(verdictPair.rule==='不可飞'?'danger':(verdictPair.rule==='需谨慎'?'watch':'ok'))">{{ verdictPair.rule }}</b>
          </div>
          <div class="ded-cf-row">
            <span>观测 + 概率档（AI 参与）</span>
            <b :class="'tone-'+(verdictPair.fused==='不可飞'?'danger':(verdictPair.fused==='需谨慎'?'watch':'ok'))">{{ verdictPair.fused }}</b>
          </div>
          <p class="ded-cf-note" v-if="verdictPair.rule!==verdictPair.fused">
            本条走廊的差别就在这一步：观测没到线，概率到了。
          </p>
          <p class="ded-cf-note" v-else>本条走廊两种裁决一致：{{ verdictPair.fused }}。</p>
        </div>
        <aside class="ded-facts">
          <template v-if="cfReady">
            <dl class="ded-io">
              <dt>本步输入</dt>
              <dd>同一份运行计划、同一份气象快照，只换最后一层裁决规则</dd>
              <dt>本步输出</dt>
              <dd>关掉 AI {{ cfA?.exposure }} 架次暴露 → 开启 {{ cfB?.exposure }} 架次</dd>
            </dl>
            <p><b>代价</b>绕飞 {{ cfB?.rerouted ?? 0 }} · 延误 {{ cfB?.delayedFlights ?? 0 }} 班 {{ cfB?.delayMinutes ?? 0 }} 分钟</p>
          </template>
          <p v-else class="ded-note">{{ cf?.status==='BUILDING'?'运行计划正在重放，完成后自动填入…':'全局对照暂不可用' }}</p>
        </aside>
      </div>
    </article>

    <article class="ded-step" data-step="7" :data-step-state="folded(7)?'folded':'open'" v-show="show(7)">
      <header>
        <span class="ded-no">7</span>
        <h3>七帧</h3>
        <p class="ded-lead">同一条走廊，00–06 Z 逐时不可飞概率</p>
      </header>
      <p class="ded-fold-line" v-if="folded(7)">{{ summaries[7] }}</p>
      <div class="ded-body wide" v-else>
        <svg class="ded-svg" viewBox="0 0 560 110" role="img" aria-label="逐时不可飞概率">
          <line x1="20" y1="80" x2="540" y2="80" stroke="rgba(255,255,255,.14)"/>
          <line x1="20" y1="44" x2="540" y2="44" stroke="rgba(255,255,255,.06)" stroke-dasharray="3 4"/>
          <line x1="20" y1="8" x2="540" y2="8" stroke="rgba(255,255,255,.06)" stroke-dasharray="3 4"/>
          <text x="0" y="84" class="ded-tag">0%</text>
          <text x="0" y="48" class="ded-tag">50%</text>
          <text x="0" y="12" class="ded-tag">100%</text>
          <polyline :points="curve.line" fill="none" stroke="#9ad0ff" stroke-width="1.8"/>
          <g v-for="dot in curve.dots" :key="dot.i">
            <circle :cx="dot.x" :cy="dot.y" r="3" :fill="dot.ext?'#4c8dff':'#dce6f5'"/>
            <text :x="dot.x" y="98" class="ded-tag" text-anchor="middle">T+{{ dot.i }}</text>
          </g>
        </svg>
        <aside class="ded-facts">
          <dl class="ded-io">
            <dt>本步输入</dt>
            <dd>{{ hourly.length }} 帧观测（逐时）</dd>
            <dt>本步输出</dt>
            <dd>当前 {{ pct(probs.pMax) }} · 最低 {{ pct(Math.min(...hourly.filter(h=>h.p!=null).map(h=>h.p))) }}</dd>
          </dl>
          <p class="ded-note">
            <template v-if="hourly[0]?.frameObserved">七帧都是案例内的实测帧，不是模式延伸。</template>
            <template v-else>3–6 h 一段来自模式逐时值按历史频率校准，不是本模型。</template>
          </p>
        </aside>
      </div>
    </article>
    <article class="ded-step" data-step="8" :data-step-state="folded(8)?'folded':'open'" v-show="show(8)">
      <header>
        <span class="ded-no">8</span>
        <h3>复核</h3>
        <p class="ded-lead">模型与规则不一致时，人最后怎么判 —— 只列本走廊</p>
      </header>
      <p class="ded-fold-line" v-if="folded(8)">{{ summaries[8] }}</p>
      <div class="ded-body wide" v-else>
        <DivergencePanel :focus-corridor="d.corridorId" compact/>
      </div>
    </article>
  </template>
</section>
</template>

<style scoped>
.ded{display:flex;flex-direction:column;gap:10px}
.ded-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.ded-hd h2{margin:0;font-size:18px;font-weight:600;color:var(--alc-text)}
.ded-hd h2 small{margin-left:8px;font-size:12px;font-weight:400;color:var(--alc-text-dim)}
.ded-sub{margin:4px 0 0;font-size:12.5px;color:var(--alc-text-dim)}
.ded-sub b{color:var(--alc-text);font-weight:500}
.ded-verdict{margin-left:8px;padding:1px 7px;border-radius:3px;font-size:12px;background:rgba(255,255,255,.06)}
.ded-verdict.tone-danger{color:var(--alc-danger);background:rgba(255,77,79,.12)}
.ded-verdict.tone-watch{color:var(--alc-watch);background:rgba(250,173,20,.12)}
.ded-verdict.tone-ok{color:var(--alc-ok)}
.ded-pick{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--alc-text-dim)}
.ded-pick select{max-width:280px;padding:4px 6px;font-size:12.5px;border-radius:4px;
  background:var(--alc-bg-2);color:var(--alc-text);border:1px solid var(--alc-line)}
.ded-hint{font-size:12px;color:var(--alc-text-mute)}
.ded-state{margin:0;padding:8px 10px;font-size:12.5px;color:var(--alc-text-dim)}
.ded-state.bad{color:var(--alc-danger)}
.ded-step{border:1px solid var(--alc-line);border-radius:6px;background:rgba(255,255,255,.02);padding:10px 12px}
.ded-step>header{display:flex;align-items:baseline;gap:8px;margin-bottom:8px}
.ded-no{width:18px;height:18px;line-height:18px;text-align:center;border-radius:50%;
  font-size:12px;background:rgba(76,141,255,.18);color:#9ad0ff;flex-shrink:0}
.ded-step h3{margin:0;font-size:14px;font-weight:600;color:var(--alc-text)}
.ded-lead{margin:0;font-size:12px;color:var(--alc-text-dim)}
.ded-body{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;min-width:0}
.ded-body.wide{display:flex;flex-direction:column;gap:10px}
.ded-body.wide .ded-facts{width:auto;display:flex;flex-wrap:wrap;gap:4px 22px}
.ded-body.wide .ded-facts .ded-io{flex:1 1 320px;margin:0}
.ded-body.wide .ded-facts p{flex:1 1 320px}
.ded-body.wide .ded-facts .ded-note{flex:1 1 100%}
.ded-svg{flex:1 1 320px;min-width:0;width:100%;max-width:640px;height:auto}
.ded-facts{margin:0;flex:1 1 210px;min-width:0;max-width:100%;font-size:12px;line-height:1.7;
  color:var(--alc-text-dim);padding:8px 10px;border-radius:6px;
  background:rgba(120,170,220,.05);border:1px solid rgba(120,170,220,.12)}
.ded-facts p{margin:0}
.ded-facts b{display:inline-block;min-width:66px;color:var(--alc-text);font-weight:500}
.ded-note{margin-top:4px !important;color:var(--alc-text-mute)}
.ded-label{font-size:12px;fill:var(--alc-text-dim)}
.ded-num{font-size:12.5px;fill:var(--alc-text);font-variant-numeric:tabular-nums}
.ded-svg text.ded-tag{paint-order:stroke;stroke:rgba(4,14,22,.9);stroke-width:2.6px}
.ded-tag{font-size:12px;fill:var(--alc-text-mute)}
.ded-tag.ok{fill:var(--alc-ok)}
.ded-tag.danger{fill:var(--alc-danger)}
.ded-tag.watch{fill:var(--alc-watch)}
.ded-table{width:100%;border-collapse:collapse;font-size:12.5px}
.ded-table th{text-align:left;padding:4px 8px;font-weight:500;color:var(--alc-text-dim);
  border-bottom:1px solid rgba(255,255,255,.12);white-space:nowrap}
.ded-table td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.06);vertical-align:top}
.ded-thresh{color:var(--alc-text-dim)}
.ded-hit{padding:1px 6px;border-radius:3px;font-size:12px;background:rgba(255,255,255,.06);white-space:nowrap}
.ded-hit.block{color:var(--alc-danger);background:rgba(255,77,79,.12)}
.ded-hit.watch{color:var(--alc-watch);background:rgba(250,173,20,.12)}
.ded-hit.none{color:var(--alc-text-dim)}
.ded-cf{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:6px}
.ded-cf-row{display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding:7px 10px;border-radius:4px;background:rgba(255,255,255,.03);font-size:12.5px;color:var(--alc-text-dim)}
.ded-cf-row b{font-size:14px;font-weight:600}
.ded-cf-row b.tone-danger{color:var(--alc-danger)}
.ded-cf-row b.tone-watch{color:var(--alc-watch)}
.ded-cf-row b.tone-ok{color:var(--alc-ok)}
.ded-cf-note{margin:2px 0 0;font-size:12px;color:var(--alc-text-dim)}
@media (max-width:1100px){
  .ded-body{flex-direction:column}
  .ded-facts{width:auto}
}

.ded-track{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:8px 10px;
  border:1px solid var(--alc-line);border-radius:7px;background:rgba(255,255,255,.02)}
.ded-track-list{display:flex;align-items:center;gap:4px;margin:0;padding:0;list-style:none;flex:1 1 auto;min-width:0}
.ded-track-list button{display:flex;align-items:center;gap:6px;padding:5px 9px;border-radius:5px;
  background:transparent;border:1px solid transparent;cursor:pointer;color:#7d9ab0;font-size:12.5px}
.ded-track-list button em{font-style:normal;font-size:11px;min-width:14px;text-align:center;
  border-radius:50%;border:1px solid #2d4a5e;padding:0 2px;color:#6f92a8}
.ded-track-list button.done{color:#b7d3e4}
.ded-track-list button.done em{border-color:#2f6b4a;background:rgba(82,196,26,.16);color:#9fe07a}
.ded-track-list button.on{color:#eaf8ff;background:rgba(89,223,252,.12);border-color:rgba(89,223,252,.42)}
.ded-track-list button.on em{border-color:#59dffc;color:#59dffc}
.ded-track-actions{display:flex;align-items:center;gap:7px;flex:0 0 auto}
.ded-track-pos{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:#7fa5bd;font-weight:400}
.ded-track-actions button{font-size:12px;padding:4px 10px;border-radius:5px;cursor:pointer;
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.16);color:#cfe4f5}
.ded-track-actions button:disabled{opacity:.38;cursor:default}
.ded-track-actions button.primary{background:rgba(89,223,252,.18);border-color:rgba(89,223,252,.5);color:#eaf8ff}
.ded-fold-line{margin:0;padding:4px 0 0 22px;font-size:12.5px;color:#8fb3c9;line-height:1.5}
.ded-step[data-step-state="folded"]{background:rgba(255,255,255,.008);border-color:rgba(255,255,255,.06)}
.ded-step[data-step-state="folded"] h3{color:#8fb3c9}
.ded-io{display:grid;grid-template-columns:auto minmax(0,1fr);gap:3px 8px;margin:0 0 9px;
  padding:1px 0 1px 9px;border-left:2px solid rgba(120,170,220,.5)}
.ded-io dt{font-size:11px;color:#7fa5bd;white-space:nowrap}
.ded-io dd{margin:0;font-size:12px;color:#cfe4f5;line-height:1.45}
.ded-raw td b{font-weight:600}
.ded-raw td small{display:block;font-size:10.5px;color:#6f92a8}
.ded-raw td{padding:5px 8px}
.ded-mini{display:block;max-width:96px;margin-left:auto;height:3px;margin-top:3px;border-radius:2px;background:rgba(255,255,255,.08)}
.ded-mini b{display:block;height:100%;border-radius:2px;background:#52c41a}
.ded-mini b.danger{background:#ff4d4f}
.ded-mini b.watch{background:#faad14}
@media(max-width:1100px){
  .ded-track-list{flex-wrap:wrap}
  .ded-track-list button span{display:none}
  .ded-track-list button em{font-size:12.5px}
}
@media (max-width:1180px){
  .ded-body{flex-direction:column;align-items:stretch}
  .ded-svg{max-width:100%}
  .ded-facts{width:auto;max-width:none}
  .ded-track-list button span{display:none}
}
</style>
