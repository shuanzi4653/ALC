<script setup>
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {requestJson} from '../../api.js'
import {store} from '../../store.js'
import NationMap from './NationMap.vue'
import NationBriefing from './NationBriefing.vue'

// 全国运行台：态势 / 台账 / 情报 / 处置 四个视图共用同一份 `payload`。
//
// 三条纪律：
//   ① **数字按块写**：每级、每省、每市都显示自己的航线/在飞/异常，总数单独在顶部；
//   ② **班次是对象**：图上点哪一架，台账就选哪一架，详情里就是这一架的许可与剖面；
//   ③ **逐级重新请求**：下钻与返回都清空上一屏，内存里不留整棵树。
const props=defineProps({compact:{type:Boolean,default:false}})

const level=ref('nation')
const ident=ref('')
const trail=ref([{level:'nation',id:'',label:'全国'}])
const data=ref(null)
const view=ref('map')
const error=ref(''),loading=ref(false)
const busy=ref('')
const evidence=ref(null)
const evidenceBusy=ref(false)
const evidenceErr=ref('')

const minute=ref(60)
const playing=ref(false)
const speed=ref(1)                    // 分钟/秒：0.25≈15×、1=60×、5=300×
const radarOn=ref(true)
const fogOn=ref(true)
const terrainOn=ref(true)
const tilt=ref(false)
const virtualMode=ref(false)
const density=ref('full')
const selectedId=ref('')
const selectedCorridor=ref('')
const followId=ref('')

const flights=ref([])
const live=ref({corridors:0,airborne:0,delayed:0,hold:0,blocked:0,lowVisCities:0})
const byProvince=ref({})
const byCity=ref({})
let timer=null,pushTimer=null,fetchAt=0,seq=0

const MINUTES=180
const mapRef=ref(null)

const summary=computed(()=>data.value?.summary||{})
const rollup=computed(()=>data.value?.rollup||{level:'nation',total:{},regions:[],provinces:[],cities:[]})
const total=computed(()=>({...(rollup.value.total||{}),...live.value}))
const radarMeta=computed(()=>data.value?.radar||{})
const border=computed(()=>data.value?.border||{})
const fog=computed(()=>data.value?.fog||{available:false,counts:{},bands:{},cities:[]})

// 回波范围：三档环一起算，定位按钮按它飞过去
const radarBBox=computed(()=>{
  const bands=data.value?.radar?.bands||{}
  let minLon=999,minLat=999,maxLon=-999,maxLat=-999,any=false
  for(const level of ['STRONG','CONVECTIVE','WEAK']){
    for(const ring of bands[level]||[]){
      for(const [lon,lat] of ring||[]){
        any=true
        if(lon<minLon)minLon=lon; if(lon>maxLon)maxLon=lon
        if(lat<minLat)minLat=lat; if(lat>maxLat)maxLat=lat
      }
    }
  }
  return any?[minLon,minLat,maxLon,maxLat]:null
})
// —— 全国取证 ——
// 给的是"每一行都有来源"的证据链；大模型没配置就只显示规则链，不冒充模型结论。
async function loadEvidence(){
  const flight=selectedFlight.value
  if(!flight) return
  evidenceBusy.value=true
  evidenceErr.value=''
  try{
    evidence.value=await requestJson(
      `/api/traffic/v2/nation/evidence?flight=${encodeURIComponent(flight.id)}&minute=${Math.round(minute.value)}`,
      {timeoutMs:25000})
  }catch(e){evidenceErr.value=e.message||String(e);evidence.value=null}
  finally{evidenceBusy.value=false}
}
function clearEvidence(){evidence.value=null;evidenceErr.value=''}

function locateLayer(kind){
  followId.value=''
  const box=kind==='radar'?radarBBox.value:(data.value?.fog?.bbox||null)
  if(box) mapRef.value?.fitBounds(box)
}
const alerts=computed(()=>data.value?.alerts||[])
const intel=computed(()=>data.value?.intel||[])
const upcoming=computed(()=>data.value?.upcoming||[])

const headline=computed(()=>{
  const t=total.value
  const where=level.value==='nation'?'全国':(trail.value[trail.value.length-1]?.label||'本级')
  const parts=[`${where} ${t.corridors||0} 条航线`,`在飞 ${t.airborne||0} 架`]
  if(t.delayed)parts.push(`绕飞 ${t.delayed} 架`)
  if(t.hold)parts.push(`暂缓 ${t.hold} 架`)
  if(t.blocked)parts.push(`边境停飞 ${t.blocked} 条`)
  if(t.lowVisCities)parts.push(`低能见度 ${t.lowVisCities} 城`)
  return parts.join(' · ')
})

const selectedFlight=computed(()=>flights.value.find(f=>f.id===selectedId.value)||null)
const selectedLine=computed(()=>(data.value?.corridors||[]).find(c=>c.id===selectedCorridor.value)||null)

