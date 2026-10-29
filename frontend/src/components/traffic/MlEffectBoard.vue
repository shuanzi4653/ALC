<script setup>
import {computed,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'
import {buildMlEffectView,ML_EFFECT_SNAPSHOT} from '../../traffic/runtime.js'

const snapshot=computed(()=>buildMlEffectView(ML_EFFECT_SNAPSHOT))

const runtime=ref(null),runtimeError=ref('')

onMounted(async()=>{
  try{
    runtime.value=await requestJson('/api/track1/ml/summary?hours=24',{timeoutMs:8000})
  }catch(err){
    runtimeError.value=err?.message||'一致性读不到'
  }
})

const runtimeText=computed(()=>{
  const doc=runtime.value
  if(!doc)return null
  if(doc.available===false)return {state:'unavailable',text:'一致性台账不可用（这一版还没有建表或查询失败），不显示任何比例。'}
  if(doc.empty||doc.total===0)return {state:'empty',text:'最近 24 小时没有推理留痕 —— 不是"一致率 0"，是"还没跑过"。'}
  const agree=doc.agreement||{}
  const rate=agree.rate
  return {
    state:'ok',
    text:rate===null||rate===undefined
      ?`可比轮次 0：模型一次都没有参与，因此不显示一致率。`
      :`可比 ${agree.comparable} 轮，同档 ${agree.agree} 轮、分歧 ${agree.disagree} 轮，一致率 ${(rate*100).toFixed(1)}%；另有 ${agree.notComparable} 轮模型未参与（不计入分母）。`,
  }
})
</script>

<template>
  <div class="briefing-block" data-ml-effect>
    <div class="briefing-head"><h3>三列对照：规则 / 模型 / 人工仲裁</h3><small>训练期 · {{snapshot.samples}} 条样本 · 测试 {{snapshot.sizes.test}} 条</small></div>
    <p class="briefing-note">三列回答的<b>不是同一个问题</b>：规则列是运行放行那套（累减扣分、一票封顶），模型列学的是标注判据（逐要素分段、取最坏档），人工仲裁列是两者分歧样本的复核表。<b>不要把规则列与模型列当同一把尺比的两次读数</b>——它们的难度不同。</p>

    <div class="ml-columns">
      <article v-for="row in snapshot.rows" :key="row.key" :class="{best:snapshot.best===row.key,unmeasured:!row.measured}"
               :data-ml-column="row.key">
        <header><b>{{row.label}}</b><small>{{row.source}}</small></header>
        <strong>{{row.macroF1Text}}</strong>
        <small class="ml-metric">macroF1<template v-if="!row.measured"> · 待标注</template></small>
        <dl>
          <dt>准确率</dt><dd>{{row.accuracyText}}</dd>
          <dt>危险漏报</dt><dd>{{row.dangerMissText}}</dd>
          <dt>样本</dt><dd>{{row.denominator}}</dd>
        </dl>
        <p>{{row.note}}</p>
        <small class="ml-scoring">评分项：技术先进性 · 模型有效性（分值待核，页面上不写未核实的数字）</small>
      </article>
    </div>

    <p class="briefing-note">{{snapshot.bestNote}}</p>
    <p class="briefing-note" data-ml-caveat>{{snapshot.caveat}}</p>

    <div class="ml-annotation" v-if="snapshot.annotation" data-ml-annotation>
      <b>独立第二标注员（{{snapshot.annotation.tool}}）</b>
      <span>{{snapshot.annotation.count}} 条 · 失败 {{snapshot.annotation.failed}} · 一致率 {{(snapshot.annotation.raw*100).toFixed(1)}}% · 二次加权 κ {{snapshot.annotation.weightedKappa.toFixed(4)}}</span>
      <p>{{snapshot.annotation.note}}（来源：{{snapshot.annotation.source}}）</p>
    </div>

    <div class="ml-runtime" data-ml-runtime>
      <b>运行期一致性（最近 24 小时留痕）</b>
      <p v-if="runtimeError">{{runtimeError}} —— 不显示比例。</p>
      <p v-else-if="!runtimeText">正在读取留痕…</p>
      <p v-else :class="runtimeText.state">{{runtimeText.text}}</p>
      <small>训练期那张表衡量"能否复现判据"（0.10.1 轨1 口径，非 0.11.1 的预测能力）；这一行衡量"线上这一段时间里两边同档了几次"。两者分母不同，不能相加、不能互推。</small>
    </div>
  </div>
</template>

<style scoped>
.ml-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:14px}
.ml-columns article{background:#152b3c;border:1px solid #294859;border-radius:8px;padding:14px;min-width:0}
.ml-columns article.best{border-color:#2f6f5a;box-shadow:inset 0 0 0 1px #2f6f5a}
.ml-columns article.unmeasured{border-style:dashed}
.ml-columns header{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.ml-columns header b{font-size:13px;color:#d8ecf8;font-weight:500}
.ml-columns header small{font-size:10px;color:#6b8aa0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%}
.ml-columns strong{display:block;font-size:26px;margin:8px 0 0;color:#a8e9e7;font-weight:500}
.ml-metric{font-size:10px;color:#7fa3b8}
.ml-columns dl{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;margin:10px 0;font-size:11px}
.ml-columns dt{color:#7fa3b8}
.ml-columns dd{margin:0;color:#d8ecf8}
.ml-columns p{font-size:11px;color:#a9c6d8;line-height:1.75;margin:6px 0 0}
.ml-scoring{display:block;font-size:10px;color:#6b8aa0;margin-top:10px;padding-top:8px;border-top:1px dashed #24404f}
.ml-annotation{margin-top:14px;padding:12px;background:#132a3a;border-left:3px solid #3d8bff;border-radius:6px}
.ml-annotation b{font-size:12px;color:#cfe6f5}
.ml-annotation span{display:block;font-size:11.5px;color:#a8e9e7;margin-top:6px}
.ml-annotation p{font-size:10.5px;color:#8aa8b9;margin:6px 0 0;line-height:1.8}
.ml-runtime{margin-top:14px;padding:12px;background:#132a3a;border-left:3px solid #63c5cb;border-radius:6px}
.ml-runtime b{font-size:12px;color:#cfe6f5}
.ml-runtime p{font-size:11.5px;color:#c5dceb;margin:6px 0 0;line-height:1.8}
.ml-runtime p.empty{color:#f1c77f}
.ml-runtime p.unavailable{color:#ffd9a8}
.ml-runtime small{display:block;font-size:10px;color:#7d9cb0;margin-top:8px;line-height:1.7}
</style>
