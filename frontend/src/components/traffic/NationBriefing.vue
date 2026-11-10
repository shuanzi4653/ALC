<script setup>
import {computed,onMounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'

// 全国台账 / 全国情报：**同一份表，两个入口**。
//   ① 全国航线网页里的「台账」「情报」两个视图；
//   ② 1.0.0 原生的「调度台账」「民航情报」页（选"全国"范围时）。
// 所以它既能吃父组件已经拿到的 payload（不重复请求），也能自己拉（独立成页时）。
const props=defineProps({
  view:{type:String,default:'ledger'},          // ledger | intel
  payload:{type:Object,default:null},
  flights:{type:Array,default:()=>[]},
  minute:{type:Number,default:60},
  density:{type:String,default:'full'},
  selfFetch:{type:Boolean,default:false},
  selectedId:{type:String,default:''},
})
const emit=defineEmits(['select'])

const local=ref(null)
const localMinute=ref(props.minute)
const loading=ref(false)
const error=ref('')

async function load(){
  loading.value=true
  error.value=''
  try{
    local.value=await requestJson(
      `/api/traffic/v2/nation?level=nation&minute=${Math.round(localMinute.value)}`,
      {timeoutMs:45000})
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}
onMounted(()=>{if(props.selfFetch) load()})
watch(localMinute,()=>{if(props.selfFetch) load()})

const data=computed(()=>props.payload||local.value)
const rows=computed(()=>props.payload?props.flights:(local.value?.flights||[]))
const upcoming=computed(()=>data.value?.upcoming||[])
const intel=computed(()=>data.value?.intel||[])
const summary=computed(()=>data.value?.summary||{})
const model=computed(()=>data.value?.modelCard||null)
const modelTest=computed(()=>model.value?.nationalModel?.metrics?.test||null)

const limit=computed(()=>props.density==='slim'?16:(props.density==='min'?10:120))

// 逐市实况：和机场情报放在同一页，才有"机场能飞、周边看不见"的对照
const weatherRows=computed(()=>{
  const list=(data.value?.nodes||[]).filter(n=>n.weather).map(n=>({
    name:n.name,short:shortName(n.name),capital:!!n.capital,rank:n.rank||3,
    temp:n.weather.tempC,wind:n.weather.windMps,vis:n.weather.visM,low:!!n.weather.low,
  }))
  list.sort((a,b)=>(b.low?1:0)-(a.low?1:0)||(b.capital?1:0)-(a.capital?1:0)||a.rank-b.rank)
  return list.slice(0,props.density==='slim'?16:40)
})

function visText(vis){
  if(vis==null) return '—'
  const km=vis/1000
  return (km>=10?Math.round(km):km.toFixed(1))+' km'
}
function shortName(name){return (name||'').replace(/(市|地区|盟|自治州)$/,'')}
function clock(m){
  const base=8*60+Math.round(m||0)
  const t=((base%1440)+1440)%1440
  return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`
}
</script>

<template>
<div class="nb">
  <div class="nb-bar" v-if="selfFetch">
    <fieldset>
      <legend>数据时刻</legend>
      <input type="range" min="0" max="180" step="1" v-model.number="localMinute" aria-label="全国数据时刻"/>
      <b>{{ clock(localMinute) }}</b>
    </fieldset>
    <span class="nb-scope">全国 · {{ summary.cities }} 市 · {{ summary.corridors }} 条航线</span>
    <span class="nb-note">交通为模拟（SIM）；气象与雷达为公开源实况。</span>
  </div>

  <p class="nb-state" v-if="loading">正在加载全国数据…</p>
  <p class="nb-state bad" v-else-if="error">加载失败：{{ error }}<button @click="load">重试</button></p>

  <template v-else-if="data">
    <!-- ============ 调度台账 ============ -->
    <div class="nb-table" v-if="view==='ledger'">
      <div class="nb-hd">
        <h3>全国班次台账 <small>{{ rows.length }} 架在飞 · {{ upcoming.length }} 班待起飞</small></h3>
        <p>申请、计划、实际分列；每行是一架独立班次。数据时刻 {{ clock(localMinute) }}。</p>
      </div>
      <div class="nb-scroll">
        <table>
          <thead><tr>
            <th>班次 / 机型</th><th>起讫与航线</th><th>申请 / 计划 / 实际</th>
            <th>高度 / 许可</th><th>风险 / 裁决</th><th>限制</th>
          </tr></thead>
          <tbody>
            <tr v-for="f in rows.slice(0,limit)" :key="f.id"
                :class="{sel:f.id===selectedId}" @click="emit('select',f)">
              <td><b>{{ f.callsign }}</b><small>{{ f.id }}</small><small>{{ f.kindLabel||'省内' }}</small></td>
              <td>{{ f.fromName }} → {{ f.toName }}<small>{{ f.corridor }}</small></td>
              <td><small>申请 {{ f.requestAt }}</small><small>计划 {{ f.planAt }}</small><small>实际 {{ f.actualAt||'—' }}</small></td>
              <td><small>{{ f.altM }} m AGL</small><small>{{ f.clearance?.statusLabel }}</small></td>
              <td>
                <span class="risk" :class="f.riskLevel">{{ f.riskLevelLabel }} {{ f.riskP.toFixed(2) }}</span>
                <small>
                  {{ f.decisionLabel }}
                  <template v-if="f.pModel!=null"> · 模型 {{ (f.pModel*100).toFixed(0) }}%</template>
                  <em class="src" :class="f.probSource">{{ f.probSource==='MODEL'?'模型':'规则' }}</em>
                </small>
              </td>
              <td>{{ (f.alerts||[]).map(a=>a.label).join(' / ')||'—' }}</td>
            </tr>
            <tr v-for="f in upcoming.slice(0,props.density==='slim'?12:30)" :key="'u'+f.id" class="future">
              <td><b>{{ f.id.split('#')[0] }}</b><small>待起飞</small></td>
              <td>{{ f.fromName }} → {{ f.toName }}</td>
              <td><small>计划 {{ f.departAt }}</small><small>到达 {{ f.arriveAt }}</small></td>
              <td><small>{{ f.speedKmh }} km/h</small></td>
              <td><small>{{ f.waitMin }} 分钟后</small></td>
              <td>—</td>
            </tr>
            <tr v-if="!rows.length&&!upcoming.length"><td colspan="6" class="empty">此刻没有班次</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ 民航情报 ============ -->
    <div class="nb-table" v-else>
      <div class="nb-model" v-if="modelTest" data-model-card>
        <b>低能见度模型 {{ model.nationalModel.version }}</b>
        <span>测试集 AUC {{ modelTest.auc }} · Brier {{ modelTest.brier }} · TS {{ modelTest.ts }} · 基线 {{ (modelTest.baseRate*100).toFixed(1) }}%</span>
        <span>{{ model.nationalModel.provenance.cities }} 城 · {{ model.nationalModel.provenance.samples }} 样本 · 按时间切分</span>
        <em>输入与标签同源（open-meteo 模式能见度），指标衡量的是"模式能见度的演变可预测性"</em>
      </div>
      <div class="nb-hd">
        <h3>机场情报 <small>{{ intel.length }} 个机场城市</small></h3>
        <p>实况来自公开源（METAR / open-meteo）；“放行建议”是按能见度门槛算的规则派生值，不是官方结论。</p>
      </div>
      <div class="nb-scroll">
        <table>
          <thead><tr><th>机场</th><th>城市</th><th>能见度</th><th>风</th><th>温度</th><th>建议</th></tr></thead>
          <tbody>
            <tr v-for="row in intel.slice(0,props.density==='slim'?16:80)" :key="row.city+row.icao">
              <td><b>{{ row.icao||'—' }}</b><small>{{ row.station||'—' }}</small></td>
              <td>{{ row.city }}<small>{{ row.province }}</small></td>
              <td :class="{bad:row.low}">{{ visText(row.visM) }}</td>
              <td>{{ row.windMps==null?'—':row.windMps+' m/s' }}</td>
              <td>{{ row.tempC==null?'—':row.tempC+' °C' }}</td>
              <td><span class="tag" :class="row.tone">{{ row.status }}</span></td>
            </tr>
            <tr v-if="!intel.length"><td colspan="6" class="empty">本级没有机场城市</td></tr>
          </tbody>
        </table>
      </div>
      <div class="nb-weather">
        <h4>逐市实况 <small>{{ summary.weatherCities }} 城</small></h4>
        <ul>
          <li v-for="row in weatherRows" :key="row.name" :class="{bad:row.low}">
            <b>{{ row.short }}</b>
            <span>{{ row.temp==null?'—':row.temp+'°C' }}</span>
            <span>{{ row.wind==null?'—':row.wind+' m/s' }}</span>
            <span>{{ visText(row.vis) }}</span>
          </li>
        </ul>
      </div>
    </div>
  </template>
</div>
</template>

<style scoped>
.nb{display:flex;flex-direction:column;gap:8px;min-height:0;height:100%;color:#cfe6f5}
.nb-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:11.5px;color:#82a6bd}
.nb-bar fieldset{display:flex;align-items:center;gap:8px;border:0;margin:0;padding:0;min-width:240px;flex:0 1 340px}
.nb-bar legend{float:left;font-size:11px;color:#7d9cb3;padding:0 6px 0 0}
.nb-bar input[type=range]{flex:1;min-width:100px}
.nb-bar b{font-variant-numeric:tabular-nums;color:#bfe9ff}
.nb-scope{color:#cfe6f5}
.nb-note{color:#6f92a8;margin-left:auto}
.nb-state{margin:6px 0;font-size:12px;color:#8fb2c8}
.nb-state.bad{color:#ffa08a}
.nb-state button{margin-left:8px;background:#17394d;border:1px solid #2e6b85;color:#bfe9ff;border-radius:5px;padding:2px 8px;cursor:pointer}
.nb-table{display:flex;flex-direction:column;gap:8px;min-height:0;flex:1}
.nb-model{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;font-size:11px;color:#8fb2c8;
  border:1px solid rgba(70,140,160,.4);border-radius:7px;padding:5px 9px;background:rgba(12,40,52,.6)}
.nb-model b{color:#bfe9ff;font-size:11.5px}
.nb-model em{font-style:normal;color:#ffcf7a;flex-basis:100%}
.src{font-style:normal;font-size:9.5px;padding:0 4px;border-radius:3px;margin-left:4px}
.src.MODEL{background:rgba(70,190,150,.18);color:#7fe0bb}
.src.RULE{background:rgba(245,190,60,.16);color:#ffd479}
.nb-hd h3{margin:0;font-size:13px;color:#eaf6ff}
.nb-hd h3 small{margin-left:8px;font-size:11px;color:#7d9cb3;font-weight:400}
.nb-hd p{margin:3px 0 0;font-size:11px;color:#7d9cb3}
.nb-weather h4{margin:2px 0 4px;font-size:12px;color:#a9cde2}
.nb-weather h4 small{margin-left:6px;font-size:10.5px;color:#7d9cb3;font-weight:400}
.nb-weather ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(186px,1fr));gap:3px;max-height:128px;overflow:auto}
.nb-weather li{display:flex;gap:6px;align-items:baseline;font-size:11px;padding:3px 6px;border-radius:5px;
  background:rgba(12,32,46,.6);white-space:nowrap;overflow:hidden}
.nb-weather li b{flex:0 0 auto}
.nb-weather li.bad{outline:1px solid rgba(226,75,74,.5)}
.nb-weather span{color:#8fb2c8}
.nb-scroll{overflow:auto;min-height:0;flex:1;border:1px solid rgba(70,110,140,.3);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{position:sticky;top:0;background:#0f2a3c;color:#8fb2c8;font-weight:500;text-align:left;
  padding:6px 8px;border-bottom:1px solid rgba(70,110,140,.4);white-space:nowrap;font-size:11px}
td{padding:5px 8px;border-bottom:1px solid rgba(50,80,100,.25);color:#cfe6f5;vertical-align:top}
td small{display:block;font-size:10px;color:#7d9cb3}
tbody tr:hover td{background:rgba(30,70,95,.35)}
tbody tr.sel td{background:rgba(40,110,140,.35)}
tr.future td{color:#9dbccf;opacity:.85}
td.bad{color:#ffa08a}
td.empty{text-align:center;color:#6f92a8;padding:18px}
.risk{font-variant-numeric:tabular-nums;font-size:11px;padding:1px 5px;border-radius:4px}
.risk.HIGH{background:rgba(238,80,60,.22);color:#ffa08a}
.risk.MEDIUM{background:rgba(245,190,60,.18);color:#ffd479}
.risk.LOW{background:rgba(70,190,150,.16);color:#7fe0bb}
.tag{display:inline-block;font-size:10px;padding:1px 5px;border-radius:4px}
.tag.good{background:rgba(70,190,150,.18);color:#7fe0bb}
.tag.warn{background:rgba(245,190,60,.18);color:#ffd479}
.tag.bad{background:rgba(238,80,60,.2);color:#ffa08a}
.tag.quiet{background:rgba(120,150,175,.15);color:#9fb8c9}
@media(max-width:1440px){
  .nb-bar{font-size:11px;gap:8px}
  table{font-size:11px}
  th,td{padding:4px 6px}
}
</style>
