<script setup>
import {computed} from 'vue'
import {actionNames,atTime,clearanceStatusName,executionTimes,flightPhase,flightState,layerLabel,markFor,modeNames,orderState,phaseNames,reasonNames,relativeClock,stateNames,vehicleState} from '../../traffic/runtime.js'
const props=defineProps({
  flight:{type:Object,required:true},
  minute:{type:Number,required:true},
  selected:{type:Boolean,default:false},
  settings:{type:Object,default:()=>({})},
})
const emit=defineEmits(['locate','follow','toggle-hold'])
const points=computed(()=>Array.isArray(props.flight?.points)?props.flight.points:[])
const state=computed(()=>flightState(props.flight,props.minute))
const phase=computed(()=>flightPhase(props.flight,props.minute))
const actual=computed(()=>executionTimes(props.flight,props.minute))
const isDelivery=computed(()=>props.flight.mode==='DELIVERY')
const order=computed(()=>isDelivery.value?orderState(props.flight,state.value,phase.value):null)
const vehicle=computed(()=>isDelivery.value?vehicleState(props.flight,state.value,props.minute,props.settings):null)
const blocked=computed(()=>points.value.length?'':(reasonNames[props.flight.reason]||props.flight.reason||'—'))
const airborneAt=computed(()=>{
  if(state.value!=='AIRBORNE')return null
  const point=atTime(points.value,props.minute)
  return point||null
})
const notStarted=computed(()=>{
  const point=airborneAt.value
  return state.value==='AIRBORNE'&&(!point||point[2]<=0.5)
})
const currentAgl=computed(()=>{
  const point=airborneAt.value
  return point?Math.round(point[2]):0
})
const groundSpeed=computed(()=>{
  if(state.value!=='AIRBORNE')return null
  const pts=points.value
  const before=atTime(pts,Math.max(0,props.minute-.25)),after=atTime(pts,props.minute+.25)
  if(!before||!after)return null
  return Math.round(Math.hypot(after[0]-before[0],after[1]-before[1])/1000/(0.5/60))
})
const canHold=computed(()=>props.flight.status==='SCHEDULED'&&props.minute<props.flight.departureMinute)
const safety=computed(()=>clearanceStatusName(props.flight.clearanceStatus))
</script>

