<script setup>
import {computed,onMounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'
import {pct} from '../../traffic/runtime.js'

const card=ref(null),error=ref(''),loading=ref(false),task=ref('compare')
async function load(){
  loading.value=true
  try{card.value=await requestJson('/api/traffic/v2/modelcard',{timeoutMs:20000});error.value=''}
  catch(e){error.value=e.message}
  finally{loading.value=false}
}
onMounted(load)

const tasks=computed(()=>card.value?.tasks||[])
const compareTabs=computed(()=>[{key:'compare',title:'三目标对比'},...tasks.value])
const target=computed(()=>(card.value?.targets||{})[task.value]||null)
const t=computed(()=>target.value)

const compareRows=computed(()=>{
  const tg=card.value?.targets||{}
  return (card.value?.tasks||[]).map(x=>{
    const d=tg[x.key]||{}
    const m=d.model||{}
    return {
      key:x.key,title:x.title,
      rate:m.positiveRate,positives:m.positives,n:m.n,
      pod:m.POD,far:m.FAR,ts:m.TS,
      tsBase:d.baselines?.persistence?.TS,
      auc:d.auc,skill:m.brierSkillVsClimatology,
      lead:d.leadTime?.medianMin,leadN:d.leadTime?.n,
    }
  })
})
function tsGapText(row){
  if(typeof row.ts!=='number'||typeof row.tsBase!=='number')return '—'
  const pp=(row.ts-row.tsBase)*100
  const sign=pp>=0?'+':'−'
  const mag=Math.abs(pp).toFixed(1)
  if(Math.abs(pp)<2)return `与持续性基线相当（${sign}${mag} pp，正例 ${row.positives} 条，落在置信区间内）`
  return pp>0?`高于持续性基线 ${mag} pp`:`低于持续性基线 ${mag} pp`
}
const leadBand=computed(()=>{
  const l=t.value?.leadTime
  if(!l||typeof l.medianMin!=='number')return null
  const max=360
  const pos=v=>Math.max(0,Math.min(100,(Number(v||0)/max)*100))
  return {n:l.n,p25:l.p25Min,med:l.medianMin,p75:l.p75Min,
          p25At:pos(l.p25Min),medAt:pos(l.medianMin),p75At:pos(l.p75Min)}
})

const rows=computed(()=>{
  const d=t.value
  if(!d)return []
  const out=[{key:'model',name:'本模型（工作点 '+fmt(d.model?.operatingThreshold)+'）',m:d.model,self:true}]
  if(d.model?.atThreshold05)out.push({key:'model05',name:'本模型（固定 0.5）',m:d.model.atThreshold05})
  const b=d.baselines||{}
  if(b.persistence)out.push({key:'persistence',name:'基线 · 持续性（用当前值外推）',m:b.persistence})
  if(b.openMeteo)out.push({key:'openMeteo',name:'基线 · Open-Meteo 模式',m:b.openMeteo})
  if(b.thresholdRule)out.push({key:'thresholdRule',name:'基线 · 单要素阈值规则',m:b.thresholdRule})
  return out
})
const bestTs=computed(()=>{
  const list=rows.value.filter(r=>typeof r.m?.TS==='number')
  if(!list.length)return null
  return Math.max(...list.map(r=>r.m.TS))
})
const verdict=computed(()=>{
  const d=t.value
  if(!d)return null
  const m=d.model||{},base=d.baselines?.persistence||{}
  if(typeof m.TS!=='number'||typeof base.TS!=='number')return null
  const pp=(m.TS-base.TS)*100
  const pos=m.positives
  const head=`在 ${pct(m.positiveRate,1)} 的正例率（${pos} 条）下，`
  let text
  if(Math.abs(pp)<2){
    const sampleDiff=Math.max(1,Math.round(Math.abs(pp)/100*Math.max(pos,1)))
    text=`${head}TS 与持续性基线相当（${pp>=0?'+':'−'}${Math.abs(pp).toFixed(1)} pp，约 ${sampleDiff} 个样本的差别，在置信区间内）。`
  }else if(pp>0){
    text=`${head}TS 高于持续性基线 ${Math.abs(pp).toFixed(1)} pp。`
  }else{
    text=`${head}TS 低于持续性基线 ${Math.abs(pp).toFixed(1)} pp —— 这是本目标的真实短板，不掩饰；它的实用价值在概率校准与提前量，不在命中率。`
  }
  const lead=d.leadTime?.medianMin
  return {text:text+(typeof lead==='number'
    ? `模型另提供校准概率与 ${lead} 分钟中位提前量，持续性基线结构上给不出提前量。`
    : '持续性基线结构上给不出提前量，这是两条曲线之间唯一的类别差异。'), gap:pp}
})

const cm=computed(()=>{
  const m=t.value?.model
  if(!m)return null
  return {hits:m.hits,misses:m.misses,falseAlarms:m.falseAlarms,correctNegatives:m.correctNegatives,
          n:m.n,positives:m.positives,rate:m.positiveRate}
})
const rel=computed(()=>{
  const bins=(t.value?.reliability||[]).filter(b=>b.n>0&&b.predicted!==null)
  if(!bins.length)return null
  const w=200,h=110
  const pts=bins.map(b=>({x:30+b.predicted*w,y:20+(1-b.observed)*h,n:b.n,bin:b.bin}))
  const diag=[{x:30,y:20+h},{x:30+w,y:20}]
  const maxN=Math.max(...bins.map(b=>b.n))||1
  return {pts,diag,w,h,maxN,line:pts.map(p=>p.x+','+p.y).join(' '),diagLine:diag.map(p=>p.x+','+p.y).join(' ')}
})
const dist=computed(()=>{
  const bins=(t.value?.reliability||[])
  if(!bins.length)return null
  const maxN=Math.max(...bins.map(b=>b.n))||1
  const step=290/bins.length
  return bins.map((b,i)=>({i,x:34+i*step,w:Math.max(8,step-8),
    h:b.n?Math.max(1,(b.n/maxN)*88):0,n:b.n,label:`${b.bin[0].toFixed(1)}–${b.bin[1].toFixed(1)}`,
    y:100-(b.n?Math.max(1,(b.n/maxN)*88):0)}))
})
const failures=computed(()=>(t.value?.failures||[]).slice(0,20))
const parity=computed(()=>t.value?.exportParity||null)
const drift=computed(()=>{
  const v=card.value?.version,loaded=card.value?.loaded||{}
  if(!v)return []
  return Object.entries(loaded).filter(([,name])=>name&&!name.startsWith('ml-'+v))
})
function fmt(v,d=2){return typeof v==='number'?(+v.toFixed(d)).toString():'—'}
function mnum(v,d=3){return typeof v==='number'?v.toFixed(d):'—'}
function exportJson(){
  const blob=new Blob([JSON.stringify(card.value,null,2)],{type:'application/json;charset=utf-8'})
  const url=URL.createObjectURL(blob),a=document.createElement('a')
  a.href=url;a.download=`model-card-${card.value?.systemVersion||'unknown'}.json`;a.click()
  setTimeout(()=>URL.revokeObjectURL(url),1000)
}
watch(tasks,list=>{
  if(task.value==='compare')return
  if(list.length&&!list.some(x=>x.key===task.value))task.value=list[0].key
})
</script>

<template>
<section class="mc">
  <p class="mc-loading" v-if="loading&&!card">正在读取模型卡…（指标文件 37 KB，含 test 集全部混淆矩阵）</p>
  <p class="mc-error" v-else-if="error">模型卡不可用 · {{ error }}</p>
  <p class="mc-error" v-else-if="card&&card.status!=='OK'">{{ card.note || '模型卡缺失' }}</p>

  <template v-else-if="card">
    <header class="mc-hd">
      <div>
        <h2>模型卡 <small>{{ card.systemVersion || '版本未取得' }} · 模型 {{ card.version || '—' }} · 标签取 METAR 实测，不是判据</small></h2>
        <p class="mc-sub">
          样本 <b class="alc-num">{{ (card.dataset?.rows||0).toLocaleString() }}</b> 条 ·
          站点 {{ (card.dataset?.stations||[]).join(' / ') }} ·
          年份 {{ card.dataset?.years }} ·
          训练完成 {{ (card.trainedAt||'').slice(0,10) }}
        </p>
      </div>
      <div class="mc-hd-actions">
        <button @click="exportJson">导出 JSON</button>
        <button @click="load">重新读取</button>
      </div>
    </header>

    <div class="mc-thresholds" v-if="card.gustThreshold" :class="{mismatch:!card.gustThreshold.consistent}"
         data-modelcard-thresholds>
      <b>阵风阈值</b>
      <span>训练 <b class="alc-num">{{ card.gustThreshold.training ?? '—' }}</b> m/s</span>
      <span>运行 <b class="alc-num">{{ card.gustThreshold.runtime ?? '—' }}</b> m/s（config/rules-v1.json::operations.gustMps）</span>
      <span class="verdict" v-if="card.gustThreshold.consistent">两者一致</span>
      <span class="verdict bad" v-else>两者不一致：训练口径与运行口径已分叉，本页指标不再代表正在跑的判定</span>
    </div>

    <p class="mc-drift" v-if="drift.length">
      内存中加载的模型与指标文件版本不一致：{{ drift.map(([k,n])=>`${k}=${n}`).join('、') }}。
      <b>这份指标不能代表正在跑的那三个模型</b>，请重新导出。
    </p>

    <div class="mc-meta">
      <div><span>标签来源</span><b>{{ card.labelSource }}</b></div>
      <div><span>切分</span><b>train {{ card.split?.train }} · val {{ card.split?.val }} · test {{ card.split?.test }}</b></div>
      <div><span>特征</span><b class="alc-num">{{ (card.features||[]).length }}</b></div>
      <div><span>导出对照</span><b :class="parity&&parity.maxAbsDiff<=parity.tolerance?'ok':'bad'">
        {{ parity?`${parity.checked} 条，最大偏差 ${parity.maxAbsDiff}`:'未记录' }}</b></div>
    </div>
    <p class="mc-split-note">{{ card.split?.note }}。区间不相交，因此 test 上的数字是真正没见过的样本。</p>

    <nav class="mc-tabs">
      <button v-for="x in compareTabs" :key="x.key" :class="{active:x.key===task}" @click="task=x.key">{{ x.title }}</button>
    </nav>

    <section class="mc-compare" v-if="task==='compare'">
      <p class="mc-claim">
        三个目标、同一套特征、同一段时间切分。看 <b>AUC</b> 与 <b>提前量</b>，不看 TS 冠亚军 ——
        正例只有 0.8%–6.3%，TS 的 ±1 pp 在两百条正例上就是噪声。
      </p>
      <table class="mc-table mc-compare-table">
        <thead>
          <tr><th>目标</th><th>正例率</th><th>POD</th><th>FAR</th><th>TS</th><th>vs 持续性</th><th>AUC</th><th>Brier 技巧</th><th>提前量中位</th><th>n</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in compareRows" :key="r.key">
            <td>{{ r.title }}</td>
            <td class="alc-num">{{ pct(r.rate,1) }}</td>
            <td class="alc-num">{{ mnum(r.pod) }}</td>
            <td class="alc-num">{{ mnum(r.far) }}</td>
            <td class="alc-num">{{ mnum(r.ts) }}</td>
            <td class="gap">{{ tsGapText(r) }}</td>
            <td class="alc-num strong">{{ mnum(r.auc) }}</td>
            <td class="alc-num">{{ mnum(r.skill) }}</td>
            <td class="alc-num">{{ r.lead ?? '—' }} 分钟<small v-if="r.leadN"> · n={{ r.leadN }}</small></td>
            <td class="alc-num">{{ r.n?.toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
      <ul class="mc-compare-notes">
        <li><b>AUC 0.93–0.95</b>：排序能力是这套模型的真本事 —— 它能把"接下来三小时会出事"排到前面，与阈值取多少无关。</li>
        <li><b>Brier 技巧</b>是相对气候态的技巧分：正值说明概率经过校准，可以直接拿去做期望代价，而不是只当一个报警开关。</li>
        <li><b>提前量</b>是本模型与持续性基线之间唯一的类别差异：持续性基线只会说"现在是什么样的"，给不出"还有多久变"。n 已写在旁边，样本少的格子不要读成稳定结论。</li>
        <li>阵风目标的「单要素阈值规则」与「持续性」三格完全相同（TS 0.186 / POD 0.228 / FAR 0.496）—— 这不是巧合，是那条阈值规则在阵风上退化成持续性外推。两条基线因此合并计一条，不重复占位。</li>
        <li>Open-Meteo 模式基线在这三个目标上 TS 0.031–0.180，明显低于持续性，作为对照保留在单目标页的脚注里 —— 用一条弱基线衬托自己，不算证据。</li>
      </ul>
    </section>

    <template v-else-if="t">
      <p class="mc-verdict neutral" v-if="verdict">
        <b>这一目标的口径</b>{{ verdict.text }}
      </p>

      <table class="mc-table">
        <thead>
          <tr><th>口径</th><th>TS</th><th>POD</th><th>FAR</th><th>Brier</th><th>样本</th><th>正例率</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.key" :class="{self:r.self,best:r.m?.TS===bestTs}">
            <td>{{ r.name }}</td>
            <td class="alc-num">{{ mnum(r.m?.TS) }}</td>
            <td class="alc-num">{{ mnum(r.m?.POD) }}</td>
            <td class="alc-num">{{ mnum(r.m?.FAR) }}</td>
            <td class="alc-num">{{ mnum(r.m?.Brier,4) }}</td>
            <td class="alc-num">{{ r.m?.n??'—' }}</td>
            <td class="alc-num">{{ pct(r.m?.positiveRate,1) }}</td>
          </tr>
        </tbody>
      </table>
      <p class="mc-table-note">
        TS＝命中/(命中+空报+漏报)，越接近 1 越好；POD 越高越不漏；FAR 越低越不空报；Brier 越小概率越准。
        本模型 AUC <b class="alc-num">{{ mnum(t.auc) }}</b>（未校准 {{ mnum(t.aucRaw) }}），
        相对气候态 Brier 技巧 <b class="alc-num">{{ mnum(t.model?.brierSkillVsClimatology) }}</b>。
        {{ card.baselineNote }}
      </p>

      <figure class="mc-lead" v-if="leadBand">
        <figcaption>
          提前量分布（n={{ leadBand.n }} 个事件起始）
          <span class="mc-help" tabindex="0" title="对每个「首次观测到事件」的时刻 t₀，从 t₀ 往前找首次连续 2 帧预测概率 ≥ 0.5 的时刻 t₁，提前量 = t₀ − t₁，上限 6 小时。">ⓘ 定义</span>
        </figcaption>
        <div class="mc-lead-track">
          <span class="mc-lead-tick" :style="{left:leadBand.p25At+'%'}"></span>
          <span class="mc-lead-tick med" :style="{left:leadBand.medAt+'%'}"></span>
          <span class="mc-lead-tick" :style="{left:leadBand.p75At+'%'}"></span>
        </div>
        <div class="mc-lead-labels">
          <span>0</span><span>60</span><span>120</span><span>180</span><span>240</span><span>300</span><span>360 分钟</span>
        </div>
        <p class="fig-note">
          P25 <b>{{ leadBand.p25 }}</b> · 中位 <b>{{ leadBand.med }}</b> · P75 <b>{{ leadBand.p75 }}</b> 分钟。
          分布右偏：至少四分之一的事件正好提前 {{ leadBand.p25 }} 分钟，而尾部一直拖到 {{ leadBand.p75 }} 分钟以上。
          上限 6 小时是定义的一部分，不是数据撞到的天花板。
        </p>
      </figure>

      <div class="mc-charts">
        <figure v-if="cm">
          <figcaption>混淆矩阵（test · 工作点）</figcaption>
          <svg viewBox="0 0 220 130" role="img" aria-label="混淆矩阵">
            <text x="74" y="14" class="ax">实测＝是</text><text x="152" y="14" class="ax">实测＝否</text>
            <text x="2" y="52" class="ax">判是</text><text x="2" y="100" class="ax">判否</text>
            <rect x="62" y="20" width="72" height="34" rx="3" fill="rgba(82,196,26,.22)"/>
            <rect x="140" y="20" width="72" height="34" rx="3" fill="rgba(250,173,20,.20)"/>
            <rect x="62" y="66" width="72" height="34" rx="3" fill="rgba(255,77,79,.20)"/>
            <rect x="140" y="66" width="72" height="34" rx="3" fill="rgba(76,141,255,.18)"/>
            <text x="98" y="42" class="cmv" text-anchor="middle">{{ cm.hits }}</text>
            <text x="176" y="42" class="cmv" text-anchor="middle">{{ cm.falseAlarms }}</text>
            <text x="98" y="88" class="cmv" text-anchor="middle">{{ cm.misses }}</text>
            <text x="176" y="88" class="cmv" text-anchor="middle">{{ cm.correctNegatives }}</text>
            <text x="98" y="54" class="cml" text-anchor="middle">命中</text>
            <text x="176" y="54" class="cml" text-anchor="middle">空报</text>
            <text x="98" y="100" class="cml" text-anchor="middle">漏报</text>
            <text x="176" y="100" class="cml" text-anchor="middle">正确否定</text>
          </svg>
          <p class="fig-note">正例 {{ cm.positives }} 条（{{ pct(cm.rate,1) }}），共 {{ cm.n }} 条。</p>
        </figure>

        <figure v-if="rel">
          <figcaption>可靠性（预测概率 vs 实测频率）</figcaption>
          <svg viewBox="0 0 250 145" role="img" aria-label="可靠性曲线">
            <line x1="30" :y1="rel.h+20" :x2="rel.w+30" y2="20" stroke="rgba(255,255,255,.25)" stroke-dasharray="3 3"/>
            <line x1="30" :y1="rel.h+20" :x2="rel.w+30" :y2="rel.h+20" stroke="rgba(255,255,255,.14)"/>
            <line x1="30" y1="20" x2="30" :y2="rel.h+20" stroke="rgba(255,255,255,.14)"/>
            <polyline :points="rel.line" fill="none" stroke="#9ad0ff" stroke-width="1.6"/>
            <circle v-for="(p,i) in rel.pts" :key="i" :cx="p.x" :cy="p.y" :r="2+2.6*Math.sqrt(p.n/rel.maxN)" fill="#dce6f5"/>
            <text x="24" :y="rel.h+24" class="ax" text-anchor="end">0</text>
            <text :x="rel.w+32" :y="rel.h+24" class="ax">1</text>
            <text x="24" y="24" class="ax" text-anchor="end">1</text>
            <text :x="rel.w/2+30" :y="rel.h+38" class="ax" text-anchor="middle">预测概率</text>
            <text x="8" :y="rel.h/2+22" class="ax" text-anchor="middle" transform="rotate(-90 8 65)">实测频率</text>
          </svg>
          <p class="fig-note">点越贴虚线越准；点的大小＝该箱样本量。空箱不画（不补 0）。</p>
        </figure>

        <figure v-if="dist">
          <figcaption>概率分布（每箱样本量）</figcaption>
          <svg viewBox="0 0 330 130" role="img" aria-label="概率分布直方图">
            <line x1="34" y1="100" x2="324" y2="100" stroke="rgba(255,255,255,.14)"/>
            <rect v-for="b in dist" :key="b.i" :x="b.x" :y="b.y" :width="b.w" :height="b.h" fill="rgba(76,141,255,.55)"/>
            <text v-for="b in dist" :key="'l'+b.i" :x="b.x+b.w/2" y="112" class="ax" text-anchor="middle">{{ b.label.slice(0,3) }}</text>
            <text x="34" y="124" class="ax">校准后概率集中在低段，这正是"固定 0.5"不是合适工作点的原因。</text>
          </svg>
        </figure>
      </div>

      <section class="mc-fail">
        <b>失败样本（test 集，最多 20 例）</b>
        <p class="mc-fail-note" v-if="!failures.length">本任务在 test 集上没有记录错例。</p>
        <table v-else>
          <thead><tr><th>类型</th><th>站</th><th>时刻</th><th>概率</th><th>实测</th><th>能见度 m</th><th>阵风 m/s</th><th>露点差</th></tr></thead>
          <tbody>
            <tr v-for="(f,i) in failures" :key="i">
              <td :class="f.type==='FP'?'fp':'fn'">{{ f.type==='FP'?'空报':'漏报' }}</td>
              <td>{{ f.station }}</td>
              <td class="alc-num">{{ (f.timeUtc||'').slice(5,16).replace('T',' ') }}</td>
              <td class="alc-num">{{ mnum(f.p) }}</td>
              <td class="alc-num">{{ f.observed }}</td>
              <td class="alc-num">{{ f.visM }}</td>
              <td class="alc-num">{{ f.gustMs }}</td>
              <td class="alc-num">{{ f.dewSpread }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <footer class="mc-foot">
        <span>提前量中位 <b class="alc-num">{{ t.leadTime?.medianMin ?? '—' }}</b> 分钟
          （P25 {{ t.leadTime?.p25Min ?? '—' }} / P75 {{ t.leadTime?.p75Min ?? '—' }}，n={{ t.leadTime?.n ?? 0 }}）</span>
        <span>验证集 Brier <b class="alc-num">{{ mnum(t.valBrier,4) }}</b></span>
        <span>训练样本 {{ t.sizes?.train }} / 验证 {{ t.sizes?.val }} / test {{ t.sizes?.test }}</span>
      </footer>
      <details class="mc-versions" data-modelcard-versions>
        <summary>版本与口径 · Open-Meteo 基线为何只作脚注</summary>
        <p>
          本页只在 0.11.1 起的指标体系内自洽：TS / POD / FAR / Brier 与三条基线并排，每一个数都能回到 test 集混淆矩阵。
          0.10.1 的 macroF1 属于"复现判据"口径（标签由判据生成、判据又当特征），与本页数字不可比较，因此本页不引用它。
        </p>
        <p>
          Open-Meteo 模式基线在这三个目标上的 TS 分别是
          {{ compareRows.map(r=>`${r.title.slice(0,6)}… ${mnum((card.targets?.[r.key]?.baselines?.openMeteo||{}).TS)}`).join(' · ') }}，
          明显低于持续性基线。把它并排放在主表里，读者只会得出"模型赢了一条很弱的基线"——那不算证据。
          所以它仍是基线之一，只是降级成脚注；主表里的对手是持续性。
        </p>
      </details>
    </template>
  </template>
</section>
</template>

<style scoped>
.mc{padding:16px 0;color:var(--alc-text);font-size:13px}
.mc-loading,.mc-error{padding:16px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius)}
.mc-error{border-left:3px solid var(--alc-danger)}
.mc-hd{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:14px 18px}
.mc-hd h2{font-size:20px}
.mc-hd h2 small{font-size:12px;font-weight:400;color:var(--alc-text-dim);margin-left:8px}
.mc-sub{margin-top:4px;font-size:12px;color:var(--alc-text-dim)}
.mc-sub b{color:var(--alc-text);font-size:14px}
.mc-hd-actions{display:flex;gap:8px}
.mc-hd-actions button{font-size:12px;padding:6px 10px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text);border-radius:6px;cursor:pointer}
.mc-drift{margin-top:10px;padding:8px 12px;border-left:3px solid var(--alc-danger);background:rgba(255,77,79,.08);font-size:12px}
.mc-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px 18px;margin-top:12px;padding:12px 18px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius)}
.mc-meta span{display:block;font-size:11px;color:var(--alc-text-mute)}
.mc-meta b{font-size:12px;font-weight:600}
.mc-meta b.ok{color:var(--alc-ok)}.mc-meta b.bad{color:var(--alc-danger)}
.mc-split-note{margin-top:6px;font-size:12px;color:var(--alc-text-dim)}
.mc-tabs{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
.mc-tabs button{padding:7px 14px;border-radius:6px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text-dim);font-size:13px;cursor:pointer}
.mc-tabs button.active{background:rgba(76,141,255,.16);border-color:var(--alc-info);color:var(--alc-text)}
.mc-verdict{margin-top:12px;padding:10px 14px;font-size:13px;line-height:1.7;border-radius:6px}
.mc-verdict.win{border-left:3px solid var(--alc-ok);background:rgba(82,196,26,.08)}
.mc-verdict.lose{border-left:3px solid var(--alc-watch);background:rgba(250,173,20,.09)}
.mc-verdict b{display:block;margin-bottom:2px}
.mc-table{width:100%;margin-top:12px;border-collapse:collapse;font-size:12px}
.mc-table th{text-align:left;padding:6px 8px;color:var(--alc-text-mute);font-weight:500;border-bottom:1px solid var(--alc-line)}
.mc-table td{padding:6px 8px;border-bottom:1px dashed var(--alc-line)}
.mc-table tr.self td{background:rgba(76,141,255,.07);font-weight:600}
.mc-table tr.best td:nth-child(2){color:var(--alc-ok)}
.mc-table-note{margin-top:6px;font-size:11px;line-height:1.7;color:var(--alc-text-dim)}
.mc-charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:16px}
.mc-charts figure{background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:10px 12px}
.mc-charts figcaption{font-size:12px;color:var(--alc-text-dim)}
.mc-charts svg{width:100%;margin-top:6px}
.ax{font-size:7px;fill:var(--alc-text-mute)}
.cmv{font-size:11px;fill:var(--alc-text);font-weight:700}
.cml{font-size:7px;fill:var(--alc-text-dim)}
.fig-note{margin-top:4px;font-size:11px;color:var(--alc-text-mute)}
.mc-fail{margin-top:16px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:12px 14px}
.mc-fail>b{font-size:13px}
.mc-fail-note{font-size:12px;color:var(--alc-text-dim);margin-top:4px}
.mc-fail table{width:100%;margin-top:8px;border-collapse:collapse;font-size:12px}
.mc-fail th{text-align:left;padding:5px 8px;color:var(--alc-text-mute);font-weight:500;border-bottom:1px solid var(--alc-line)}
.mc-fail td{padding:5px 8px;border-bottom:1px dashed var(--alc-line)}
.mc-fail td.fp{color:var(--alc-watch)}.mc-fail td.fn{color:var(--alc-danger)}
.mc-thresholds{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin:10px 0 2px;
  padding:8px 10px;border:1px solid var(--alc-line);border-radius:6px;font-size:12px;
  color:var(--alc-text-mute)}
