<script setup>
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {scrollCycle,scrollWrap,scrollTarget} from '../../traffic/runtime.js'

const props=defineProps({
  items:{type:Array,default:()=>[]},
  holdMs:{type:Number,default:5000},
  moveMs:{type:Number,default:450},
  maxVisible:{type:Number,default:4},
  label:{type:String,default:'循环列表'},
  emptyText:{type:String,default:'当前视图没有条目（筛选条件或数据来源见上方口径）'},
  narrow:{type:Boolean,default:false},
})

const RESUME_HOVER_MS=1500
const RESUME_MANUAL_MS=8000

const view=ref(null)
const offset=ref(0)
const animating=ref(false)
const paused=ref(false)
const peeking=ref(false)
const height=ref(0)
const reduced=ref(false)
let raf=0,autoTimer=0,resumeTimer=0,holdTimer=0

const rowHeight=computed(()=>{
  const rows=Math.max(1,props.maxVisible)
  return height.value>0?height.value/rows:0
})
const cycle=computed(()=>scrollCycle(props.items.length,rowHeight.value))
const looping=computed(()=>!reduced.value&&props.items.length>props.maxVisible)
const nativeMode=computed(()=>reduced.value&&props.items.length>props.maxVisible)
const idx=computed(()=>{
  if(!props.items.length)return 0
  const rows=Math.max(1,props.maxVisible)
  return Math.round(scrollWrap(offset.value,cycle.value)/rowHeight.value)%props.items.length
})
const progress=computed(()=>props.items.length?((idx.value+1)/props.items.length)*100:0)
const trackStyle=computed(()=>({transform:`translateY(${-offset.value}px)`}))

function clearTimers(){
  clearTimeout(autoTimer);clearTimeout(resumeTimer);clearTimeout(holdTimer)
}

function scheduleAuto(){
  clearTimeout(autoTimer)
  if(paused.value||peeking.value||!looping.value)return
  autoTimer=setTimeout(()=>{step(1,false)},props.holdMs)
}

function pauseFor(ms){
  peeking.value=true
  clearTimeout(resumeTimer)
  resumeTimer=setTimeout(()=>{peeking.value=false;scheduleAuto()},ms)
}

function animateTo(target,then){
  cancelAnimationFrame(raf)
  const from=offset.value
  if(reduced.value||!(props.moveMs>0)){offset.value=target;then&&then();return}
  const span=target-from
  const start=performance.now()
  animating.value=true
  const tick=now=>{
    const p=Math.min(1,(now-start)/props.moveMs)
    const eased=1-Math.pow(1-p,3)
    offset.value=from+span*eased
    if(p<1){raf=requestAnimationFrame(tick)}
    else{animating.value=false;then&&then()}
  }
  raf=requestAnimationFrame(tick)
}

function step(direction,manual){
  if(reduced.value||!looping.value)return
  if(manual)pauseFor(RESUME_MANUAL_MS)
  const target=scrollTarget(offset.value,direction*rowHeight.value,cycle.value)
  animateTo(target,()=>{
    offset.value=scrollWrap(offset.value,cycle.value)
    scheduleAuto()
  })
}

function toggle(){
  paused.value=!paused.value
  if(paused.value)clearTimeout(autoTimer);else scheduleAuto()
}

function onWheel(event){
  if(reduced.value||!looping.value)return
  const dy=event.deltaY
  if(!dy)return
  event.preventDefault()
  if(Math.abs(dy)<40)return
  step(dy>0?1:-1,true)
}

function onKey(event){
  if(reduced.value||!looping.value)return
  if(event.key==='ArrowDown'||event.key==='PageDown'){event.preventDefault();step(1,true)}
  else if(event.key==='ArrowUp'||event.key==='PageUp'){event.preventDefault();step(-1,true)}
  else if(event.key===' '||event.key==='Enter'){event.preventDefault();toggle()}
}

function onEnter(){clearTimeout(autoTimer)}
function onLeave(){scheduleAuto()}

let observer=null
function measure(){
  if(!view.value)return
  height.value=view.value.clientHeight
}
onMounted(()=>{
  const query=window.matchMedia('(prefers-reduced-motion: reduce)')
  reduced.value=query.matches
  const onChange=event=>{reduced.value=event.matches;offset.value=0;scheduleAuto()}
  query.addEventListener?.('change',onChange)
  measure()
  if(typeof ResizeObserver!=='undefined'){
    observer=new ResizeObserver(measure)
    if(view.value)observer.observe(view.value)
  }
  scheduleAuto()
})
onBeforeUnmount(()=>{
  clearTimers()
  cancelAnimationFrame(raf)
  if(observer)observer.disconnect()
})
watch(()=>props.items.length,()=>{offset.value=0;scheduleAuto()})
</script>

