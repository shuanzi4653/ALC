<script setup>
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'

// 全国台账 / 全国情报：**同一份表，两个入口**。
//   ① 全国航线网页里的「台账」「情报」两个视图；
//   ② 1.0.0 原生的「调度台账」「运行情报」页（选"全国"范围时）。
// 所以它既能吃父组件已经拿到的 payload（不重复请求），也能自己拉（独立成页时）。
const props=defineProps({
  view:{type:String,default:'ledger'},          // ledger | intel
  payload:{type:Object,default:null},
  flights:{type:Array,default:()=>[]},
  minute:{type:Number,default:60},
  density:{type:String,default:'full'},
  selfFetch:{type:Boolean,default:false},
  selectedId:{type:String,default:''},
  // 'ledger'  = 调度台账：看"这一班什么时候飞、批没批"
  // 'briefing'= 班次情报：看"这一班为什么这么判"，按风险从高到低排
  // 两者共用一份数据与一张表，但排序与表头不同 —— 否则两个入口看到的是同一个页面。
  variant:{type:String,default:'ledger'},
})
const emit=defineEmits(['select'])

const local=ref(null)
const localMinute=ref(props.minute)
const loading=ref(false)
const error=ref('')

// 请求纪律（V1.0.2）：
//  ① 同一分钟不重取 —— 切 tab 回来、页面重渲染都不该再打一次 479 KB；
//  ② 拖滑杆防抖 300 ms、只在停下来后发一次，且取消上一次在途请求；
//  ③ 超过 3 秒在界面上报秒数，而不是让"正在加载"无限转。
let inflight=null
let debounceTimer=null
let lastKey=''
const elapsed=ref(0)
let tickTimer=null

function keyOf(minute){return `nation|${Math.round(minute)}`}

async function load(cached){
  const key=keyOf(localMinute.value)
  if(!cached&&key===lastKey&&local.value){return}
  if(inflight){try{inflight.abort()}catch(_){}}
  const controller=typeof AbortController!=='undefined'?new AbortController():null
  inflight=controller
  loading.value=true
  error.value=''
  elapsed.value=0
  if(tickTimer) clearInterval(tickTimer)
  tickTimer=setInterval(()=>{elapsed.value+=1},1000)
  try{
    const body=await requestJson(
      `/api/traffic/v2/nation?level=nation&minute=${Math.round(localMinute.value)}`,
      {timeoutMs:45000,signal:controller?.signal})
    if(controller&&controller.signal.aborted) return
    local.value=body
    lastKey=key
  }catch(e){
    if(controller&&controller.signal.aborted) return
    error.value=e.message||String(e)
  }finally{
    if(!controller||!controller.signal.aborted){
      loading.value=false
      if(tickTimer){clearInterval(tickTimer);tickTimer=null}
    }
  }
}

onMounted(()=>{if(props.selfFetch) load()})
watch(localMinute,()=>{
  if(!props.selfFetch) return
  if(debounceTimer) clearTimeout(debounceTimer)
  debounceTimer=setTimeout(()=>load(),300)
})
onUnmounted(()=>{
  if(debounceTimer) clearTimeout(debounceTimer)
  if(tickTimer) clearInterval(tickTimer)
  if(inflight){try{inflight.abort()}catch(_){}}
})

