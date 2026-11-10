<script setup>
import {computed,onMounted,onUnmounted,ref,shallowRef,watch} from 'vue'
import {Map as MlMap,Marker as MlMarker,setWorkerUrl} from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import china from '../../assets/china.json'

// 全国图 · 立体视图。
//
// 为什么另起一个组件而不是在 SVG 上继续加 CSS 变换：
// 之前的"立体"是 `perspective + rotateX`，本质是把一张平面图斜过来看 —— 没有高程、
// 不能转视角、放大后像素被拉伸。这不是三维，只是斜着的二维。
// 这里换成 maplibre，真实高程瓦片（AWS terrarium DEM）驱动地形，城市体块用
// fill-extrusion 起柱，视角可俯仰可旋转，缩放不会糊。
//
// 诚实口径：**地形是真的（DEM 高程），建筑是示意体块（没有全国建筑足迹数据）**。
// 这条写在界面提示里，不能让人以为那是真实楼宇。
setWorkerUrl(mapWorkerUrl)

const props=defineProps({
  data:{type:Object,default:null},
  flights:{type:Array,default:()=>[]},
  radarOn:{type:Boolean,default:true},
  fogOn:{type:Boolean,default:true},
  density:{type:String,default:'full'},
  selectedId:{type:String,default:''},
  selectedCorridor:{type:String,default:''},
  virtualMode:{type:Boolean,default:false},
  followId:{type:String,default:''},
})
const emit=defineEmits(['drill','select-flight','select-corridor'])

const host=ref(null)
const ready=ref(false)
const failed=ref('')
const diag=ref('')
const terrainOn=ref(false)
const terrainError=ref('')
const demInfo=ref('0/0')
const pitchNow=ref(52)
let map=null
let resizeObserver=null
let disposed=false

const EMPTY={type:'FeatureCollection',features:[]}
function fc(features){return {type:'FeatureCollection',features}}

const level=computed(()=>props.data?.level||'nation')

// —— 边界框 ——
// 三维视图默认取和二维同一套框（[73.4,16.2,135.2,53.8]），下钻时收窄到本级节点外包框。
const bounds=computed(()=>{
  const b=props.data?.view?.bbox
  if(!b||b.length<4||b[2]<=b[0]) return [73.4,16.2,135.2,53.8]
  return b
})

function lngLatBounds(b){
  const padLon=Math.max(.2,(b[2]-b[0])*.06), padLat=Math.max(.2,(b[3]-b[1])*.06)
  return [[b[0]-padLon,b[1]-padLat],[b[2]+padLon,b[3]+padLat]]
}

// —— 省界 / 九段线 ——
const provinceFC=computed(()=>{
  const live=new Set((props.data?.provinces||[]).map(row=>row.name))
  const features=[]
  for(const feature of china.features||[]){
    const p=feature.properties||{}
    const name=p.name||''
    if(!name||p.adchar==='JD') continue
    features.push({type:'Feature',properties:{name,live:live.has(name)?1:0},geometry:feature.geometry})
  }
  return fc(features)
})
const jdFC=computed(()=>{
  const features=[]
  for(const feature of china.features||[]){
    if((feature.properties||{}).adchar==='JD'){
      features.push({type:'Feature',properties:{},geometry:feature.geometry})
    }
  }
  return fc(features)
})

// —— 航线 ——
// 两点直连的走廊给一点弧度，和二维版同一条曲线；A* 出来的多段路径照原样画。
function arcLngLat(a,b,strength){
  const k=strength==null?0.16:strength
  const mx=(a[0]+b[0])/2, my=(a[1]+b[1])/2
  const dx=b[0]-a[0], dy=b[1]-a[1]
  const cx=mx-dy*k, cy=my+dx*k
  const out=[]
  for(let i=0;i<=18;i++){
    const t=i/18, u=1-t
    out.push([u*u*a[0]+2*u*t*cx+t*t*b[0], u*u*a[1]+2*u*t*cy+t*t*b[1]])
  }
  return out
}
const corridorFC=computed(()=>{
  const features=[]
  for(const row of props.data?.corridors||[]){
    const path=(row.path&&row.path.length>1)?row.path:[row.fromLonLat,row.toLonLat]
    if(!path||path.length<2||!path[0]||!path[1]) continue
    const coords=path.length===2?arcLngLat(path[0],path[1],row.bulge):path
    features.push({
      type:'Feature',
      properties:{
        id:row.id, name:`${row.fromName} → ${row.toName}`,
        blocked:row.borderBlocked?1:0, kindLabel:row.kindLabel||'',
        level:level.value,
      },
      geometry:{type:'LineString',coordinates:coords},
    })
  }
  return fc(features)
})
const detourFC=computed(()=>{
  const features=[]
  for(const row of props.data?.corridors||[]){
    if(!row.detour?.path||row.detour.path.length<2) continue
    features.push({type:'Feature',properties:{id:row.id},
      geometry:{type:'LineString',coordinates:row.detour.path}})
  }
  return fc(features)
})