<template>
  <div class="sl-wrap" :class="{'sl-native':nativeMode,peeking}" role="group" :aria-label="label"
       :tabindex="nativeMode?null:0"
       @wheel="onWheel" @keydown="onKey"
       @pointerdown="pauseFor(RESUME_MANUAL_MS)"
       @pointerenter="onEnter" @pointerleave="onLeave"
       @focusin="onEnter" @focusout="onLeave">
    <div ref="view" class="sl-view" :tabindex="nativeMode?0:null">
      <div class="sl-track" :style="trackStyle" :class="{moving:animating}">
        <div class="list-page">
          <template v-for="(item,i) in items" :key="'p0-'+i">
            <slot name="item" :item="item" :index="i"></slot>
          </template>
        </div>
        <div v-if="looping" class="list-page" aria-hidden="true" inert>
          <template v-for="(item,i) in items" :key="'p1-'+i">
            <slot name="item" :item="item" :index="i"></slot>
          </template>
        </div>
      </div>
    </div>

    <div class="sl-stat" v-if="!reduced&&items.length&&!looping">
      <span class="sl-stat-t">{{ narrow?'已按筛选收窄':'内容未超出' }}</span>
      <span class="sl-stat-h">共 {{ items.length }} 条 · 全部可见、无需轮播</span>
    </div>

    <div class="sl-ctl" v-if="looping">
      <button class="sl-btn" type="button" @click="toggle"
              :aria-label="paused?'恢复自动轮播':'暂停自动轮播'" :aria-pressed="paused?'true':'false'">
        <span aria-hidden="true">{{ paused?'▶':'||' }}</span>
      </button>
      <button class="sl-btn" type="button" @click="step(-1,true)" aria-label="上一条"><span aria-hidden="true">▲</span></button>
      <button class="sl-btn" type="button" @click="step(1,true)" aria-label="下一条"><span aria-hidden="true">▼</span></button>
      <span class="sl-prog"><i :style="{width:progress+'%'}"></i></span>
      <span class="sl-idx">{{ idx+1 }}/{{ items.length }}</span>
    </div>

    <p class="sl-empty" v-if="!items.length">{{ emptyText }}</p>
  </div>
</template>

<style scoped>
.sl-wrap{position:relative;flex:1;min-height:0;display:flex;flex-direction:column;gap:6px;outline:none}
.sl-view{flex:1;min-height:0;overflow:hidden}
.sl-wrap.sl-native .sl-view{overflow-y:auto}
.sl-track{display:flex;flex-direction:column;will-change:transform}
.sl-track.moving{transition:none}
.list-page{display:flex;flex-direction:column}
.sl-stat{display:flex;align-items:center;gap:9px;font-size:10px;color:#6f95c4;padding:2px 2px 0}
.sl-stat-t{color:#8fb4de}
.sl-stat-h{color:#5d80ab}
.sl-ctl{display:flex;align-items:center;gap:6px;flex:none;padding:2px 2px 0}
.sl-btn{background:rgba(61,139,255,.14);border:1px solid rgba(80,158,255,.35);color:#bcd8f5;
  border-radius:4px;min-width:20px;height:18px;font-size:9px;line-height:1;cursor:pointer;padding:0 4px;flex:none}
.sl-btn:hover{background:rgba(61,139,255,.34);border-color:#5aa4ff;color:#eaf5ff}
.sl-prog{flex:1;height:2px;background:rgba(64,140,230,.20);border-radius:1px;overflow:hidden;min-width:20px}
.sl-prog i{display:block;height:100%;background:linear-gradient(90deg,#3d8bff,#27e0ff);
  transition:width .3s ease;box-shadow:0 0 6px rgba(39,224,255,.6)}
.sl-idx{font-size:10px;color:#8fb4de;font-variant-numeric:tabular-nums;flex:none}
.sl-empty{font-size:11px;color:#5d80ab;padding:10px 2px}
@media (prefers-reduced-motion: reduce){.sl-track{transform:none!important}}
</style>
