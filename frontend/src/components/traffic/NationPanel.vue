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

// —— 推演时间轴 / 图层开关 / 视角 ——
const MINUTES=180
const minute=ref(0)
const playing=ref(false)
const radarOn=ref(true)
const tilt=ref(false)
const flights=ref([])
const traffic=ref({corridors:0,airborne:0,delayed:0})
let timer=null, flightSeq=0

// 缩放与平移：地图内容整体做仿射变换，投影本身不动（拖动缩放只改这层）
const zoom=ref(1)
const pan=ref({x:0,y:0})
const dragging=ref(false)
let dragStart=null

const KIND_NAME={INTRA:'省内',AIRPORT_FEED:'机场接驳',CROSS:'跨省通道'}

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

// 底图：35 个要素全画 —— 34 个省级单元 + 南海诸岛界线（adchar=JD，name 为空）。
// 纪律（2026-11-10 用户要求）：
//   ① 台湾、西藏等**所有省级单元一律实线**，不做虚线、不做"未未纳入"特殊标注；
//   ② 九段线必须画出来，南海诸岛不能缺 —— 这是地图完整性，不能省。
function toPath(geometry, projectFn){
  const polygons=geometry.type==='Polygon'?[geometry.coordinates]
    :(geometry.type==='MultiPolygon'?geometry.coordinates:[])
  let d=''
  for(const poly of polygons) for(const ring of poly){
    for(let i=0;i<ring.length;i++){
      const [x,y]=projectFn(ring[i][0],ring[i][1])
      d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)
    }
  }
  return d
}

const shapes=computed(()=>{
  const rows=[]
  for(const feature of china.features||[]){
    const props=feature.properties||{}
    const name=props.name||''
    const boundary=props.adchar==='JD'
    if(!name&&!boundary) continue
    // 九段线是**国家尺度**的符号：省/市级放大后会被拉成夸张的粗弧，反而读不出来。
    // 全国层（和跨省的大区层）一定画，省/市层隐藏 —— 岛屿本身仍由海南几何照常绘制。
    if(boundary&&!['nation','region'].includes(level.value)) continue
    const d=toPath(feature.geometry||{},project)
    if(!d) continue
    rows.push({key:name||'jd', name:name||'南海诸岛界线', boundary, d})
  }
  // 界线最后画，压在所有省界之上
  rows.sort((a,b)=>(a.boundary?1:0)-(b.boundary?1:0))
  return rows
})

// 南海诸岛小图（inset）：主图按大陆取框，南海诸岛按惯例放在右下角小图里，
// 这样既不把大陆压成一条缝，也不会漏掉南海。
const INSET={x:786,y:428,w:196,h:196,lon0:105.5,lon1:124.5,lat0:3.2,lat1:24.8}
const insetProj=computed(()=>{
  const cos=Math.cos(((INSET.lat0+INSET.lat1)/2)*Math.PI/180)
  const w=(INSET.lon1-INSET.lon0)*cos,h=INSET.lat1-INSET.lat0
  const scale=Math.min(INSET.w/w,INSET.h/h)
  return {cos,scale,ox:INSET.x+(INSET.w-w*scale)/2,oy:INSET.y+(INSET.h-h*scale)/2}
})
function projectInset(lon,lat){
  const p=insetProj.value
  return [p.ox+(lon-INSET.lon0)*p.cos*p.scale, p.oy+(INSET.lat1-lat)*p.scale]
}
const insetShapes=computed(()=>{
  if(level.value!=='nation') return []
  const rows=[]
  for(const feature of china.features||[]){
    const props=feature.properties||{}
    const name=props.name||''
    const boundary=props.adchar==='JD'
    if(!name&&!boundary) continue
    const d=toPath(feature.geometry||{},projectInset)
    if(!d) continue
    rows.push({key:name||'jd',boundary,d})
  }
  rows.sort((a,b)=>(a.boundary?1:0)-(b.boundary?1:0))
  return rows
})

