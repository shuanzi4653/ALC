<script setup>
import {computed,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'

const props=defineProps({
  compact:{type:Boolean,default:false},
})

const data=ref(null),error=ref(''),loading=ref(false),region=ref('')

const STATE_NAME={operational:'运行态',observing:'观测态',pending:'待接入'}
const STATE_NOTE={
  operational:'有走廊、有站，可下钻到运行细节',
  observing:'有 METAR 站，暂无走廊网络',
  pending:'尚未接入，按规划预留',
}

async function load(){
  loading.value=true
  try{data.value=await requestJson('/api/traffic/v2/national',{timeoutMs:20000});error.value=''}
  catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}
onMounted(load)

const summary=computed(()=>data.value?.summary||{})
const visible=computed(()=>{
  const rows=data.value?.provinces||[]
  return region.value?rows.filter(item=>item.region===region.value):rows
})
const operationalList=computed(()=>(data.value?.provinces||[]).filter(item=>item.state==='operational'))
</script>

<template>
<section class="nl">
  <p class="nl-state" v-if="loading&&!data">正在汇总全国口径…</p>
  <p class="nl-state bad" v-else-if="error">全国视图不可用 · {{ error }}<button class="nl-retry" @click="load">重试</button></p>

  <template v-else-if="data">
    <header class="nl-hd">
      <div>
        <h2 v-if="!compact">全国视图 <small>七个大区 · {{ summary.provinces }} 个省级单元</small></h2>
        <p class="nl-sub">
          运行态 <b class="alc-num">{{ summary.operational }}</b> ·
          观测态 <b class="alc-num">{{ summary.observing }}</b> ·
          待接入 <b class="alc-num">{{ summary.pending }}</b> ·
          城际走廊 <b class="alc-num">{{ summary.corridors }}</b><span class="nl-dim">（另有跨省 {{ summary.interprovincialCorridors }} 条）</span> ·
          METAR 站 <b class="alc-num">{{ summary.stations }}</b>
        </p>
      </div>
      <div class="nl-legend">
        <span v-for="(label,key) in STATE_NAME" :key="key" :class="['nl-key',key]">{{ label }}</span>
      </div>
    </header>

    <nav class="nl-chips" aria-label="按大区筛选">
      <button :class="{on:region===''}" @click="region=''">全部 <em>{{ summary.provinces }}</em></button>
      <button v-for="r in data.regions" :key="r.id" :class="{on:region===r.id}" @click="region=r.id">
        {{ r.name }} <em>{{ r.operational }}/{{ r.provinceCount }}</em>
      </button>
    </nav>

    <div class="nl-grid">
      <article v-for="p in visible" :key="p.adcode" :class="['nl-cell',p.state]" :title="STATE_NOTE[p.state]">
        <header>
          <span class="nl-dot"></span>
          <b>{{ p.name }}</b>
          <em>{{ STATE_NAME[p.state] }}</em>
        </header>
        <p v-if="p.state!=='pending'">
          走廊 {{ p.corridors }} · 城市 {{ p.cities }} · 站 {{ p.stations }}
        </p>
        <p v-else class="nl-mute">—</p>
      </article>
    </div>

    <p class="nl-hint" v-if="!visible.length">该大区暂无省级记录。</p>

    <footer class="nl-foot">
      <p class="nl-run" v-if="operationalList.length">
        可下钻：
        <span v-for="p in operationalList" :key="p.adcode">{{ p.name }}（{{ p.corridors }} 条城际走廊）</span>
      </p>
      <p class="nl-notes" v-for="n in data.notes" :key="n">{{ n }}</p>
    </footer>
  </template>
</section>
</template>

<style scoped>
.nl{display:flex;flex-direction:column;gap:var(--alc-space-gap);padding:var(--alc-space-card);color:var(--alc-text)}
.nl-state{margin:0;color:var(--alc-text-dim);font-size:var(--alc-fs-body)}
.nl-state.bad{color:var(--alc-danger)}
.nl-retry{margin-left:12px;background:none;border:1px solid var(--alc-line);border-radius:6px;
  color:var(--alc-text);padding:2px 10px;cursor:pointer;font-size:var(--alc-fs-aux)}
.nl-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.nl-hd h2{margin:0;font-size:var(--alc-fs-title)}
.nl-hd h2 small{margin-left:8px;font-size:var(--alc-fs-aux);color:var(--alc-text-mute);font-weight:400}
.nl-sub{margin:6px 0 0;font-size:var(--alc-fs-aux);color:var(--alc-text-dim)}
.nl-sub b{color:var(--alc-text);font-weight:500}
.nl-dim{color:var(--alc-text-mute)}
.nl-legend{display:flex;gap:10px;align-items:center}
.nl-key{font-size:var(--alc-fs-aux);color:var(--alc-text-dim);display:inline-flex;align-items:center;gap:6px}
.nl-key::before{content:'';width:8px;height:8px;border-radius:50%;background:var(--alc-neutral)}
.nl-key.operational::before{background:var(--alc-ok)}
.nl-key.observing::before{background:var(--alc-watch)}
.nl-key.pending::before{background:var(--alc-neutral)}
.nl-chips{display:flex;gap:8px;flex-wrap:wrap}
.nl-chips button{background:var(--alc-bg-2);border:1px solid var(--alc-line);color:var(--alc-text-dim);
  border-radius:999px;padding:4px 12px;font-size:var(--alc-fs-aux);cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.nl-chips button.on{color:var(--alc-text);border-color:var(--alc-info);background:rgba(76,141,255,.12)}
.nl-chips em{font-style:normal;color:var(--alc-text-mute)}
.nl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.nl-cell{background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:10px;padding:10px 12px}
.nl-cell.operational{border-color:rgba(82,196,26,.45)}
.nl-cell.observing{border-color:rgba(250,173,20,.45)}
.nl-cell.pending{opacity:.62}
.nl-cell header{display:flex;align-items:center;gap:8px;font-size:var(--alc-fs-body)}
.nl-cell header em{margin-left:auto;font-style:normal;font-size:11px;color:var(--alc-text-mute)}
.nl-dot{width:7px;height:7px;border-radius:50%;background:var(--alc-neutral);flex:none}
.nl-cell.operational .nl-dot{background:var(--alc-ok)}
.nl-cell.observing .nl-dot{background:var(--alc-watch)}
.nl-cell p{margin:6px 0 0;font-size:var(--alc-fs-aux);color:var(--alc-text-dim)}
.nl-cell p.nl-mute{color:var(--alc-text-mute)}
.nl-hint{margin:0;color:var(--alc-text-mute);font-size:var(--alc-fs-aux)}
.nl-foot{display:flex;flex-direction:column;gap:4px;border-top:1px solid var(--alc-line);padding-top:10px}
.nl-run{margin:0;font-size:var(--alc-fs-aux);color:var(--alc-text-dim)}
.nl-run span{color:var(--alc-text)}
.nl-run span+span::before{content:' · ';color:var(--alc-text-mute)}
.nl-notes{margin:0;font-size:11px;color:var(--alc-text-mute);line-height:1.6}
</style>