const data=computed(()=>props.payload||local.value)
const baseRows=computed(()=>props.payload?props.flights:(local.value?.flights||[]))
// —— 二次归类：表头可点排序 + 状态筛选片 ——
// 之前只有写死的"按风险降序"一种排法：想按起飞时刻看、想把延期挑出来，都做不到。
// 排序状态放在组件内（不写 URL）：这是"看一眼"的读法，不是需要分享的视图。
const sortKey=ref(props.variant==='briefing'?'risk':'depart')
const sortDir=ref(props.variant==='briefing'?'desc':'asc')
const filterKey=ref('all')
// 台账的搜索框（V1.0.6 补回）：V1.0.5 把旧的那张台账表换成这个组件时，
// 搜索与导出一起丢了 —— 而"能按班次号/城市定位一行"是值班时最常用的动作。
const query=ref('')
const q=computed(()=>query.value.trim().toLowerCase())
function matchQuery(row){
  const k=q.value
  if(!k) return true
  const hay=[row.callsign,row.fromName,row.toName,row.corridor,row.altM+'m',row.decisionLabel]
    .filter(Boolean).join(' ').toLowerCase()
  return hay.includes(k)
}
const FILTERS=[
  {key:'all',label:'全部'},
  {key:'high',label:'高风险'},
  {key:'detour',label:'绕飞'},
  {key:'hold',label:'延期'},
  {key:'model',label:'模型预警'},
]
function toggleSort(key){
  if(sortKey.value===key){ sortDir.value=sortDir.value==='asc'?'desc':'asc' }
  else{
    sortKey.value=key
    // 数值列第一次点按"从大到小"更符合直觉（先看风险最高的、先看能见度最差的）；
    // 文本列第一次点按"从小到大"（按拼音/编号顺着来）。
    sortDir.value=(key==='callsign'||key==='city'||key==='icao')?'asc':'desc'
  }
}
function sortMark(key){ return sortKey.value===key?(sortDir.value==='asc'?'▲':'▼'):'' }

const SORTERS={
  risk:(f)=>f.riskP||0,
  depart:(f)=>f.departMinute==null?1e9:f.departMinute,
  arrive:(f)=>f.arriveMinute==null?1e9:f.arriveMinute,
  callsign:(f)=>String(f.callsign||''),
  alt:(f)=>f.altM||0,
  pModel:(f)=>f.pModel==null?-1:f.pModel,
}
function matchFilter(f){
  const k=filterKey.value
  if(k==='all') return true
  if(k==='high') return f.riskLevel==='HIGH'
  if(k==='detour') return f.decision==='DETOUR'
  if(k==='hold') return f.decision==='HOLD'
  if(k==='model') return (f.pModel||0)>=0.35
  return true
}
const shownRows=computed(()=>{
  let list=baseRows.value.filter(matchFilter).filter(matchQuery)
  const get=SORTERS[sortKey.value]
  if(get){
    const dir=sortDir.value==='asc'?1:-1
    list=[...list].sort((a,b)=>{
      const x=get(a),y=get(b)
      if(typeof x==='string'||typeof y==='string') return String(x).localeCompare(String(y),'zh')*dir
      return (x-y)*dir
    })
  }
  return list
})
const SORT_LABEL={risk:'风险从高到低',depart:'起飞从早到晚',arrive:'到达从早到晚',
  callsign:'班次号',alt:'高度从高到低',pModel:'模型概率从高到低'}
const sortLabel=computed(()=>{
  const name=SORT_LABEL[sortKey.value]||sortKey.value
  return (sortDir.value==='asc'?name.replace('从高到低','从低到高').replace('从早到晚','从晚到早'):name)
})
/** 导出台账（前端生成，不占后端接口）：一行一班次，列与表头一致，UTF-8 BOM 保证 Excel 不乱码。 */
function exportLedger(){
  const list=shownRows.value
  if(!list.length) return
  const head=['班次','类型','起点','终点','航线','高度(m)','申请','计划','实际','裁决','风险']
  const lines=[head.join(',')]
  for(const row of list){
    lines.push([row.callsign,row.kind||'',row.fromName,row.toName,row.corridor,row.altM,
      row.requestAt||'',row.planAt||'',row.actualAt||'',row.decisionLabel||'',row.riskLevel||'']
      .map(v=>`"${String(v??'').replace(/"/g,'""')}"`).join(','))
  }
  const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob)
  const a=document.createElement('a')
  a.href=url; a.download=`全国班次台账-${new Date().toISOString().slice(0,10)}.csv`
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(()=>URL.revokeObjectURL(url),1000)
}