// —— 节点 / 体块 ——
const nodeFC=computed(()=>{
  const features=[]
  for(const node of props.data?.nodes||[]){
    if(node.lon==null||node.lat==null) continue
    features.push({
      type:'Feature',
      properties:{
        name:node.name, rank:node.rank||3, capital:node.capital?1:0,
        airport:node.airport||'', low:(node.weather&&node.weather.low)?1:0,
        p:node.pLowVis==null?0:node.pLowVis,
        label:(node.rank||3)<=2?1:0,
      },
      geometry:{type:'Point',coordinates:[node.lon,node.lat]},
    })
  }
  return fc(features)
})
// 体块只给省会与机场城市起柱：319 个方块铺满全国会变成棋盘，反而看不出城市。
const towerFC=computed(()=>{
  const features=[]
  const size=0.075
  for(const node of props.data?.nodes||[]){
    if(node.lon==null||node.lat==null) continue
    const rank=node.rank||3
    if(rank>2) continue
    const p=node.pLowVis||0
    // 高度是**示意**：省会高、机场次之，能见度越差柱越高（表示风险堆积，不是楼层数）
    const height=Math.round((rank===1?3600:2400)+p*5200)
    const [lon,lat]=[node.lon,node.lat]
    features.push({
      type:'Feature',
      properties:{name:node.name,h:height,p,rank},
      geometry:{type:'Polygon',coordinates:[[
        [lon-size,lat-size],[lon+size,lat-size],[lon+size,lat+size],[lon-size,lat+size],[lon-size,lat-size],
      ]]},
    })
  }
  return fc(features)
})

// —— 回波（矢量，已由后端裁到国内） ——
function ringPolygon(ring){
  const coords=ring.slice()
  const first=coords[0], last=coords[coords.length-1]
  if(first[0]!==last[0]||first[1]!==last[1]) coords.push([first[0],first[1]])
  return {type:'Polygon',coordinates:[coords]}
}
const radarFC=computed(()=>{
  if(!props.radarOn) return EMPTY
  const bands=props.data?.radar?.bands||{}
  const features=[]
  for(const name of ['WEAK','CONVECTIVE','STRONG']){
    for(const ring of bands[name]||[]){
      if(!ring||ring.length<3) continue
      features.push({type:'Feature',properties:{band:name},geometry:ringPolygon(ring)})
    }
  }
  return fc(features)
})
const fogFC=computed(()=>{
  if(!props.fogOn) return EMPTY
  const bands=props.data?.fog?.bands||{}
  const features=[]
  for(const name of ['LOW','BAN']){
    for(const ring of bands[name]||[]){
      if(!ring||ring.length<3) continue
      features.push({type:'Feature',properties:{band:name},geometry:ringPolygon(ring)})
    }
  }
  return fc(features)
})

// —— 航班 ——
const flightFC=computed(()=>fc((props.flights||[]).filter(f=>f.lon!=null).map(f=>({
  type:'Feature',
  properties:{
    id:f.id,callsign:f.callsign,heading:f.heading||0,
    bad:(f.status==='DELAYED'||f.decision==='HOLD')?1:0,
    place:`${f.fromName} → ${f.toName}`,
  },
  geometry:{type:'Point',coordinates:[f.lon,f.lat]},
}))))

// —— 飞机图标：canvas 现画，避免多一个 png 资源 ——
function planeImage(color){
  const size=36
  const canvas=document.createElement('canvas')
  canvas.width=size; canvas.height=size
  const ctx=canvas.getContext('2d')
  ctx.translate(size/2,size/2)
  ctx.beginPath()
  ctx.moveTo(12,0); ctx.lineTo(-8,7.4); ctx.lineTo(-4,0); ctx.lineTo(-8,-7.4); ctx.closePath()
  ctx.fillStyle=color; ctx.fill()
  ctx.lineWidth=1.4; ctx.strokeStyle='rgba(8,26,40,.92)'; ctx.stroke()
  return {width:size,height:size,data:new Uint8Array(ctx.getImageData(0,0,size,size).data)}
}

