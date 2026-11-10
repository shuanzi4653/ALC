<script setup>
import {computed,onMounted,ref} from 'vue'
import {requestJson} from '../../api.js'
import china from '../../assets/china.json'

// 北方地区四级：北方 → 大区 → 省 → 市。
// 逐级加载的纪律（用户 2026-11-10 要求）：
//   ① 每次下钻/回退都**重新请求**，不复用上一级的数据对象；
//   ② 进入下一级前先把上一级数据清空（data=null），让 Vue 把上一屏卸载掉，
//      不在内存里留整棵树；只保留一条面包屑（名字，不含数据）。
const props=defineProps({compact:{type:Boolean,default:false}})

const level=ref('north')
const ident=ref('')
const trail=ref([{level:'north',id:'',label:'北方地区'}])
const data=ref(null)
const error=ref(''),loading=ref(false)
const hovered=ref(null)

const STATE_NAME={operational:'运行态',observing:'观测态',trunk:'仅干线',pending:'待接入'}
const STATE_FILL={operational:'rgba(82,196,26,.30)',observing:'rgba(250,173,20,.26)',trunk:'rgba(90,170,220,.22)',pending:'rgba(150,180,210,.12)'}
const STATE_STROKE={operational:'#5fbf3a',observing:'#e0a83a',trunk:'#5aaadc',pending:'rgba(150,180,210,.35)'}

const BOUNDS={lon0:73,lon1:136,lat0:30,lat1:54}
const VIEW={w:1000,h:640}
const COS=Math.cos(42*Math.PI/180)
const SCALE=Math.min(VIEW.w/((BOUNDS.lon1-BOUNDS.lon0)*COS),VIEW.h/(BOUNDS.lat1-BOUNDS.lat0))
const OFFSET={x:(VIEW.w-(BOUNDS.lon1-BOUNDS.lon0)*COS*SCALE)/2,
              y:(VIEW.h-(BOUNDS.lat1-BOUNDS.lat0)*SCALE)/2}
function project(lon,lat){
  return [OFFSET.x+(lon-BOUNDS.lon0)*COS*SCALE, OFFSET.y+(BOUNDS.lat1-lat)*SCALE]
}

const NORTH_NAMES=new Set(['北京市','天津市','河北省','山西省','内蒙古自治区','辽宁省','吉林省',
  '黑龙江省','陕西省','甘肃省','青海省','宁夏回族自治区','新疆维吾尔自治区'])

const shapes=computed(()=>{
  const rows=[]
  for(const feature of china.features||[]){
    const name=(feature.properties||{}).name
    if(!NORTH_NAMES.has(name)) continue
    const geo=feature.geometry||{}
    const polys=geo.type==='Polygon'?[geo.coordinates]:(geo.type==='MultiPolygon'?geo.coordinates:[])
    let d=''
    for(const poly of polys) for(const ring of poly){
      for(let i=0;i<ring.length;i++){
        const [x,y]=project(ring[i][0],ring[i][1])
        d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)
      }
    }
    if(d) rows.push({name,d})
  }
  return rows
})

const byName=computed(()=>{
  const map={}
  for(const row of data.value?.provinces||[]) map[row.name]=row
  return map
})
const activeNames=computed(()=>{
  const map=new Map()
  for(const row of data.value?.provinces||[]) map.set(row.name,row.state||'pending')
  return map
})
const corridors=computed(()=>{
  const rows=[]
  for(const row of data.value?.corridors||[]){
    const path=row.path
    if(Array.isArray(path)&&path.length>1){
      const points=path.map(([lon,lat])=>project(lon,lat))
      rows.push({id:row.id,points,source:row.source})
    }else{
      const a=project(row.fromLonLat[0],row.fromLonLat[1])
      const b=project(row.toLonLat[0],row.toLonLat[1])
      rows.push({id:row.id,points:[a,b],source:row.source})
    }
  }
  return rows
})
const stations=computed(()=>(data.value?.stationPoints||[]).map(point=>{
  const [x,y]=project(point.lon,point.lat)
  return {code:point.code,city:point.name,x,y,low:!!point.low,vis:point.visM,temp:point.tempC}
}))
const summary=computed(()=>data.value?.summary||{})
const regions=computed(()=>data.value?.regions||[])
const provinceRows=computed(()=>data.value?.provinces||[])
const cities=computed(()=>data.value?.cities||[])

