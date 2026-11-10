<script setup>
import {computed,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'
import china from '../../assets/china.json'

// 全国航线网四级：全国 → 大区 → 省 → 市（每市一个节点）。
// 逐级加载纪律（用户 2026-11-10 要求）：
//   ① 每次下钻/回退都**重新请求**，不复用上一级的数据对象；
//   ② 进入下一级前先把上一级数据清空（data=null），让 Vue 把上一屏卸载掉，
//      不在内存里留整棵树；只保留一条面包屑（名字，不含数据）。
//
// 配色纪律（同日要求）：**地图不上状态色**，省界保持原色，航线一律一条蓝线。
const props=defineProps({compact:{type:Boolean,default:false}})

const level=ref('nation')
const ident=ref('')
const trail=ref([{level:'nation',id:'',label:'全国'}])
const data=ref(null)
const error=ref(''),loading=ref(false)
const hovered=ref(null)

const KIND_NAME={INTRA:'省内',AIRPORT_FEED:'机场接驳',CROSS:'跨省通道'}
const EXCLUDED=new Set(['台湾省','西藏自治区','香港特别行政区','澳门特别行政区'])

const VIEW={w:1000,h:640}
const SOUTH_CHINA_SEA={lon0:108,lon1:125,lat0:2,lat1:25}   // 南海诸岛单独画，不撑大主图

const box=computed(()=>{
  const bbox=data.value?.view?.bbox
  if(!bbox||bbox.length<4) return {lon0:73,lon1:136,lat0:17,lat1:54.5}
  const padLon=Math.max(0.5,(bbox[2]-bbox[0])*0.06)
  const padLat=Math.max(0.5,(bbox[3]-bbox[1])*0.06)
  return {lon0:bbox[0]-padLon,lon1:bbox[2]+padLon,lat0:bbox[1]-padLat,lat1:bbox[3]+padLat}
})
const proj=computed(()=>{
  const v=box.value
  const cos=Math.cos(((v.lat0+v.lat1)/2)*Math.PI/180)
  const w=(v.lon1-v.lon0)*cos,h=v.lat1-v.lat0
  const scale=Math.min(VIEW.w/w,VIEW.h/h)
  return {cos,scale,ox:(VIEW.w-w*scale)/2,oy:(VIEW.h-h*scale)/2,v}
})
function project(lon,lat){
  const p=proj.value
  return [p.ox+(lon-p.v.lon0)*p.cos*p.scale, p.oy+(p.v.lat1-lat)*p.scale]
}

// 底图：全国省级单元都画（保持原色），台湾/西藏不参与网络，单独标注。
const shapes=computed(()=>{
  const rows=[]
  for(const feature of china.features||[]){
    const name=(feature.properties||{}).name
    if(!name) continue
    const geo=feature.geometry||{}
    const polys=geo.type==='Polygon'?[geo.coordinates]:(geo.type==='MultiPolygon'?geo.coordinates:[])
    let d=''
    for(const poly of polys) for(const ring of poly){
      for(let i=0;i<ring.length;i++){
        const [x,y]=project(ring[i][0],ring[i][1])
        d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)
      }
    }
    if(d) rows.push({name,d,excluded:EXCLUDED.has(name)})
  }
  return rows
})

const activeNames=computed(()=>{
  const map=new Map()
  for(const row of data.value?.provinces||[]) map.set(row.name,row)
  return map
})
const corridors=computed(()=>{
  const rows=[]
  for(const row of data.value?.corridors||[]){
    const path=row.path
    const points=(Array.isArray(path)&&path.length>1?path:[row.fromLonLat,row.toLonLat])
      .map(([lon,lat])=>project(lon,lat))
    rows.push({id:row.id,points})
  }
  return rows
})
const stations=computed(()=>(data.value?.stationPoints||[]).map(point=>{
  const [x,y]=project(point.lon,point.lat)
  return {code:point.code,city:point.city||point.name,x,y,low:!!point.low,
    vis:point.visM,visLower:!!point.visLower,temp:point.tempC,
    source:point.source||'METAR',ts:point.ts}
}))
const nodes=computed(()=>(data.value?.nodes||[]).map(node=>{
  const [x,y]=project(node.lon,node.lat)
  return {...node,x,y}
}))
const showCityLabels=computed(()=>nodes.value.length>0&&nodes.value.length<=26)

const summary=computed(()=>data.value?.summary||{})
const regions=computed(()=>data.value?.regions||[])
const provinceRows=computed(()=>data.value?.provinces||[])
const cities=computed(()=>data.value?.cities||[])
const cityDetail=computed(()=>data.value?.city||null)