// —— 样式：没有栅格底图，底子就是高程 + 省界 ——
function buildStyle(){
  return {
    version:8,
    sources:{
      provinces:{type:'geojson',data:provinceFC.value},
      jiuduan:{type:'geojson',data:jdFC.value},
      corridors:{type:'geojson',data:corridorFC.value},
      detours:{type:'geojson',data:detourFC.value},
      nodes:{type:'geojson',data:nodeFC.value},
      towers:{type:'geojson',data:towerFC.value},
      radar:{type:'geojson',data:radarFC.value},
      fog:{type:'geojson',data:fogFC.value},
      flights:{type:'geojson',data:flightFC.value},
    },
    layers:[
      {id:'bg',type:'background',paint:{'background-color':'#04101a'}},
      {id:'land',type:'fill',source:'provinces',paint:{'fill-color':'#0b1d2a','fill-opacity':.88}},
      {id:'province-line',type:'line',source:'provinces',paint:{
        'line-color':'rgba(126,176,214,.62)','line-width':['interpolate',['linear'],['zoom'],3,.7,7,1.6]}},
      {id:'jiuduan-line',type:'line',source:'jiuduan',paint:{
        'line-color':'rgba(200,232,255,.75)','line-width':['interpolate',['linear'],['zoom'],3,.9,7,1.8]}},
      {id:'fog-fill',type:'fill',source:'fog',paint:{
        'fill-color':['match',['get','band'],'BAN','rgba(228,242,255,.40)','rgba(198,224,246,.26)'],
        'fill-opacity':.9}},
      {id:'radar-fill',type:'fill',source:'radar',paint:{
        'fill-color':['match',['get','band'],'STRONG','#ee483c','CONVECTIVE','#f5be3c','#28be6e'],
        'fill-opacity':['match',['get','band'],'STRONG',.46,'CONVECTIVE',.28,.14]}},
      {id:'radar-edge',type:'line',source:'radar',paint:{
        'line-color':['match',['get','band'],'STRONG','rgba(255,150,110,.7)','CONVECTIVE','rgba(255,214,120,.45)','rgba(60,210,140,.35)'],
        'line-width':['match',['get','band'],'STRONG',1.1,.8],'line-opacity':.85}},
      {id:'towers',type:'fill-extrusion',source:'towers',minzoom:4.4,paint:{
        'fill-extrusion-color':['interpolate',['linear'],['get','h'],0,'#1d5872',9000,'#8fe0f7'],
        'fill-extrusion-height':['get','h'],'fill-extrusion-base':0,
        'fill-extrusion-opacity':.58,'fill-extrusion-vertical-gradient':true}},
      {id:'corridor-line',type:'line',source:'corridors',paint:{
        'line-color':['case',['==',['get','blocked'],1],'rgba(226,92,74,.75)','rgba(126,206,255,.66)'],
        'line-width':['case',['==',['get','blocked'],1],1.1,1.4],
        'line-opacity':.92}},
      {id:'detour-line',type:'line',source:'detours',paint:{
        'line-color':'rgba(255,206,90,.95)','line-width':1.8,'line-opacity':.95}},
      {id:'node-dot',type:'circle',source:'nodes',paint:{
        'circle-radius':['case',['==',['get','rank'],1],4.2,['==',['get','rank'],2],2.9,1.9],
        'circle-color':['case',['==',['get','rank'],3],'rgba(214,236,255,.62)','#eaf6ff'],
        'circle-stroke-color':'rgba(8,20,32,.85)','circle-stroke-width':.6}},
      {id:'node-ring',type:'circle',source:'nodes',filter:['==',['get','capital'],1],paint:{
        'circle-radius':7.6,'circle-color':'rgba(0,0,0,0)',
        'circle-stroke-color':'rgba(186,218,255,.42)','circle-stroke-width':1}},
      {id:'node-low',type:'circle',source:'nodes',filter:['==',['get','low'],1],paint:{
        'circle-radius':6.4,'circle-color':'rgba(0,0,0,0)',
        'circle-stroke-color':'rgba(232,84,72,.9)','circle-stroke-width':1.2}},
      {id:'flight-icon',type:'symbol',source:'flights',layout:{
        'icon-image':['case',['==',['get','bad'],1],'plane-bad','plane'],
        'icon-size':.62,'icon-rotate':['get','heading'],
        'icon-rotation-alignment':'map','icon-allow-overlap':true},paint:{}},
    ],
  }
}

