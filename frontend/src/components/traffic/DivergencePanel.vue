<script setup>
import {computed,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'
import {pct} from '../../traffic/runtime.js'
import {deliverCsv,csvDeliveryText} from '../../traffic/clipboard.js'
const csvNote=ref('')

const props=defineProps({
  focusCorridor:{type:String,default:''},
  compact:{type:Boolean,default:false},
})
const data=ref(null),error=ref(''),loading=ref(false)
const VERDICT_LABEL={ACCEPT:'采纳模型判断',REJECT:'否决模型',MANUAL:'转人工复核'}
const ACTION_LABEL={RELEASE:'放行',DETOUR:'改绕飞',HOLD:'停飞'}

// 全国层没有服务端裁决台账（日志是按分钟重算的派生表，没有可写的历史），
// 人做过的事只落在 `alc.review.v1` —— 走廊页的「人工裁决」写的就是它。
// 以前这一页只读服务端，于是全国层永远是空表：不是"没人判过"，是"读错了地方"。
// 这里把本机记录并进同一张表：判定口径不变（与算法原判一致=采纳，不一致=否决），
// 列也一套 —— 两份记录并排，靠"操作人"区分来源。
const REVIEW_KEY='alc.review.v1'
function readLocal(){
  try{
    const table=JSON.parse(localStorage.getItem(REVIEW_KEY)||'{}')||{}
    return Object.entries(table).filter(([,rec])=>rec&&rec.action).map(([corridor,rec])=>{
      const auto=String(rec.auto||'').trim()
      return {
        at:'', corridorId:corridor, flightId:'', p:null, confidence:null,
        ruleLevel:auto||'—',
        verdict:auto&&rec.action===auto?'ACCEPT':'REJECT',
        note:[rec.reason||'', auto?`算法原判 ${ACTION_LABEL[auto]||auto}`:'',
              `人工 ${ACTION_LABEL[rec.action]||rec.action}`].filter(Boolean).join('；'),
        operator:'本机值班员 · 走廊页', local:true,
      }
    })
  }catch(_){return []}
}
const localRows=ref(readLocal())

async function load(){
  loading.value=true
  localRows.value=readLocal()          // 换了标签页再回来，本机记录要重读
  try{data.value=await requestJson('/api/traffic/v2/divergences?limit=50',{timeoutMs:15000});error.value=''}
  catch(e){error.value=e.message}
  finally{loading.value=false}
}
onMounted(load)

const allRows=computed(()=>[...localRows.value,...(data.value?.rows||[])])
const rows=computed(()=>{
  const focus=String(props.focusCorridor||'').trim()
  if(!focus)return allRows.value
  return allRows.value.filter(r=>String(r.corridorId||'')===focus)
})
const scoped=computed(()=>!!String(props.focusCorridor||'').trim())
const counts=computed(()=>{
  const c={ACCEPT:0,REJECT:0,MANUAL:0,other:0}
  for(const r of rows.value)c[r.verdict]!==undefined?c[r.verdict]++:c.other++
  return c
})
const decided=computed(()=>counts.value.ACCEPT+counts.value.REJECT+counts.value.MANUAL+counts.value.other)
const acceptRate=computed(()=>decided.value?counts.value.ACCEPT/decided.value:null)
const lowConfidence=computed(()=>rows.value.filter(r=>typeof r.confidence==='number'&&r.confidence<0.65).length)

async function exportCsv(){
  const head='at,corridorId,flightId,p,confidence,ruleLevel,verdict,operator,note\n'
  const body=rows.value.map(r=>[r.at,r.corridorId||'',r.flightId||'',r.p??'',r.confidence??'',
    r.ruleLevel??'',r.verdict||'',r.operator||'',
    '"'+String(r.note||'').replace(/"/g,'""')+'"'].join(',')).join('\n')
  csvNote.value=csvDeliveryText(await deliverCsv(head+body,'divergence-ledger.csv'))
}
</script>

<template>
<section class="dg">
  <p class="dg-state" v-if="loading&&!data">正在读取台账…</p>
  <p class="dg-state bad" v-else-if="error">台账不可用 · {{ error }}</p>

  <template v-else-if="data || localRows.length">
    <header class="dg-hd">
      <div>
        <h2 v-if="!compact">分歧台账 <small>AI 与规则不一致时，人的最终判断</small></h2>
        <p class="dg-sub" v-if="decided">
          共 <b class="alc-num">{{ allRows.length }}</b> 条 ·
          采纳 <b class="alc-num">{{ counts.ACCEPT }}</b> ·
          否决 <b class="alc-num">{{ counts.REJECT }}</b> ·
          转人工 <b class="alc-num">{{ counts.MANUAL }}</b>
          <template v-if="acceptRate!==null"> · 采纳率 <b class="alc-num">{{ pct(acceptRate) }}</b></template>
        </p>
        <p class="dg-sub" v-else>尚无裁决记录</p>
      </div>
      <div class="dg-actions">
        <button @click="exportCsv" :disabled="!rows.length">导出 CSV</button>
        <button @click="load">刷新</button>
      </div>
    </header>

    <div class="dg-empty" v-if="!rows.length">
      <b v-if="scoped">本走廊还没有人工复核记录。</b>
      <b v-else>台账为空，属当前状态，非加载失败。</b>
      <p>记录来源两处：走廊页「人工裁决」（放行 / 改绕飞 / 停飞，存于本浏览器）与预警中心处置按钮（采纳 / 否决 / 转人工，存于服务端台账）。</p>
      <p v-if="scoped && allRows.length">全库共 {{ allRows.length }} 条，但都不在本走廊。</p>
      <p>本版本没有回放式补录：宁可空着，也不塞占位内容充数。</p>
    </div>

    <template v-else>
      <p class="dg-note" v-if="lowConfidence">其中 {{ lowConfidence }} 条发生于置信度低于 0.65 时，此时系统建议转人工。该组复盘优先级最高。</p>
      <table class="dg-table">
        <thead>
          <tr><th>时间（UTC）</th><th>走廊</th><th>航班</th><th>不可飞概率</th><th>置信度</th>
            <th>规则等级</th><th>处置</th><th>理由</th><th>操作人</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r,i) in rows" :key="i" :class="{lo:typeof r.confidence==='number'&&r.confidence<0.65}">
            <td class="alc-num">{{ (r.at||'').replace('T',' ').replace('Z','') }}</td>
            <td>{{ r.corridorId || '—' }}</td>
            <td>{{ r.flightId || '—' }}</td>
            <td class="alc-num">{{ pct(r.p,1) }}</td>
            <td class="alc-num">{{ typeof r.confidence==='number'?r.confidence.toFixed(2):'—' }}</td>
            <td class="alc-num">{{ r.ruleLevel ?? '—' }}</td>
            <td :class="'v-'+(r.verdict||'other')">{{ VERDICT_LABEL[r.verdict] || r.verdict || '—' }}</td>
            <td class="note">{{ r.note || '（未填）' }}</td>
            <td class="op">{{ r.operator || 'operator' }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <footer class="dg-foot">
      <span v-if="data?.note && !allRows.length">{{ data.note }}</span>
      <span>服务端台账按工作区（<code>X-ALC-Workspace</code>）隔离，工作区之间互不可见；
        标注「本机值班员 · 走廊页」的记录存放于浏览器本地，更换设备后不再显示。</span>
      <span>否决与回滚须填写理由，理由为空时接口返回 422。</span>
    </footer>
  </template>
</section>
</template>

<style scoped>
.dg{padding:16px 0;color:var(--alc-text);font-size:13px}
.dg-state{padding:16px;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius)}
.dg-state.bad{border-left:3px solid var(--alc-danger)}
.dg-hd{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);padding:14px 18px}
.dg-hd h2{font-size:20px}
.dg-hd h2 small{font-size:12px;font-weight:400;color:var(--alc-text-dim);margin-left:8px}
.dg-sub{margin-top:4px;font-size:12px;color:var(--alc-text-dim)}
.dg-sub b{color:var(--alc-text);font-size:14px}
.dg-actions{display:flex;gap:8px}
.dg-actions button{font-size:12px;padding:6px 10px;border:1px solid var(--alc-line);background:var(--alc-bg-2);color:var(--alc-text);border-radius:6px;cursor:pointer}
.dg-actions button:disabled{opacity:.45;cursor:not-allowed}
.dg-empty{margin-top:12px;padding:16px 18px;background:var(--alc-bg-1);border:1px dashed var(--alc-line);border-radius:var(--alc-radius)}
.dg-empty b{font-size:14px}
.dg-empty p{margin-top:6px;font-size:12px;line-height:1.8;color:var(--alc-text-dim)}
.dg-note{margin-top:10px;padding:8px 12px;border-left:3px solid var(--alc-watch);background:rgba(250,173,20,.08);font-size:12px}
.dg-table{width:100%;margin-top:12px;border-collapse:collapse;font-size:12px}
.dg-table th{text-align:left;padding:6px 8px;color:var(--alc-text-mute);font-weight:500;border-bottom:1px solid var(--alc-line)}
.dg-table td{padding:6px 8px;border-bottom:1px dashed var(--alc-line);vertical-align:top}
.dg-table tr.lo td{background:rgba(250,173,20,.05)}
.dg-table td.note{color:var(--alc-text-dim);max-width:280px}
.dg-table td.op{color:var(--alc-text-mute)}
.v-ACCEPT{color:var(--alc-ok)}
.v-REJECT{color:var(--alc-danger)}
.v-MANUAL{color:var(--alc-watch)}
.dg-foot{display:flex;flex-direction:column;gap:4px;margin-top:14px;font-size:11px;color:var(--alc-text-mute)}
</style>
