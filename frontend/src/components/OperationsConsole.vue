<script setup>
import {computed,ref,watch,onUnmounted} from 'vue'
import {postAction} from '../api.js'
import RegionalObservations from './RegionalObservations.vue'
import {reasonNames} from '../traffic/runtime.js'
const props=defineProps({view:String,session:Object,flights:Array,weather:Object,selected:Object,minute:Number,cityName:String,operations:Array})
const emit=defineEmits(['select-flight'])
const question=ref('当前运行有哪些风险，为什么需要绕行或暂停？'),answer=ref(null),asking=ref(false),error=ref('')
let token=0
const alerts=computed(()=>{
  const groups=new Map()
  for(const f of props.flights||[]){
    if(f.status!=='CLOSED'&&!f.delayMinutes&&!f.detourMinutes)continue
    const key=f.routeId+':'+f.reason+':'+(f.status==='CLOSED')
    if(!groups.has(key))groups.set(key,{key,flight:f,count:0})
    groups.get(key).count++
  }
  return [...groups.values()].sort((a,b)=>(b.flight.status==='CLOSED')-(a.flight.status==='CLOSED'))
})
const wind=computed(()=>{
  const values=(props.weather?.winds||[]).map(w=>Math.hypot(w.u,w.v)).sort((a,b)=>a-b)
  return values.length?values[Math.floor(values.length/2)].toFixed(1):'—'
})
async function ask(){
  if(asking.value||!props.session||!question.value.trim())return
  const current=++token;asking.value=true;error.value='';answer.value=null
  try{const result=await postAction('/api/traffic/explain',{seed:props.session.seed,scenario:props.session.scenario,flightId:props.selected?.id||null,minute:props.minute,question:question.value},28000);if(current===token)answer.value=result}
  catch(e){if(current===token)error.value=e.message}
  finally{if(current===token)asking.value=false}
}
watch(()=>[props.session?.sessionId,props.selected?.id],()=>{++token;answer.value=null;asking.value=false})
onUnmounted(()=>++token)
</script>
<template>
<section class="operations-console">
  <template v-if="view==='alerts'"><div class="operations-heading"><h2>预警中心 <small>{{cityName}} · {{alerts.length}} 个合并事件</small></h2><p>同一走廊与原因合并展示，点击事件直接进入航班和城市地图。关闭、绕行与等待均来自当前调度计划。</p></div><div class="alert-grid"><button class="operational-alert" v-for="a in alerts" :key="a.key" @click="emit('select-flight',a.flight)"><span :class="{danger:a.flight.status==='CLOSED'}">{{a.flight.status==='CLOSED'?'停止放行':'调度调整'}}</span><h3>{{a.flight.name}}</h3><p>{{reasonNames[a.flight.reason]||a.flight.reason}}</p><small>{{a.count}} 个相关班次 · 查看航班 →</small></button><p v-if="!alerts.length">当前筛选范围暂无调度事件。</p></div></template>
  <template v-else-if="view==='weather'"><div class="operations-heading"><h2>气象监测与来源 <small>{{cityName}}</small></h2><p>空间气象随当前时间轴变化；官方历史观测作为独立数据台账，不与模拟天气混用。</p></div><div class="weather-metrics"><article><small>当前空间数据状态</small><strong>{{weather?.available?'模拟场可用':'数据不可用'}}</strong></article><article><small>区域背景风速中位数</small><strong>{{wind}} <em>m/s</em></strong></article><article><small>当前显示风场点</small><strong>{{weather?.winds?.length??0}}</strong></article><article><small>全域活动天气单体</small><strong>{{weather?.cells?.length??0}}</strong></article></div><div class="weather-cells"><article v-for="cell in weather?.cells||[]" :key="cell.id"><b>{{{RAIN:'降水',STORM:'雷暴',WIND:'强风'}[cell.kind]}}</b><span>{{cell.id}}</span><p>场区 / 谨慎外环 / 禁飞核心独立计算</p></article></div><RegionalObservations/></template>
  <template v-else-if="view==='assistant'"><div class="operations-heading"><h2>智能运行研判</h2><p>{{selected?'当前班次：'+selected.name:'研判范围：全网调度计划'}} · 共享当前场景、种子、时间和人工操作记录</p></div><div class="assistant-context"><span>计划 {{session?.sessionId?.slice(0,12)||'未就绪'}}</span><span>第 {{minute.toFixed(1)}} 分钟</span><span>{{selected?.id||'全域运行'}}</span></div><div class="operations-question"><textarea v-model="question" aria-label="运行研判问题" rows="3" maxlength="1200" placeholder="询问当前城市、班次的风险、绕行或等待原因"></textarea><button @click="ask" :disabled="asking||!session||session.status!=='READY'||!question.trim()">{{asking?'正在查证…':'查证并研判'}}</button></div><p class="operations-error" v-if="error">{{error}}</p><p v-if="!answer" class="operations-muted">研判只引用当前计划证据，模型不能绕过气象与冲突约束放行班次。</p><div v-else><p class="operations-muted">证据时刻：第 {{answer.minute.toFixed(1)}} 分钟 · {{answer.source==='deepseek'?'DeepSeek 证据检索':'本地规则证据'}}<span v-if="answer.errorCode"> · 外部模型状态 {{answer.errorCode}}</span></p><div class="answer-cards"><article v-for="e in answer.citations" :key="e.id"><h3>{{e.title}}</h3><p>{{e.text}}</p><small>证据 {{e.id}}</small></article></div></div></template>
  <template v-else-if="view==='history'"><div class="operations-heading"><h2>运行记录与操作留痕</h2><p>人工暂停和恢复写入本地日志；回看更早时刻时，不提前应用尚未发生的操作。</p></div><div class="assistant-context"><span>计划 {{session?.sessionId}}</span><span>算法 {{session?.version}}</span><span>指纹 {{session?.fingerprint}}</span></div><table class="operation-journal"><thead><tr><th>操作时刻</th><th>推演分钟</th><th>班次</th><th>操作</th></tr></thead><tbody><tr v-for="op in [...(operations||[])].reverse()" :key="op.id"><td>{{new Date(op.at).toLocaleString('zh-CN',{hour12:false})}}</td><td>{{op.minute.toFixed(1)}}</td><td>{{op.name}}<small>{{op.flightId}}</small></td><td>{{op.action==='SUSPEND'?'人工暂停':'恢复原时隙'}}</td></tr><tr v-if="!operations?.length"><td colspan="4">本计划暂无人工操作。算法调度记录可在“调度台账”查询并导出。</td></tr></tbody></table></template>