const filterCounts=computed(()=>{
  const list=baseRows.value
  return {
    all:list.length,
    high:list.filter(f=>f.riskLevel==='HIGH').length,
    detour:list.filter(f=>f.decision==='DETOUR').length,
    hold:list.filter(f=>f.decision==='HOLD').length,
    model:list.filter(f=>(f.pModel||0)>=0.35).length,
  }
})
const rows=computed(()=>{
  const list=[...baseRows.value]
  if(props.variant==='briefing'&&sortKey.value==='risk'&&sortDir.value==='desc'){
    list.sort((a,b)=>(b.riskP||0)-(a.riskP||0))
  }
  return list
})
const upcoming=computed(()=>data.value?.upcoming||[])
const intel=computed(()=>data.value?.intel||[])
const summary=computed(()=>data.value?.summary||{})
const zones=computed(()=>data.value?.zones||{available:false,counts:{}})
const model=computed(()=>data.value?.modelCard||null)
const modelTest=computed(()=>model.value?.nationalModel?.metrics?.test||null)

const limit=computed(()=>props.density==='slim'?16:(props.density==='min'?10:120))

// 机场情报的排序：默认保持接口顺序（机场城市按重要性排过），点表头才换。
const intelKey=ref('')
const intelDir=ref('asc')
function toggleIntel(key){
  if(intelKey.value===key){ intelDir.value=intelDir.value==='asc'?'desc':'asc' }
  else{ intelKey.value=key; intelDir.value=(key==='city'||key==='icao')?'asc':'asc' }
}
function intelMark(key){ return intelKey.value===key?(intelDir.value==='asc'?'▲':'▼'):'' }
const intelRows=computed(()=>{
  const list=[...intel.value]
  if(!intelKey.value) return list
  const get={vis:r=>r.visM==null?1e9:r.visM, wind:r=>r.windMps==null?-1:r.windMps,
             temp:r=>r.tempC==null?-1e9:r.tempC,
             city:r=>String(r.city||''), icao:r=>String(r.icao||'')}[intelKey.value]
  if(!get) return list
  const dir=intelDir.value==='asc'?1: -1
  return list.sort((a,b)=>{
    const x=get(a),y=get(b)
    if(typeof x==='string'||typeof y==='string') return String(x).localeCompare(String(y),'zh')*dir
    return (x-y)*dir
  })
})

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