const activeNames=computed(()=>{
  const map=new Map()
  for(const row of data.value?.provinces||[]) map.set(row.name,row)
  return map
})
// 航线画法（参照民航航线图）：
//   ① 一条线一个样：**同色、同宽、同端点样式**，不按类型分色分虚线；
//   ② 两点之间走**微弧**（不是直尺线），弧度随长度轻微增长，像航路图上的大圆弧；
//   ③ 弧一律朝图面上方鼓，同一屏里的弧成为一族，不会互相打结。
function arcPoints(a,b,bulgeIn){
  const dx=b[0]-a[0],dy=b[1]-a[1]
  const len=Math.hypot(dx,dy)
  if(len<10) return [a,b]
  // 弧度由后端算好（它验过"弧不能鼓出国境"），没给就退回小弧
  const bulge=(bulgeIn===undefined||bulgeIn===null)?0.02:bulgeIn
  const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2
  let px=-dy/len,py=dx/len                        // 法线
  if(py>0){px=-px;py=-py}                         // 统一朝屏幕上方鼓
  const cx=mx+px*len*bulge,cy=my+py*len*bulge
  const steps=Math.max(24,Math.min(96,Math.round(len/3)))   // 采样密一点，弧才圆
  const pts=[]
  for(let i=0;i<=steps;i++){
    const t=i/steps,u=1-t
    pts.push([u*u*a[0]+2*u*t*cx+t*t*b[0],u*u*a[1]+2*u*t*cy+t*t*b[1]])
  }
  return pts
}

const corridors=computed(()=>{
  const rows=[]
  for(const row of data.value?.corridors||[]){
    const path=row.path
    const raw=Array.isArray(path)&&path.length>1?path:[row.fromLonLat,row.toLonLat]
    const coords=raw.map(([lon,lat])=>project(lon,lat))
    // A* 算出来的多段折线保留原形；两点直连的用微弧，视觉上才像航路而不是连线题
    const points=coords.length===2?arcPoints(coords[0],coords[1],row.bulge):coords
    rows.push({id:row.id,points,blocked:!!row.borderBlocked,border:!!row.borderDetour})
  }
  return rows
})
// 图上用短名：去掉"市/地区/盟/自治州"这类后缀
function shortName(name){
  return (name||'').replace(/(市|地区|盟|自治州|回族自治区|维吾尔自治区)$/,'')
}

const nodes=computed(()=>(data.value?.nodes||[]).map(node=>{
  const [x,y]=project(node.lon,node.lat)
  return {...node,x,y,short:shortName(node.name),flip:x>VIEW.w-110}
}))
// 节点一律画：线是连到这些点上的，隐掉就会留下"悬空线头"。
// 全国层靠尺寸区分层级（机场略大 + 细环），省/市层再给文字标注。
const visibleNodes=computed(()=>nodes.value)
const showCityLabels=computed(()=>nodes.value.length>0&&nodes.value.length<=30)
// 标注避让：机场城市优先，同一块地方只留一个名字，避免珠三角那种糊成一坨
const labels=computed(()=>{
  if(!showCityLabels.value) return []
  const ordered=[...nodes.value].sort((a,b)=>(a.rank||3)-(b.rank||3))
  const placed=[]
  for(const node of ordered){
    if(placed.some(p=>Math.abs(p.y-node.y)<11&&Math.abs(p.x-node.x)<52)) continue
    placed.push(node)
  }
  return placed
})

// —— 回波 / 绕飞 / 航班 三个图层 ——
const RADAR_COLOR={WEAK:'rgba(34,197,94,.34)',CONVECTIVE:'rgba(245,197,66,.46)',STRONG:'rgba(239,68,68,.60)'}
const radarPolys=computed(()=>{
  const bands=data.value?.radar?.bands||{}
  const out=[]
  for(const band of ['WEAK','CONVECTIVE','STRONG']){
    for(const ring of bands[band]||[]){
      if(!ring||ring.length<3) continue
      const d=ring.map(([lon,lat],i)=>{const [x,y]=project(lon,lat);return (i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)}).join(' ')+' Z'
      out.push({band,d})
    }
  }
  return out
})

// 绕飞后的实际航迹：跟原航路叠在一起看，才看得出"往哪边偏了"
const detourLines=computed(()=>{
  const rows=[]
  for(const row of data.value?.corridors||[]){
    const det=row.detour
    if(!det||!Array.isArray(det.path)) continue
    rows.push({id:row.id,points:det.path.map(([lon,lat])=>project(lon,lat))})
  }
  return rows
})

function pointAt(path,progress){
  if(!path||path.length<2) return null
  const seg=path.length-1
  const pos=Math.max(0,Math.min(1,progress))*seg
  const idx=Math.min(seg-1,Math.floor(pos))
  const frac=pos-idx
  const a=path[idx],b=path[idx+1]
  return [a[0]+(b[0]-a[0])*frac,a[1]+(b[1]-a[1])*frac]
}

