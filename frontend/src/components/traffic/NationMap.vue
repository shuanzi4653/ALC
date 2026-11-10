<script setup>
import {computed,onMounted,onUnmounted,reactive,ref,watch} from 'vue'
import china from '../../assets/china.json'

// 全国航线图（墨卡托）。
//
// 为什么从等经纬改成墨卡托：回波是**墨卡托瓦片**，地形阴影也是墨卡托瓦片。
// 只要底图投影不是墨卡托，这两层就只能"矢量化后近似"，回波边界必然发虚 ——
// 换投影比调透明度管用得多。改完之后瓦片可以 1:1 贴上去，边界就是原始像素。
//
// 三层叠放顺序：地形阴影 → 雷达瓦片 → 行政区 → 建筑/航线/节点/航班。
const props=defineProps({
  data:{type:Object,default:null},
  flights:{type:Array,default:()=>[]},
  minute:{type:Number,default:0},
  radarOn:{type:Boolean,default:true},
  fogOn:{type:Boolean,default:true},
  terrainOn:{type:Boolean,default:true},
  tilt:{type:Boolean,default:false},
  density:{type:String,default:'full'},
  selectedId:{type:String,default:''},
  selectedCorridor:{type:String,default:''},
  virtualMode:{type:Boolean,default:false},
  followId:{type:String,default:''},
})
const emit=defineEmits(['drill','select-flight','select-corridor','hover-node'])

// 视口尺寸跟容器走：viewBox 的宽高比和容器一致，图上就不会留出两条黑边。
// 之前固定 1000x640，装进窄高或扁宽的槽位都会被 letterbox 压小一圈。
const VIEW=reactive({w:1000,h:640})
const host=ref(null)
let ro=null
function fitView(){
  const el=host.value
  if(!el) return
  const rect=el.getBoundingClientRect()
  if(rect.width>80&&rect.height>80){
    VIEW.w=Math.round(rect.width)
    VIEW.h=Math.round(rect.height)
  }
}
onMounted(()=>{
  fitView()
  if(typeof ResizeObserver!=='undefined'&&host.value){
    ro=new ResizeObserver(fitView)
    ro.observe(host.value)
  }
})
onUnmounted(()=>{if(ro) ro.disconnect()})
const RADAR_COLOR={WEAK:'rgba(40,190,110,.20)',CONVECTIVE:'rgba(245,190,60,.30)',STRONG:'rgba(238,72,60,.42)'}

const level=computed(()=>props.data?.level||'nation')
const box=computed(()=>{
  const b=props.data?.view?.bbox
  if(!b||b.length<4||b[2]<=b[0]) return {lon0:73,lon1:136,lat0:17,lat1:54.5}
  const padLon=Math.max(.35,(b[2]-b[0])*.07), padLat=Math.max(.3,(b[3]-b[1])*.07)
  return {lon0:b[0]-padLon,lon1:b[2]+padLon,lat0:b[1]-padLat,lat1:b[3]+padLat}
})

// —— 墨卡托投影 ——
const rad=d=>d*Math.PI/180
const merc=lat=>Math.log(Math.tan(Math.PI/4+rad(Math.max(-85,Math.min(85,lat)))/2))
const proj=computed(()=>{
  const v=box.value
  const w=rad(v.lon1)-rad(v.lon0)
  const h=merc(v.lat1)-merc(v.lat0)
  const k=Math.min(VIEW.w/w,VIEW.h/h)
  return {k,ox:(VIEW.w-w*k)/2,oy:(VIEW.h-h*k)/2,v,lon0:rad(v.lon0),lat1:merc(v.lat1)}
})
function project(lon,lat){
  const p=proj.value
  return [p.ox+(rad(lon)-p.lon0)*p.k, p.oy+(p.lat1-merc(lat))*p.k]
}

