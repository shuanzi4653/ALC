<script setup>
import {ref} from 'vue'
import {requestJson} from '../../api.js'
import {supplementCoverageNote,supplementObservationRows,modelSpreadRows} from '../../traffic/runtime.js'
import {isCaseMode} from '../../traffic/caseMode.js'
const state=ref({'observations':{busy:false,data:null,error:''},'models':{busy:false,data:null,error:''}})
const caseMode=isCaseMode()
async function run(key,call){
  const slot=state.value[key]
  if(slot.busy)return
  slot.busy=true;slot.error=''
  try{
    state.value[key].data=await call()
  }catch(error){
    state.value[key].error=error.message||String(error)
  }finally{
    state.value[key].busy=false
  }
}
const loadObservations=()=>run('observations',()=>requestJson('/api/traffic/weather/observations'))
const loadModels=()=>run('models',()=>requestJson('/api/traffic/weather/models'))
const observationRows=()=>supplementObservationRows(state.value.observations.data)
const spreadRows=()=>modelSpreadRows(state.value.models.data)
function emptyText(key,label){
  const slot=state.value[key]
  if(slot.error)return `取数失败：${slot.error}`
  if(!slot.data)return `未取数 —— 点上面的按钮取一次${label}`
  return `已取数，但没有返回任何${label}`
}
</script>

<template>
 <div class="weather-supplement">
  <h3>免费气象源补充通道 <span class="muted">按需取数 · 不进每轮加载</span></h3>
  <p v-if="caseMode" class="case-scope-hint" data-case-scope>
   本块取的是<b>此刻</b>的实测报文与模型场，与上方回放案例（2025-01-05）不是同一时次——案例的气象判据只看案例帧里的实测站，不读这里。
  </p>
  <p class="muted">下面两条都是免费、无需密钥的公开源。它们各自缓存 10 分钟；取数失败只影响本块，不影响运行台的天气。</p>

  <section class="channel" data-channel="observations">
   <header>
    <b>机场实测报文（Aviation Weather Center METAR）</b>
    <button type="button" :disabled="state.observations.busy" @click="loadObservations()">
     {{state.observations.busy?'取数中…':'取实测报文'}}
    </button>
   </header>
   <p class="note">{{state.observations.data?supplementCoverageNote(state.observations.data):emptyText('observations','报文')}}</p>
   <div class="metar-grid" v-if="observationRows().length">
    <article v-for="row in observationRows()" :key="row.id">
     <h4>{{row.cityName}} · {{row.stationId}} <span class="muted">站距 {{row.stationDistanceKm}}</span></h4>
     <dl><template v-for="line in row.lines" :key="line.label"><dt>{{line.label}}</dt><dd>{{line.value}}</dd></template></dl>
     <p class="raw" v-if="row.rawText">{{row.rawText}}</p>
    </article>
   </div>
  </section>

  <section class="channel" data-channel="models">
   <header>
    <b>双模型差值（Open-Meteo GFS / ICON）</b>
    <button type="button" :disabled="state.models.busy" @click="loadModels()">
     {{state.models.busy?'取数中…':'取模型差值'}}
    </button>
   </header>
   <p class="note">{{state.models.data?'同一供应商下两个独立模型之间的差 · 这是不确定性，不是第二份实测':emptyText('models','模型差值')}}</p>
   <table class="spread" v-if="spreadRows().length">
    <thead><tr><th>城市</th><th>参与模型</th><th>温差</th><th>风速差</th></tr></thead>
    <tbody><tr v-for="row in spreadRows()" :key="row.id"><td>{{row.cityName}}</td><td>{{row.models||'//'}}</td><td>{{row.temperatureText}}</td><td>{{row.windText}}</td></tr></tbody>
   </table>
  </section>
 </div>
</template>

<style scoped>
.weather-supplement{margin:14px 0}
.weather-supplement h3{font-size:14px;color:#a6d6c9;margin:0 0 6px;font-weight:600}
.weather-supplement h3 span{font-size:11px;color:#7b9cb1;margin-left:10px;font-weight:400}
.weather-supplement>p.muted{font-size:11px;color:#7f9cb0;margin:0 0 10px;line-height:1.7}
.channel{border:1px solid #294657;border-radius:8px;padding:12px 14px;margin-bottom:12px;min-width:0}
.channel header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.channel header b{font-size:13px;color:#cfe6f0;font-weight:600}
.channel button{font-size:12px;padding:5px 12px;border-radius:6px;border:1px solid #2f5a72;background:#152b3c;color:#9fd9e2;cursor:pointer}
.channel button:hover:not(:disabled){background:#1d3a4f;color:#c6eef5}
.channel button:disabled{opacity:.55;cursor:default}
.channel .note{font-size:11px;color:#8fa9bb;margin:8px 0 10px;line-height:1.7;overflow-wrap:anywhere}
.metar-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.metar-grid article{border:1px solid #223c4d;border-radius:6px;padding:10px 12px;min-width:0}
.metar-grid h4{font-size:12px;color:#a6d6c9;margin:0 0 8px;font-weight:600}
.metar-grid h4 .muted{font-size:10px;color:#6f92a8;font-weight:400;margin-left:6px}
.metar-grid dl{display:grid;grid-template-columns:minmax(0,auto) minmax(0,1fr);gap:4px 8px;font-size:11px;margin:0}
.metar-grid dt{color:#7b9cb1;min-width:0}
.metar-grid dd{margin:0;color:#d5e7f1;min-width:0;overflow-wrap:anywhere}
.metar-grid p.raw{font-size:10px;color:#6f92a8;margin:8px 0 0;line-height:1.6;overflow-wrap:anywhere;font-family:ui-monospace,Consolas,monospace}
table.spread{width:100%;border-collapse:collapse;font-size:11px}
table.spread th{text-align:left;color:#7b9cb1;font-weight:500;padding:4px 8px;border-bottom:1px solid #223c4d}
table.spread td{padding:4px 8px;color:#d5e7f1;border-bottom:1px solid #1c3041}
</style>