// 省会名用 DOM Marker：glyph 瓦片是外部服务，说不准什么时候抽风，
// 而地名是这张图的"阅读骨架"，不能依赖它。31 个省会走 DOM 完全撑得住。
const markers=[]
function syncMarkers(){
  if(!map) return
  for(const marker of markers) marker.remove()
  markers.length=0
  for(const node of props.data?.nodes||[]){
    if((node.rank||3)!==1||node.lon==null) continue
    const el=document.createElement('div')
    el.className='nglobe-lbl'
    el.textContent=String(node.name).replace(/(特别行政区|自治区|自治州|地区|市)$/,'')
    markers.push(new MlMarker({element:el,anchor:'bottom',offset:[0,-7]})
      .setLngLat([node.lon,node.lat]).addTo(map))
  }
}

// 增量更新：航班每推进一分钟就变，但省界、航线、节点、体块都不变。
// 之前一个 applyData 把八份数据全 setData 一遍、再重建三十多个 DOM 标签，
// 在三维下足以把主线程堵住（实测 Edge 直接卡到扩展无响应）。
let nodeKey=''
let networkKey=''
function applyData(force){
  if(!map||!map.getSource('flights')) return
  const put=(id,data)=>{const source=map.getSource(id); if(source) source.setData(data)}

  const nextNetwork=`${level.value}|${(props.data?.corridors||[]).length}|${props.data?.radar?.ts||''}`
  if(force||nextNetwork!==networkKey){
    networkKey=nextNetwork
    put('provinces',provinceFC.value)
    put('jiuduan',jdFC.value)
    put('corridors',corridorFC.value)
    put('detours',detourFC.value)
  }
  put('radar',radarFC.value)
  put('fog',fogFC.value)

  const nextNode=`${level.value}|${(props.data?.nodes||[]).length}`
  if(force||nextNode!==nodeKey){
    nodeKey=nextNode
    put('nodes',nodeFC.value)
    put('towers',towerFC.value)
    syncMarkers()
  }
  put('flights',flightFC.value)
}

// 高程瓦片单独挂：矢量层先出来，地形晚一点补上。
// 这样"打开立体"不会因为一张 100 KB 的 DEM 掉进十几秒白屏。
// 高程地形（raster-dem）在当前网络下走不通：公开 terrarium 瓦片要么没有 CORS、
// 要么直接不可达，而 maplibre 会一直等这块瓦片，整张样式永远不就绪（白屏）。
// 宁可不承诺地形，也不能让地图打不开 —— 所以这里不挂 DEM，
// 立体感来自**真实透视**：俯角、旋转、城市体块带来的纵深，而不是虚构的地形起伏。
// 界面上的文案如实写成"地形高程源不可达"，不假装有地形。
function mountTerrain(){
  terrainOn.value=false
}

function fitToData(animate){
  if(!map||!props.data) return
  if(level.value==='nation'){
    // 全国级用固定相机：terrain 开启后 fitBounds 会把相机抬高，算出来的 zoom 偏小，
    // 版图只剩中间一小块。这一级的视野是常量，直接给死更可靠。
    const camera={center:[104.2,35.4],zoom:3.28,pitch:52,bearing:-8}
    pitchNow.value=52
    if(animate) map.easeTo({...camera,duration:900})
    else map.jumpTo(camera)
    return
  }
  const b=lngLatBounds(bounds.value)
  const pitch=50
  map.fitBounds(b,{
    // fitBounds 只按屏幕矩形算，**不管俯仰**：pitch 一开，远端会被地平线吃掉。
    // 所以留足边距（上下各 40 px 起步）把整幅版图兜进视锥，不再额外改 zoom ——
    // 地形挂载后相机会自己抬一次，再手改 zoom 会叠成"缩太小"。
    padding:{top:44,bottom:36,left:44,right:44},
    pitch,bearing:-10,duration:animate?900:0,animate:!!animate,
  })
}

