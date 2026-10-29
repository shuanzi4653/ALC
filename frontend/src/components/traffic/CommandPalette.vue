<script setup>
import {computed,nextTick,ref,watch} from 'vue'
import {HIDDEN_SECTIONS,sectionName} from '../../traffic/runtime.js'

const props=defineProps({
  open:{type:Boolean,default:false},
  groups:{type:Array,default:()=>[]},
  routes:{type:Array,default:()=>[]},
  flights:{type:Array,default:()=>[]},
})
const emit=defineEmits(['close','run'])
const query=ref(''),cursor=ref(0),box=ref(null)

const items=computed(()=>{
  const out=[]
  for(const group of props.groups){
    for(const entry of group.subs||[]){
      if(HIDDEN_SECTIONS.has(entry.key))continue
      const meta=`${group.no} ${group.label} · ${entry.hint||group.subtitle}`
      out.push({kind:'section',key:entry.key,group:'跳转',label:entry.label,meta})
      if(entry.merged){
        for(const member of entry.members){
          if(member===entry.key||HIDDEN_SECTIONS.has(member))continue
          out.push({
            kind:'section',key:member,group:'跳转',
            label:sectionName(member),
            meta:`${group.no} ${group.label} · ${entry.label} 内`,
          })
        }
      }
    }
  }
  for(const route of props.routes)out.push({
    kind:'corridor',key:route.id,group:'跳转',
    label:`${route.name||route.id}`,meta:`走廊 ${route.id} · ${route.lengthKm??'—'} km`,
  })
  for(const flight of props.flights.slice(0,400))out.push({
    kind:'flight',key:flight.id,group:'跳转',
    label:`${flight.id} ${flight.name||''}`.trim(),
    meta:`班次 · ${flight.fromCity||'—'} → ${flight.toCity||'—'}`,
  })
  for(const term of [
    {key:'TS',text:'TS（临界成功指数）＝命中/(命中+空报+漏报)'},
    {key:'FAR',text:'FAR（空报率）＝空报/(命中+空报)'},
    {key:'POD',text:'POD（命中率）＝命中/(命中+漏报)'},
    {key:'Brier',text:'Brier 分数：概率预报的均方误差，越小越准'},
    {key:'基线',text:'三条基线：持续性 / Open-Meteo 模式 / 单要素阈值规则'},
  ])out.push({kind:'section',key:'card',group:'指标解释',label:term.key,meta:term.text})
  return out
})

const matched=computed(()=>{
  const q=query.value.trim().toLowerCase()
  if(!q)return items.value.slice(0,14)
  const scored=[]
  for(const item of items.value){
    const hay=`${item.label} ${item.meta} ${item.key}`.toLowerCase()
    const at=hay.indexOf(q)
    if(at>=0)scored.push({item,score:at})
  }
  scored.sort((a,b)=>a.score-b.score)
  return scored.slice(0,18).map(x=>x.item)
})
const grouped=computed(()=>{
  const order=['跳转','指标解释']
  return order.map(name=>({name,list:matched.value.filter(i=>i.group===name)})).filter(g=>g.list.length)
})
const flat=computed(()=>grouped.value.flatMap(g=>g.list))

watch(()=>props.open,async open=>{
  if(open){query.value='';cursor.value=0;await nextTick();box.value?.focus()}
})
watch(query,()=>{cursor.value=0})
function move(step){
  if(!flat.value.length)return
  cursor.value=(cursor.value+step+flat.value.length)%flat.value.length
}
function run(item){emit('run',item||flat.value[cursor.value]||null)}
function onKey(event){
  if(event.key==='ArrowDown'){event.preventDefault();move(1)}
  else if(event.key==='ArrowUp'){event.preventDefault();move(-1)}
  else if(event.key==='Enter'){event.preventDefault();run()}
  else if(event.key==='Escape'){event.preventDefault();emit('close')}
}
</script>

<template>
<div class="cmdk-mask" v-if="open" @click.self="emit('close')" data-command-palette>
  <div class="cmdk" role="dialog" aria-label="命令面板">
    <input ref="box" v-model="query" class="cmdk-input" @keydown="onKey"
           placeholder="输走廊号（如 1-07）/ 班次号 / 页面名 / TS、FAR …" aria-label="搜索">
    <div class="cmdk-list">
      <p class="cmdk-empty" v-if="!flat.length">
        没有匹配项。可搜：走廊号、班次号、城市名、页面名、指标名（TS / FAR / POD / Brier）。
      </p>
      <template v-for="group in grouped" :key="group.name">
        <p class="cmdk-group">{{ group.name }}</p>
        <button v-for="item in group.list" :key="item.kind+item.key+(item.meta||'')"
                class="cmdk-item" :class="{active:flat[cursor]===item}"
                @click="run(item)" @mousemove="cursor=flat.indexOf(item)">
          <span class="cmdk-label">{{ item.label }}</span>
          <span class="cmdk-meta">{{ item.meta }}</span>
        </button>
      </template>
      <p class="cmdk-empty" v-if="!routes.length&&!flights.length">
        走廊与班次清单尚未载入 —— 等运行计划就绪后再搜编号。
      </p>
    </div>
    <p class="cmdk-foot">↑↓ 选择 · 回车执行 · Esc 关闭 · 由 Ctrl+K 唤起</p>
  </div>
</div>
</template>

<style scoped>
.cmdk-mask{position:fixed;inset:0;background:rgba(4,8,16,.62);display:flex;align-items:flex-start;justify-content:center;padding-top:12vh;z-index:90}
.cmdk{width:min(680px,92vw);background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:var(--alc-radius);box-shadow:0 24px 60px rgba(0,0,0,.5);overflow:hidden}
.cmdk-input{width:100%;padding:14px 18px;background:transparent;border:0;border-bottom:1px solid var(--alc-line);color:var(--alc-text);font-size:16px;outline:none}
.cmdk-list{max-height:52vh;overflow:auto;padding:8px 0}
.cmdk-group{margin:8px 18px 4px;font-size:11px;color:var(--alc-text-mute);letter-spacing:.08em}
.cmdk-item{display:flex;justify-content:space-between;gap:14px;width:100%;padding:8px 18px;background:transparent;border:0;color:var(--alc-text);font-size:13px;text-align:left;cursor:pointer}
.cmdk-item.active{background:rgba(76,141,255,.16)}
.cmdk-label{font-weight:600;white-space:nowrap}
.cmdk-meta{font-size:12px;color:var(--alc-text-dim);text-align:right}
.cmdk-empty{margin:8px 18px;font-size:12px;color:var(--alc-text-dim);line-height:1.7}
.cmdk-foot{margin:0;padding:8px 18px;border-top:1px solid var(--alc-line);font-size:11px;color:var(--alc-text-mute)}
</style>