function label(levelKey,id,name){
  if(levelKey==='north') return '北方地区'
  if(levelKey==='region') return name||id
  if(levelKey==='province') return name||id
  return name||id
}

async function load(){
  loading.value=true
  error.value=''
  data.value=null                      // 先卸屏，避免上一级的数据留在内存里
  try{
    const query=`level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}`
    data.value=await requestJson(`/api/traffic/v2/northern?${query}`,{timeoutMs:30000})
  }catch(e){error.value=e.message||String(e)}
  finally{loading.value=false}
}

function go(nextLevel,nextId,nextLabel){
  level.value=nextLevel
  ident.value=nextId||''
  if(nextLevel==='north'){
    trail.value=[{level:'north',id:'',label:'北方地区'}]
  }else{
    const cut=trail.value.findIndex(item=>item.level===nextLevel)
    if(cut>=0) trail.value=trail.value.slice(0,cut)
    trail.value=[...trail.value,{level:nextLevel,id:nextId||'',label:label(nextLevel,nextId,nextLabel)}]
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
      运行态 <b class="alc-num">{{ summary.operational }}</b> ·
      待接入 <b class="alc-num">{{ summary.pending }}</b> ·
      干线 <b class="alc-num">{{ summary.trunk }}</b> ·
      走廊合计 <b class="alc-num">{{ summary.corridors }}</b> ·
      METAR 站 <b class="alc-num">{{ summary.stations }}</b>
    </p>
  </header>

  <p class="nrn-state" v-if="loading">正在加载本级数据…</p>
  <p class="nrn-state bad" v-else-if="error">本级不可用 · {{ error }}<button @click="load">重试</button></p>

  <div class="nrn-body" v-else-if="data">
    <div class="nrn-map">
      <svg :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`" role="img" aria-label="北方地区层级地图">
        <defs>
          <pattern id="nrn-grid" width="50" height="50" patternUnits="userSpaceOnUse">
            <path d="M50 0H0V50" fill="none" stroke="rgba(120,170,220,.10)" stroke-width="1"/>
          </pattern>
        </defs>
        <rect x="0" y="0" :width="VIEW.w" :height="VIEW.h" fill="url(#nrn-grid)"/>
        <g v-for="line in corridors" :key="line.id">
          <polyline :points="line.points.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')"
                    fill="none" :stroke="line.source==='RUN'?'rgba(89,223,252,.55)':'rgba(90,170,220,.38)'"
                    :stroke-width="line.source==='RUN'?1.6:1.1" stroke-linejoin="round"/>
        </g>
        <g>
          <path v-for="shape in shapes" :key="shape.name" :d="shape.d"
                :fill="STATE_FILL[activeNames.get(shape.name)||'pending']"
                :stroke="hovered===shape.name?'#7fd4ff':STATE_STROKE[activeNames.get(shape.name)||'pending']"
                :stroke-width="activeNames.has(shape.name)?1.1:0.5"
                @mouseenter="hovered=shape.name" @mouseleave="hovered=null"
                @click="activeNames.has(shape.name) && go('province',shape.name,shape.name)">
            <title>{{ shape.name }}{{ activeNames.has(shape.name)?' · '+STATE_NAME[activeNames.get(shape.name)]:' · 不在本级范围' }}</title>
          </path>
        </g>
        <g v-for="point in stations" :key="point.code">
          <circle :cx="point.x" :cy="point.y" :r="point.low?4.2:2.8"
                  :fill="point.low?'#e24b4a':'#4dd0e1'" stroke="#0b1220" stroke-width="0.8"/>
          <title>{{ point.city }} {{ point.code }} · 能见 {{ point.vis==null?'—':Math.round(point.vis)+' m' }}</title>
        </g>
      </svg>
      <p class="nrn-note">
        点省下钻；颜色按四态；青线为东北真实城际走廊，浅蓝为北方干线（A* 生成，模拟派生）。
        <span v-if="hovered">指向：{{ hovered }}</span>
      </p>
    </div>

    <aside class="nrn-side">
      <div class="nrn-card">
        <h3>{{ regions.length ? '各大区概览' : (level==='region' ? '本区省份' : (level==='province' ? '本省城市' : '本省')) }}</h3>
        <ul v-if="regions.length" class="nrn-list">
          <li v-for="region in regions" :key="region.id" @click="go('region',region.id,region.name)">
            <b>{{ region.name }}</b>
            <span>{{ region.provinces }} 省 · {{ region.corridors }} 条 · {{ region.stations }} 站</span>
            <em>{{ region.operational }} 运行 / {{ region.pending }} 待接入</em>
          </li>
        </ul>
        <ul v-else-if="provinceRows.length" class="nrn-list">
          <li v-for="row in provinceRows" :key="row.name" @click="go('province',row.name,row.name)">
            <b>{{ row.name }}</b>
            <span>{{ STATE_NAME[row.state] }} · 干线 {{ row.trunkCorridors }} · 本地 {{ row.localCorridors }}</span>
            <em>{{ row.stations }} 站</em>
          </li>
        </ul>
        <ul v-else-if="cities.length" class="nrn-list">
          <li v-for="city in cities" :key="city.name" @click="go('city',city.name,city.name)">
            <b>{{ city.name }}</b>
            <span>{{ city.source==='RUN_CATALOG' ? '运行目录城市 · '+city.pads+' 个起降点' : '省会代表点' }}</span>
          </li>
        </ul>
        <p v-else class="nrn-hint">本级没有更深一层的数据。</p>
      </div>

      <div class="nrn-card nrn-wx">
        <h3>气象实况 <small>{{ stations.length }} 站</small></h3>
        <ul v-if="stations.length" class="nrn-wx-list">
          <li v-for="point in stations" :key="point.code">
            <b>{{ point.city }}</b><em>{{ point.code }}</em>
            <span>{{ point.temp==null?'—':point.temp+' °C' }} · 能见 {{ point.vis==null?'—':Math.round(point.vis)+' m' }}</span>
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
.nrn-sub{margin:0;font-size:12px;color:var(--alc-text-dim)}
.nrn-state{padding:24px;color:var(--alc-text-dim)}
.nrn-state.bad{color:var(--alc-watch)}
.nrn-body{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:12px;min-height:0;align-items:stretch}
.nrn-map{position:relative;border:1px solid var(--alc-line);border-radius:10px;background:var(--alc-bg-1);overflow:hidden}
.nrn-map svg{display:block;width:100%;height:100%}
.nrn-note{margin:0;padding:6px 10px;font-size:12px;color:var(--alc-text-mute);border-top:1px solid var(--alc-line)}
.nrn-side{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,1fr);gap:10px;min-height:0}
.nrn-card{border:1px solid var(--alc-line);border-radius:10px;background:var(--alc-bg-1);padding:10px 12px;min-height:0;overflow:auto}
.nrn-card h3{margin:0 0 8px;font-size:13px;color:var(--alc-text)}
.nrn-card h3 small{font-size:12px;color:var(--alc-text-mute);margin-left:6px}
.nrn-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.nrn-list li{display:grid;grid-template-columns:1fr auto;gap:2px 8px;padding:8px 10px;border:1px solid var(--alc-line);
  border-radius:7px;cursor:pointer;background:var(--alc-bg-2)}
.nrn-list li:hover{border-color:var(--alc-info)}
.nrn-list b{font-size:13px;color:var(--alc-text)}
.nrn-list span{font-size:12px;color:var(--alc-text-dim);grid-column:1;grid-row:2}
.nrn-list em{font-size:12px;font-style:normal;color:var(--alc-text-mute);grid-column:2;grid-row:1/3;align-self:center}
.nrn-wx-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:5px}
.nrn-wx-list li{display:flex;gap:8px;align-items:baseline;font-size:12px;color:var(--alc-text-dim);
  padding:5px 8px;background:var(--alc-bg-2);border-radius:6px}
.nrn-wx-list b{color:var(--alc-text)}
.nrn-wx-list em{font-style:normal;color:var(--alc-text-mute)}
.nrn-wx-list span{margin-left:auto}
.nrn-hint{margin:6px 0 0;font-size:12px;color:var(--alc-text-mute);line-height:1.6}
</style>
