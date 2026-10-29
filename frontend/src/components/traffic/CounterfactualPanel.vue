<script setup>
import {computed,onBeforeUnmount,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'
import {activeCase,caseMeta} from '../../traffic/caseMode.js'
import {pct} from '../../traffic/runtime.js'

const data=ref(null),error=ref(''),loading=ref(false),policy=ref('balanced')

const DEFAULT_CF_CASE='fog-20250105'
const scope=ref('')
const effectiveCase=computed(()=>{
  if(scope.value==='live')return ''
  return activeCase()||DEFAULT_CF_CASE
})
const cfCaseQuery=computed(()=>(effectiveCase.value?`&case=${encodeURIComponent(effectiveCase.value)}`:''))
const caseNote=computed(()=>{
  if(effectiveCase.value&&!activeCase())return 'forced'
  if(!effectiveCase.value)return 'live'
  return ''
})
const caseLabel=computed(()=>{
  const meta=caseMeta()||{}
  return effectiveCase.value===(activeCase()||'')&&meta.label?meta.label:'2025-01-05 沈阳大雾'
})
function switchScope(next){scope.value=next;polls=0;load()}
const POLL_MS=3000
const MAX_POLLS=40
let timer=null,disposed=false,polls=0
const POLICIES=[
  {key:'conservative',label:'保守',note:'事故代价 20 000（宁可误停）'},
  {key:'balanced',label:'均衡',note:'事故代价 10 000（默认）'},
  {key:'efficiency',label:'效率',note:'事故代价 4 000（宁可少停）'},
]
function stopPolling(){if(timer){clearTimeout(timer);timer=null}}
async function load(silent=false){
  if(disposed)return
  if(!silent)loading.value=true
  try{
    const payload=await requestJson(`/api/traffic/v2/counterfactual?seed=42&scenario=live&policy=${policy.value}${cfCaseQuery.value}`,{timeoutMs:30000})
    if(disposed)return
    data.value=payload
    error.value=''
    if(payload?.status==='BUILDING'&&polls<MAX_POLLS){
      polls+=1
      stopPolling()
      timer=setTimeout(()=>load(true),POLL_MS)
    }else{
      stopPolling()
    }
  }catch(e){
    if(!disposed)error.value=e.message
  }finally{
    if(!disposed&&!silent)loading.value=false
    else if(!disposed)loading.value=false
  }
}
onMounted(()=>{polls=0;load()})
onBeforeUnmount(()=>{disposed=true;stopPolling()})

const d=computed(()=>data.value||null)
const ready=computed(()=>d.value?.status==='OK')
const building=computed(()=>d.value?.status==='BUILDING')
const delta=computed(()=>d.value?.delta||{})
const totalFlights=computed(()=>d.value?.scope?.flights||0)
const head=computed(()=>{
  const a=d.value?.a,b=d.value?.b
  if(!a||!b)return null
  const saved=Math.max(0,(a.exposure||0)-(b.exposure||0))
  const actions=[]
  if(b.rerouted)actions.push(`绕飞 ${b.rerouted} 架次`)
  if(b.delayedFlights)actions.push(`延误 ${b.delayedFlights} 架次（${delta.value.delayMinutes||0} 分钟）`)
  if(b.cancelled)actions.push(`取消 ${b.cancelled} 架次`)
  return {saved,delay:delta.value.delayMinutes||0,
          cancelled:b.cancelled||0,
          actions:actions.join('、'),
          same:a.exposure===b.exposure}
})
function pctText(v){return typeof v==='number'?`${v>0?'+':''}${v}%`:'—'}
</script>

<template>
<section class="cf">
  <p class="cf-state" v-if="loading&&!d">正在重放运行计划…（要等同一份计划算完）</p>
  <p class="cf-state bad" v-else-if="error">对照不可用 · {{ error }}</p>
  <p class="cf-state" v-else-if="d&&!ready&&building">
    <span aria-hidden="true" class="cf-spin"></span>
    运行计划还在生成（{{ d.progress!=null?d.progress+'%':'进度未报告' }}）·
    反事实要等同一份计划算完，本页每 {{POLL_MS/1000}} 秒自动重试（第 {{ polls }}/{{ MAX_POLLS }} 次）
    <span v-if="d.note"> · {{ d.note }}</span>
  </p>
  <p class="cf-state" v-else-if="d&&!ready">
    对照不可用（{{ d.status }}）<span v-if="d.note"> · {{ d.note }}</span>
    <button @click="polls=0;load()">重试</button>
  </p>

  <template v-else-if="ready">
    <header class="cf-hd">
      <div>
        <h2>反事实对照 <small>同一份计划，只换裁决规则</small></h2>
        <p class="cf-sub">
          计划 {{ String(d.scope?.plan||'').slice(0,8) }} · 参评 {{ d.scope?.reviewed }} / {{ totalFlights }} 架次 ·
          <span class="cf-scope" data-cf-scope>{{ effectiveCase ? '气象 · 2025-01-05 沈阳大雾' : '气象 · 实时' }}</span> ·
          <span :title="`观测档改判 ${delta.divergedObservation ?? 0} 架次（此刻观测已达不可飞）；概率档改判 ${delta.divergedProbability ?? 0} 架次（未来概率过半且高置信）`">
            AI 改判 {{ delta.diverged }} 架次<template v-if="delta.diverged">（观测档 {{ delta.divergedObservation ?? 0 }} · 概率档 {{ delta.divergedProbability ?? 0 }}）</template>
          </span>
        </p>
      </div>
      <div class="cf-policy">
        <button v-for="p in POLICIES" :key="p.key" :class="{active:p.key===policy}" @click="policy=p.key;load()">
          {{ p.label }}<small>{{ p.note }}</small>
        </button>
      </div>
    </header>

    <p class="cf-notice forced" v-if="caseNote==='forced'" data-cf-notice="forced">
      未指定案例，按 <b>2025-01-05 沈阳大雾</b> 重放。
      <button class="cf-switch" @click="switchScope('live')">改看实时气象</button>
    </p>
    <p class="cf-notice live" v-else-if="caseNote==='live'" data-cf-notice="live">
      <b>实时气象</b> · 当前无风险走廊 · 两组均为 0 架次。
      <button class="cf-switch" @click="switchScope('')">切到 2025-01-05 沈阳大雾</button>
    </p>

    <p class="cf-head" v-if="head" :class="head.saved>0?'good':'flat'">
      <b>{{ head.same?'本快照下两组没有差别':'本快照下 AI 组更保守' }}</b>
      关掉 AI：<span class="alc-num">{{ d.a.exposure }}</span> 架次暴露在不可飞走廊上；
      开启 AI：<span class="alc-num">{{ d.b.exposure }}</span> 架次。
      <template v-if="head.saved>0">换言之，用 <span class="alc-num">{{ head.actions||'等待' }}</span>，
        换掉 <span class="alc-num">{{ head.saved }}</span> 架次的风险暴露。</template>
    </p>
    <p class="cf-why" v-if="d.conclusion" data-cf-conclusion>{{ d.conclusion }}</p>

    <div class="cf-grid">
      <div class="cf-card a">
        <h3>A · {{ d.a.label }}</h3>
        <dl>
          <dt>风险暴露</dt><dd class="alc-num">{{ d.a.exposure }} 架次</dd>
          <dt>额外延误</dt><dd class="alc-num">0 分钟</dd>
          <dt>取消</dt><dd class="alc-num">0 架次</dd>
        </dl>
        <p class="cf-card-note">规则说不飞就不飞、说飞就飞 —— 没有概率，也没有"要不要复核"这一步。</p>
      </div>
      <div class="cf-card b">
        <h3>B · {{ d.b.label }}</h3>
        <dl>
          <dt>风险暴露</dt><dd class="alc-num">{{ d.b.exposure }} 架次</dd>
          <dt>额外延误</dt><dd class="alc-num">{{ d.b.delayMinutes }} 分钟</dd>
          <dt>取消</dt><dd class="alc-num">{{ d.b.cancelled }} 架次（延误 {{ d.b.delayedFlights ?? 0 }} 班）</dd>
        </dl>
        <p class="cf-card-note" data-probability-rule>
          概率档只允许更严，不允许更松：概率说他能飞、观测说不能飞 → 按不能飞执行；
          概率说他不能飞、观测说能飞 → 转人工复核（置信度 &lt;0.65 直接转人工）。
          概率档阈值 <b>0.25</b>（停飞）/ <b>0.15</b>（谨慎），与后端常量
          <code>P_PROB_BLOCK / P_PROB_WATCH</code> 同源，界面上不另写一份。
        </p>
      </div>
      <div class="cf-card d">
        <h3>差值（B − A）</h3>
        <dl>
          <dt>暴露变化</dt><dd class="alc-num" :class="delta.exposure<0?'good':delta.exposure>0?'bad':''">
            {{ delta.exposure>0?'+':'' }}{{ delta.exposure }} 架次（{{ pctText(delta.exposurePct) }}）</dd>
          <dt>延误代价</dt><dd class="alc-num">{{ delta.delayMinutes }} 分钟（占计划总时长 {{ delta.delaySharePct }}%）</dd>
          <dt>改判架次</dt><dd class="alc-num">{{ delta.diverged }}</dd>
        </dl>
        <p class="cf-card-note">"暴露变化为负"＝AI 把风险降下来了；为正＝AI 让更多班次暴露，属异常，应查台账。</p>
      </div>
    </div>

    <p class="cf-conclusion">{{ d.conclusion }}</p>

    <section class="cf-sample" v-if="d.sample&&d.sample.length">
      <b>改判明细（最多 20 条 · 真改判优先）</b>
      <small class="cf-sample-note">前段是档位真的变了的班次；后段「低置信 · 留痕未改判」是看过但没动的，
        它们不计入上面的改判架次 —— 两段不可合并读。</small>
      <table>
        <thead><tr><th>航班</th><th>走廊</th><th>不可飞概率</th><th>置信度</th><th>规则</th><th>生效后</th><th>依据</th><th>理由</th></tr></thead>
        <tbody>
          <tr v-for="(r,i) in d.sample" :key="i">
            <td>{{ r.flightId }}</td><td>{{ r.corridorId }}</td>
            <td class="alc-num">{{ pct(r.p,1) }}</td>
            <td class="alc-num">{{ (r.confidence??0).toFixed(2) }}</td>
            <td class="alc-num">{{ r.ruleLevel }}</td>
            <td class="alc-num" :class="(r.effectiveLevel??r.fusedLevel)>r.ruleLevel?'strict':''">{{ r.effectiveLevel??r.fusedLevel }}</td>
            <td class="note">{{ r.obsBan ? '观测档' : (r.fusedLevel !== r.ruleLevel ? '概率档' : '—') }}</td>
            <td class="note">{{ r.note }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="cf-foot">
      <span>代价参数：事故 {{ d.params?.incident }} · 每次改航 {{ d.params?.reroute }} · 每次取消 {{ d.params?.cancel }} · 每 40 分钟延误 {{ d.params?.delay }}</span>
      <span class="warn">{{ d.note }}</span>
      <span class="warn">{{ d.caveat }}</span>
    </footer>
  </template>
</section>
</template>

<style scoped>
.cf-notice{margin:0 0 10px;padding:7px 10px;border-radius:5px;font-size:12.5px;line-height:1.55}
.cf-notice.forced{background:rgba(90,140,190,.10);border-left:3px solid rgba(120,170,220,.55);color:#cfe4f5}
.cf-notice.live{background:rgba(255,181,71,.10);border-left:3px solid var(--alc-watch);color:#f4e2c4}
.cf-notice b{font-weight:600;color:#fff}
.cf-switch{margin-left:8px;padding:1px 8px;font-size:11.5px;border-radius:3px;cursor:pointer;
  background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.22);color:#e2f1fa}
.cf-switch:hover{background:rgba(255,255,255,.18)}
.cf-scope{color:#9fc4dd}

.cf{padding:16px 0;color:var(--alc-text);font-size:13px}
.cf-state{padding:16px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius)}
.cf-state.bad{border-left:3px solid var(--alc-danger)}
.cf-spin{display:inline-block;width:9px;height:9px;margin-right:6px;border-radius:50%;border:2px solid var(--alc-line);border-top-color:var(--alc-info);animation:cf-spin .9s linear infinite;vertical-align:-1px}
@keyframes cf-spin{to{transform:rotate(360deg)}}
.cf-state button{margin-left:10px;padding:2px 10px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text);border-radius:4px;font-size:12px;cursor:pointer}
.cf-hd{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:14px 18px}
.cf-hd h2{font-size:20px}
.cf-hd h2 small{font-size:12px;font-weight:400;color:var(--alc-text-dim);margin-left:8px}
.cf-sub{margin-top:4px;font-size:12px;color:var(--alc-text-dim)}
.cf-policy{display:flex;gap:6px}
.cf-policy button{display:flex;flex-direction:column;gap:2px;padding:6px 10px;border-radius:6px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text-dim);font-size:12px;cursor:pointer;text-align:left}
.cf-policy button small{font-size:10px;color:var(--alc-text-mute)}
.cf-policy button.active{border-color:var(--alc-info);background:rgba(76,141,255,.14);color:var(--alc-text)}
.cf-head{margin-top:12px;padding:12px 16px;font-size:14px;line-height:1.8;border-radius:6px}
.cf-head.good{border-left:3px solid var(--alc-ok);background:rgba(82,196,26,.08)}
.cf-head.flat{border-left:3px solid var(--alc-neutral);background:var(--alc-bg-1)}
.cf-head b{display:block;margin-bottom:2px}
.cf-head .alc-num{font-size:16px;font-weight:700}
.cf-why{margin-top:8px;padding:10px 16px;font-size:13px;line-height:1.7;
  color:var(--alc-text-dim);background:var(--alc-bg-1);border:1px dashed var(--alc-line);border-radius:6px}
.cf-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:12px}
.cf-card{background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:12px 14px}
.cf-card.a{border-top:2px solid var(--alc-text-mute)}
.cf-card.b{border-top:2px solid var(--alc-info)}
.cf-card.d{border-top:2px solid var(--alc-watch)}
.cf-card h3{font-size:13px;color:var(--alc-text-dim);font-weight:600}
.cf-card dl{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;margin-top:8px;font-size:13px}
.cf-card dt{color:var(--alc-text-mute);font-size:12px}
.cf-card dd{text-align:right;font-weight:700}
.cf-card dd.good{color:var(--alc-ok)}.cf-card dd.bad{color:var(--alc-danger)}
.cf-card-note{margin-top:8px;font-size:11px;line-height:1.6;color:var(--alc-text-mute)}
.cf-conclusion{margin-top:12px;padding:10px 14px;border-left:3px solid var(--alc-info);background:rgba(76,141,255,.08);font-size:13px}
.cf-sample{margin-top:16px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:12px 14px}
.cf-sample>b{font-size:13px}
.cf-sample-note{display:block;margin:2px 0 8px;color:var(--alc-text-dim);font-size:12px;line-height:1.5}
.cf-sample table{width:100%;margin-top:8px;border-collapse:collapse;font-size:12px}
.cf-sample th{text-align:left;padding:5px 8px;color:var(--alc-text-mute);font-weight:500;border-bottom:1px solid var(--alc-line)}
.cf-sample td{padding:5px 8px;border-bottom:1px dashed var(--alc-line)}
.cf-sample td.strict{color:var(--alc-watch);font-weight:700}
.cf-sample td.note{color:var(--alc-text-dim);font-size:11px}
.cf-foot{display:flex;flex-direction:column;gap:4px;margin-top:14px;font-size:11px;color:var(--alc-text-mute)}
.cf-foot .warn{color:var(--alc-watch)}
</style>
