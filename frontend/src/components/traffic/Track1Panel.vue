<script setup>
import {computed,ref,watch,onUnmounted} from 'vue'
import {postAction} from '../../api.js'
import {buildTrack1View,track1SnapshotOf} from '../../traffic/runtime.js'

const props=defineProps({
  weather:Object,
  minute:{type:Number,default:0},
  cityId:{type:String,default:''},
  session:Object,
})

const loading=ref(false),error=ref(''),result=ref(null),lastKey=ref('')
let token=0

const observation=computed(()=>{
  const list=Array.isArray(props.weather?.observations)?props.weather.observations:[]
  if(!list.length)return null
  if(props.cityId){const hit=list.find(item=>item&&item.cityId===props.cityId);if(hit)return hit}
  return list[0]
})
const observedCity=computed(()=>observation.value?.cityName||observation.value?.cityId||'—')

const view=computed(()=>buildTrack1View({
  rule:result.value?.rule||null,
  model:result.value?.model||null,
}))

const key=computed(()=>{
  const snap=track1SnapshotOf(observation.value)
  return [props.cityId,snap.sampleKey,JSON.stringify(snap.snapshot)].join('|')
})

async function run(){
  const snap=track1SnapshotOf(observation.value)
  if(!snap.present.length){error.value='';result.value=null;return}
  const mine=++token
  loading.value=true;error.value=''
  try{
    const body={snapshot:snap.snapshot,hour:Number.isFinite(props.minute)?(props.minute/60)%24:undefined,
      month:new Date().getUTCMonth()+1}
    if(snap.sampleKey)body.sampleKey=snap.sampleKey
    if(snap.timeBasis)body.timeBasis=snap.timeBasis
    const data=await postAction('/api/track1/arbitrate',body,12_000)
    if(mine!==token)return
    result.value=data
    lastKey.value=key.value
  }catch(err){
    if(mine!==token)return
    result.value=null
    error.value=err?.status===422
      ?`规则拒判：${err.message}（没有档位就是没有档位，不拿兜底值顶上）`
      :(err?.message||'研判失败')
  }finally{
    if(mine===token)loading.value=false
  }
}

watch([key,()=>props.minute],([value],[previous])=>{
  if(!observation.value)return
  if(value===previous&&lastKey.value===value)return
  if(lastKey.value===value)return
  run()
},{immediate:true})

onUnmounted(()=>{token+=1})

const confidenceText=computed(()=>{
  const value=view.value.model.confidence
  return value===null?'—':`${(value*100).toFixed(0)}%`
})
const sfiText=computed(()=>{
  const value=view.value.rule.sfi
  return value===null?'—':String(Math.round(value))
})
</script>

<template>
  <section class="track1-panel" data-track1-card>
    <div class="briefing-head">
      <h3>轨1 研判：规则与模型各说了什么</h3>
      <small>{{observedCity}} · 第 {{minute.toFixed(0)}} 分钟 · 模型 {{view.model.modelVersion||'—'}}</small>
    </div>
    <p class="briefing-note">放行、关闭、改航的档位始终由规则给出。模型只能把结论<b>变得更保守</b>，不能让它更乐观 —— 这一条写死在服务端，不在本页面比较。</p>

    <p class="track1-error" v-if="error" data-track1-error>{{error}}</p>
    <p class="briefing-note" v-else-if="!observation" data-track1-empty>当前没有可研判的观测（这一轮气象源没有返回任何城市读数）。不显示档位：没有要素就没有结论。</p>
    <p class="briefing-note" v-else-if="loading&&!result">正在取规则档位与模型档位…</p>

    <template v-if="result">
      <ol class="track1-decisions" data-track1-decisions>
        <li v-for="item in view.decisions" :key="item.key" :class="item.tone"
            :data-track1-decision="item.key">
          <b>{{item.label}}</b>
          <em v-if="view.decision===item.key" data-track1-current>当前</em>
        </li>
      </ol>

      <div class="track1-grid">
        <article class="track1-block" data-track1-rule>
          <header><span>规则</span><small>{{view.rule.ruleVersion||'—'}}</small></header>
          <strong :data-track1-rule-level="view.rule.level||''">{{view.rule.levelLabel||'—'}}</strong>
          <dl>
            <dt>适飞指数 SFI</dt><dd>{{sfiText}}</dd>
          </dl>
          <p v-if="view.rule.reasons.length">{{view.rule.reasons.join('；')}}</p>
          <p v-else class="muted">各要素均在适飞阈值内。</p>
          <small class="muted">阈值与扣分口径：config/rules-v1.json</small>
        </article>

        <article class="track1-block" data-track1-model :class="{absent:!view.model.available}">
          <header><span>模型</span><small>{{view.model.labelsVersion?('判据 '+view.model.labelsVersion):'—'}}</small></header>
          <strong v-if="view.model.available"
                  :data-track1-model-level="view.model.level">{{view.model.levelLabel}}</strong>
          <strong v-else class="absent" data-track1-model-absent>未参与</strong>
          <dl v-if="view.model.available">
            <dt>置信度</dt><dd>{{confidenceText}}</dd>
            <dt>与次高的差</dt><dd>{{view.model.margin===null?'—':view.model.margin.toFixed(3)}}</dd>
          </dl>
          <p v-else class="muted">
            {{view.model.absentReason==='NOT_REQUESTED'?'这一轮还没有向模型发起请求。':'模型不可用：'+view.model.absentReason}}
            没有档位可比，因此不参与裁决。
          </p>
          <p class="track1-flag warn" v-if="view.model.lowConfidence" data-track1-low>置信不足：与次高档的差距很小，这一档不宜单独作依据。</p>
          <p class="track1-flag warn" v-if="view.model.degraded" data-track1-degraded>{{view.model.degradedReason}}</p>
          <div v-if="view.model.top3.length" class="track1-top3" data-track1-top3>
            <small>近似归因 Top3</small>
            <ul>
              <li v-for="item in view.model.top3" :key="item.feature">
                <b>{{item.featureLabel}}</b>
                <span>{{item.value===null?'—':item.value}}</span>
              </li>
            </ul>
          </div>
          <small class="muted" v-if="view.attributionNote">{{view.attributionNote}}</small>
        </article>

        <article class="track1-block wide" data-track1-arbitration :class="view.decisionTone">
          <header><span>融合</span><small>{{view.decisionLabel}}</small></header>
          <strong :data-track1-final="view.finalLevel||''">{{view.finalLabel||'无法判定'}}</strong>
          <p>{{view.decisionNote}}</p>
          <small class="muted">最终档位由服务端一处裁决（规则否决模型时不改档、不加权）。</small>
        </article>
      </div>

      <p class="briefing-note track1-sources">
        可回到来源：
        <span v-for="item in view.sources" :key="item.path">{{item.label}}（{{item.path}}）</span>
      </p>
    </template>
  </section>
