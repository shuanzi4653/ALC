<script setup>
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import FlightStrip from './FlightStrip.vue'
import {groupFlights,groupNames,modeNames,reasonNames,releaseQueue,releaseWindows,virtualWindow} from '../../traffic/runtime.js'
const props=defineProps({
  flights:{type:Array,default:()=>[]},
  minute:{type:Number,required:true},
  selectedId:{type:String,default:''},
  settings:{type:Object,default:()=>({})},
  ready:{type:Boolean,default:false},
  planRevision:{type:String,default:''},
  previewCount:{type:Number,default:6},
  rowSlackPx:{type:Number,default:18},
})
const emit=defineEmits(['locate','follow','toggle-hold','select'])
const expanded=ref(false),group=ref(''),modeFilter=ref('ALL'),reasonFilter=ref(''),windowIndex=ref(0)
const scroller=ref(null),scrollTop=ref(0),viewportHeight=ref(0),rowHeight=ref(196)
let resizeObserver=null
const overscan=4
const windowOption=computed(()=>releaseWindows[windowIndex.value])
const scoped=computed(()=>props.flights.filter(f=>(modeFilter.value==='ALL'||f.mode===modeFilter.value)&&(!reasonFilter.value||f.reason===reasonFilter.value)))
const queue=computed(()=>{
  const minutes=windowOption.value.minutes
  if(minutes==null)return scoped.value.filter(f=>f.status==='SCHEDULED').sort((a,b)=>a.departureMinute-b.departureMinute||a.id.localeCompare(b.id))
  return releaseQueue(scoped.value,props.minute,minutes)
})
const groups=computed(()=>groupFlights(scoped.value,props.minute))
const reasons=computed(()=>[...new Set(props.flights.map(f=>f.reason).filter(Boolean))].sort())
const list=computed(()=>group.value?groups.value[group.value]||[]:queue.value)
const window=computed(()=>virtualWindow(list.value.length,scrollTop.value,viewportHeight.value,rowHeight.value,overscan))
const startIndex=computed(()=>expanded.value?window.value.startIndex:0)
const endIndex=computed(()=>expanded.value?window.value.endIndex:list.value.length)
const rows=computed(()=>{
  if(!expanded.value)return list.value.slice(0,props.previewCount).map(f=>({f,top:null}))
  return list.value.slice(startIndex.value,endIndex.value).map((f,offset)=>({f,top:(startIndex.value+offset)*rowHeight.value}))
})
const renderedCount=computed(()=>rows.value.length)
const totalHeight=computed(()=>list.value.length*rowHeight.value)
const heading=computed(()=>{
  if(!expanded.value)return `${windowOption.value.label}待放行 ${queue.value.length} 班次`
  return group.value?`${group.value} · ${list.value.length} 班次`:`${windowOption.value.label}队列 · ${list.value.length} 班次`
})
function measure(){
  const node=scroller.value
  if(!node)return
  viewportHeight.value=node.clientHeight
  const first=node.querySelector('.db-row')
  if(first){
    const measured=Math.round(first.getBoundingClientRect().height)
    if(measured>60)rowHeight.value=measured+props.rowSlackPx
  }
}
function onScroll(){scrollTop.value=scroller.value?.scrollTop||0}
function scrollToTop(){if(scroller.value)scroller.value.scrollTop=0;scrollTop.value=0}
watch([modeFilter,reasonFilter,windowIndex,group,expanded],()=>{scrollToTop();nextTick(measure)})
watch(()=>list.value.length,()=>nextTick(measure))
watch(()=>props.minute,()=>nextTick(measure))
onMounted(()=>{
  nextTick(measure)
  if(typeof ResizeObserver!=='undefined'){
    resizeObserver=new ResizeObserver(measure)
    if(scroller.value)resizeObserver.observe(scroller.value)
  }
})
onUnmounted(()=>{resizeObserver?.disconnect()})
function select(flight){emit('select',flight);emit('locate',flight)}
</script>