// 在飞的飞行汽车：位置 + 朝向 + 是否绕飞改航
const flightDots=computed(()=>{
  const byId={}
  for(const row of data.value?.corridors||[]) byId[row.id]=row
  const out=[]
  for(const f of flights.value||[]){
    const row=byId[f.corridor]
    const path=row?.path||[row?.fromLonLat,row?.toLonLat]
    if(!path||!path[0]) continue
    const [lon,lat]=[f.lon,f.lat]
    const ahead=pointAt(path,Math.min(1,f.progress+0.02))
    const cur=project(lon,lat)
    const nxt=ahead?project(ahead[0],ahead[1]):cur
    const angle=Math.atan2(nxt[1]-cur[1],nxt[0]-cur[0])*180/Math.PI
    out.push({...f,x:cur[0],y:cur[1],angle,delayed:f.status==='DELAYED'})
  }
  return out
})

const minuteLabel=computed(()=>{
  const base=8*60      // 推演窗口从 08:00 起，和"早高峰"对齐
  const t=base+minute.value
  return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`
})

// 线宽随层级：省级看的是"本市到哪"，线要粗；全国层 514 条，细线才不糊。
const lineWidth=computed(()=>({nation:1.0,region:1.3,province:1.9,city:1.6}[level.value]||1.05))

// 逐市气象：先列能见度低的，再列省会，其余按层级；全国层只列前 18 条，省/市层全列
const weatherRows=computed(()=>{
  const rows=(data.value?.nodes||[]).filter(node=>node.weather).map(node=>({
    name:node.name,short:shortName(node.name),rank:node.rank||3,capital:!!node.capital,
    temp:node.weather.tempC,wind:node.weather.windMps,vis:node.weather.visM,low:!!node.weather.low,
  }))
  rows.sort((a,b)=>(b.low?1:0)-(a.low?1:0)||(b.capital?1:0)-(a.capital?1:0)||a.rank-b.rank)
  return rows.slice(0,level.value==='nation'?18:60)
})

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

async function loadFlights(){
  const seq=++flightSeq
  try{
    const query=`level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}&minute=${minute.value}`
    const payload=await requestJson(`/api/traffic/v2/nation/flights?${query}`,{timeoutMs:20000})
    if(seq!==flightSeq) return                      // 只认最后一次请求，防止拖动时乱序覆盖
    flights.value=payload.flights||[]
    traffic.value=payload.traffic||{corridors:0,airborne:0,delayed:0}
  }catch(e){/* 时间轴刷新失败不打断主界面 */}
}

function togglePlay(){
  playing.value=!playing.value
  if(playing.value){
    timer=setInterval(()=>{
      minute.value=(minute.value+3)%MINUTES
      loadFlights()
    },1200)
  }else if(timer){clearInterval(timer);timer=null}
}

function onSlide(){
  loadFlights()
}

function onWheel(event){
  const rect=event.currentTarget.getBoundingClientRect()
  const factor=event.deltaY<0?1.12:1/1.12
  const next=Math.max(1,Math.min(6,zoom.value*factor))
  if(next===zoom.value) return
  // 以鼠标位置为中心缩放
  const mx=(event.clientX-rect.left)/rect.width*VIEW.w
  const my=(event.clientY-rect.top)/rect.height*VIEW.h
  const k=next/zoom.value
  pan.value={x:mx-(mx-pan.value.x)*k,y:my-(my-pan.value.y)*k}
  zoom.value=next
}

function onDown(event){
  dragging.value=true
  dragStart={x:event.clientX,y:event.clientY,px:pan.value.x,py:pan.value.y}
}
function onMove(event){
  if(!dragging.value||!dragStart) return
  const rect=event.currentTarget.getBoundingClientRect()
  pan.value={x:dragStart.px+(event.clientX-dragStart.x)/rect.width*VIEW.w,
             y:dragStart.py+(event.clientY-dragStart.y)/rect.height*VIEW.h}
}
function onUp(){dragging.value=false;dragStart=null}
function resetView(){zoom.value=1;pan.value={x:0,y:0}}

async function load(){
  loading.value=true
  error.value=''
  data.value=null                      // 先卸屏，避免上一级的数据留在内存里
  try{
    const query=`level=${encodeURIComponent(level.value)}&id=${encodeURIComponent(ident.value)}`
    data.value=await requestJson(`/api/traffic/v2/nation?${query}&minute=${minute.value}`,{timeoutMs:30000})
    flights.value=data.value?.flights||[]
    traffic.value=data.value?.traffic||{corridors:0,airborne:0,delayed:0}
    resetView()
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

onMounted(()=>{load()})
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
      逐市气象 <b class="alc-num">{{ summary.weatherCities }}</b>
    </p>
  </header>

  <p class="nrn-state" v-if="loading">正在加载本级数据…</p>
  <p class="nrn-state bad" v-else-if="error">本级不可用 · {{ error }}<button @click="load">重试</button></p>

  <div class="nrn-body" v-else-if="data">
    <div class="nrn-map">
      <!-- 推演时间轴 + 图层开关 + 视角复位 -->
      <div class="nrn-tools">
        <button class="play" @click="togglePlay">{{ playing?'暂停':'播放' }}</button>
        <input type="range" min="0" :max="MINUTES" step="1" v-model.number="minute"
               @input="onSlide" @change="onSlide" aria-label="推演时间"/>
        <b class="clock">{{ minuteLabel }}</b>
        <button :class="{on:radarOn}" @click="radarOn=!radarOn">回波</button>
        <button :class="{on:tilt}" @click="tilt=!tilt">立体</button>
        <button @click="resetView">复位</button>
      </div>
      <!-- 飞行汽车：等距视角的简化模型（转子带旋转动画），当图例也用 -->
      <div class="nrn-car">
        <svg viewBox="0 0 168 104" aria-label="飞行汽车模型">
          <defs>
            <linearGradient id="carBody" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#eaf7ff"/><stop offset="100%" stop-color="#9dc9e8"/>
            </linearGradient>
            <linearGradient id="carSide" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#6ea6c9"/><stop offset="100%" stop-color="#3c6b8c"/>
            </linearGradient>
          </defs>
          <ellipse cx="84" cy="92" rx="46" ry="7" fill="rgba(10,26,40,.45)"/>
          <!-- 机臂 -->
          <g stroke="#7fb6d6" stroke-width="5" stroke-linecap="round" opacity=".85">
            <line x1="52" y1="52" x2="28" y2="40"/><line x1="116" y1="52" x2="140" y2="40"/>
            <line x1="52" y1="60" x2="28" y2="72"/><line x1="116" y1="60" x2="140" y2="72"/>
          </g>
          <!-- 转子 -->
          <g fill="none" stroke="#bfe9ff" stroke-width="2">
            <ellipse class="rotor" cx="28" cy="40" rx="15" ry="5"/>
            <ellipse class="rotor" cx="140" cy="40" rx="15" ry="5"/>
            <ellipse class="rotor" cx="28" cy="72" rx="15" ry="5"/>
            <ellipse class="rotor" cx="140" cy="72" rx="15" ry="5"/>
          </g>
          <!-- 车身：上盖 + 侧面 + 座舱 -->
          <path d="M84 34 L120 48 L84 62 L48 48 Z" fill="url(#carBody)"/>
          <path d="M48 48 L84 62 L84 74 L48 60 Z" fill="url(#carSide)"/>
          <path d="M120 48 L84 62 L84 74 L120 60 Z" fill="#2f5975"/>
          <path d="M68 44 L84 38 L100 44 L84 50 Z" fill="#12324a" opacity=".85"/>
          <circle cx="84" cy="46" r="2.2" fill="#8ef0ff"/>
        </svg>
        <span>飞行汽车 · 在飞 <b class="alc-num">{{ traffic.airborne }}</b></span>
      </div>

      <svg :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`" role="img" aria-label="全国航线网层级地图"
           :class="{tilt, dragging}"
           @wheel.prevent="onWheel" @mousedown="onDown" @mousemove="onMove"
           @mouseup="onUp" @mouseleave="onUp">
        <defs>
          <pattern id="nrn-grid" width="50" height="50" patternUnits="userSpaceOnUse">
            <path d="M50 0H0V50" fill="none" stroke="rgba(120,170,220,.08)" stroke-width="1"/>
          </pattern>
          <filter id="nrn-radar-blur" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="2.4"/>
          </filter>
        </defs>
        <rect x="0" y="0" :width="VIEW.w" :height="VIEW.h" fill="url(#nrn-grid)"/>

        <g :transform="`translate(${pan.x} ${pan.y}) scale(${zoom})`">

        <!-- 雷达回波：压在底图之上、航线之下，透明度足够低才不抢航路 -->
        <g v-if="radarOn" class="nrn-radar" filter="url(#nrn-radar-blur)" opacity="0.95">
          <path v-for="(poly,i) in radarPolys" :key="'r'+i" :d="poly.d"
                :fill="RADAR_COLOR[poly.band]" stroke="none"/>
        </g>

        <g>
          <path v-for="shape in shapes" :key="shape.key" :d="shape.d"
                :fill="shape.boundary?'rgba(150,200,235,.55)':'rgba(96,132,170,.10)'"
                :stroke="shape.boundary?'none':(hovered===shape.name?'#7fd4ff':'rgba(120,165,205,.40)')"
                :stroke-width="hovered===shape.name?1.2:0.8"
                :class="{live:!shape.boundary && activeNames.has(shape.name)}"
                @mouseenter="hovered=shape.name" @mouseleave="hovered=null"
                @click="!shape.boundary && activeNames.has(shape.name) && level!=='province' && level!=='city' && go('province',shape.name,shape.name)">
            <title>{{ shape.name }}{{ shape.boundary?' · 南海诸岛界线':(activeNames.has(shape.name)?' · 点击下钻':' · 不在本级范围') }}</title>
          </path>
        </g>

        <!-- 南海诸岛小图：全国层才显示，保证"地图完整" -->
        <g v-if="level==='nation'" class="nrn-inset">
          <clipPath id="nrn-inset-clip">
            <rect :x="INSET.x" :y="INSET.y" :width="INSET.w" :height="INSET.h" rx="4"/>
          </clipPath>
          <rect :x="INSET.x" :y="INSET.y" :width="INSET.w" :height="INSET.h" rx="4"
                fill="rgba(8,18,30,.55)" stroke="rgba(120,165,205,.45)" stroke-width="0.8"/>
          <g :clip-path="'url(#nrn-inset-clip)'">
            <path v-for="shape in insetShapes" :key="'i'+shape.key" :d="shape.d"
                  :fill="shape.boundary?'rgba(150,200,235,.55)':'rgba(96,132,170,.12)'"
                  :stroke="shape.boundary?'none':'rgba(120,165,205,.40)'" stroke-width="0.6"/>
          </g>
          <text :x="INSET.x+8" :y="INSET.y+INSET.h-8" class="nrn-inset-lbl">南海诸岛</text>
        </g>

        <!-- 航线：同色同宽同端点，下面一层极淡的光晕只做体积感，不区分类别 -->
        <g class="nrn-routes" fill="none" stroke-linecap="round" stroke-linejoin="round">
          <!-- 边境管制带内不放飞：细红线只作提示，不当作正常航路 -->
          <polyline v-for="line in corridors.filter(l=>l.blocked)" :key="'b'+line.id"
                    :points="line.points.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')"
                    stroke="rgba(226,92,74,.30)" :stroke-width="lineWidth*0.9"/>
                    :points="line.points.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')"
                    stroke="rgba(120,200,255,.07)" :stroke-width="lineWidth*2.9"/>
          <polyline v-for="line in corridors" :key="line.id"
                    :points="line.points.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')"
                    stroke="rgba(126,206,255,.60)" :stroke-width="lineWidth"/>
        </g>

        <!-- 节点：圆点一律同尺寸同色；机场城市加一圈细环（航图里的机场符号） -->
        <g class="nrn-nodes">
          <g v-for="node in visibleNodes" :key="'n'+node.name">
            <!-- 三级节点：省会/首府最大 + 浅色环；机场城市中点；一般节点小点 -->
            <circle v-if="node.external" :cx="node.x" :cy="node.y" :r="node.rank===1?3.4:2.4"
                    fill="none" stroke="rgba(160,200,235,.75)" stroke-width="1.1"/>
            <circle v-else :cx="node.x" :cy="node.y" :r="node.rank===1?3.1:(node.rank===2?2.2:1.45)"
                    :fill="node.rank===3?'rgba(214,236,255,.5)':'#eaf6ff'"
                    :stroke="node.rank===3?'none':'rgba(8,20,32,.85)'" stroke-width="0.55"/>
            <circle v-if="node.capital" :cx="node.x" :cy="node.y" r="5.6"
                    fill="none" stroke="rgba(186,218,255,.40)" stroke-width="0.9"/>
            <circle v-if="node.weather&&node.weather.low" :cx="node.x" :cy="node.y" r="4.6"
                    fill="none" stroke="rgba(226,75,74,.9)" stroke-width="1"/>
            <title>{{ node.name }}{{ node.external?' · 邻省端点':'' }}{{ node.capital?' · 省会/首府':'' }}{{ node.hasAirport?' · 机场 '+node.airport:' · 无机场（有专用接驳航线）' }}<template v-if="node.weather"> · {{ node.weather.tempC==null?'—':node.weather.tempC+' °C' }} 能见 {{ visText(node.weather.visM,false) }}</template></title>
          </g>
        </g>

        <!-- 绕飞航迹：回波挡路时实际飞的这条，比原航路亮一档 -->
        <g class="nrn-detour" fill="none" stroke-linecap="round">
          <polyline v-for="line in detourLines" :key="'d'+line.id"
                    :points="line.points.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')"
                    stroke="rgba(255,214,102,.85)" :stroke-width="lineWidth*1.35"/>
        </g>

        <!-- 在飞的飞行汽车：同一个 glyph，按航向旋转；绕飞改航的用琥珀色 -->
        <g class="nrn-flights">
          <g v-for="f in flightDots" :key="f.id" :transform="`translate(${f.x.toFixed(1)} ${f.y.toFixed(1)}) rotate(${f.angle.toFixed(0)})`">
            <ellipse v-if="f.delayed" cx="0" cy="0" rx="9" ry="6" fill="rgba(255,196,64,.10)"/>
            <path d="M7 0 L-4 4 L-2 0 L-4 -4 Z"
                  :fill="f.delayed?'#ffc857':'#dff3ff'"
                  :stroke="f.delayed?'rgba(120,60,0,.7)':'rgba(10,30,45,.8)'" stroke-width="0.5"/>
            <title>{{ f.fromName }} → {{ f.toName }} · {{ f.speedKmh }} km/h · 高度 {{ f.altM }} m{{ f.delayed?(' · 绕飞 +'+f.delayMin+' min / +'+f.detourKm+' km'):' · 正常' }}</title>
          </g>
        </g>

        <g class="nrn-labels" v-if="labels.length">
          <text v-for="node in labels" :key="'t'+node.name"
                :x="node.x+(node.flip?-6:6)" :y="node.y+3.4" class="nrn-lbl"
                :text-anchor="node.flip?'end':'start'">{{ node.short }}</text>
        </g>

        </g>
      </svg>
      <p class="nrn-note">
        回波按反射率分档：<i class="sw weak"></i>弱 <i class="sw conv"></i>对流 <i class="sw strong"></i>强；琥珀色航迹＝绕飞改航。
        一条弧线＝一条航线（同色同宽，不分类型）；节点三级：省会/首府（大点＋浅环）＞机场城市（中点）＞一般城市（小点）<template v-if="level==='nation'">；右下小图为南海诸岛</template>。
        定位：飞行汽车分担城市间出行，跨省长距离仍靠飞机与火车。
        <span v-if="hovered">指向：{{ hovered }}</span>
      </p>
    </div>

    <aside class="nrn-side">
      <div class="nrn-card">
        <div class="nrn-stats">
          <div><b class="alc-num">{{ traffic.corridors }}</b><span>航线</span></div>
          <div><b class="alc-num">{{ traffic.airborne }}</b><span>在飞汽车</span></div>
          <div :class="{alarm:traffic.delayed>0}"><b class="alc-num">{{ traffic.delayed }}</b><span>异常</span></div>
          <div :class="{alarm:(traffic.blocked||0)>0}" v-if="traffic.blocked"><b class="alc-num">{{ traffic.blocked }}</b><span>边境待批</span></div>
        </div>
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
            <span>{{ row.cities }} 市 · 机场 {{ row.airports }} · 气象 {{ row.weatherCities||0 }}</span>
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
        <h3>逐市气象 <small>{{ weatherRows.length }} 城 · open-meteo 公开实况</small></h3>
        <ul v-if="weatherRows.length" class="nrn-wx-list">
          <li v-for="row in weatherRows" :key="row.name" :class="{low:row.low}">
            <b>{{ row.short }}</b>
            <em v-if="row.capital">首府</em>
            <span>{{ row.temp==null?'—':row.temp+' °C' }} · 风 {{ row.wind==null?'—':row.wind+' m/s' }} · 能见 {{ visText(row.vis,false) }}</span>
          </li>
        </ul>
        <p v-else class="nrn-hint">气象源暂不可用（公开源拿不到就是没有，不补零）。</p>
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
.nrn-map svg{display:block;width:100%;height:100%;flex:1;min-height:0;cursor:grab}
.nrn-map svg.dragging{cursor:grabbing}
/* 立体视角：整体做轻微俯仰，只在"看形状"时用；倾斜状态下不做点选 */
.nrn-map svg.tilt{transform:perspective(1800px) rotateX(17deg) scale(.86);transform-origin:50% 62%}
.nrn-tools{position:absolute;left:10px;top:10px;z-index:3;display:flex;align-items:center;gap:6px;
  padding:6px 8px;border:1px solid var(--alc-line);border-radius:8px;background:rgba(8,18,30,.82);
  backdrop-filter:blur(4px);font-size:12px;color:var(--alc-text-dim)}
.nrn-tools button{background:transparent;border:1px solid var(--alc-line);border-radius:5px;
  color:var(--alc-text-dim);padding:2px 8px;font-size:12px;cursor:pointer}
.nrn-tools button.on{border-color:var(--alc-info);color:#bfe9ff;background:rgba(90,170,220,.14)}
.nrn-tools button.play{border-color:rgba(120,200,255,.5);color:#d6f1ff;min-width:46px}
.nrn-tools input[type=range]{width:150px;accent-color:#5aaadc}
.nrn-car{position:absolute;left:12px;bottom:44px;z-index:3;display:flex;flex-direction:column;align-items:center;
  gap:2px;width:132px;padding:6px 8px 4px;border:1px solid var(--alc-line);border-radius:10px;
  background:rgba(8,18,30,.62);backdrop-filter:blur(3px)}
.nrn-car svg{width:120px;height:74px;display:block}
.nrn-car span{font-size:11px;color:var(--alc-text-dim);white-space:nowrap}
.nrn-car b{color:#e6f4ff}
.rotor{animation:rotor-spin 1.1s linear infinite;transform-origin:center;transform-box:fill-box}
@keyframes rotor-spin{from{opacity:.35;transform:scaleX(.35)}50%{opacity:.95;transform:scaleX(1)}to{opacity:.35;transform:scaleX(.35)}}
.nrn-tools .clock{color:#e6f4ff;font-variant-numeric:tabular-nums;min-width:44px;text-align:center}
.nrn-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:0 0 8px}
.nrn-stats div{border:1px solid var(--alc-line);border-radius:7px;background:var(--alc-bg-2);
  padding:6px 8px;display:flex;flex-direction:column;gap:2px}
.nrn-stats b{font-size:18px;color:#e6f4ff;line-height:1.1}
.nrn-stats span{font-size:12px;color:var(--alc-text-mute)}
.nrn-stats div.alarm{border-color:rgba(255,196,64,.5);background:rgba(255,196,64,.10)}
.nrn-stats div.alarm b{color:#ffc857}
.nrn-map svg path.live{cursor:pointer}
/* 标注：统一字号、统一颜色，加深色描边保证压在航线上也能读 */
.nrn-lbl{font-size:9.5px;fill:rgba(226,241,255,.86);pointer-events:none;
  paint-order:stroke;stroke:rgba(6,14,24,.85);stroke-width:2.4px;stroke-linejoin:round}
.nrn-inset-lbl{font-size:9px;fill:rgba(190,215,235,.75);pointer-events:none}
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
.nrn-wx-list em{color:var(--alc-text-mute)}
.nrn-wx-list li.low{background:rgba(226,75,74,.12);box-shadow:inset 0 0 0 1px rgba(226,75,74,.35)}
.nrn-wx-list li.low b{color:#ffb4b2}
.nrn-wx-list span{margin-left:auto}
.nrn-hint{margin:6px 0 0;font-size:12px;color:var(--alc-text-mute);line-height:1.6}
.nrn-note .sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 3px 0 6px;vertical-align:-1px}
.nrn-note .sw.weak{background:rgba(64,180,120,.55)}
.nrn-note .sw.conv{background:rgba(232,190,60,.6)}
.nrn-note .sw.strong{background:rgba(228,92,64,.65)}
</style>