// —— 瓦片 ——
// 一张瓦片的墨卡托宽高恒为 2π/2^z；选 z 让单瓦片落在 180–360 px 之间。
function tilesFor(template,minZoom,maxZoom){
  if(!template) return []
  const p=proj.value
  let z=Math.round(Math.log2((2*Math.PI*p.k)/420))
  z=Math.max(minZoom,Math.min(maxZoom,z))
  const n=2**z, size=(2*Math.PI/n)*p.k, out=[]
  const lonL=p.v.lon0, lonR=p.v.lon1
  const latT=p.v.lat1, latB=p.v.lat0
  const x0=Math.floor((rad(lonL)+Math.PI)/(2*Math.PI)*n)
  const x1=Math.floor((rad(lonR)+Math.PI)/(2*Math.PI)*n)
  const y0=Math.floor((Math.PI-merc(latT))/(2*Math.PI)*n)
  const y1=Math.floor((Math.PI-merc(latB))/(2*Math.PI)*n)
  for(let x=x0;x<=x1;x++) for(let y=y0;y<=y1;y++){
    if(y<0||y>=n) continue
    if(out.length>160) return out
    const lon=((x/n)*360-180)
    const latTop=Math.atan(Math.sinh(Math.PI*(1-2*y/n)))*180/Math.PI
    const [px,py]=project(lon,latTop)
    out.push({key:`${z}/${x}/${y}`,x:px,y:py,size:size+0.6,
      href:template.replace('{z}',z).replace('{x}',x).replace('{y}',y)})
  }
  return out
}
const terrainTiles=computed(()=>{
  if(!props.terrainOn) return []
  return tilesFor('https://tiles.openfreemap.org/natural_earth/ne2sr/{z}/{x}/{y}.png',5,5)
})
const radarTiles=computed(()=>{
  if(!props.radarOn) return []
  const t=props.data?.radar?.tiles
  if(!t) return []
  return tilesFor(t,6,6)
})

// —— 雾区 ——
// 面是后端按城市能见度外扩合并出来的（DERIVED），点才是实测；所以面画得很淡，
// 城市本身仍由节点的红圈标注，两者不混。
const fogPolys=computed(()=>{
  if(!props.fogOn) return []
  const bands=props.data?.fog?.bands||{}
  const out=[]
  for(const level of ['BAN','LOW']){
    for(const ring of bands[level]||[]){
      if(!ring||ring.length<3) continue
      out.push({level,d:toPath({type:'Polygon',coordinates:[ring]},project)})
    }
  }
  return out
})

// —— 行政区 ——
function toPath(geometry,projectFn){
  const polys=geometry.type==='Polygon'?[geometry.coordinates]
    :(geometry.type==='MultiPolygon'?geometry.coordinates:[])
  const put=projectFn||project
  let d=''
  for(const poly of polys) for(const ring of poly){
    for(let i=0;i<ring.length;i++){
      const [x,y]=put(ring[i][0],ring[i][1])
      d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)
    }
  }
  return d
}
const shapes=computed(()=>{
  const rows=[]
  const live=new Set((props.data?.provinces||[]).map(r=>r.name))
  for(const f of china.features||[]){
    const p=f.properties||{}
    const name=p.name||''
    const boundary=p.adchar==='JD'
    if(!name&&!boundary) continue
    // 九段线只在国家级画：省级放大后它会变成夸张的粗弧
    if(boundary&&!['nation','region'].includes(level.value)) continue
    const d=toPath(f.geometry||{},project)
    if(!d) continue
    rows.push({key:name||'jd',name:name||'南海诸岛界线',boundary,live:live.has(name),d})
  }
  rows.sort((a,b)=>(a.boundary?1:0)-(b.boundary?1:0))
  return rows
})

// 雷达裁剪：回波只画**国内**。RainViewer 是整幅瓦片，邻国回波会跟着贴进来，
// 评审看到"境外有回波、国内航线在躲"会问为什么管到国外去。
// 裁的是国界多边形（34 个省级单元并起来），台湾、港澳、海南都在里面；
// 九段线是线状要素，不参与裁剪面积。
const chinaClipD=computed(()=>{
  const parts=[]
  for(const f of china.features||[]){
    const p=f.properties||{}
    if(!p.name||p.adchar==='JD') continue
    const d=toPath(f.geometry||{},project)
    if(d) parts.push(d)
  }
  return parts.join(' ')
})