</section>
</template>
<style scoped>
.operations-console{background:#0e1c2b;border:1px solid #294355;border-radius:12px;padding:22px;min-height:480px}.operations-heading{margin-bottom:22px}.operations-heading h2{font-size:20px;font-weight:500}.operations-heading h2 small{font-size:12px;color:#7198ad;margin-left:12px}.operations-heading p{font-size:12px;color:#849fb1;line-height:1.8;margin-top:10px}.alert-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}.operational-alert{text-align:left;background:#152b3c!important;padding:18px!important;border:1px solid #315168!important}.operational-alert>span{font-size:10px;color:#f1c77f}.operational-alert>span.danger{color:#f29ba9}.operational-alert h3{font-size:15px;margin:10px 0;color:#c9deec}.operational-alert p{font-size:12px;margin-bottom:14px}.operational-alert small{font-size:10px;color:#7194a9}.weather-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.weather-metrics article{padding:18px;background:#152b3c;border-radius:9px}.weather-metrics small{display:block;color:#82a4b7}.weather-metrics strong{display:block;font-size:25px;margin-top:12px;color:#a8e9e7;font-weight:500}.weather-metrics em{font-size:12px;font-style:normal}.weather-cells{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:20px 0}.weather-cells article{padding:14px;border:1px solid #284859;border-radius:6px}.weather-cells span{font-size:10px;color:#7597ac;margin-left:12px}.weather-cells p{font-size:11px;color:#8aa8b9;margin-top:9px}.assistant-context{display:flex;flex-wrap:wrap;gap:10px;font-size:11px;color:#7aa6bd;margin-bottom:18px}.assistant-context span{padding:6px 10px;background:#142e40;border-radius:5px}.operations-question{display:flex;gap:12px}.operations-question textarea{flex:1;resize:vertical;min-width:0;color:#dcebf7;background:#0a1b29;border:1px solid #31526a;border-radius:8px;padding:14px;font:14px 'Microsoft YaHei',sans-serif;line-height:1.8}.operations-question button{align-self:flex-end;background:#236580!important;color:#ecfaff!important}.operations-muted{font-size:12px;color:#8aabbf;line-height:1.9;margin:20px 0}.answer-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.answer-cards article{padding:18px;border-left:3px solid #63c5cb;background:#142b3b;line-height:1.9}.answer-cards h3{font-size:14px;color:#94deda;margin-bottom:12px}.answer-cards p{font-size:13px}.answer-cards small{font-size:10px;color:#688ca2}.operations-error{color:#f7a5b4;padding:16px}.operation-journal{width:100%;border-collapse:collapse;font-size:12px;text-align:left}.operation-journal th,.operation-journal td{padding:16px 12px;border-bottom:1px solid #294353}.operation-journal th{color:#7095ac}.operation-journal small{display:block;color:#6b8aa0;font-size:10px;margin-top:5px}@media(max-width:800px){.weather-metrics{grid-template-columns:repeat(2,1fr)}.operations-question{flex-direction:column}.operation-journal{font-size:10px}.operations-console{padding:14px}}
</style>