</template>

<style scoped>
.track1-panel{border:1px solid #294355;border-radius:10px;background:#122636;padding:18px;margin:0 0 18px}
.track1-panel .briefing-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.track1-panel .briefing-head h3{font-size:15px;color:#d8ecf8;font-weight:500}
.track1-panel .briefing-head small{font-size:11px;color:#7fa3b8}
.briefing-note{font-size:11px;color:#8aa8b9;line-height:1.9;margin:10px 0}
.track1-error{color:#ffd9a8;font-size:12px;margin:10px 0;padding:10px 12px;background:#3a2712;border-left:3px solid #d98a2b;border-radius:4px}
.track1-decisions{display:flex;gap:8px;flex-wrap:wrap;list-style:none;margin:12px 0 16px;padding:0}
.track1-decisions li{position:relative;font-size:11px;padding:7px 11px;border-radius:5px;border:1px solid #2c4a5e;color:#9dc0d4;background:#10222f}
.track1-decisions li.ok{border-color:#2f6f5a;color:#9ee6c8}
.track1-decisions li.warn{border-color:#6b5730;color:#f1c77f}
.track1-decisions li.veto{border-color:#7a3a26;color:#ffb59a}
.track1-decisions li.muted{border-color:#37505f;color:#8aa8b9}
.track1-decisions li em{font-style:normal;margin-left:7px;font-size:10px;padding:1px 5px;border-radius:3px;background:#2f6076;color:#e9fbff}
.track1-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.track1-block{background:#152b3c;border:1px solid #294859;border-radius:8px;padding:14px;min-width:0}
.track1-block header{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.track1-block header span{font-size:10px;letter-spacing:1px;color:#7fa3b8}
.track1-block header small{font-size:10px;color:#6b8aa0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track1-block strong{display:block;font-size:24px;margin:10px 0 6px;color:#a8e9e7;font-weight:500}
.track1-block strong.absent{color:#8aa8b9;font-size:18px}
.track1-block dl{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;margin:8px 0;font-size:11px}
.track1-block dt{color:#7fa3b8}
.track1-block dd{margin:0;color:#d8ecf8}
.track1-block p{font-size:11.5px;color:#a9c6d8;line-height:1.8;margin:8px 0 0;overflow-wrap:anywhere}
.track1-block p.muted,.track1-block small.muted{color:#7d9cb0}
.track1-block small.muted{display:block;font-size:10px;line-height:1.7;margin-top:8px}
.track1-flag.warn{background:#3a2712;border-left:3px solid #d98a2b;border-radius:4px;padding:7px 9px;color:#ffd9a8}
.track1-top3{margin-top:10px}
.track1-top3 small{font-size:10px;color:#7fa3b8}
.track1-top3 ul{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:4px}
.track1-top3 li{display:flex;justify-content:space-between;font-size:11px;color:#c5dceb;border-bottom:1px dashed #24404f;padding-bottom:3px}
.track1-top3 li b{font-weight:400;color:#a9c6d8}
.track1-block.wide{grid-column:1/-1}
.track1-block.veto{border-left:3px solid #c0392b}
.track1-block.ok{border-left:3px solid #2e8b57}
.track1-block.warn{border-left:3px solid #d98a2b}
.track1-sources span{display:inline-block;margin-right:12px;color:#93b6ca}
</style>