// —— 南海诸岛小图 ——
// 主图按大陆取框，南海诸岛（曾母暗沙到北纬 4°）会被裁在外面；按国内地图惯例放右下角小图。
// 小图自己一套墨卡托投影，和主图同源，只是范围不同。
const INSET={x:786,y:428,w:196,h:196,lon0:105.5,lon1:124.5,lat0:3.2,lat1:24.8}
const insetBox=computed(()=>({...INSET,
  x:Math.max(8,Math.min(INSET.x,VIEW.w-INSET.w-8)),
  y:Math.max(8,Math.min(INSET.y,VIEW.h-INSET.h-8))}))
const insetProj=computed(()=>{
  const b=insetBox.value
  const w=rad(b.lon1)-rad(b.lon0)
  const h=merc(b.lat1)-merc(b.lat0)
  const k=Math.min(b.w/w,b.h/h)
  return {k,ox:b.x+(b.w-w*k)/2,oy:b.y+(b.h-h*k)/2,lon0:rad(b.lon0),lat1:merc(b.lat1)}
})
function projectInset(lon,lat){
  const p=insetProj.value
  return [p.ox+(rad(lon)-p.lon0)*p.k, p.oy+(p.lat1-merc(lat))*p.k]
}
const insetShapes=computed(()=>{
  if(level.value!=='nation') return []
  const rows=[]
  for(const f of china.features||[]){
    const p=f.properties||{}
    const name=p.name||''
    const boundary=p.adchar==='JD'
    if(!name&&!boundary) continue
    const d=toPath(f.geometry||{},projectInset)
    if(!d) continue
    rows.push({key:(name||'jd'),boundary,d})
  }
  rows.sort((a,b)=>(a.boundary?1:0)-(b.boundary?1:0))
  return rows
})

// —— 航线 ——
function arcPoints(a,b,bulgeIn){
  const dx=b[0]-a[0],dy=b[1]-a[1]
  const len=Math.hypot(dx,dy)
  if(len<10) return [a,b]
  const bulge=(bulgeIn===undefined||bulgeIn===null)?0.02:bulgeIn
  const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2
  let px=-dy/len,py=dx/len
  if(py>0){px=-px;py=-py}
  const cx=mx+px*len*bulge,cy=my+py*len*bulge
  const steps=Math.max(20,Math.min(80,Math.round(len/4)))
  const pts=[]
  for(let i=0;i<=steps;i++){
    const t=i/steps,u=1-t
    pts.push([u*u*a[0]+2*u*t*cx+t*t*b[0],u*u*a[1]+2*u*t*cy+t*t*b[1]])
  }
  return pts
}
const lineWidth=computed(()=>({nation:.9,region:1.15,province:1.7,city:1.5}[level.value]||1))

const corridors=computed(()=>(props.data?.corridors||[]).map(row=>{
  const path=row.path&&row.path.length>1?row.path:[row.fromLonLat,row.toLonLat]
  const coords=path.map(([lon,lat])=>project(lon,lat))
  const points=coords.length===2?arcPoints(coords[0],coords[1],row.bulge):coords
  const d='M'+points.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join('L')
  let detour=null
  if(row.detour?.path?.length>1){
    const dp=row.detour.path.map(([lon,lat])=>project(lon,lat))
    detour='M'+dp.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join('L')
  }
  return {id:row.id,d,detour,blocked:!!row.borderBlocked,
    fromName:row.fromName,toName:row.toName,kindLabel:row.kindLabel,lengthKm:row.lengthKm,
    selected:props.selectedCorridor===row.id}
}))