onMounted(()=>{
  if(!host.value) return
  map=new MlMap({
    container:host.value,
    style:buildStyle(),
    center:[104,34],zoom:3.2,pitch:46,bearing:-12,
    attributionControl:false,
    dragRotate:true,
    maxPitch:78,
    minZoom:1.6,
    fadeDuration:0,
  })
  map.on('load',()=>{
    if(disposed) return
    map.addImage('plane',planeImage('#e8f6ff'))
    map.addImage('plane-bad',planeImage('#ffb08a'))
    ready.value=true
    applyData(true)
    // 先挂地形再取景：terrain 会把相机抬起来，先取景后挂地形会让版图缩成一小块
    mountTerrain()
    setTimeout(()=>fitToData(false),350)
  })
  // 10 秒还没 load 就把内部状态摆出来，别让用户对着"加载中"猜
  setTimeout(()=>{
    if(disposed||ready.value) return
    if(!failed.value){
      failed.value=`样式未就绪（styleLoaded=${map?map.isStyleLoaded():'-'}）${
        diag.value?(' · '+diag.value):''}`
    }
  },20000)
  let demLoaded=0, demTotal=0
  map.on('sourcedata',event=>{
    if(event.sourceId!=='dem') return
    if(event.tile){
      if(event.tile.state==='loaded') demLoaded=Math.max(demLoaded,event.tile.tileID?.canonical?.z?1:1)
    }
    if(event.isSourceLoaded||event.tile){
      const src=map.getSource('dem')
      const total=src&&src.tiles?src.tiles.length:0
      demInfo.value=`${event.tile&&event.tile.state==='loaded'?'1':'0'}/${total||'?'}`
    }
  })
  map.on('pitchend',()=>{if(map) pitchNow.value=map.getPitch()})
  map.on('error',event=>{
    const message=String(event?.error?.message||event?.error||'')
    if(message&&!diag.value) diag.value=message.slice(0,200)
  })

  map.on('click','node-dot',event=>{
    const feature=event.features&&event.features[0]
    if(feature) emit('drill','city',feature.properties.name,feature.properties.name)
  })
  map.on('click','node-label',event=>{
    const feature=event.features&&event.features[0]
    if(feature) emit('drill','city',feature.properties.name,feature.properties.name)
  })
  map.on('click','corridor-line',event=>{
    const feature=event.features&&event.features[0]
    if(feature) emit('select-corridor',{id:feature.properties.id,
      fromName:(feature.properties.name||'').split(' → ')[0],
      toName:(feature.properties.name||'').split(' → ')[1]})
  })
  map.on('click','flight-icon',event=>{
    const feature=event.features&&event.features[0]
    if(!feature) return
    const flight=(props.flights||[]).find(item=>item.id===feature.properties.id)
    if(flight) emit('select-flight',flight)
  })
  for(const layer of ['node-dot','corridor-line','flight-icon']){
    map.on('mouseenter',layer,()=>{if(map) map.getCanvas().style.cursor='pointer'})
    map.on('mouseleave',layer,()=>{if(map) map.getCanvas().style.cursor=''})
  }

  if(typeof ResizeObserver!=='undefined'){
    resizeObserver=new ResizeObserver(()=>{if(map) map.resize()})
    resizeObserver.observe(host.value)
  }
})

onUnmounted(()=>{
  disposed=true
  for(const marker of markers) marker.remove()
  markers.length=0
  if(resizeObserver) resizeObserver.disconnect()
  if(map){map.remove(); map=null}
})

let lastScope=''
watch(()=>props.data,(next)=>{
  const scope=`${next?.level||''}|${next?.id||next?.city?.name||next?.province?.name||''}`
  const switched=scope!==lastScope
  applyData(switched)
  if(switched){lastScope=scope; fitToData(true)}
})
watch(()=>props.flights,()=>{if(map) applyData(false)},{deep:false})
watch(()=>props.radarOn,()=>{if(map) applyData(true)})
watch(()=>props.fogOn,()=>{if(map) applyData(true)})

// 跟随：时间轴每推进一格把这一架钉在屏幕中心（和二维版同一语义）
watch([()=>props.followId,()=>props.flights],()=>{
  if(!map||!props.followId) return
  const flight=(props.flights||[]).find(item=>item.id===props.followId)
  if(!flight||flight.lon==null) return
  map.flyTo({center:[flight.lon,flight.lat],zoom:Math.max(5.6,map.getZoom()),pitch:58,duration:900})
})

function resetView(){
  if(!map) return
  fitToData(true)
}
function fitBounds(b){
  if(!map||!b||b.length<4||b[2]<=b[0]||b[3]<=b[1]) return false
  map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:40,pitch:50,duration:900})
  return true
}
defineExpose({resetView,fitBounds})