<template>
<section class="dispatch-board" :class="{expanded}">
  <header class="db-head">
    <div><h2>放行队列与调度台账</h2><span>{{ready?heading:'等待运行计划'}}</span></div>
    <div class="db-controls">
      <select aria-label="放行时间窗" v-model.number="windowIndex" :disabled="!ready"><option v-for="(w,i) in releaseWindows" :key="i" :value="i">{{w.label}}</option></select>
      <select aria-label="交通类型" v-model="modeFilter" :disabled="!ready"><option value="ALL">全部类型</option><option value="CAR">{{modeNames.CAR}}</option><option value="DELIVERY">{{modeNames.DELIVERY}}</option></select>
      <select v-if="expanded" aria-label="关闭原因" v-model="reasonFilter" :disabled="!ready"><option value="">全部原因</option><option v-for="r in reasons" :key="r" :value="r">{{reasonNames[r]||r}}</option></select>
      <button @click="expanded=!expanded" :disabled="!ready">{{expanded?'收起为放行队列':'展开完整调度台账'}}</button>
    </div>
  </header>
  <nav v-if="expanded" class="db-groups">
    <button :class="{active:group===''}" @click="group=''">全部 {{queue.length}}</button>
    <button v-for="name in groupNames" :key="name" :class="{active:group===name}" @click="group=name">{{name}} {{groups[name].length}}</button>
  </nav>
  <div v-if="expanded" ref="scroller" class="db-scroll" @scroll.passive="onScroll">
    <div class="db-canvas" :style="{height:totalHeight+'px'}">
      <div v-for="row in rows" :key="row.f.id" class="db-row" :style="{top:row.top+'px',height:rowHeight+'px'}">
        <FlightStrip :flight="row.f" :minute="minute" :settings="settings" :selected="row.f.id===selectedId" @locate="select" @follow="f=>emit('follow',f)" @toggle-hold="f=>emit('toggle-hold',f)"/>
      </div>
    </div>
  </div>
  <div class="db-grid" v-else-if="rows.length">
    <FlightStrip v-for="row in rows" :key="row.f.id" :flight="row.f" :minute="minute" :settings="settings" :selected="row.f.id===selectedId" @locate="select" @follow="f=>emit('follow',f)" @toggle-hold="f=>emit('toggle-hold',f)"/>
  </div>
  <p class="db-empty" v-if="!rows.length">{{ready?'当前筛选没有班次；队列按计划放行时间排序，被关闭的班次不会重新排入。':'正在生成运行计划…'}}</p>
  <footer class="db-foot" v-if="expanded&&list.length">
    <span>已渲染 {{renderedCount}} / {{list.length}} 张进程单 · 虚拟滚动 · 计划版本 {{planRevision||'—'}}</span>
  </footer>
  <footer class="db-foot" v-else-if="!expanded&&queue.length>previewCount">
    <span>队列共 {{queue.length}} 班次，此处预览前 {{previewCount}} 张。</span>
  </footer>
  <p class="db-note">进程单与地图选中双向联动；放行时刻来自算法时隙，暂停与恢复不绕过净空、气象与资源校验。</p>
</section>
</template>

<style scoped>
.dispatch-board{border:1px solid #22394a;border-radius:12px;background:#0e1b29;margin:14px 0;padding:0 0 12px}
.dispatch-board.expanded{background:#0c1824}
.db-head{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;padding:15px}
.db-head h2{font-size:14px;font-weight:500;margin-bottom:6px}
.db-head span{font-size:11px;color:#6d899d}
.db-controls{display:flex;gap:8px;flex-wrap:wrap}
.db-controls select,.db-controls button{background:#122334;color:#bcd3e2;border:1px solid #294153;border-radius:6px;padding:7px 10px;font:inherit;font-size:11px;cursor:pointer}
.db-controls button:hover{border-color:#65cce5;color:#fff}
.db-groups{display:flex;gap:6px;flex-wrap:wrap;padding:0 15px 10px;border-bottom:1px solid #1c3041}
.db-groups button{background:transparent;border:1px solid #294153;border-radius:999px;color:#93b0c2;padding:5px 12px;font:inherit;font-size:11px;cursor:pointer}
.db-groups button.active{background:#204658;border-color:#398098;color:#aaf0ff}
.db-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:12px;padding:14px 15px 0}
.db-scroll{position:relative;overflow:auto;padding:12px 15px 0;max-height:min(62vh,620px)}
.db-canvas{position:relative;width:100%}
.db-row{position:absolute;left:0;right:0;overflow:hidden}
.db-empty{padding:24px 18px;color:#6b8ba1;font-size:12px}
.db-foot{display:flex;gap:12px;align-items:center;padding:10px 15px 0;color:#7797ac;font-size:11px}
.db-foot span{margin-right:auto}
.db-note{padding:10px 15px 0;color:#5f7d90;font-size:10px;line-height:1.8}
@media(max-width:900px){.db-grid{grid-template-columns:1fr}}
</style>