// —— 节点与建筑 ——
function shortName(name){return (name||'').replace(/(市|地区|盟|自治州|回族自治区|维吾尔自治区)$/,'')}
const nodes=computed(()=>(props.data?.nodes||[]).map(node=>{
  const [x,y]=project(node.lon,node.lat)
  return {...node,x,y,short:shortName(node.name),
    tower:node.rank===1?17:(node.rank===2?11:7)}
}))
const labels=computed(()=>{
  const list=(props.data?.nodes||[]).map(node=>{
    const [x,y]=project(node.lon,node.lat)
    return {...node,x,y,short:shortName(node.name)}
  })
  const limit=level.value==='nation'?0:(props.density==='slim'?12:40)
  if(!limit) return []
  const ordered=list.sort((a,b)=>(a.rank||3)-(b.rank||3))
  const placed=[]
  for(const node of ordered){
    if(placed.some(p=>Math.abs(p.y-node.y)<12&&Math.abs(p.x-node.x)<54)) continue
    placed.push(node)
    if(placed.length>=limit) break
  }
  return placed
})
const provinceLabels=computed(()=>{
  if(level.value!=='nation') return []
  return (props.data?.provinces||[]).map(row=>{
    const [x,y]=project(row.center[0],row.center[1])
    return {name:shortName(row.name),x,y}
  })
})

// —— 航班 ——
const flightDots=computed(()=>{
  const out=[]
  for(const f of props.flights||[]){
    const [x,y]=project(f.lon,f.lat)
    out.push({...f,x,y,selected:props.selectedId===f.id,
      bad:f.decision==='HOLD'||f.riskLevel==='HIGH'})
  }
  return out
})

// —— 交互 ——
const zoom=ref(1)
const pan=ref({x:0,y:0})
const dragging=ref(false)
let dragStart=null,moved=false
function onWheel(e){
  const rect=e.currentTarget.getBoundingClientRect()
  const factor=e.deltaY<0?1.14:1/1.14
  const next=Math.max(1,Math.min(9,zoom.value*factor))
  if(next===zoom.value) return
  const mx=(e.clientX-rect.left)/rect.width*VIEW.w
  const my=(e.clientY-rect.top)/rect.height*VIEW.h
  const k=next/zoom.value
  pan.value={x:mx-(mx-pan.value.x)*k,y:my-(my-pan.value.y)*k}
  zoom.value=next
}
function onDown(e){dragging.value=true;moved=false;dragStart={x:e.clientX,y:e.clientY,px:pan.value.x,py:pan.value.y}}
function onMove(e){
  if(!dragging.value||!dragStart) return
  if(Math.abs(e.clientX-dragStart.x)>3||Math.abs(e.clientY-dragStart.y)>3) moved=true
  const rect=e.currentTarget.getBoundingClientRect()
  pan.value={x:dragStart.px+(e.clientX-dragStart.x)/rect.width*VIEW.w,
             y:dragStart.py+(e.clientY-dragStart.y)/rect.height*VIEW.h}
}
function onUp(){dragging.value=false;dragStart=null}
function resetView(){zoom.value=1;pan.value={x:0,y:0}}
// 缩放到指定经纬框（定位回波 / 定位雾区用）。留 18% 余量，别贴边。
function fitBounds(b){
  if(!b||b.length<4||b[2]<=b[0]||b[3]<=b[1]) return false
  const nw=project(b[0],b[3]), se=project(b[2],b[1])
  const w=Math.abs(se[0]-nw[0])||1, h=Math.abs(se[1]-nw[1])||1
  const next=Math.max(1,Math.min(9,Math.min(VIEW.w/w,VIEW.h/h)*0.82))
  const cx=(nw[0]+se[0])/2, cy=(nw[1]+se[1])/2
  zoom.value=next
  pan.value={x:VIEW.w/2-cx*next, y:VIEW.h/2-cy*next}
  return true
}
defineExpose({resetView,fitBounds})