// 报文 "6+" 是下界：显示 ≥，否则一排站全是 9656 m，像假数据。
function visText(vis,lower){
  if(vis==null) return '—'
  const km=vis/1000
  return (lower?'≥':'')+(km>=10?Math.round(km):km.toFixed(1))+' km'
}

async function load(){
  loading.value=true
  error.value=''
  data.value=null                      // 先卸屏，避免上一级的数据留在内存里
  try{
    const query=`level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}`
    data.value=await requestJson(`/api/traffic/v2/nation?${query}`,{timeoutMs:30000})
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}

function go(nextLevel,nextId,nextLabel){
  level.value=nextLevel
  ident.value=nextId||''
  if(nextLevel==='nation'){
    trail.value=[{level:'nation',id:'',label:'全国'}]
  }else{
    const cut=trail.value.findIndex(item=>item.level===nextLevel)
    if(cut>=0) trail.value=trail.value.slice(0,cut)
    trail.value=[...trail.value,{level:nextLevel,id:nextId||'',label:nextLabel||nextId}]
  }
  load()
}

function back(){
  if(trail.value.length<=1){return}
  const next=trail.value[trail.value.length-2]
  trail.value=trail.value.slice(0,-1)
  level.value=next.level
  ident.value=next.id
  load()
}

onMounted(load)
</script>

<template>
<section class="nrn">
  <header class="nrn-hd">
    <div class="nrn-crumb">
      <template v-for="(item,index) in trail" :key="item.level+item.id">
        <button v-if="index<trail.length-1" @click="go(item.level,item.id,item.label)">{{ item.label }}</button>
        <b v-else>{{ item.label }}</b>
        <span v-if="index<trail.length-1" class="nrn-sep">›</span>
      </template>
      <button v-if="trail.length>1" class="nrn-back" @click="back">返回上一级</button>
    </div>
    <p class="nrn-sub">
      省 <b class="alc-num">{{ summary.provinces }}</b> ·
      市 <b class="alc-num">{{ summary.cities }}</b> ·
      机场城市 <b class="alc-num">{{ summary.airports }}</b> ·
      无机场市 <b class="alc-num">{{ summary.feedCities }}</b> ·
      航线 <b class="alc-num">{{ summary.corridors }}</b>
      <span v-if="summary.byKind">（省内 {{ summary.byKind.INTRA }} · 接驳 {{ summary.byKind.AIRPORT_FEED }} · 跨省 {{ summary.byKind.CROSS }}）</span> ·
      实况 <b class="alc-num">{{ summary.stations }}</b>
    </p>
  </header>

  <p class="nrn-state" v-if="loading">正在加载本级数据…</p>
  <p class="nrn-state bad" v-else-if="error">本级不可用 · {{ error }}<button @click="load">重试</button></p>

  <div class="nrn-body" v-else-if="data">
    <div class="nrn-map">
      <svg :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`" role="img" aria-label="全国航线网层级地图">
        <defs>
          <pattern id="nrn-grid" width="50" height="50" patternUnits="userSpaceOnUse">
            <path d="M50 0H0V50" fill="none" stroke="rgba(120,170,220,.08)" stroke-width="1"/>
          </pattern>
        </defs>
        <rect x="0" y="0" :width="VIEW.w" :height="VIEW.h" fill="url(#nrn-grid)"/>

        <g>
          <path v-for="shape in shapes" :key="shape.name" :d="shape.d"
                fill="rgba(96,132,170,.10)"
                :stroke="hovered===shape.name?'#7fd4ff':'rgba(120,165,205,.40)'"
                :stroke-width="hovered===shape.name?1.2:0.8"
                :stroke-dasharray="shape.excluded?'5 4':null"
                :class="{live:activeNames.has(shape.name)}"
                @mouseenter="hovered=shape.name" @mouseleave="hovered=null"
                @click="activeNames.has(shape.name) && level!=='province' && level!=='city' && go('province',shape.name,shape.name)">
            <title>{{ shape.name }}{{ shape.excluded?' · 未纳入（不通航）':(activeNames.has(shape.name)?' · 点击下钻':' · 不在本级范围') }}</title>
          </path>
        </g>

        <g v-for="line in corridors" :key="line.id">
          <polyline :points="line.points.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')"
                    fill="none" stroke="rgba(90,170,220,.42)" stroke-width="1.05" stroke-linejoin="round"/>
        </g>

        <g v-for="node in nodes" :key="'n'+node.name">
          <circle :cx="node.x" :cy="node.y" :r="node.hasAirport?3.2:1.9"
                  :fill="node.hasAirport?'#8ef0ff':'rgba(200,225,245,.5)'"
                  :stroke="node.hasAirport?'#0b1220':'rgba(11,18,32,.8)'" :stroke-width="0.7"/>
          <template v-if="showCityLabels">
            <text :x="node.x+5" :y="node.y+3.4" class="nrn-lbl">{{ node.name }}</text>
          </template>
          <title>{{ node.name }}{{ node.hasAirport?' · 机场 '+node.airport:' · 无机场（有专用接驳航线）' }}</title>
        </g>

        <g v-for="point in stations" :key="point.code">
          <circle :cx="point.x" :cy="point.y" :r="point.low?3.2:2.2"
                  :fill="point.source==='MODEL'?'none':(point.low?'#e24b4a':'#4dd0e1')"
                  :stroke="point.source==='MODEL'?'#e0a83a':(point.low?'#e24b4a':'#4dd0e1')"
                  :stroke-width="point.source==='MODEL'?1.4:0.7"/>
          <title>{{ point.city }} · {{ point.source==='MODEL'?'模型实况':'METAR '+point.code }} · 能见 {{ visText(point.vis,point.visLower) }}</title>
        </g>
      </svg>
      <p class="nrn-note">
        实心点＝机场城市，空心小点＝无机场市（都有一条接驳航线连到最近的机场城市）；虚线省界＝未纳入网络（台湾、西藏）。
        <span v-if="hovered">指向：{{ hovered }}</span>
      </p>
    </div>

    <aside class="nrn-side">
      <div class="nrn-card">
        <h3>
          <template v-if="level==='nation'">各大区概览</template>
          <template v-else-if="level==='region'">本区省份</template>
          <template v-else-if="level==='province'">本省城市 <small>{{ cities.length }} 个节点</small></template>
          <template v-else>城市节点</template>
        </h3>

        <ul v-if="level==='nation'" class="nrn-list">
          <li v-for="region in regions" :key="region.id" @click="go('region',region.id,region.name)">
            <b>{{ region.name }}</b>
            <span>{{ region.provinces }} 省 · {{ region.cities }} 市 · {{ region.airports }} 机场</span>
            <em>{{ region.corridors }} 条</em>
          </li>
        </ul>

        <ul v-else-if="level==='region'" class="nrn-list">
          <li v-for="row in provinceRows" :key="row.name" @click="go('province',row.name,row.name)">
            <b>{{ row.name }}</b>
            <span>{{ row.cities }} 市 · 机场 {{ row.airports }} · 实况 {{ row.stations + (row.modelStations||0) }}</span>
            <em>{{ row.corridors }} 条</em>
          </li>
        </ul>

        <ul v-else-if="level==='province'" class="nrn-list">
          <li v-for="city in cities" :key="city.name" @click="go('city',city.name,city.name)">
            <b>{{ city.name }}<i :class="['nrn-tag',city.hasAirport?'air':'feed']">{{ city.hasAirport?'机场 '+city.airport:'无机场' }}</i></b>
            <span v-if="city.hasAirport">{{ city.links }} 条航线</span>
            <span v-else>接驳 → {{ city.feedTarget||'—' }} · {{ city.links }} 条</span>
            <em>{{ city.links }}</em>
          </li>
        </ul>

        <div v-else-if="cityDetail" class="nrn-city">
          <p class="nrn-city-hd">
            <b>{{ cityDetail.name }}</b>
            <i :class="['nrn-tag',cityDetail.hasAirport?'air':'feed']">{{ cityDetail.hasAirport?'机场 '+cityDetail.airport:'无机场' }}</i>
          </p>
          <dl>
            <div><dt>所属</dt><dd>{{ cityDetail.province }}</dd></div>
            <div><dt>机场接驳</dt><dd>{{ cityDetail.hasAirport?'本场即机场':('直飞 '+ (cityDetail.feedTarget||'—')) }}</dd></div>
            <div><dt>航线</dt><dd>{{ cityDetail.links }} 条</dd></div>
            <div><dt>坐标</dt><dd>{{ cityDetail.lon }}, {{ cityDetail.lat }}</dd></div>
          </dl>
          <p class="nrn-city-nb">相邻：{{ cityDetail.neighbours.join(' · ') }}</p>
          <ul class="nrn-list slim">
            <li v-for="line in data.corridors" :key="line.id" @click="go('city',line.fromName===cityDetail.name?line.toName:line.fromName)">
              <b>{{ line.fromName===cityDetail.name?line.toName:line.fromName }}</b>
              <span>{{ line.kindLabel || KIND_NAME[line.kind] }} · {{ line.lengthKm }} km</span>
            </li>
          </ul>
        </div>

        <p v-else class="nrn-hint">本级没有更深一层的数据。</p>
      </div>

      <div class="nrn-card nrn-wx">
        <h3>气象实况 <small>{{ stations.length }} 点</small></h3>
        <ul v-if="stations.length" class="nrn-wx-list">
          <li v-for="point in stations" :key="point.code">
            <b>{{ point.city }}</b>
            <em :class="{model:point.source==='MODEL'}">{{ point.source==='MODEL'?'模型':point.code }}</em>
            <span>{{ point.temp==null?'—':point.temp+' °C' }} · 能见 {{ visText(point.vis,point.visLower) }}</span>
          </li>
        </ul>
        <p v-else class="nrn-hint">本范围内没有可用报文站（拿不到就是没有，不补零）。</p>
      </div>
    </aside>
  </div>
</section>
</template>

<style scoped>
.nrn{display:flex;flex-direction:column;gap:10px;min-height:0}
.nrn-hd{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
.nrn-crumb{display:flex;align-items:center;gap:8px;font-size:15px}
.nrn-crumb button{background:transparent;border:0;color:var(--alc-info);cursor:pointer;padding:0;font-size:15px}
.nrn-crumb b{color:var(--alc-text);font-weight:600}
.nrn-sep{color:var(--alc-text-mute)}
.nrn-back{margin-left:10px;border:1px solid var(--alc-line)!important;border-radius:5px;padding:3px 10px!important;
  color:var(--alc-text-dim)!important;font-size:12px!important}
.nrn-sub{margin:0;font-size:12px;color:var(--alc-text-dim);line-height:1.7}
.nrn-state{padding:24px;color:var(--alc-text-dim)}
.nrn-state.bad{color:var(--alc-watch)}
.nrn-body{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:12px;min-height:0;align-items:stretch}
.nrn-map{position:relative;border:1px solid var(--alc-line);border-radius:10px;background:var(--alc-bg-1);overflow:hidden;
  display:flex;flex-direction:column;min-height:420px}
.nrn-map svg{display:block;width:100%;height:100%;flex:1;min-height:0}
.nrn-map svg path.live{cursor:pointer}
.nrn-lbl{font-size:9px;fill:rgba(200,225,245,.7);pointer-events:none}
.nrn-note{margin:0;padding:6px 10px;font-size:12px;color:var(--alc-text-mute);border-top:1px solid var(--alc-line)}
.nrn-side{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,.7fr);gap:10px;min-height:0}
.nrn-card{border:1px solid var(--alc-line);border-radius:10px;background:var(--alc-bg-1);padding:10px 12px;min-height:0;overflow:auto}
.nrn-card h3{margin:0 0 8px;font-size:13px;color:var(--alc-text)}
.nrn-card h3 small{font-size:12px;color:var(--alc-text-mute);margin-left:6px}
.nrn-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.nrn-list li{display:grid;grid-template-columns:1fr auto;gap:2px 8px;padding:7px 10px;border:1px solid var(--alc-line);
  border-radius:7px;cursor:pointer;background:var(--alc-bg-2)}
.nrn-list li:hover{border-color:var(--alc-info)}
.nrn-list b{font-size:13px;color:var(--alc-text);display:flex;align-items:center;gap:6px}
.nrn-list span{font-size:12px;color:var(--alc-text-dim);grid-column:1;grid-row:2}
.nrn-list em{font-size:12px;font-style:normal;color:var(--alc-text-mute);grid-column:2;grid-row:1/3;align-self:center}
.nrn-list.slim li{padding:5px 8px}
.nrn-tag{font-style:normal;font-size:11px;padding:0 5px;border-radius:4px;line-height:16px}
.nrn-tag.air{color:#8ef0ff;border:1px solid rgba(142,240,255,.35);background:rgba(142,240,255,.08)}
.nrn-tag.feed{color:#e0a83a;border:1px solid rgba(224,168,58,.35);background:rgba(224,168,58,.08)}
.nrn-city{margin:0}
.nrn-city-hd{display:flex;align-items:center;gap:8px;margin:0 0 8px}
.nrn-city-hd b{font-size:15px;color:var(--alc-text)}
.nrn-city dl{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;margin:0 0 8px}
.nrn-city dt{font-size:12px;color:var(--alc-text-mute)}
.nrn-city dd{margin:2px 0 0;font-size:12px;color:var(--alc-text-dim)}
.nrn-city-nb{margin:0 0 8px;font-size:12px;color:var(--alc-text-mute);line-height:1.6}
.nrn-wx-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:5px}
.nrn-wx-list li{display:flex;gap:8px;align-items:baseline;font-size:12px;color:var(--alc-text-dim);
  padding:5px 8px;background:var(--alc-bg-2);border-radius:6px}
.nrn-wx-list b{color:var(--alc-text)}
.nrn-wx-list em{font-style:normal;color:var(--alc-text-mute)}
.nrn-wx-list em.model{color:#e0a83a}
.nrn-wx-list span{margin-left:auto}
.nrn-hint{margin:6px 0 0;font-size:12px;color:var(--alc-text-mute);line-height:1.6}
</style>