<template>
<article class="flight-strip" :class="{selected,closed:state==='CLOSED'}" @click="emit('locate',flight)">
  <header>
    <div class="fs-id">
      <span class="fs-mode" :class="isDelivery?'amber':'cyan'">{{modeNames[flight.mode]}}</span>
      <b>{{flight.name}}</b>
      <code>{{flight.id}}</code>
    </div>
    <span class="fs-state" :class="state">{{markFor(state)}} {{stateNames[state]}}</span>
  </header>
  <div class="fs-grid">
    <div><small>路由</small><span>{{flight.fromPad}} → {{flight.toPad}}</span></div>
    <div><small>申请起飞</small><span>{{relativeClock(flight.requestedDepartureMinute)}}</span></div>
    <div><small>计划放行</small><span>{{flight.plannedReleaseAt?relativeClock(flight.departureMinute):'—'}}</span></div>
    <div><small>实际放行</small><span>{{actual.actualReleaseAt?relativeClock(flight.departureMinute):'未发生'}}</span></div>
    <div><small>预计到达</small><span>{{flight.estimatedArrivalAt?relativeClock(flight.arrivalMinute):'—'}}</span></div>
    <div><small>地面等待 / 绕行</small><span>{{Math.round(flight.delayMinutes||0)}} / {{Math.round(flight.detourMinutes||0)}} 分钟</span></div>
    <div><small>当前距地高度</small><span v-if="notStarted" class="fs-pending">待起飞 · T+0 未推进</span><span v-else-if="state!=='AIRBORNE'">地面</span><span v-else>{{currentAgl}} m AGL</span></div>
    <div><small>目标高度层</small><span>{{layerLabel(flight)}}</span></div>
    <div><small>升降状态 / 地速</small><span v-if="notStarted">{{phaseNames[phase]||phase}} · 未启动</span><span v-else>{{phaseNames[phase]||phase}}{{groundSpeed!=null&&groundSpeed>0?` · ${groundSpeed} km/h`:(' · 地面滑行前')}}</span></div>
    <div v-if="isDelivery"><small>订单状态</small><span>{{order}}</span></div>
    <div v-if="isDelivery"><small>载具 / 剩余电量</small><span>{{vehicle}} · {{flight.energyPercentRemainingAtHandover??'—'}}%</span></div>
    <div><small>起降与交叉资源</small><span v-if="flight.slim&&flight.crossingZones===undefined" class="pending">加载中</span><span v-else>{{flight.crossingZones?.length?`${flight.crossingZones.length} 个交叉区已预约`:'无交叉区'}}</span></div>
    <div><small>冲突班次</small><span v-if="flight.slim&&flight.conflictWith===undefined" class="pending">加载中</span><span v-else>{{flight.conflictWith?.length?`${flight.conflictWith.length} 个关联冲突`:'无'}}</span></div>
    <div><small>数据质量</small><span>{{safety}}</span></div>
    <div class="wide"><small>限制与处理</small><span>{{blocked}} · {{actionNames[flight.separationAction]||flight.separationAction}}</span></div>
  </div>
  <footer>
    <button @click.stop="emit('locate',flight)">定位</button>
    <button @click.stop="emit('follow',flight)" :disabled="!points.length">跟随</button>
    <button v-if="canHold" @click.stop="emit('toggle-hold',flight)">{{flight.manuallySuspended?'申请恢复':'暂停'}}</button>
  </footer>
</article>
</template>

<style scoped>
.pending{color:var(--alc-text-dim);font-style:italic}
.flight-strip{border:1px solid #22394a;border-radius:10px;background:#0e1b29;padding:12px 14px;cursor:pointer;min-width:0}
.flight-strip.selected{border-color:#65cce5;background:#12283a}
.flight-strip.closed{opacity:.72;border-color:#4a2735}
.flight-strip header{display:flex;align-items:center;gap:8px;font-size:12px;padding-bottom:9px;border-bottom:1px solid #1c3041}
.flight-strip header .fs-id{display:flex;align-items:center;gap:8px;min-width:0;flex:1}
.flight-strip header b{font-size:13px;font-weight:500;color:#d6e5ef;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.flight-strip header code{font-size:10px;color:#64869b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:none;max-width:45%}
.fs-mode{font-size:10px;padding:2px 6px;border-radius:4px;background:#203447;flex:none;white-space:nowrap}
.fs-mode.cyan{color:#64ddf6}.fs-mode.amber{color:#e8bd72}
.fs-state{flex:none;font-size:10px;padding:3px 7px;border-radius:4px;background:#203447;color:#7f9caf;white-space:nowrap}
.fs-state.AIRBORNE{background:#173e45;color:#6ad6c9}
.fs-state.HOLD{background:#493b23;color:#e5bd72}
.fs-state.PENDING{background:#2a3346;color:#a5b0c8}
.fs-state.CLOSED{background:#4a2a12;color:#ffd9a8}
.fs-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 12px;padding:10px 0 0}
.fs-grid>div{min-width:0;overflow:hidden}
.fs-grid>div.wide{grid-column:1/-1}
.fs-grid small{display:block;color:#6e90a6;font-size:10px;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-grid span{font-size:11px;color:#c2d7e5;overflow-wrap:anywhere;display:block}
.flight-strip footer{display:flex;gap:6px;padding-top:10px;flex-wrap:wrap}
.flight-strip footer button{padding:5px 9px;font-size:10px;white-space:nowrap}
@media(min-width:520px){.fs-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>