// —— 跟随航班 ——
// 1.0.0 的"跟随"是相机跟着这一架走。这里没有相机，就把这一架钉在屏幕中心：
// 时间轴每刷新一次（flights 换引用）重新居中一次，所以它看起来是"停在中间、地图在动"。
function centerOn(lon,lat,scale){
  const [x,y]=project(lon,lat)
  const z=scale||zoom.value
  zoom.value=z
  pan.value={x:VIEW.w/2-x*z, y:VIEW.h/2-y*z}
}
watch([()=>props.followId,()=>props.flights],()=>{
  if(!props.followId) return
  const flight=(props.flights||[]).find(item=>item.id===props.followId)
  if(flight) centerOn(flight.lon,flight.lat,Math.max(2.2,zoom.value))
})

function clickShape(shape){
  if(moved||shape.boundary||!shape.live) return
  emit('drill','province',shape.name,shape.name)
}
function clickNode(node){
  if(moved) return
  emit('drill','city',node.name,node.name)
}
</script>

<template>
<div class="nmap" :class="{tilt}" ref="host">
  <svg :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`" role="img" aria-label="全国航线网"
       :class="{dragging}" @wheel.prevent="onWheel" @mousedown="onDown"
       @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp">
    <defs>
      <linearGradient id="towerFace" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(150,210,245,.85)"/>
        <stop offset="100%" stop-color="rgba(38,86,120,.25)"/>
      </linearGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="1.6"/></filter>
      <filter id="nmap-fog-blur" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="3.2"/>
      </filter>
      <clipPath id="nmap-china-clip"><path :d="chinaClipD"/></clipPath>
    </defs>

    <g :transform="`translate(${pan.x} ${pan.y}) scale(${zoom})`">
      <!-- 1 地形：真实晕渲瓦片（墨卡托，与投影一致） -->
      <g v-if="terrainTiles.length" class="nmap-terrain" :clip-path="'url(#nmap-china-clip)'">
        <image v-for="t in terrainTiles" :key="'t'+t.key" :x="t.x" :y="t.y"
               :width="t.size" :height="t.size" :href="t.href"
               preserveAspectRatio="none"/>
      </g>

      <!-- 2 雷达：原始瓦片，边界就是像素边界；**按国界裁掉境外回波** -->
      <g v-if="radarTiles.length" :opacity="virtualMode?1:.92" :clip-path="'url(#nmap-china-clip)'">
        <image v-for="t in radarTiles" :key="'r'+t.key" :x="t.x" :y="t.y"
               :width="t.size" :height="t.size" :href="t.href"
               preserveAspectRatio="none"/>
      </g>
      <!-- 分档描边：瓦片给"像不像"，描边给"哪一档"，两者都要 -->
      <g v-if="radarOn" fill="none" :clip-path="'url(#nmap-china-clip)'">
        <path v-for="(ring,i) in (data?.radar?.bands?.STRONG||[])" :key="'s'+i"
              :d="toPath({type:'Polygon',coordinates:[ring]})"
              :stroke="virtualMode?'rgba(255,150,110,.95)':'rgba(255,120,90,.75)'"
              :stroke-width="virtualMode?2.2:.9"/>
      </g>

      <!-- 2.5 雾区：低能见度面（DERIVED） -->
      <g v-if="fogPolys.length" class="nmap-fog" filter="url(#nmap-fog-blur)">
        <path v-for="(poly,i) in fogPolys" :key="'fg'+i" :d="poly.d"
              :fill="poly.level==='BAN'?'rgba(226,240,252,.34)':'rgba(196,222,244,.22)'"
              stroke="rgba(206,232,255,.35)" stroke-width=".8"/>
      </g>

      <!-- 3 行政区 -->
      <g>
        <path v-for="shape in shapes" :key="shape.key" :d="shape.d"
              :fill="shape.boundary?'rgba(150,200,235,.55)':(shape.live?'rgba(96,140,180,.13)':'rgba(96,132,170,.05)')"
              :stroke="shape.boundary?'none':'rgba(132,180,220,.52)'"
              stroke-width=".7" :class="{clickable:shape.live&&!shape.boundary}"
              @click="clickShape(shape)">
          <title>{{ shape.name }}{{ shape.boundary?' · 南海诸岛界线':(shape.live?'':' · 不在本级范围') }}</title>
        </path>
      </g>

      <!-- 3.5 南海诸岛小图：全国层才显示，保证地图完整 -->
      <g v-if="level==='nation'" class="nmap-inset">
        <defs>
          <clipPath id="nmap-inset-clip">
            <rect :x="insetBox.x" :y="insetBox.y" :width="insetBox.w" :height="insetBox.h" rx="4"/>
          </clipPath>
        </defs>
        <rect :x="insetBox.x" :y="insetBox.y" :width="insetBox.w" :height="insetBox.h" rx="4"
              fill="rgba(6,18,28,.72)" stroke="rgba(120,165,205,.45)" stroke-width=".8"/>
        <g :clip-path="'url(#nmap-inset-clip)'">
          <path v-for="shape in insetShapes" :key="'i'+shape.key" :d="shape.d"
                :fill="shape.boundary?'rgba(150,200,235,.55)':'rgba(96,132,170,.12)'"
                :stroke="shape.boundary?'none':'rgba(120,165,205,.45)'" stroke-width=".6"/>
        </g>
        <text :x="insetBox.x+7" :y="insetBox.y+insetBox.h-7" class="inset-lbl">南海诸岛</text>
      </g>

      <!-- 4 建筑：城市体块。立体模式下才立起来，平面模式只留底影 -->
      <g class="nmap-towers">
        <g v-for="node in nodes" :key="'b'+node.name">
          <rect v-if="tilt" :x="node.x-1.8" :y="node.y-node.tower*2.6" width="3.6"
                :height="node.tower*2.6" fill="url(#towerFace)" opacity=".5"/>
          <ellipse v-else :cx="node.x" :cy="node.y" rx="2.6" ry="1.4" fill="rgba(8,20,32,.5)"/>
        </g>
      </g>

      <!-- 4.5 地面：倾斜时铺一层，避免透视看穿 -->
      <rect v-if="tilt" x="-400" y="-300" :width="VIEW.w+800" :height="VIEW.h+900"
            fill="rgba(6,16,25,.55)" pointer-events="none"/>

      <!-- 5 航线 -->
      <g fill="none" stroke-linecap="round">
        <path v-for="line in corridors" :key="'c'+line.id" :d="line.d"
              :stroke="line.blocked?(virtualMode?'rgba(255,96,70,.95)':'rgba(226,92,74,.55)'):'rgba(126,206,255,.62)'"
              :stroke-width="line.blocked?lineWidth*(virtualMode?2.2:.8):lineWidth"
              :class="{hit:line.selected,clickable:true,'virt-alarm':virtualMode&&line.blocked}"
              @click="!moved&&emit('select-corridor',line)"/>
        <path v-for="line in corridors.filter(l=>l.detour)" :key="'d'+line.id" :d="line.detour"
              :stroke="virtualMode?'rgba(255,214,120,1)':'rgba(255,206,90,.9)'"
              :stroke-width="lineWidth*(virtualMode?2.4:1.3)" class="hit"
              @click="!moved&&emit('select-corridor',line)"/>
      </g>

      <!-- 6 节点 -->
      <g class="nmap-nodes">
        <g v-for="node in nodes" :key="'n'+node.name" @click="clickNode(node)">
          <circle v-if="node.external" :cx="node.x" :cy="node.y" :r="node.rank===1?3.4:2.4"
                  fill="none" stroke="rgba(160,200,235,.75)" stroke-width="1.1"/>
          <template v-else>
            <circle :cx="node.x" :cy="node.y" :r="node.rank===1?3.1:(node.rank===2?2.2:1.5)"
                    :fill="node.rank===3?'rgba(214,236,255,.55)':'#eaf6ff'"
                    :stroke="node.rank===3?'none':'rgba(8,20,32,.85)'" stroke-width=".55"/>
            <circle v-if="node.capital" :cx="node.x" :cy="node.y" r="5.8" fill="none"
                    stroke="rgba(186,218,255,.40)" stroke-width=".9"/>
            <circle v-if="node.weather&&node.weather.low" :cx="node.x" :cy="node.y" r="4.8"
                    fill="none" stroke="rgba(226,75,74,.92)" stroke-width="1"/>
          </template>
          <title>{{ node.name }}{{ node.capital?' · 省会/首府':'' }}{{ node.hasAirport?' · 机场 '+node.airport:' · 无机场（有专用接驳）' }}<template v-if="node.weather"> · {{ node.weather.tempC==null?'—':node.weather.tempC+' °C' }}</template></title>
        </g>
      </g>

      <!-- 7 航班：每架一个独立对象，点谁选谁 -->
      <g class="nmap-flights">
        <g v-for="f in flightDots" :key="f.id"
           :transform="`translate(${f.x.toFixed(1)} ${f.y.toFixed(1)}) rotate(${f.heading.toFixed(0)})`"
           @click.stop="!moved&&emit('select-flight',f)">
          <circle v-if="f.selected" r="9" fill="none" stroke="#8ef0ff" stroke-width="1.4" filter="url(#glow)"/>
          <path v-if="f.selected" d="M7 0 L-4 4 L-2 0 L-4 -4 Z" fill="#8ef0ff"
                stroke="rgba(10,30,45,.85)" stroke-width=".5"/>
          <template v-else>
            <path d="M6 0 L-3.4 3.2 L-1.7 0 L-3.4 -3.2 Z"
                  :fill="f.bad?'#ff8f6b':(f.status==='DELAYED'?'#ffc857':'#dff3ff')"
                  :stroke="f.bad?'rgba(90,20,10,.8)':'rgba(10,30,45,.8)'" stroke-width=".45"/>
          </template>
          <title>{{ f.callsign }} · {{ f.fromName }} → {{ f.toName }} · {{ f.altM }} m · {{ f.decisionLabel }}</title>
        </g>
      </g>

      <!-- 8 标注 -->
      <g class="nmap-labels">
        <text v-for="row in provinceLabels" :key="'p'+row.name" :x="row.x" :y="row.y-8"
              text-anchor="middle" class="prov">{{ row.name }}</text>
        <text v-for="node in labels" :key="'l'+node.name"
              :x="node.x+(node.x>VIEW.w-90?-5.5:5.5)" :y="node.y+3.2"
              :text-anchor="node.x>VIEW.w-90?'end':'start'" class="city">{{ node.short }}</text>
      </g>
    </g>
  </svg>
</div>
</template>

<style scoped>
.nmap{position:absolute;inset:0;border-radius:10px;overflow:hidden;
  background:radial-gradient(120% 90% at 50% 0%,#0b2033 0%,#061019 70%)}
.nmap svg{display:block;width:100%;height:100%;cursor:grab;transition:transform .45s ease}
.nmap svg.dragging{cursor:grabbing;transition:none}
.nmap.tilt svg{transform:perspective(1150px) rotateX(39deg) scale(1.2) translateY(3%);transform-origin:50% 82%}
.nmap-terrain{opacity:.13;filter:grayscale(1) brightness(.75) contrast(1.1)}
.nmap-terrain image{mix-blend-mode:screen}
.nmap .clickable{cursor:pointer}
.nmap path.hit{filter:drop-shadow(0 0 2px rgba(255,206,90,.55))}
.nmap path.virt-alarm{filter:drop-shadow(0 0 4px rgba(255,90,60,.85))}
.nmap .inset-lbl{font-size:8.5px;fill:rgba(170,205,230,.85)}
.nmap .prov{font-size:9px;letter-spacing:.6px;fill:rgba(158,196,224,.72);pointer-events:none}
.nmap .city{font-size:8.6px;fill:#dceefb;paint-order:stroke;stroke:rgba(4,12,20,.85);stroke-width:2.4px;pointer-events:none}
</style>