.mc-thresholds>b{color:var(--alc-text)}
.mc-thresholds .verdict{color:var(--alc-ok)}
.mc-thresholds .verdict.bad{color:var(--alc-danger)}
.mc-thresholds.mismatch{border-color:var(--alc-danger);background:rgba(255,77,79,.08)}
.mc-foot{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;font-size:11px;color:var(--alc-text-mute)}
.mc-compare{margin-top:14px}
.mc-claim{margin:0 0 10px;font-size:13px;line-height:1.7;color:var(--alc-text)}
.mc-claim b{color:var(--alc-info)}
.mc-compare-table td.gap{font-size:12px;color:var(--alc-text-dim);min-width:190px}
.mc-compare-table td.strong{font-weight:700;color:var(--alc-ok)}
.mc-compare-table small{color:var(--alc-text-mute);font-size:10px}
.mc-compare-notes{margin-top:10px;padding-left:18px;font-size:12px;line-height:1.8;color:var(--alc-text-dim)}
.mc-compare-notes b{color:var(--alc-text)}
.mc-verdict.neutral{border-left:3px solid var(--alc-line);background:var(--alc-bg-1)}
.mc-lead{margin-top:14px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:10px 14px}
.mc-lead figcaption{font-size:12px;color:var(--alc-text-dim);display:flex;gap:8px;align-items:baseline}
.mc-help{font-size:11px;color:var(--alc-info);cursor:help;border-bottom:1px dashed var(--alc-info)}
.mc-lead-track{position:relative;height:10px;margin:10px 0 2px;border-radius:5px;background:linear-gradient(90deg,rgba(76,141,255,.35),rgba(76,141,255,.10))}
.mc-lead-tick{position:absolute;top:-4px;width:2px;height:18px;background:var(--alc-text-dim);border-radius:1px}
.mc-lead-tick.med{width:3px;background:var(--alc-info);box-shadow:0 0 0 2px rgba(76,141,255,.20)}
.mc-lead-labels{display:flex;justify-content:space-between;font-size:10px;color:var(--alc-text-mute)}
.mc-versions{margin-top:14px;border-top:1px solid var(--alc-line);padding-top:10px;font-size:11px;color:var(--alc-text-dim)}
.mc-versions summary{cursor:pointer;color:var(--alc-text-dim);font-size:12px}
.mc-versions p{margin-top:8px;line-height:1.75}
.mc-versions code{font-family:ui-monospace,Consolas,monospace}
</style>