function clock(m){
  const base=8*60+Math.round(m||0)
  const t=((base%1440)+1440)%1440
  return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`
}
function shortName(name){return (name||'').replace(/(市|地区|盟|自治州)$/,'')}

async function loadFlights(){
  const now=Date.now()
  if(now<fetchAt) return
  fetchAt=now+850
  const my=++seq
  try{
    const payload=await requestJson(
      `/api/traffic/v2/nation/flights?level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${Math.round(minute.value)}`,
      {timeoutMs:20000})
    if(my!==seq) return
    flights.value=payload.flights||[]
    byProvince.value=payload.byProvince||{}
    byCity.value=payload.byCity||{}
    live.value={...live.value,...(payload.traffic||{})}
  }catch(e){/* 时间轴刷新失败不打断主界面 */}
}

async function load(){
  loading.value=true
  error.value=''
  data.value=null
  selectedId.value=''
  selectedCorridor.value=''
  followId.value=''
  flights.value=[]
  try{
    data.value=await requestJson(
      `/api/traffic/v2/nation?level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${Math.round(minute.value)}`,
      {timeoutMs:45000})
    flights.value=data.value?.flights||[]
    live.value={...(data.value?.traffic||{})}
    byProvince.value={}
    byCity.value={}
    mapRef.value?.resetView?.()
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}

function go(nextLevel,nextId,nextLabel){
  level.value=nextLevel
  ident.value=nextId||''
  if(nextLevel==='nation') trail.value=[{level:'nation',id:'',label:'全国'}]
  else{
    const cut=trail.value.findIndex(item=>item.level===nextLevel)
    if(cut>=0) trail.value=trail.value.slice(0,cut)
    trail.value=[...trail.value,{level:nextLevel,id:nextId||'',label:nextLabel||nextId}]
  }
  load()
}
function back(){
  if(trail.value.length<=1) return
  const next=trail.value[trail.value.length-2]
  trail.value=trail.value.slice(0,-1)
  level.value=next.level
  ident.value=next.id
  load()
}
function drill(nextLevel,nextId,label){
  if(nextLevel==='province'&&level.value==='province') return
  if(nextLevel==='city'&&level.value==='city') return
  go(nextLevel,nextId,label)
}

function togglePlay(){
  playing.value=!playing.value
  if(playing.value){
    timer=setInterval(()=>{
      minute.value=(minute.value+speed.value)%MINUTES
      loadFlights()
    },1000)
  }else if(timer){clearInterval(timer);timer=null}
}
watch(speed,()=>{ if(playing.value){togglePlay();togglePlay()} })

function pickFlight(flight){
  if(selectedId.value!==flight.id){followId.value='';clearEvidence()}
  selectedId.value=flight.id
  selectedCorridor.value=''
}
function toggleFollow(){
  followId.value=followId.value===selectedId.value?'':selectedId.value
}
function pickCorridor(line){
  selectedCorridor.value=line.id
  selectedId.value=''
  followId.value=''
}
function locate(){ if(selectedFlight.value) minute.value=selectedFlight.value.departMinute; playing.value=false }

const ledgerRows=computed(()=>{
  const rows=[...(flights.value||[]).map(f=>({...f,state:'AIRBORNE'}))]
  const limit=density.value==='slim'?20:(density.value==='min'?10:120)
  return rows.slice(0,limit)
})
const upcomingRows=computed(()=>upcoming.value.slice(0,density.value==='slim'?12:30))
const intelRows=computed(()=>{
  const limit=density.value==='slim'?16:80
  return intel.value.slice(0,limit)
})
const weatherRows=computed(()=>{
  const rows=(data.value?.nodes||[]).filter(n=>n.weather).map(n=>({
    name:n.name,short:shortName(n.name),capital:!!n.capital,rank:n.rank||3,
    temp:n.weather.tempC,wind:n.weather.windMps,vis:n.weather.visM,low:!!n.weather.low,
  }))
  rows.sort((a,b)=>(b.low?1:0)-(a.low?1:0)||(b.capital?1:0)-(a.capital?1:0)||a.rank-b.rank)
  return rows.slice(0,level.value==='nation'?12:(density.value==='slim'?16:40))
})

// 时间轴推进时，只刷新"在飞/绕飞/暂缓"这三个会变的数；航线数、停飞数是静态的，
// 不该跟着分钟乱跳。所以按省/市名去 byProvince/byCity 里取，取不到就退回快照值。
function airOf(name,fallback){const row=byProvince.value[name];return row?row.airborne:(fallback||0)}
function airOfCity(name,fallback){const row=byCity.value[name];return row?row.airborne:(fallback||0)}

// —— 走廊逐公里剖面 ——
// 为什么要"逐公里"而不是一个总数：一条 120 km 的航路，回波可能只压住中间 15 km，
// 说"穿回波"会让人以为整条都不能飞；逐段标出来，才知道是哪一段、多长。
const BAND_LABEL={STRONG:'强回波（45 dBZ 以上）',CONVECTIVE:'对流回波（35–45）',WEAK:'弱回波（15–35）','':'无回波'}
const BAND_COLOR={STRONG:'rgba(238,72,60,.55)',CONVECTIVE:'rgba(245,190,60,.45)',WEAK:'rgba(40,190,110,.30)','':'transparent'}

function haversine(a,b){
  const R=6371,rad=Math.PI/180
  const dLat=(b[1]-a[1])*rad,dLon=(b[0]-a[0])*rad
  const h=Math.sin(dLat/2)**2+Math.cos(a[1]*rad)*Math.cos(b[1]*rad)*Math.sin(dLon/2)**2
  return 2*R*Math.asin(Math.min(1,Math.sqrt(h)))
}
function ringHit(ring,lon,lat){
  let inside=false
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1]
    if(((yi>lat)!==(yj>lat))&&(lon<(xj-xi)*(lat-yi)/((yj-yi)||1e-9)+xi)) inside=!inside
  }
  return inside
}
function bandAt(lon,lat){
  const bands=data.value?.radar?.bands||{}
  for(const name of ['STRONG','CONVECTIVE','WEAK']){
    for(const ring of bands[name]||[]){ if(ringHit(ring,lon,lat)) return name }
  }
  return ''
}
const corridorProfile=computed(()=>{
  const line=selectedLine.value
  if(!line) return null
  const path=(line.path&&line.path.length>1)?line.path:[line.fromLonLat,line.toLonLat]
  const legs=[]
  let total=0
  for(let i=0;i<path.length-1;i++){
    const len=haversine(path[i],path[i+1])
    legs.push({a:path[i],b:path[i+1],len,start:total})
    total+=len
  }
  if(!legs.length||total<=0) return null
  const count=Math.min(72,Math.max(16,Math.round(total/6)))
  const samples=[]
  for(let k=0;k<=count;k++){
    const target=total*k/count
    const leg=legs.find(item=>target<=item.start+item.len)||legs[legs.length-1]
    const t=leg.len?(target-leg.start)/leg.len:0
    const lon=leg.a[0]+(leg.b[0]-leg.a[0])*t
    const lat=leg.a[1]+(leg.b[1]-leg.a[1])*t
    samples.push({km:Math.round(target),lon,lat,band:bandAt(lon,lat)})
  }
  const segments=[]
  for(const sample of samples){
    const last=segments[segments.length-1]
    if(last&&last.band===sample.band) last.to=sample.km
    else segments.push({band:sample.band,from:sample.km,to:sample.km})
  }
  return {totalKm:Math.round(total),segments}
})
// 剖面里的计划高度包线：15% 爬升 / 70% 巡航 / 15% 下降
const profilePoints=computed(()=>{
  const prof=corridorProfile.value
  if(!prof) return ''
  const x0=8,w=304,yGround=68,yTop=14
  return [[0,yGround],[0.15,yTop],[0.85,yTop],[1,yGround]]
    .map(([fx,fy])=>`${(x0+fx*w).toFixed(1)},${fy}`).join(' ')
})

const profileText=computed(()=>{
  const prof=corridorProfile.value
  if(!prof) return ''
  return prof.segments.filter(s=>s.band)
    .map(s=>`${s.from}–${s.to} km ${BAND_LABEL[s.band]}`).join(' · ')||'全线无回波'
})

function visText(vis){
  if(vis==null) return '—'
  const km=vis/1000
  return (km>=10?Math.round(km):km.toFixed(1))+' km'
}

// 推送：网关每 5 秒广播一条心跳，只有"雷达换帧 / 实况更新 / 模型换版"才算变化。
// 变化时重取本级数据；没变化就什么都不做 —— 屏幕空闲时不再定时轮询整份载荷。
const pushAge=ref(0)
watch(()=>store.nationPulse,(value)=>{
  if(!value) return
  pushAge.value=0
  if(value.changed) load()
})

onMounted(()=>{
  load()
  // 推送计时用独立定时器：不能和推演播放共用一个变量，否则一开播就把计时器顶掉
  pushTimer=setInterval(()=>{pushAge.value+=1},1000)
})
onUnmounted(()=>{
  if(timer) clearInterval(timer)
  if(pushTimer) clearInterval(pushTimer)
})
</script>

<template>
<section class="nrn">
  <header class="nrn-hd">
    <div class="nrn-crumb">
      <template v-for="(item,index) in trail" :key="item.level+item.id">
        <button v-if="index<trail.length-1" @click="go(item.level,item.id,item.label)">{{ item.label }}</button>
        <b v-else>{{ item.label }}</b>
        <span v-if="index<trail.length-1" class="sep">›</span>
      </template>
      <button v-if="trail.length>1" class="back" @click="back">返回上一级</button>
    </div>
    <p class="nrn-headline" data-nation-headline>{{ headline }}</p>
    <p class="nrn-sub">
      省 <b>{{ summary.provinces }}</b> · 市 <b>{{ summary.cities }}</b> ·
      机场 <b>{{ summary.airports }}</b> · 无机场市 <b>{{ summary.feedCities }}</b> ·
      逐市气象 <b>{{ summary.weatherCities }}</b>
      <span v-if="level==='nation'&&border.excludeKm"> · 边境 {{ border.excludeKm }} km 内 <b>{{ (border.excludedCities||[]).length }}</b> 城已退出通航</span>
    </p>
  </header>

  <nav class="nrn-tabs" data-nation-tabs>
    <button :class="{on:view==='map'}" @click="view='map'">态势</button>
    <button :class="{on:view==='ledger'}" @click="view='ledger'">台账 <em>{{ flights.length }}</em></button>
    <button :class="{on:view==='intel'}" @click="view='intel'">情报 <em>{{ intel.length }}</em></button>
    <button :class="{on:view==='alerts'}" @click="view='alerts'">处置 <em :class="{bad:alerts.length}">{{ alerts.length }}</em></button>
  </nav>

  <p class="nrn-state" v-if="loading">正在加载本级数据…</p>
  <p class="nrn-state bad" v-else-if="error">本级不可用 · {{ error }}<button @click="load">重试</button></p>

  <div class="nrn-body" v-else-if="data" :class="{'no-map':view!=='map'}">
    <!-- ================= 态势 ================= -->
    <div class="nrn-map" v-show="view==='map'">
      <div class="nrn-tools">
        <button class="play" @click="togglePlay">{{ playing?'Ⅱ 暂停':'▶ 推演' }}</button>
        <input type="range" min="0" :max="MINUTES" step="1" v-model.number="minute"
               @input="loadFlights" aria-label="推演时间"/>
        <b class="clock">{{ clock(minute) }}</b>
        <select v-model.number="speed" aria-label="推演倍速">
          <option :value="0.25">15 倍速</option>
          <option :value="1">60 倍速</option>
          <option :value="5">300 倍速</option>
        </select>
        <button :class="{on:radarOn}" @click="radarOn=!radarOn">回波</button>
        <button :class="{on:fogOn}" @click="fogOn=!fogOn" :disabled="!fog.available">雾区</button>
        <button :class="{on:terrainOn}" @click="terrainOn=!terrainOn">地形</button>
        <button :class="{on:tilt}" @click="tilt=!tilt">立体</button>
        <button :class="{on:virtualMode}" @click="virtualMode=!virtualMode"
                :title="'虚拟增强：回波与绕飞/停飞在图上更醒目，用于演示'">{{ virtualMode?'虚拟':'实测' }}</button>
        <select v-model="density" aria-label="信息密度">
          <option value="full">标准</option>
          <option value="slim">精简</option>
          <option value="min">极简</option>
        </select>
        <button :disabled="!radarBBox" @click="locateLayer('radar')">定位回波</button>
        <button :disabled="!fog.bbox" @click="locateLayer('fog')">定位雾区</button>
        <button @click="followId='';mapRef?.resetView()">复位</button>
      </div>

      <div class="nrn-canvas">
      <NationMap ref="mapRef" :data="data" :flights="flights" :minute="minute"
                 :radar-on="radarOn" :fog-on="fogOn" :terrain-on="terrainOn" :tilt="tilt"
                 :density="density" :virtual-mode="virtualMode"
                 :selected-id="selectedId" :selected-corridor="selectedCorridor"
                 :follow-id="followId"
                 @drill="drill" @select-flight="pickFlight" @select-corridor="pickCorridor"/>
      </div>

      <div class="nrn-monitor" data-border-monitor>
        <strong>越界监视：本视图内 {{ border.inside||0 }} 架位于管制带</strong>
        <span>比对范围：{{ border.scope }}</span>
        <span>停飞航线 {{ border.blockedCorridors||0 }} 条<template v-if="(border.blockedNames||[]).length">（{{ (border.blockedNames||[]).slice(0,3).join('、') }}{{ (border.blockedNames||[]).length>3?' 等':'' }}）</template></span>
        <span>已改线 {{ border.reroutedCorridors||0 }} 条</span>
        <span v-if="fog.available">低能见度 {{ fog.counts.cities }} 城（&lt;1.5 km {{ fog.counts.BAN }} 城）</span>
        <span class="push" :class="{on:store.wsConnected}" :title="store.wsConnected?'雷达/实况/模型任一变化由服务端推送':'未连上推送，仅按需拉取'">
          {{ store.wsConnected?('推送 · '+pushAge+'s 前'):'未连推送' }}</span>
        <span class="quiet">{{ border.note }}</span>
      </div>

      <p class="nrn-legend">
        <i class="dot"></i>节点三级：省会/首府（大点+浅环）＞机场城市＞一般
        <i class="line"></i>航线同色同宽
        <i class="line warn"></i>琥珀＝绕飞航迹
        <i class="line bad"></i>红＝边境受限停飞
        <span v-if="virtualMode" class="virt">虚拟增强：回波与绕飞/停飞加亮</span>
      </p>
    </div>

    <!-- ================= 台账 / 情报：与原生页共用同一份组件 ================= -->
    <div class="nrn-table" v-show="view==='ledger'">
      <NationBriefing view="ledger" :payload="data" :flights="flights"
                      :minute="minute" :density="density"/>
    </div>
    <div class="nrn-table" v-show="view==='intel'">
      <NationBriefing view="intel" :payload="data" :density="density"/>
    </div>

    <!-- ================= 处置 ================= -->
    <div class="nrn-table" v-show="view==='alerts'">
      <div class="nrn-table-hd">
        <h3>事件处置 <small>{{ alerts.length }} 条</small></h3>
        <p>低能见度、回波绕飞、边境停飞、放行暂缓四类。自动处置的是规则动作，待处置的需要人工确认。</p>
      </div>
      <ul class="nrn-alerts">
        <li v-for="row in alerts" :key="row.id" :class="row.severity">
          <b>{{ row.kind }}</b>
          <em>{{ row.place }}</em>
          <p>{{ row.detail }}</p>
          <p class="act">处置：{{ row.action }}</p>
          <span class="tag" :class="row.auto?'good':'warn'">{{ row.status }}</span>
        </li>
        <li v-if="!alerts.length" class="empty">本级暂无需要处置的事件</li>
      </ul>
    </div>

    <!-- ================= 右栏：分块统计 ================= -->
    <aside class="nrn-side">
      <div class="nrn-total">
        <div><b>{{ total.corridors||0 }}</b><span>航线</span></div>
        <div><b>{{ total.airborne||0 }}</b><span>在飞</span></div>
        <div :class="{alarm:total.delayed>0}"><b>{{ total.delayed||0 }}</b><span>绕飞</span></div>
        <div :class="{alarm:total.blocked>0}"><b>{{ total.blocked||0 }}</b><span>停飞</span></div>
        <div :class="{alarm:total.hold>0}"><b>{{ total.hold||0 }}</b><span>暂缓</span></div>
      </div>

      <template v-if="rollup.level==='nation'">
        <h3>各大区<small>点区块下钻</small></h3>
        <div class="nrn-block" v-for="region in rollup.regions" :key="region.id">
          <button class="nrn-block-hd" @click="go('region',region.id,region.name)">
            <b>{{ region.name }}</b>
            <span>{{ region.total.cities }} 市 · {{ region.total.corridors }} 条 · 在飞 {{ region.total.airborne }}</span>
            <em v-if="region.total.blocked">停飞 {{ region.total.blocked }}</em>
          </button>
          <!-- 省一级也做成按钮：整块可点，键盘也能走 -->
          <button class="nrn-prov" v-for="p in region.provinces" :key="p.name"
                  @click="go('province',p.name,p.name)">
            <b>{{ shortName(p.name) }}</b>
            <span>{{ p.cities }} 市 · {{ p.corridors }} 条</span>
            <em :class="{warn:airOf(p.name,p.airborne)>0}">在飞 {{ airOf(p.name,p.airborne) }}</em>
          </button>
        </div>
      </template>

      <template v-else-if="rollup.level==='region'">
        <h3>本区省份<small>点省下钻</small></h3>
        <div class="nrn-block" v-for="p in rollup.provinces" :key="p.name">
          <button class="nrn-block-hd" @click="go('province',p.name,p.name)">
            <b>{{ p.name }}</b>
            <span>{{ p.cities }} 市 · 机场 {{ p.airports }} · {{ p.corridors }} 条</span>
            <em :class="{warn:p.blocked>0}">{{ p.blocked?'停飞 '+p.blocked:'在飞 '+p.airborne }}</em>
          </button>
        </div>
      </template>

      <template v-else-if="rollup.level==='province'">
        <h3>本省城市<small>{{ (rollup.cities||[]).length }} 个节点</small></h3>
        <ul class="nrn-city-list">
          <li v-for="city in rollup.cities" :key="city.name" @click="go('city',city.name,city.name)">
            <b>{{ shortName(city.name) }}<i :class="['tag',city.hasAirport?'good':'quiet']">{{ city.hasAirport?city.airport:'无机场' }}</i></b>
            <span>{{ city.feedTarget?('接驳 → '+shortName(city.feedTarget)):'' }} {{ city.corridors }} 条</span>
            <em :class="{warn:airOfCity(city.name,city.airborne)>0}">在飞 {{ airOfCity(city.name,city.airborne) }}</em>
          </li>
        </ul>
      </template>

      <template v-else>
        <h3>城市节点<small>{{ data.city?.name }}</small></h3>
        <div class="nrn-city-detail">
          <p><span>省</span><b>{{ data.city?.province }}</b></p>
          <p><span>机场</span><b>{{ data.city?.airport||'无（有专用接驳）' }}</b></p>
          <p><span>航线</span><b>{{ data.city?.links }} 条</b></p>
          <p><span>在飞</span><b>{{ data.city?.airborne }}</b></p>
          <p><span>相邻</span><b>{{ (data.city?.neighbours||[]).map(shortName).join('、') }}</b></p>
        </div>
      </template>

      <div class="nrn-border-card" v-if="(border.excludedCities||[]).length&&level==='nation'">
        <h4>边境 {{ border.excludeKm }} km 内退出通航</h4>
        <p>{{ (border.excludedCities||[]).map(c=>shortName(c.name)+' '+c.distanceKm+'km').join('、') }}</p>
        <small>城市与航线一并删除；口径为“到境外距离”，不是到省界或海岸线。</small>
      </div>
    </aside>
  </div>

  <!-- ================= 详情：班次 / 走廊 ================= -->
  <div class="nrn-detail" v-if="selectedFlight||selectedLine" data-nation-detail>
    <template v-if="selectedFlight">
      <header>
        <b>{{ selectedFlight.callsign }}</b>
        <code>{{ selectedFlight.id }}</code>
        <span class="tag" :class="selectedFlight.riskLevel==='HIGH'?'bad':(selectedFlight.riskLevel==='MEDIUM'?'warn':'good')">{{ selectedFlight.decisionLabel }}</span>
        <button class="follow" :class="{on:followId===selectedFlight.id}" @click="toggleFollow">
          {{ followId===selectedFlight.id?'取消跟随':'跟随此班次' }}</button>
        <button class="follow" :disabled="evidenceBusy" @click="loadEvidence">
          {{ evidenceBusy?'取证中…':'取证' }}</button>
        <button @click="selectedId='';clearEvidence()">收起</button>
      </header>
      <div class="cols">
        <div>
          <h4>班次</h4>
          <p><span>航线</span><b>{{ selectedFlight.fromName }} → {{ selectedFlight.toName }}</b></p>
          <p><span>计划</span><b>{{ selectedFlight.departAt }}–{{ selectedFlight.arriveAt }}</b></p>
          <p><span>已飞</span><b>{{ selectedFlight.elapsedMin }} / {{ selectedFlight.durationMin }} 分</b></p>
          <p><span>高度</span><b>{{ selectedFlight.altM }} m AGL</b></p>
          <p><span>速度</span><b>{{ selectedFlight.speedKmh }} km/h</b></p>
          <button class="mini" @click="locate">跳到起飞时刻</button>
        </div>
        <div>
          <h4>放行许可 <small>{{ selectedFlight.clearance?.statusLabel }}</small></h4>
          <p><span>航路</span><b>{{ selectedFlight.clearance?.route }}</b></p>
          <p><span>高度带</span><b>{{ selectedFlight.clearance?.altitudeBand }}</b></p>
          <p><span>时窗</span><b>{{ selectedFlight.clearance?.timeWindow }}</b></p>
          <p><span>条件</span><b>{{ (selectedFlight.clearance?.conditions||[]).join('；') }}</b></p>
        </div>
        <div>
          <h4>裁决依据 <small>规则派生</small></h4>
          <p><span>风险</span><b>{{ selectedFlight.riskP.toFixed(2) }}（{{ selectedFlight.riskLevelLabel }}）</b></p>
          <p v-for="(d,i) in selectedFlight.drivers" :key="i"><span>依据 {{ i+1 }}</span><b>{{ d }}</b></p>
          <p><span>反事实</span><b>不绕飞将暴露 {{ selectedFlight.exposure?.directMin||0 }} 分钟；绕飞后 0</b></p>
        </div>
        <div class="prof">
          <h4>高度剖面 <small>计划</small></h4>
          <svg viewBox="0 0 260 96" role="img" aria-label="班次高度剖面">
            <path d="M8 8V80H252" stroke="#2c4a60" fill="none"/>
            <polyline :points="(selectedFlight.altProfile||[]).map((p,i)=>`${8+i*244/Math.max(1,(selectedFlight.altProfile.length-1))},${80-p[1]*64/1200}`).join(' ')"
                      fill="none" stroke="#59dffc" stroke-width="1.8"/>
            <text x="10" y="92" fill="#7d9cb3" font-size="7.5">0 分</text>
            <text x="222" y="92" fill="#7d9cb3" font-size="7.5">{{ Math.round(selectedFlight.durationMin) }} 分</text>
            <text x="10" y="16" fill="#7d9cb3" font-size="7.5">1200 m</text>
          </svg>
        </div>
      </div>

      <div class="evidence" v-if="evidence||evidenceErr" data-nation-evidence>
        <p class="ev-err" v-if="evidenceErr">取证失败：{{ evidenceErr }}</p>
        <template v-else>
          <div class="ev-hd">
            <b>取证链</b>
            <span>{{ evidence.conclusion }}</span>
            <em>{{ evidence.steps.length }} 步 · {{ evidence.generatedAt }}</em>
          </div>
          <div class="ev-steps">
            <div class="ev-step" v-for="step in evidence.steps" :key="step.n">
              <h5><i>{{ step.n }}</i>{{ step.title }}</h5>
              <p v-for="row in step.rows" :key="row.label">
                <span>{{ row.label }}</span>
                <b>{{ row.value }}</b>
                <code :class="row.source">{{ row.source }}</code>
              </p>
            </div>
          </div>
          <p class="ev-note">{{ evidence.llm?.note }}</p>
          <p class="ev-note quiet">{{ evidence.discipline }}</p>
        </template>
      </div>
    </template>

    <template v-else-if="selectedLine">
      <header>
        <b>{{ selectedLine.fromName }} → {{ selectedLine.toName }}</b>
        <code>{{ selectedLine.id }}</code>
        <span class="tag" :class="selectedLine.borderBlocked?'bad':(selectedLine.detour?'warn':'good')">
          {{ selectedLine.borderBlocked?'边境停飞':(selectedLine.detour?'绕飞放行':'直飞') }}
        </span>
        <button @click="selectedCorridor=''">收起</button>
      </header>
      <div class="cols">
        <div>
          <h4>航线</h4>
          <p><span>类型</span><b>{{ selectedLine.kindLabel }}</b></p>
          <p><span>长度</span><b>{{ selectedLine.lengthKm }} km</b></p>
          <p><span>两端</span><b>{{ selectedLine.fromProvince }} / {{ selectedLine.toProvince }}</b></p>
          <p><span>边境</span><b>{{ selectedLine.borderDetour?'已改线避让':'未触发' }}</b></p>
        </div>
        <div>
          <h4>回波遭遇</h4>
          <p><span>绕飞</span><b>{{ selectedLine.detour?('外偏 '+selectedLine.detour.shiftKm+' km'):'未绕飞' }}</b></p>
          <p><span>暴露</span><b>{{ selectedLine.detour?('原航路 '+selectedLine.detour.hitKm+' km 穿回波'):'无' }}</b></p>
          <p><span>高度带</span><b>600–1100 m AGL</b></p>
          <p><span>班次</span><b>{{ flights.filter(f=>f.corridor===selectedLine.id).length }} 架在飞</b></p>
        </div>
        <div class="prof span2" v-if="corridorProfile">
          <h4>逐公里剖面 <small>{{ corridorProfile.totalKm }} km · {{ corridorProfile.segments.length }} 段 · 采样步长约 6 km</small></h4>
          <svg viewBox="0 0 320 92" preserveAspectRatio="none" role="img" aria-label="走廊逐公里回波剖面">
            <rect x="8" y="6" width="304" height="62" fill="rgba(8,22,34,.7)" stroke="rgba(70,110,140,.35)"/>
            <rect v-for="(seg,i) in corridorProfile.segments" :key="'sg'+i"
                  :x="8+304*seg.from/corridorProfile.totalKm"
                  :width="Math.max(1,304*(seg.to-seg.from)/corridorProfile.totalKm)"
                  y="6" height="62" :fill="BAND_COLOR[seg.band]"/>
            <polyline :points="profilePoints" fill="none" stroke="#59dffc" stroke-width="1.4"/>
            <text x="10" y="82" fill="#7d9cb3" font-size="7.5">0 km · {{ selectedLine.fromName }}</text>
            <text x="310" y="82" fill="#7d9cb3" font-size="7.5" text-anchor="end">{{ corridorProfile.totalKm }} km · {{ selectedLine.toName }}</text>
            <text x="10" y="14" fill="#7d9cb3" font-size="7.5">1100 m</text>
          </svg>
          <p class="quiet">{{ profileText }}</p>
          <p class="quiet" v-if="selectedLine.detour">
            琥珀色航迹＝按法线外偏 {{ selectedLine.detour.shiftKm }} km 后的实际航路；原航路穿回波 {{ selectedLine.detour.hitKm }} km。
          </p>
        </div>
      </div>
    </template>
  </div>
</section>
</template>

<style scoped>
.nrn{display:flex;flex-direction:column;gap:8px;min-height:0;height:100%;overflow:hidden;color:#cfe6f5}
.nrn-hd{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;padding:2px 2px 0}
.nrn-crumb{display:flex;align-items:center;gap:5px;font-size:13px}
.nrn-crumb button{background:none;border:0;color:#7fd4ff;cursor:pointer;font-size:13px;padding:2px 4px}
.nrn-crumb button:hover{text-decoration:underline}
.nrn-crumb .sep{color:#4f7288}
.nrn-crumb .back{margin-left:8px;border:1px solid #2c4a60;border-radius:5px;padding:2px 8px;color:#a8cee6}
.nrn-headline{margin:0;font-size:13.5px;color:#eaf6ff;letter-spacing:.2px}
.nrn-sub{margin:0;font-size:11.5px;color:#82a6bd}
.nrn-sub b{color:#cfe9f8;font-variant-numeric:tabular-nums}

.nrn-tabs{display:flex;gap:6px;border-bottom:1px solid rgba(70,110,140,.35);padding-bottom:6px}
.nrn-tabs button{background:transparent;border:1px solid transparent;color:#8fb2c8;padding:5px 13px;border-radius:6px;cursor:pointer;font-size:12.5px}
.nrn-tabs button.on{background:#17394d;border-color:#2e6b85;color:#bfe9ff}
.nrn-tabs em{font-style:normal;opacity:.75;margin-left:4px;font-size:11px}
.nrn-tabs em.bad{color:#ffb38a}

.nrn-body{display:grid;grid-template-columns:minmax(0,1fr) 292px;gap:10px;min-height:0;flex:1;align-items:stretch}
.nrn-body.no-map{grid-template-columns:minmax(0,1fr) 292px}

.nrn-map{position:relative;display:flex;flex-direction:column;min-height:0;gap:6px;min-width:0}
.nrn-canvas{position:relative;flex:1;min-height:240px;border-radius:10px;overflow:hidden;border:1px solid rgba(70,110,140,.3)}
.nrn-tools{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:12px}
.nrn-tools button,.nrn-tools select{background:#10283a;border:1px solid #2b4c62;color:#a9cde2;border-radius:5px;padding:4px 9px;font-size:11.5px;cursor:pointer}
.nrn-tools button.on{background:#1d5670;border-color:#3f8ba8;color:#c8f0ff}
.nrn-tools button.play{background:#1b4d63;color:#d6f6ff;border-color:#3d8aa6}
.nrn-tools input[type=range]{flex:1;min-width:90px}
.nrn-tools .clock{font-variant-numeric:tabular-nums;color:#bfe9ff;font-size:12px}

.nrn-monitor{margin:0;padding:6px 9px;border:1px solid rgba(80,130,160,.35);border-radius:7px;
  background:rgba(12,30,44,.72);font-size:11px;color:#8fb2c8;display:flex;flex-wrap:wrap;gap:4px 12px}
.nrn-monitor strong{color:#ffd08a;font-weight:600}
.nrn-monitor .quiet{color:#6f92a8}
.nrn-monitor .push{color:#7d9cb3}
.nrn-monitor .push.on{color:#7fe0bb}
.nrn-legend{margin:0;font-size:10.5px;color:#6f92a8;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.nrn-legend i{display:inline-block;width:14px;height:2px;background:rgba(126,206,255,.62);margin-right:4px;vertical-align:middle}
.nrn-legend i.dot{width:6px;height:6px;border-radius:50%;background:#eaf6ff}
.nrn-legend i.warn{background:rgba(255,206,90,.9)}
.nrn-legend i.bad{background:rgba(226,92,74,.75)}
.nrn-legend .virt{color:#ffcf7a}

.nrn-side{display:flex;flex-direction:column;gap:8px;overflow:auto;padding-right:2px;min-height:0}
/* 侧栏是滚动列表，不是弹性布局：子项一旦被 flex 压缩，块里的省行就被裁掉了 */
.nrn-side>*{flex:0 0 auto}
.nrn-total{display:grid;grid-template-columns:repeat(5,1fr);gap:4px;background:rgba(12,32,46,.8);
  border:1px solid rgba(70,110,140,.4);border-radius:8px;padding:7px 6px}
.nrn-total div{text-align:center}
.nrn-total b{display:block;font-size:15px;color:#eaf6ff;font-variant-numeric:tabular-nums}
.nrn-total span{font-size:10px;color:#7d9cb3}
.nrn-total .alarm b{color:#ffab7a}
.nrn-side h3{margin:4px 0 0;font-size:12px;color:#a9cde2;font-weight:600}
.nrn-side h3 small{margin-left:6px;font-size:10px;color:#6f92a8;font-weight:400}
.nrn-block{border:1px solid rgba(70,110,140,.32);border-radius:8px;overflow:hidden;background:rgba(10,26,38,.6)}
.nrn-block-hd{width:100%;display:grid;grid-template-columns:1fr auto;gap:2px 6px;text-align:left;
  background:rgba(20,52,72,.55);border:0;color:#cfe6f5;padding:6px 9px;cursor:pointer}
.nrn-block-hd b{font-size:12.5px}
.nrn-block-hd span{font-size:10.5px;color:#82a6bd;grid-column:1}
.nrn-block-hd em{font-style:normal;font-size:10.5px;color:#8fb2c8;grid-column:2;grid-row:1}
.nrn-block-hd em.warn{color:#ffb38a}
.nrn-block-list{list-style:none;margin:0;padding:2px 0}
.nrn-block-list li{display:grid;grid-template-columns:1fr auto;gap:2px 6px;padding:4px 9px;cursor:pointer;font-size:11.5px}
.nrn-block-list li:hover{background:rgba(40,96,124,.35)}
.nrn-block-list b{font-weight:500;color:#cfe6f5}
.nrn-block-list span{font-size:10px;color:#7d9cb3;grid-column:1}
.nrn-block-list em{font-style:normal;font-size:10.5px;color:#8fb2c8;grid-row:1;grid-column:2}
.nrn-block-list em.warn{color:#8ef0ff}
/* 省一级的按钮行：三列对齐，和区块头同一套网格 */
.nrn-prov{width:100%;display:grid;grid-template-columns:1fr auto;gap:2px 6px;text-align:left;
  background:transparent;border:0;border-top:1px solid rgba(60,95,120,.22);color:#cfe6f5;
  padding:5px 9px;cursor:pointer;font-size:11.5px}
.nrn-prov:hover{background:rgba(40,96,124,.35)}
.nrn-prov b{font-weight:500;color:#cfe6f5}
.nrn-prov span{grid-column:1;font-size:10px;color:#7d9cb3}
.nrn-prov em{grid-row:1;grid-column:2;font-style:normal;font-size:10.5px;color:#8fb2c8}
.nrn-prov em.warn{color:#8ef0ff}
.nrn-city-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px;overflow:auto}
.nrn-city-list li{display:grid;grid-template-columns:1fr auto;gap:2px 6px;padding:5px 8px;border-radius:6px;
  background:rgba(12,32,46,.6);cursor:pointer;font-size:11.5px}
.nrn-city-list li:hover{background:rgba(40,96,124,.45)}
.nrn-city-list span{font-size:10px;color:#7d9cb3;grid-column:1}
.nrn-city-list em{font-style:normal;font-size:10.5px;color:#8fb2c8;grid-row:1;grid-column:2}
.nrn-city-list em.warn{color:#8ef0ff}
.tag{display:inline-block;font-style:normal;font-size:10px;padding:1px 5px;border-radius:4px;margin-left:4px}
.tag.good{background:rgba(70,190,150,.18);color:#7fe0bb}
.tag.warn{background:rgba(245,190,60,.18);color:#ffd479}
.tag.bad{background:rgba(238,80,60,.2);color:#ffa08a}
.tag.quiet{background:rgba(120,150,175,.15);color:#9fb8c9}

.nrn-city-detail{display:flex;flex-direction:column;gap:4px;font-size:11.5px}
.nrn-city-detail p{margin:0;display:grid;grid-template-columns:48px 1fr;gap:6px}
.nrn-city-detail span{color:#7d9cb3}
.nrn-city-detail b{font-weight:500;color:#d9eefb}
.nrn-border-card{border:1px solid rgba(200,120,80,.35);border-radius:8px;padding:7px 9px;background:rgba(60,28,16,.35)}
.nrn-border-card h4{margin:0 0 4px;font-size:11.5px;color:#ffc0a0}
.nrn-border-card p{margin:0;font-size:10.5px;color:#e8b9a2;line-height:1.6}
.nrn-border-card small{color:#a98a7a;font-size:10px}

.nrn-table{display:flex;flex-direction:column;gap:8px;min-height:0}
.nrn-table-hd h3{margin:0;font-size:13px;color:#eaf6ff}
.nrn-table-hd h3 small{margin-left:8px;font-size:11px;color:#7d9cb3;font-weight:400}
.nrn-table-hd p{margin:3px 0 0;font-size:11px;color:#7d9cb3}
.nrn-scroll{overflow:auto;min-height:0;flex:1;border:1px solid rgba(70,110,140,.3);border-radius:8px}
.nrn-table table{width:100%;border-collapse:collapse;font-size:11.5px}
.nrn-table th{position:sticky;top:0;background:#0f2a3c;color:#8fb2c8;font-weight:500;text-align:left;
  padding:6px 8px;border-bottom:1px solid rgba(70,110,140,.4);white-space:nowrap;font-size:11px}
.nrn-table td{padding:5px 8px;border-bottom:1px solid rgba(50,80,100,.25);color:#cfe6f5;vertical-align:top}
.nrn-table td small{display:block;font-size:10px;color:#7d9cb3}
.nrn-table tr.sel td{background:rgba(40,110,140,.35)}
.nrn-table tbody tr{cursor:pointer}
.nrn-table tbody tr:hover td{background:rgba(30,70,95,.35)}
.nrn-table tr.future td{color:#9dbccf;opacity:.85}
.nrn-table td.bad{color:#ffa08a}
.nrn-table td.empty{text-align:center;color:#6f92a8;padding:18px}
.risk{font-variant-numeric:tabular-nums;font-size:11px;padding:1px 5px;border-radius:4px}
.risk.HIGH{background:rgba(238,80,60,.22);color:#ffa08a}
.risk.MEDIUM{background:rgba(245,190,60,.18);color:#ffd479}
.risk.LOW{background:rgba(70,190,150,.16);color:#7fe0bb}

.nrn-weather{margin-top:4px}
.nrn-weather h3{margin:0 0 4px;font-size:12px;color:#a9cde2}
.nrn-weather ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:3px}
.nrn-weather li{display:flex;gap:6px;align-items:baseline;font-size:11px;padding:3px 6px;border-radius:5px;background:rgba(12,32,46,.6)}
.nrn-weather li.bad{outline:1px solid rgba(226,75,74,.5)}
.nrn-weather span{color:#8fb2c8}

.nrn-alerts{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:7px;overflow:auto;min-height:0}
.nrn-alerts li{border:1px solid rgba(70,110,140,.35);border-left-width:3px;border-radius:7px;padding:7px 9px;background:rgba(10,26,38,.62)}
.nrn-alerts li.bad{border-left-color:#ee5040}
.nrn-alerts li.warn{border-left-color:#f5be3c}
.nrn-alerts li.empty{grid-column:1/-1;text-align:center;color:#6f92a8;padding:20px}
.nrn-alerts b{font-size:12px;color:#eaf6ff}
.nrn-alerts em{font-style:normal;font-size:11px;color:#8fb2c8;margin-left:8px}
.nrn-alerts p{margin:3px 0 0;font-size:11px;color:#a8c6d8;line-height:1.5}
.nrn-alerts p.act{color:#ffd08a}
.nrn-alerts .tag{margin-top:4px}

.nrn-detail{border:1px solid rgba(70,110,140,.4);border-radius:9px;background:rgba(10,26,38,.9);padding:8px 10px}
.nrn-detail header{display:flex;align-items:center;gap:9px;font-size:12.5px;padding-bottom:6px;border-bottom:1px solid rgba(70,110,140,.3)}
.nrn-detail header b{color:#eaf6ff;font-size:13px}
.nrn-detail header code{font-size:10.5px;color:#7fb6d6}
.nrn-detail header button.follow{color:#8ef0ff;border-color:#2e6b85}
.nrn-detail header button.follow.on{background:#1d5670;color:#d6f6ff}
.nrn-detail header button{margin-left:auto;background:none;border:1px solid #2c4a60;color:#9dbccf;border-radius:5px;padding:2px 9px;font-size:11px;cursor:pointer}
.nrn-detail .cols{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding-top:7px}
.nrn-detail h4{margin:0 0 4px;font-size:11px;color:#8fb2c8;font-weight:600}
.nrn-detail h4 small{margin-left:5px;color:#6f92a8;font-weight:400}
.nrn-detail p{margin:2px 0;display:grid;grid-template-columns:52px 1fr;gap:6px;font-size:11px}
.nrn-detail p>span{color:#7493a8}
.nrn-detail p>b{font-weight:400;color:#d9eefb}
.nrn-detail .prof svg{width:100%;height:88px}
.nrn-detail .prof.span2{grid-column:span 2}
@media(max-width:1180px){.nrn-detail .prof.span2{grid-column:span 2}}
.nrn-detail .mini{margin-top:5px;background:#17394d;border:1px solid #2e6b85;color:#bfe9ff;border-radius:5px;padding:3px 8px;font-size:10.5px;cursor:pointer}
.nrn-detail .quiet{display:block;color:#7d9cb3;font-size:10.5px;line-height:1.6}

.evidence{margin-top:8px;border-top:1px solid rgba(70,110,140,.3);padding-top:7px}
.ev-hd{display:flex;align-items:baseline;gap:10px;font-size:11.5px;flex-wrap:wrap}
.ev-hd b{color:#eaf6ff}
.ev-hd span{color:#8ef0ff}
.ev-hd em{font-style:normal;color:#6f92a8;font-size:10.5px;margin-left:auto}
.ev-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-top:6px}
.ev-step{border:1px solid rgba(70,110,140,.3);border-radius:7px;padding:6px 8px;background:rgba(8,22,34,.55)}
.ev-step h5{margin:0 0 4px;font-size:11px;color:#a9cde2;display:flex;align-items:center;gap:5px;font-weight:600}
.ev-step h5 i{font-style:normal;width:14px;height:14px;line-height:14px;text-align:center;border-radius:50%;
  background:rgba(60,130,160,.35);color:#bfe9ff;font-size:9px}
.ev-step p{margin:2px 0;display:grid;grid-template-columns:auto 1fr auto;gap:6px;font-size:10.5px;align-items:baseline}
.ev-step p>span{color:#7493a8}
.ev-step p>b{font-weight:400;color:#d9eefb}
.ev-step code{font-size:9px;padding:0 4px;border-radius:3px;color:#9fb8c9;background:rgba(120,150,175,.12)}
.ev-step code.PUBLIC{color:#7fe0bb;background:rgba(70,190,150,.14)}
.ev-step code.DERIVED{color:#ffd479;background:rgba(245,190,60,.14)}
.ev-step code.OFFICIAL{color:#c6b4ff;background:rgba(160,140,255,.14)}
.ev-note{margin:6px 0 0;font-size:10.5px;color:#ffcf7a;line-height:1.6}
.ev-note.quiet{color:#6f92a8}
.ev-err{color:#ffa08a;font-size:11px}
.nrn-state{margin:6px 0;color:#8fb2c8;font-size:12px}
.nrn-state.bad{color:#ffa08a}
.nrn-state button{margin-left:8px;background:#17394d;border:1px solid #2e6b85;color:#bfe9ff;border-radius:5px;padding:2px 8px;cursor:pointer}

/* 1366×768 是评委席最常见的分辨率（实测项目里记过这一条）。
 * 这一档只做两件事：**把小字抬到 11px 地板**，再靠收紧内边距把高度省回来 ——
 * 抬字号会把一屏撑破，所以必须同时压缩 padding，否则地图会被挤没。 */
@media(max-width:1500px){
  .nrn-monitor,.nrn-legend,.nrn-sub{font-size:11px}
  .nrn-total span,.nrn-block-hd span,.nrn-prov span,.nrn-city-list span{font-size:11px}
  .nrn-total b{font-size:14px}
  .nrn-block-hd b,.nrn-prov b,.nrn-city-list b{font-size:11.5px}
  .nrn-block-hd em,.nrn-prov em,.nrn-city-list em{font-size:11px}
  .nrn-tools{gap:5px}
  .nrn-tools button,.nrn-tools select{font-size:11px;padding:3px 7px}
  .nrn-tabs button{font-size:11.5px;padding:4px 10px}
  .nrn-detail p,.nrn-detail p>b{font-size:11px}
  .nrn-detail header b{font-size:12.5px}
  .nrn-side h3{font-size:11.5px}
  .tag{font-size:10.5px}
  .nrn-table td small{font-size:10.5px}
  .ev-step p{font-size:10.5px}
}
/* 768 高的屏：把详情区限高并允许内部滚动，别让地图被压没 */
@media(max-height:820px){
  .nrn-canvas{min-height:220px}
  .nrn-detail{max-height:44vh;overflow:auto}
  .nrn-side{max-height:none}
}
@media(max-width:1180px){
  .nrn-body{grid-template-columns:minmax(0,1fr) 250px}
  .nrn-detail .cols{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:760px){
  .nrn-body{grid-template-columns:1fr;min-height:0}
  .nrn-side{max-height:190px}
  .nrn-canvas{min-height:200px}
}
</style>