// 纳入范围（口径，不是实时态势）。
// 主页右栏原本挂着一张"外围缓冲带内 N 城已退出通航"的折叠卡 —— N 和名单都随数据变，
// 摆在首页右下角会被读成"有一条正在发生的告警"。它其实是**建网规则**，
// 所以放到这里：机场情报讲的是"网络里有哪些点"，规则跟着网络走才对。
const borderKm=computed(()=>data.value?.border?.excludeKm||0)
const excluded=computed(()=>data.value?.border?.excludedCities||[])
function clock(m){
  // 同 NationPanel：跨零点加 +Nd，否则 00:40 分不清是哪一天。
  const raw=8*60+Math.round(m||0)
  const day=Math.floor(raw/1440)
  const t=((raw%1440)+1440)%1440
  const hhmm=`${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`
  return day>0?`${hhmm} +${day}d`:hhmm
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
    <!-- 这里不再重复"全国 N 市 · M 条航线"和口径句：
         页面顶栏已经写了作用域与口径，同一屏两处一样的话只是噪声。 -->
  </div>

  <p class="nb-state" v-if="loading">正在加载全国数据…{{ elapsed>2?`（已用 ${elapsed} 秒）`:'' }}</p>
  <p class="nb-state bad" v-else-if="error">加载失败：{{ error }}<button @click="load">重试</button></p>

  <template v-else-if="data">
    <!-- ============ 调度台账 ============ -->
    <div class="nb-table" v-if="view==='ledger'">
      <div class="nb-hd">
        <template v-if="variant==='evidence'">
          <h3>选取证对象 <small>{{ rows.length }} 架在飞</small></h3>
          <p>点一行选中班次，再在下方详情里点「取证」，得到从实况、判据到裁决的逐行来源链。</p>
        </template>
        <template v-else-if="variant==='briefing'">
          <h3>在飞班次情报 <small>{{ shownRows.length }} 架 · {{ sortLabel }}</small></h3>
          <p>每行一架飞行汽车：风险分、判据来源与放行裁决。申请 / 计划 / 实际三个时刻见「处置 · 调度台账」。</p>
        </template>
        <template v-else>
          <h3>全国班次台账 <small>{{ shownRows.length }} 架在飞 · {{ upcoming.length }} 班待起飞</small></h3>
          <p>申请、计划、实际分列；每行是一架独立班次，点行选中后在详情里可取证。</p>
        </template>
      </div>

      <!-- 二次归类：状态筛选片 + 表头排序。默认"全部 / 风险降序"，
           但读者可以自己换成"按起飞时刻""只看延期"等等。 -->
      <div class="nb-filters" data-intel-filters>
        <button v-for="f in FILTERS" :key="f.key" :class="{on:filterKey===f.key}"
                :data-filter="f.key" @click="filterKey=f.key">
          {{ f.label }} <em>{{ filterCounts[f.key] }}</em>
        </button>
        <span class="nb-sortnote">
          排序：{{ sortLabel }}<template v-if="filterKey!=='all'||q"> · 已筛 {{ shownRows.length }} 架</template>
        </span>
        <input v-model="query" type="search" class="nb-q" aria-label="搜索班次或城市"
               placeholder="搜索班次 / 城市 / 航线"/>
        <button class="nb-export" :disabled="!shownRows.length" @click="exportLedger"
                title="把当前筛选结果导成 CSV（前端生成，不请求后端）">导出 CSV</button>
      </div>

      <div class="nb-scroll">
        <table class="ledger">
          <thead><tr>
            <th class="srt" @click="toggleSort('callsign')">班次 / 类型 <i>{{ sortMark('callsign') }}</i></th>
            <th>起讫与航线</th>
            <th class="srt" @click="toggleSort('depart')">申请 / 计划 / 实际 <i>{{ sortMark('depart') }}</i></th>
            <th class="srt" @click="toggleSort('alt')">高度 / 许可 <i>{{ sortMark('alt') }}</i></th>
            <th class="srt" @click="toggleSort('risk')">风险 / 裁决 <i>{{ sortMark('risk') }}</i></th>
            <th class="srt" @click="toggleSort('pModel')">限制 <i>{{ sortMark('pModel') }}</i></th>
          </tr></thead>
          <tbody>
            <tr v-for="f in shownRows.slice(0,limit)" :key="f.id"
                :class="{sel:f.id===selectedId}" @click="emit('select',f)">
              <td><b>{{ f.callsign }}</b><small>{{ f.id }} · {{ f.kindLabel||'省内' }}</small></td>
              <td><span class="leg">{{ f.fromName }} → {{ f.toName }}</span><small>{{ f.corridor }}</small></td>
              <td class="times"><small>申请 {{ f.requestAt }}</small><small>计划 {{ f.planAt }}</small><small>实际 {{ f.actualAt||'—' }}</small></td>
              <td><small>{{ f.altM }} m AGL</small><small>{{ f.clearance?.statusLabel }}</small></td>
              <td>
                <span class="risk" :class="f.riskLevel">{{ f.riskLevelLabel }}风险 {{ f.riskP.toFixed(2) }}</span>
                <small>
                  {{ f.decisionLabel }}
                  <template v-if="f.pModel!=null"> · 模型 {{ (f.pModel*100).toFixed(0) }}%</template>
                  <em class="src" :class="f.probSource">{{ f.probSource==='MODEL'?'模型':'规则' }}</em>
                </small>
              </td>
              <td>{{ (f.alerts||[]).map(a=>a.label).join(' / ')||'—' }}</td>
            </tr>
            <tr v-if="filterKey==='all'" v-for="f in upcoming.slice(0,props.density==='slim'?12:30)" :key="'u'+f.id" class="future">
              <td><b>{{ f.id.split('#')[0] }}</b><small>待起飞</small></td>
              <td>{{ f.fromName }} → {{ f.toName }}</td>
              <td><small>计划 {{ f.departAt }}</small><small>到达 {{ f.arriveAt }}</small></td>
              <td><small>{{ f.speedKmh }} km/h</small></td>
              <td><small>{{ f.waitMin }} 分钟后</small></td>
              <td>—</td>
            </tr>
            <tr v-if="!shownRows.length&&!upcoming.length"><td colspan="6" class="empty">
              {{ filterKey==='all'?'此刻没有班次':'当前筛选下没有班次 —— 换一个筛选片或点「全部」' }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ 空域情报（机场实况 + 逐市实况） ============ -->
    <div class="nb-table" v-else>
      <div class="nb-model" v-if="modelTest" data-model-card>
        <b>低能见度模型 {{ model.nationalModel.version }}</b>
        <span>测试集 AUC {{ modelTest.auc }} · Brier {{ modelTest.brier }} · TS {{ modelTest.ts }} · 基线 {{ (modelTest.baseRate*100).toFixed(1) }}%</span>
        <span>{{ model.nationalModel.provenance.cities }} 城 · {{ model.nationalModel.provenance.samples }} 样本 · 按时间切分</span>
        <em>输入与标签同源（open-meteo 模式能见度），指标衡量的是"模式能见度的演变可预测性"</em>
      </div>
      <!-- 空域禁飞区：原来挂在「态势」侧栏，跟着 mode 跑到推演页去过。
           它是空域的事，就该跟「空域情报」这一页在一起；边界与穿越明细在
           地图「空域视角」里看，这里给的是同一套几何的**账目**。 -->
      <section class="nb-airspace" v-if="zones.available" data-airspace-block>
        <h3>空域禁飞区 <small>规则化生成 · {{ zones.policy==='PROHIBITED'?'一律禁飞':'可申请穿越' }}</small></h3>
        <div class="nb-air-grid">
          <div><small>受限机场</small><b>{{ zones.counts.airports||0 }}</b></div>
          <div><small>限制区</small><b>{{ zones.counts.limitZones||0 }} 个</b></div>
          <div><small>跑道梯形</small><b>{{ zones.counts.runwayZones||0 }} 处</b></div>
          <div><small>覆盖陆域</small><b>{{ ((zones.counts.coverageRatio||0)*100).toFixed(2) }}%</b></div>
        </div>
        <p class="nb-air-note">
          {{ zones.note }} 边界与逐条穿越在地图右上「空域视角」里看：那里画的是同一套多边形，
          可以逐条核对哪条航线穿过了哪个限制区。
        </p>
      </section>
      <div class="nb-hd">
        <h3>机场情报 <small>{{ intel.length }} 个机场城市</small></h3>
        <p>实况来自公开源（METAR / open-meteo）；“放行建议”是按能见度门槛算的规则派生值，不是官方结论。
          <template v-if="payload?.weatherMode?.virtual">
            <b class="vvis-note">虚拟气象开启中：能见度与放行建议按合成雾区重算，温度与风仍是实况。</b>
          </template>
        </p>
        <p v-if="zones.available" class="nb-zone-line">
          净空（规则化生成，非官方公布）：<b>{{ zones.counts.airports }}</b> 机场 ·
          限制区 <b>{{ zones.counts.limitZones }}</b> 个 · 覆盖 <b>{{ ((zones.counts.coverageRatio||0)*100).toFixed(2) }}%</b> 陆域 ·
          待审穿越 <b>{{ zones.crossings ? zones.crossings.hit+'/'+zones.crossings.corridors : '见「空域视角」' }}</b>
        </p>
      </div>      <div class="nb-scroll">
        <table>
          <thead><tr>
            <th class="srt" @click="toggleIntel('icao')">机场 <i>{{ intelMark('icao') }}</i></th>
            <th class="srt" @click="toggleIntel('city')">城市 <i>{{ intelMark('city') }}</i></th>
            <th class="srt" @click="toggleIntel('vis')">能见度 <i>{{ intelMark('vis') }}</i></th>
            <th class="srt" @click="toggleIntel('wind')">风 <i>{{ intelMark('wind') }}</i></th>
            <th class="srt" @click="toggleIntel('temp')">温度 <i>{{ intelMark('temp') }}</i></th>
            <th>建议</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in intelRows.slice(0,props.density==='slim'?16:80)" :key="row.city+row.icao">
              <td><b>{{ row.icao||'—' }}</b><small>{{ row.station||'—' }}</small></td>
              <td>{{ row.city }}<small>{{ row.province }}</small></td>
              <td :class="{bad:row.low}">{{ visText(row.visM) }}<em v-if="row.virtualVis" class="vvis" title="虚拟气象：这个能见度来自合成雾区，不是实况">虚拟</em></td>
              <td>{{ row.windMps==null?'—':row.windMps+' m/s' }}</td>
              <td>{{ row.tempC==null?'—':row.tempC+' °C' }}</td>
              <td><span class="tag" :class="row.tone">{{ row.status }}</span></td>
            </tr>
            <tr v-if="!intel.length"><td colspan="6" class="empty">本级没有机场城市</td></tr>
          </tbody>
        </table>
      </div>
      <p class="nb-scope-foot" v-if="view==='intel'&&borderKm" data-scope-foot>
        纳入范围：台湾、西藏、香港、澳门不纳入通航；外围 <b>{{ borderKm }}</b> km 缓冲带内的城市整体退出通航（保守取值）。
        <template v-if="excluded.length">
          当前共 <b>{{ excluded.length }}</b> 城：{{ excluded.map(row=>row.name.replace(/市$/,'')+' '+row.distanceKm+' km').join('、') }}。
        </template>
      </p>
      <!-- 逐市实况收进折叠块：它和「气象监测」页重复，而上面的机场表有 56 行，
           两者抢高度时表格只剩 4 行可见 —— 表头写着 56、只看到 4，比不给还糟。 -->
      <details class="nb-weather">
        <summary>逐市实况 <small>{{ summary.weatherCities }} 城 · 点开看逐市温度 / 风速 / 能见度</small></summary>
        <ul>
          <li v-for="row in weatherRows" :key="row.name" :class="{bad:row.low}">
            <b>{{ row.short }}</b>
            <span>{{ row.temp==null?'—':row.temp+'°C' }}</span>
            <span>{{ row.wind==null?'—':row.wind+' m/s' }}</span>
            <span>{{ visText(row.vis) }}</span>
          </li>
        </ul>
      </details>
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
.nb-q{width:150px;padding:3px 8px;border-radius:6px;font-size:11px;
  border:1px solid rgba(70,110,140,.4);background:rgba(10,26,38,.7);color:#dff3ff}
.nb-q::placeholder{color:#6f92a8}
.nb-export{padding:3px 9px;border-radius:6px;font-size:11px;cursor:pointer;
  border:1px solid rgba(70,110,140,.4);background:transparent;color:#9fc6dd}
.nb-export:hover:not(:disabled){border-color:rgba(76,141,255,.55);color:#cfe6f5}
.nb-export:disabled{opacity:.45;cursor:not-allowed}
html[data-theme="light"] .nb-q{background:#fff !important;color:#16324a !important;border-color:#cfdcea !important}
html[data-theme="light"] .nb-q::placeholder{color:#7d97ad}
html[data-theme="light"] .nb-export{color:#31556f !important;border-color:#cfdcea !important}
.nb-bar b{font-variant-numeric:tabular-nums;color:#bfe9ff}
.nb-scope{color:#cfe6f5}
.nb-scope-foot{margin:0;font-size:10.5px;line-height:1.7;color:#7d9cb3;
  border-left:2px solid rgba(120,160,190,.35);padding:2px 0 2px 8px}
.nb-scope-foot b{color:#bfe9ff;font-weight:500}
.nb-zone-line{color:#9fb7c8}
.nb-zone-line b{color:#bfe9ff;font-weight:500}
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
.nb-weather summary{cursor:pointer;font-size:12px;color:#a9cde2;padding:1px 0;list-style:none}
.nb-weather summary::-webkit-details-marker{display:none}
.nb-weather summary::before{content:'▸ ';color:#7fa5bd}
.nb-weather[open] summary::before{content:'▾ '}
.nb-weather[open] summary{margin-bottom:4px}
.nb-weather h4{margin:2px 0 4px;font-size:12px;color:#a9cde2}
.nb-weather h4 small{margin-left:6px;font-size:10.5px;color:#7d9cb3;font-weight:400}
.nb-weather ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(186px,1fr));gap:3px;max-height:128px;overflow:auto}
.nb-weather li{display:flex;gap:6px;align-items:baseline;font-size:11px;padding:3px 6px;border-radius:5px;
  background:rgba(12,32,46,.6);white-space:nowrap;overflow:hidden}
.nb-weather li b{flex:0 0 auto}
.nb-weather li.bad{outline:1px solid rgba(226,75,74,.5)}
.nb-weather span{color:#8fb2c8}
.nb-airspace{border:1px solid rgba(70,110,140,.35);border-radius:8px;padding:8px 10px;
  margin:0 2px 8px;background:rgba(10,26,38,.5)}
.nb-airspace h3{font-size:12px;color:#cfe6f5;margin-bottom:6px}
.nb-airspace h3 small{margin-left:6px;font-size:10px;color:#6f92a8;font-weight:400}
.nb-air-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
.nb-air-grid div{display:flex;flex-direction:column;gap:1px}
.nb-air-grid small{font-size:10px;color:#7d9cb3}
.nb-air-grid b{font-size:13px;color:#dfeefb;font-variant-numeric:tabular-nums}
.nb-air-note{margin-top:6px;font-size:10px;line-height:1.55;color:#6f92a8}
html[data-theme="light"] .nb-airspace{background:#f6fafd;border-color:#dbe6f1}
html[data-theme="light"] .nb-airspace h3{color:#12314a}
html[data-theme="light"] .nb-air-grid b{color:#0f3550}
html[data-theme="light"] .nb-air-note,html[data-theme="light"] .nb-air-grid small{color:#6b8399}
.nb-filters{display:flex;align-items:center;gap:5px;flex-wrap:wrap;padding:0 2px 6px}
.nb-filters button{background:none;border:1px solid rgba(70,110,140,.45);color:#9dbccf;
  border-radius:999px;padding:2px 9px;font-size:10.5px;cursor:pointer;transition:.15s}
.nb-filters button:hover{border-color:rgba(110,180,215,.7);color:#cfe6f5}
.nb-filters button.on{background:rgba(126,206,255,.16);border-color:rgba(126,206,255,.7);color:#eaf8ff}
.nb-filters button em{font-style:normal;opacity:.7;margin-left:3px}
.nb-sortnote{margin-left:auto;font-size:10px;color:#6f92a8}
table th.srt{cursor:pointer;user-select:none;white-space:nowrap}
table th.srt:hover{color:#eaf8ff}
table th.srt i{font-style:normal;font-size:9px;color:#8ef0ff;margin-left:2px}
html[data-theme="light"] .nb-filters button{border-color:#cfdcea;color:#31556f}
html[data-theme="light"] .nb-filters button.on{background:#e3f0fb;border-color:#9cc7e8;color:#0d4f74}
html[data-theme="light"] .nb-sortnote{color:#6b8399}
html[data-theme="light"] table th.srt:hover{color:#0f3550}
html[data-theme="light"] table th.srt i{color:#0b7ea6}
.nb-scroll{overflow:auto;min-height:0;flex:1;border:1px solid rgba(70,110,140,.3);border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
/* 台账：列宽定死，否则"起讫与航线"会把后面几列挤到看不见；表格本身不横向滚 */
table.ledger{table-layout:fixed}
table.ledger th:nth-child(1),table.ledger td:nth-child(1){width:15%}
table.ledger th:nth-child(2),table.ledger td:nth-child(2){width:27%}
table.ledger th:nth-child(3),table.ledger td:nth-child(3){width:24%}
table.ledger th:nth-child(4),table.ledger td:nth-child(4){width:12%}
table.ledger th:nth-child(5),table.ledger td:nth-child(5){width:13%}
table.ledger th:nth-child(6),table.ledger td:nth-child(6){width:9%}
table.ledger td{overflow:hidden}
table.ledger .leg{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 三个时刻并排：竖排会把每条班次撑成三行，106 条就要滚很长 */
td.times{white-space:nowrap}
td.times small{display:inline;margin-right:7px;font-size:10px}
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

/* 虚拟气象下能见度是合成值：一枚小标，避免"620 m"被当成实况读数抄进材料 */
.vvis{margin-left:4px;font-style:normal;font-size:9px;padding:0 4px;border-radius:999px;
  color:#ffd08a;background:rgba(200,140,30,.18);border:1px solid rgba(220,170,60,.5);vertical-align:1px}
.vvis-note{color:#ffd08a;display:block;margin-top:2px}
html[data-theme="light"] .vvis{color:#7a5200;background:#fdf3e0;border-color:#e0bb78}
html[data-theme="light"] .vvis-note{color:#7a5200}
</style>
