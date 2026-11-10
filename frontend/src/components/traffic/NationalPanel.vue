<script setup>
import {computed,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'
import china from '../../assets/china.json'

const props=defineProps({compact:{type:Boolean,default:false}})

const national=ref(null),network=ref(null),weather=ref(null)
const error=ref(''),loading=ref(false)
const region=ref(''),selected=ref(null),hovered=ref(null)

const STATE_NAME={operational:'运行态',observing:'观测态',trunk:'仅干线',pending:'待接入'}
const STATE_FILL={operational:'rgba(82,196,26,.30)',observing:'rgba(250,173,20,.26)',trunk:'rgba(90,170,220,.22)',pending:'rgba(120,150,190,.10)'}
const STATE_STROKE={operational:'#5fbf3a',observing:'#e0a83a',trunk:'#5aaadc',pending:'rgba(150,180,210,.30)'}

async function load(){
  loading.value=true
  try{
    const [n,net,w]=await Promise.all([
      requestJson('/api/traffic/v2/national',{timeoutMs:20000}),
      requestJson('/api/traffic/network',{timeoutMs:20000}).catch(()=>null),
      requestJson('/api/traffic/weather/observations',{timeoutMs:20000}).catch(()=>null),
    ])
    national.value=n; network.value=net; weather.value=w; error.value=''
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}
onMounted(load)

const provinces=computed(()=>national.value?.provinces||[])
const summary=computed(()=>national.value?.summary||{})
const byName=computed(()=>{
  const map={}
  for(const p of provinces.value) map[p.name]=p
  return map
})
const cityProvince=computed(()=>{
  const map={}
  for(const c of network.value?.cities||[]) map[c.name]=c.province
  return map
})

const BOUNDS={lon0:73,lon1:136,lat0:17,lat1:54}
const VIEW={w:1000,h:700}
const COS=Math.cos(35*Math.PI/180)
const SCALE=Math.min(VIEW.w/((BOUNDS.lon1-BOUNDS.lon0)*COS),VIEW.h/(BOUNDS.lat1-BOUNDS.lat0))
const OFFSET={x:(VIEW.w-(BOUNDS.lon1-BOUNDS.lon0)*COS*SCALE)/2,y:(VIEW.h-(BOUNDS.lat1-BOUNDS.lat0)*SCALE)/2}

function project(lon,lat){
  return [OFFSET.x+(lon-BOUNDS.lon0)*COS*SCALE, OFFSET.y+(BOUNDS.lat1-lat)*SCALE]
}

function ringPath(ring){
  let d=''
  for(let i=0;i<ring.length;i++){
    const [x,y]=project(ring[i][0],ring[i][1])
    d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)
  }
  return d+'Z'
}

const shapes=computed(()=>{
  const rows=[]
  for(const feature of china.features||[]){
    const props=feature.properties||{}
    const name=props.name
    if(!name) continue
    const geo=feature.geometry||{}
    const polys=geo.type==='Polygon'?[geo.coordinates]:(geo.type==='MultiPolygon'?geo.coordinates:[])
    let d=''
    for(const poly of polys) for(const ring of poly) d+=ringPath(ring)
    if(!d) continue
    const row=byName.value[name]
    rows.push({name,adcode:props.adcode,d,state:row?row.state:'pending'})
  }
  return rows
})

const regionProvinceNames=computed(()=>{
  if(!region.value) return null
  return new Set(provinces.value.filter(p=>p.region===region.value).map(p=>p.name))
})

const corridors=computed(()=>{
  const allowed=regionProvinceNames.value
  const trunk=national.value?.corridors
  if(Array.isArray(trunk)&&trunk.length){
    const nameOf={}
    for(const p of provinces.value) nameOf[p.adcode]=p.name
    const out=[]
    for(const row of trunk){
      if(allowed&&!allowed.has(nameOf[row.from])&&!allowed.has(nameOf[row.to])) continue
      const [x1,y1]=project(row.fromLonLat[0],row.fromLonLat[1])
      const [x2,y2]=project(row.toLonLat[0],row.toLonLat[1])
      out.push({id:row.id,x1,y1,x2,y2,trunk:true,lengthKm:row.lengthKm})
    }
    return out
  }
  const net=network.value
  if(!net||!net.cities||!net.routes) return []
  const cities={},prov={}
  for(const c of net.cities){cities[c.id]=c.coordinate;prov[c.id]=c.province}
  const lines=[]
  for(const r of net.routes){
    if(r.mode==='DELIVERY') continue
    const a=cities[r.fromCity],b=cities[r.toCity]
    if(!a||!b) continue
    if(allowed&&!allowed.has(prov[r.fromCity])&&!allowed.has(prov[r.toCity])) continue
    const [x1,y1]=project(a[0],a[1]),[x2,y2]=project(b[0],b[1])
    lines.push({id:r.id,x1,y1,x2,y2,trunk:false})
  }
  return lines
})

const stations=computed(()=>{
  const points=national.value?.stationPoints
  if(Array.isArray(points)&&points.length){
    const allowed=regionProvinceNames.value
    return points.filter(p=>!allowed||allowed.has(p.name)).map(p=>{
      const [x,y]=project(p.lon,p.lat)
      return {id:p.code,city:p.name,x,y,low:!!p.low,temp:p.tempC,vis:p.visM}
    })
  }
  const rows=weather.value?.observations||[]
  const out=[]
  for(const item of rows){
    const at=item.gridLocation
    if(!at) continue
    const [x,y]=project(at[0],at[1])
    const vis=item.visibilityM??item.visibility
    out.push({id:item.stationId,city:item.cityName,x,y,low:typeof vis==='number'&&vis<3000,temp:item.temperatureC,vis})
  }
  return out
})

const wxRows=computed(()=>{
  const rows=(weather.value?.observations||[]).map(item=>({
    city:item.cityName,station:item.stationId,temp:item.temperatureC,
    vis:item.visibilityM??item.visibility,wind:item.windSpeedMps??item.windSpeed,
  }))
  const allowed=regionProvinceNames.value
  if(!allowed) return rows
  return rows.filter(row=>{
    const pname=cityProvince.value[row.city]
    return pname&&allowed.has(pname)
  })
})

const regionStats=computed(()=>{
  const base={operational:0,observing:0,pending:0,corridors:0,cities:0,provinces:0,stations:0}
  for(const p of provinces.value){
    if(region.value&&p.region!==region.value) continue
    base[p.state]+=1; base.corridors+=p.corridors; base.cities+=p.cities
    base.stations+=p.stations; base.provinces+=1
  }
  return base
})

const regionLabel=computed(()=>{
  if(!region.value) return '全国'
  const hit=(national.value?.regions||[]).find(r=>r.id===region.value)
  return hit?hit.name:'全国'
})

const detail=computed(()=>selected.value?byName.value[selected.value]||null:null)

function pick(name){ selected.value=selected.value===name?null:name }
function stateOf(name){ return byName.value[name]?.state||'pending' }
function fillOf(name){
  if(region.value&&byName.value[name]&&byName.value[name].region!==region.value) return 'rgba(90,110,140,.07)'
  const state=stateOf(name)
  // 待接入用斜纹填充：不是"空白"，是"这一类没有数据源"。
  if(state==='pending') return 'url(#nlx-hatch)'
  return STATE_FILL[state]
}
function fmt(value,suffix){
  return typeof value==='number'?`${Math.round(value*10)/10}${suffix||''}`:'—'
}
</script>

<template>
<section class="nlx">
  <p class="nlx-state" v-if="loading&&!national">正在汇总全国口径…</p>
  <p class="nlx-state bad" v-else-if="error">全国视图不可用 · {{ error }}<button class="nlx-retry" @click="load">重试</button></p>

  <template v-else-if="national">
    <header class="nlx-hd">
      <div>
        <h2 v-if="!compact">全国视图 <small>七个大区 · {{ summary.provinces }} 个省级单元</small></h2>
        <p class="nlx-sub">
          运行态 <b class="alc-num">{{ summary.operational }}</b> ·
          观测态 <b class="alc-num">{{ summary.observing }}</b> ·
          仅干线 <b class="alc-num">{{ summary.trunkOnly }}</b> ·
          待接入 <b class="alc-num">{{ summary.pending }}</b> ·
          干线 <b class="alc-num">{{ summary.trunkCorridors }}</b>（模拟派生）+
          省内走廊 <b class="alc-num">{{ summary.corridors - summary.trunkCorridors }}</b> ·
          METAR 站 <b class="alc-num">{{ summary.stations }}</b>
        </p>
      </div>
      <div class="nlx-legend">
        <span class="nlx-key operational">运行态</span>
        <span class="nlx-key observing">观测态</span>
        <span class="nlx-key trunk">仅干线</span>
        <span class="nlx-key pending">待接入</span>
      </div>
    </header>

    <nav class="nlx-chips" aria-label="按大区筛选">
      <button :class="{on:region===''}" @click="region='';selected=null">全国 <em>{{ summary.provinces }}</em></button>
      <button v-for="r in national.regions" :key="r.id" :class="{on:region===r.id}" @click="region=r.id;selected=null">
        {{ r.name }} <em>{{ r.operational }}/{{ r.provinceCount }}</em>
      </button>
    </nav>

    <div class="nlx-body">
      <div class="nlx-map">
        <svg :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`" role="img" aria-label="全国省级三态地图">
          <defs>
            <pattern id="nlx-grid" width="50" height="50" patternUnits="userSpaceOnUse">
              <path d="M50 0H0V50" fill="none" stroke="rgba(120,170,220,.10)" stroke-width="1"/>
            </pattern>
            <!-- 待接入省的斜纹：让"没有数据源"看起来是一个确定状态，而不是"还没画" -->
            <pattern id="nlx-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="7" height="7" fill="rgba(120,150,190,.10)"/>
              <line x1="0" y1="0" x2="0" y2="7" stroke="rgba(150,185,215,.28)" stroke-width="1.1"/>
            </pattern>
          </defs>
          <rect x="0" y="0" :width="VIEW.w" :height="VIEW.h" fill="url(#nlx-grid)"/>
          <g class="nlx-prov">
            <path v-for="s in shapes" :key="s.adcode" :d="s.d"
                  :fill="fillOf(s.name)"
                  :stroke="selected===s.name?'#7fd4ff':STATE_STROKE[s.state]"
                  :stroke-width="selected===s.name?2:0.8"
                  @click="pick(s.name)"
                  @mouseenter="hovered=s.name"
                  @mouseleave="hovered=null">
              <title>{{ s.name }} · {{ STATE_NAME[s.state] }}</title>
            </path>
          </g>
          <g class="nlx-corr">
            <line v-for="c in corridors" :key="c.id" :x1="c.x1" :y1="c.y1" :x2="c.x2" :y2="c.y2"
                  stroke="rgba(90,220,255,.55)" stroke-width="1.2"/>
          </g>
          <g class="nlx-sta">
            <circle v-for="st in stations" :key="st.id+st.city" :cx="st.x" :cy="st.y"
                    :r="st.low?4.5:3.2" :fill="st.low?'#e24b4a':'#4dd0e1'" stroke="#0b1220" stroke-width="0.8">
              <title>{{ st.city }} {{ st.id }}</title>
            </circle>
          </g>
        </svg>
        <p class="nlx-mapnote">
          省界按四态着色；青线为省级干线（模拟派生）与东北城际走廊；圆点为真实 METAR 站，红色=能见度低于 3000 m。
          <span v-if="hovered">指向：{{ hovered }}</span>
        </p>
      </div>

      <aside class="nlx-side">
        <div class="nlx-kpi">
          <h3 v-if="!detail">{{ regionLabel }} 口径</h3>
          <h3 v-else>{{ detail.name }} <small>{{ STATE_NAME[detail.state] }}</small></h3>
          <dl v-if="!detail">
            <div><dt>省级单元</dt><dd>{{ regionStats.provinces }}</dd></div>
            <div><dt>运行态</dt><dd class="ok">{{ regionStats.operational }}</dd></div>
            <div><dt>走廊（条）</dt><dd>{{ region ? regionStats.corridors : summary.corridors }}</dd></div>
            <div><dt>其中干线</dt><dd>{{ region ? '—' : summary.trunkCorridors }}</dd></div>
            <div><dt>城市</dt><dd>{{ regionStats.cities }}</dd></div>
            <div><dt>METAR 站</dt><dd>{{ regionStats.stations }}</dd></div>
          </dl>
          <dl v-else>
            <div><dt>状态</dt><dd :class="detail.state==='operational'?'ok':''">{{ STATE_NAME[detail.state] }}</dd></div>
            <div><dt>城际走廊</dt><dd>{{ detail.corridors }}</dd></div>
            <div><dt>配送走廊</dt><dd>{{ detail.deliveryCorridors }}</dd></div>
            <div><dt>城市</dt><dd>{{ detail.cities }}</dd></div>
            <div><dt>METAR 站</dt><dd>{{ detail.stations }}</dd></div>
          </dl>
          <p class="nlx-hint" v-if="detail&&detail.state==='pending'">
            这个省<strong>没有数据源</strong>：既没有报文站、也没有干线。待接入＝没接入，不是留白，也不代表可飞。
          </p>
          <p class="nlx-hint" v-else-if="detail&&detail.state==='trunk'">
            有省级干线，但<strong>本地没有 METAR 报文站</strong>：干线可示意，判据拿不到本站实况，因此不算运行态。
          </p>
          <p class="nlx-hint" v-else-if="detail&&detail.state==='observing'">
            有真实报文站，但<strong>没有干线</strong>：能看实况，不能算运行网络。
          </p>
          <p class="nlx-hint" v-else>{{ detail?'再点一次该省返回大区口径':'点地图上的省可下钻；点大区按钮只看该区' }}</p>
          <p class="nlx-coverage">
            覆盖：全国 34 个省级单元 · 省级干线 {{ summary.trunkCorridors }} 条（<b>模拟派生</b>：省会代表点 MST + 就近补边）·
            实时 METAR {{ summary.stations }} 站（<b>真实</b>，aviationweather.gov，按省界归属）。
            东北三省另有 53 条真实城际走廊参与运行计划。
          </p>
        </div>

        <div class="nlx-wx">
          <h3>气象实况 <small>{{ wxRows.length }} 站</small></h3>
          <div class="nlx-wx-scroll" v-if="wxRows.length">
            <article v-for="(row,index) in wxRows" :key="row.station+index">
              <b>{{ row.city }}</b><em>{{ row.station }}</em>
              <span>{{ fmt(row.temp,'°C') }} · 能见 {{ fmt(row.vis,' m') }} · 风 {{ fmt(row.wind,' m/s') }}</span>
            </article>
          </div>
          <p class="nlx-hint" v-else>本帧未取得机场观测（网络不可用或超出覆盖半径）。</p>
        </div>
      </aside>
    </div>

    <footer class="nlx-foot">
      <p v-for="n in national.notes" :key="n">{{ n }}</p>
    </footer>
  </template>
</section>
</template>

<style scoped>
.nlx{display:flex;flex-direction:column;gap:10px;color:var(--alc-text)}
.nlx-state{margin:0;color:var(--alc-text-dim);font-size:var(--alc-fs-body)}
.nlx-state.bad{color:var(--alc-danger)}
.nlx-retry{margin-left:12px;background:none;border:1px solid var(--alc-line);border-radius:6px;color:var(--alc-text);padding:2px 10px;cursor:pointer}
.nlx-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.nlx-hd h2{margin:0;font-size:var(--alc-fs-title)}
.nlx-hd h2 small{margin-left:8px;font-size:var(--alc-fs-aux);color:var(--alc-text-mute);font-weight:400}
.nlx-sub{margin:6px 0 0;font-size:var(--alc-fs-aux);color:var(--alc-text-dim)}
.nlx-sub b{color:var(--alc-text);font-weight:500}
.nlx-dim{color:var(--alc-text-mute)}
.nlx-legend{display:flex;gap:10px;align-items:center}
.nlx-key{font-size:var(--alc-fs-aux);color:var(--alc-text-dim);display:inline-flex;align-items:center;gap:6px}
.nlx-key::before{content:'';width:8px;height:8px;border-radius:2px;background:rgba(120,150,190,.5)}
.nlx-key.operational::before{background:#5fbf3a}
.nlx-key.observing::before{background:#e0a83a}
.nlx-key.trunk::before{background:#5aaadc}
.nlx-key.pending::before{background:rgba(150,180,210,.45)}
.nlx-chips{display:flex;gap:8px;flex-wrap:wrap}
.nlx-chips button{background:var(--alc-bg-2);border:1px solid var(--alc-line);color:var(--alc-text-dim);border-radius:999px;padding:4px 12px;font-size:var(--alc-fs-aux);cursor:pointer}
.nlx-chips button.on{color:var(--alc-text);border-color:var(--alc-info);background:rgba(76,141,255,.12)}
.nlx-chips em{font-style:normal;color:var(--alc-text-mute);margin-left:4px}
.nlx-body{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:12px;align-items:stretch}
.nlx-map{position:relative;background:rgba(10,20,34,.55);border:1px solid var(--alc-line);border-radius:12px;padding:8px;height:clamp(340px,52vh,560px);display:flex;flex-direction:column;min-width:0}
.nlx-map svg{width:100%;height:100%;flex:1;min-height:0;display:block}
.nlx-prov path{cursor:pointer;transition:fill .15s}
.nlx-prov path:hover{fill:rgba(127,212,255,.35)}
.nlx-mapnote{margin:6px 0 0;font-size:11px;color:var(--alc-text-mute);line-height:1.5}
.nlx-mapnote span{color:var(--alc-info);margin-left:8px}
.nlx-side{display:flex;flex-direction:column;gap:10px;min-height:0}
.nlx-kpi,.nlx-wx{background:var(--alc-bg-1);border:1px solid var(--alc-line);border-radius:12px;padding:12px 14px;min-height:0}
.nlx-wx{display:block;overflow:hidden;height:260px;flex:none}
.nlx-wx-scroll{display:block;height:200px;overflow-y:auto;padding-right:4px}
.nlx-kpi h3,.nlx-wx h3{margin:0 0 8px;font-size:var(--alc-fs-body);font-weight:500}
.nlx-kpi h3 small{margin-left:6px;font-size:11px;color:var(--alc-text-mute);font-weight:400}
.nlx-kpi dl{margin:0;display:grid;gap:6px}
.nlx-kpi dl div{display:flex;justify-content:space-between;font-size:var(--alc-fs-aux)}
.nlx-kpi dt{color:var(--alc-text-dim)}
.nlx-kpi dd{margin:0;color:var(--alc-text)}
.nlx-kpi dd.ok{color:#5fbf3a}
.nlx-hint{margin:8px 0 0;font-size:11px;color:var(--alc-text-mute);line-height:1.5}
.nlx-coverage{margin:8px 0 0;padding-top:8px;border-top:1px dashed var(--alc-line);
  font-size:11px;color:var(--alc-text-mute);line-height:1.6}
.nlx-wx-scroll article+article{margin-top:6px}
.nlx-wx-scroll article{display:block;background:var(--alc-bg-2);border-radius:8px;padding:7px 9px;font-size:var(--alc-fs-aux);display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.nlx-wx-scroll b{font-weight:500}
.nlx-wx-scroll em{font-style:normal;color:var(--alc-text-mute);font-size:11px}
.nlx-wx-scroll span{color:var(--alc-text-dim);font-size:11px;width:100%}
.nlx-foot{display:flex;flex-direction:column;gap:2px}
.nlx-foot p{margin:0;font-size:11px;color:var(--alc-text-mute);line-height:1.5}
</style>