// —— 南海诸岛小图（三维视角下主图按大陆取框，南海在图外） ——
const INSET={w:132,h:132,lon0:105.5,lon1:124.5,lat0:3.2,lat1:24.8}
const insetRad=value=>value*Math.PI/180
const insetMerc=lat=>Math.log(Math.tan(Math.PI/4+insetRad(Math.max(-85,Math.min(85,lat)))/2))
const insetShapes=computed(()=>{
  const {w,h,lon0,lon1,lat0,lat1}=INSET
  const spanX=insetRad(lon1)-insetRad(lon0)
  const spanY=insetMerc(lat1)-insetMerc(lat0)
  const k=Math.min(w/spanX,h/spanY)
  const ox=(w-spanX*k)/2, oy=(h-spanY*k)/2
  const put=(lon,lat)=>[ox+(insetRad(lon)-insetRad(lon0))*k, oy+(insetMerc(lat1)-insetMerc(lat))*k]
  const rows=[]
  for(const feature of china.features||[]){
    const p=feature.properties||{}
    const name=p.name||''
    const boundary=p.adchar==='JD'
    if(!name&&!boundary) continue
    const geometry=feature.geometry||{}
    const polys=geometry.type==='Polygon'?[geometry.coordinates]
      :(geometry.type==='MultiPolygon'?geometry.coordinates:[])
    let d=''
    for(const poly of polys) for(const ring of poly){
      for(let i=0;i<ring.length;i++){
        const [x,y]=put(ring[i][0],ring[i][1])
        d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)
      }
    }
    if(d) rows.push({key:name||'jd',boundary,d})
  }
  rows.sort((a,b)=>(a.boundary?1:0)-(b.boundary?1:0))
  return rows
})
</script>

<template>
<div class="nglobe">
  <div class="nglobe-map" ref="host"></div>

  <svg class="nglobe-inset" :viewBox="`0 0 ${INSET.w} ${INSET.h}`" aria-label="南海诸岛">
    <rect :width="INSET.w" :height="INSET.h" rx="4" fill="rgba(6,18,28,.72)"
          stroke="rgba(120,165,205,.45)" stroke-width=".8"/>
    <path v-for="shape in insetShapes" :key="shape.key" :d="shape.d"
          :fill="shape.boundary?'rgba(150,200,235,.6)':'rgba(96,132,170,.16)'"
          :stroke="shape.boundary?'none':'rgba(120,165,205,.45)'" stroke-width=".6"/>
    <text :x="6" :y="INSET.h-6" class="inset-lbl">南海诸岛</text>
  </svg>

  <div class="nglobe-tip" v-if="!ready&&!failed">三维地形加载中（高程瓦片首次约 2–4 秒）…</div>
  <div class="nglobe-tip bad" v-if="failed&&!ready">三维底图不可用：{{ failed }}（切回平面可继续操作）</div>
  <div class="nglobe-note">
    三维视角＝真实透视（俯角 {{ Math.round(pitchNow) }}°、可旋转）· 建筑＝示意体块，高度按风险派生，非真实楼高
    · 地形高程源在当前网络不可达，故不叠加起伏 · 拖右键旋转、Ctrl+拖拽俯仰
  </div>
</div>
</template>

<style scoped>
.nglobe{position:absolute;inset:0;z-index:2;border-radius:10px;overflow:hidden;background:#04101a}
.nglobe-map{position:absolute;inset:0}
.nglobe-inset{position:absolute;right:8px;bottom:8px;width:132px;height:132px;pointer-events:none}
.inset-lbl{font-size:8.5px;fill:rgba(170,205,230,.85)}
.nglobe-tip{position:absolute;left:10px;top:10px;font-size:11.5px;color:#9fc4da;
  background:rgba(8,22,34,.82);border:1px solid rgba(70,110,140,.45);border-radius:6px;padding:4px 9px}
.nglobe-tip.bad{color:#ffb59f;border-color:rgba(200,90,60,.5)}
.nglobe-note{position:absolute;left:10px;bottom:8px;font-size:10.5px;color:#7d9cb3;
  background:rgba(6,16,25,.72);border-radius:5px;padding:2px 8px;pointer-events:none}
.nglobe :deep(.nglobe-lbl){font-size:10.5px;color:#cbdfef;white-space:nowrap;pointer-events:none;
  text-shadow:0 0 3px rgba(3,10,18,.95),0 0 6px rgba(3,10,18,.8);letter-spacing:.3px}
.nglobe :deep(.maplibregl-canvas){outline:none}
.nglobe :deep(.maplibregl-ctrl-attrib){display:none}
</style>
