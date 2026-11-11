<script setup>
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {Map as MlMap,Marker as MlMarker,setWorkerUrl} from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import china from '../../assets/china.json'
import {probeGPU,gpuLabel,startFpsWatch} from '../../traffic/gpu.js'
import {mapPalette} from '../../theme.js'

// 全国图 · 三维视图（真实透视，不是把平面图斜过来）。
//
// 为什么另起一个组件而不是在 SVG 上加 CSS 变换：之前的"立体"是
// `perspective + rotateX`，没有视差、没有高程、放大后像素被拉伸 —— 那是斜着的二维。
// 这里用 maplibre 的真透视：俯角可调、可旋转、省界与航路按真实经纬度铺开、
// 省/市层挂 raster-dem 地形。
//
// 四条护栏（V1.0.1 两次把 Edge 拖死的直接教训，缺一条就会重演）：
//   ① 能力探测：软件渲染（SwiftShader/llvmpipe）一律不进来，由父组件退回倾斜视图；
//   ② 要素按层级裁剪：全国层只给 31 个省会起柱，不给 319 个城市铺方块；
//   ③ 帧率看门狗：连续 3 秒 < 20 fps 就回调父组件降级，不在卡死里耗；
//   ④ DEM 只在省/市层挂：全国层的高程起伏在屏幕上不到 2 px，纯耗带宽。
//
// 诚实口径：**地形是真的（DEM），净空柱是规则化生成的几何（DERIVED）且垂直放大 10 倍**。
// 曾经给每个城市起过体块柱，但全国缩放下它只是一片半透明方块，读者会当成 UI 残影 ——
// 于是全部撤掉，城市只用点+环标记。
setWorkerUrl(mapWorkerUrl)

const props=defineProps({
  data:{type:Object,default:null},
  flights:{type:Array,default:()=>[]},
  radarOn:{type:Boolean,default:true},
  fogOn:{type:Boolean,default:true},
  density:{type:String,default:'full'},
  selectedId:{type:String,default:''},
  // 本地连续时刻：与二维图共用同一个推进量，两个视图对"这一架现在在哪"必须给同一个答案
  frameMinute:{type:Number,default:-1},
  minute:{type:Number,default:0},
  selectedCorridor:{type:String,default:''},
  virtualMode:{type:Boolean,default:false},
  followId:{type:String,default:''},
  // 净空几何（bands.LIMIT / bands.RUNWAY），由父组件按需取；没给就不画
  zones:{type:Object,default:null},
  // 'ops' = 运行视角（看航线与班次）| 'airspace' = 空域视角（看净空边界）
  audience:{type:String,default:'ops'},
})
const emit=defineEmits(['drill','select-flight','select-corridor','degrade','unsupported','fps'])

const host=ref(null)
const ready=ref(false)
const failed=ref('')
const diag=ref('')
const terrainOn=ref(false)
const demInfo=ref('')
const pitchNow=ref(52)
const fpsNow=ref(0)
const gpu=probeGPU()
let map=null
let resizeObserver=null
let disposed=false
let watchdog=null

const EMPTY={type:'FeatureCollection',features:[]}
function fc(features){return {type:'FeatureCollection',features}}

const level=computed(()=>props.data?.level||'nation')

// —— 边界框 ——
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
  // 全国层不画航线：492 条线在这个缩放下只有 20–40 px，是蜘蛛网不是信息。
  // 与二维图保持同一口径 —— 两个视图对同一件事必须给同一个答案。
  if(level.value==='nation') return EMPTY
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

// —— 节点 ——
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
      },
      geometry:{type:'Point',coordinates:[node.lon,node.lat]},
    })
  }
  return fc(features)
})

// —— 回波 / 雾区（矢量，已由后端裁到国内） ——
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

// —— 净空（DERIVED）：省/市层立起来，这是三维里最有说服力的一层 ——
// "绕开机场"在平面上是两条线，在三维里是一根柱子 + 一条绕开它的弧。
// 垂直方向放大 10 倍才看得见（8 km 的圈立 800 m，屏幕上不到 1 px）。
const ZONE_EXAGGERATION=10
const zoneFC=computed(()=>{
  const bands=props.zones?.bands||{}
  const out=[]
  const show=props.audience==='airspace'||level.value==='province'||level.value==='city'
  if(!show) return EMPTY
  const b=bounds.value
  const inside=(ring)=>{
    for(const [lon,lat] of ring||[]){
      if(lon>=b[0]-1.2&&lon<=b[2]+1.2&&lat>=b[1]-1.2&&lat<=b[3]+1.2) return true
    }
    return false
  }
  const push=(rows,kind)=>{
    let count=0
    for(const ring of rows||[]){
      if(!ring||ring.length<3) continue
      if(level.value!=='nation'&&!inside(ring)) continue
      if(count>=120) break
      count+=1
      out.push({type:'Feature',properties:{kind,h:kind==='LIMIT'?9000:0},geometry:ringPolygon(ring)})
    }
  }
  push(bands.LIMIT,'LIMIT')
  push(bands.RUNWAY,'RWY')
  return fc(out)
})
const zonePolicy=computed(()=>String(props.zones?.policy||'APPROVAL_REQUIRED'))

// —— 航班 ——
// 选中班次的航线：全国层平时不画航线，这一条是例外（与二维图同口径）。
// 点哪一架，就把那一条从起点到终点摊出来。
const pickedFC=computed(()=>{
  const f=(props.flights||[]).find(x=>x.id===props.selectedId)
  if(!f) return EMPTY
  const row=(props.data?.corridors||[]).find(c=>c.id===f.corridor)
  let path=(row?.path&&row.path.length>1)?row.path:null
  if(!path&&f.fromLonLat&&f.toLonLat) path=[f.fromLonLat,f.toLonLat]
  if(!path||path.length<2) return EMPTY
  const coords=path.length===2?arcLngLat(path[0],path[1],row?.bulge):path
  return fc([
    {type:'Feature',properties:{kind:'route'},geometry:{type:'LineString',coordinates:coords}},
    {type:'Feature',properties:{kind:'end'},geometry:{type:'Point',coordinates:path[0]}},
    {type:'Feature',properties:{kind:'end'},geometry:{type:'Point',coordinates:path[path.length-1]}},
  ])
})

const flightFC=computed(()=>fc((props.flights||[])
  // 延期（HOLD）的班次还没起飞，不画
  .filter(f=>f.lon!=null&&f.decision!=='HOLD')
  .map(f=>({
  type:'Feature',
  properties:{
    id:f.id,callsign:f.callsign,heading:f.heading||0,
    // 绕飞用颜色标（琥珀），停飞/应急才换图标
    detour:f.status==='DELAYED'?1:0,
    detail:`${f.fromName} → ${f.toName} · ${f.decisionLabel}`,
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

// —— 样式 ——
function buildStyle(){
  // 调色板：深/浅两套，paint 只能吃具体颜色，所以从 theme.js 取
  const PAL=mapPalette()
  const zoneColor=zonePolicy.value==='PROHIBITED'
    ?['match',['get','kind'],'LIMIT','rgba(226,74,58,.62)','rgba(226,120,74,.5)']
    :['match',['get','kind'],'LIMIT','rgba(245,190,60,.42)','rgba(245,190,60,.28)']
  return {
    version:8,
    sources:{
      provinces:{type:'geojson',data:provinceFC.value},
      jiuduan:{type:'geojson',data:jdFC.value},
      corridors:{type:'geojson',data:corridorFC.value},
      detours:{type:'geojson',data:detourFC.value},
      nodes:{type:'geojson',data:nodeFC.value},
      radar:{type:'geojson',data:radarFC.value},
      fog:{type:'geojson',data:fogFC.value},
      zones:{type:'geojson',data:zoneFC.value},
      flights:{type:'geojson',data:flightFC.value},
      picked:{type:'geojson',data:pickedFC.value},
    },
    layers:[
      {id:'bg',type:'background',paint:{'background-color':PAL.background}},
      {id:'land',type:'fill',source:'provinces',paint:{'fill-color':PAL.land,'fill-opacity':PAL.landOpacity}},
      {id:'province-line',type:'line',source:'provinces',paint:{
        'line-color':PAL.provinceLine,'line-width':['interpolate',['linear'],['zoom'],3,.7,7,1.6]}},
      {id:'jiuduan-line',type:'line',source:'jiuduan',paint:{
        'line-color':PAL.boundaryLine,'line-width':['interpolate',['linear'],['zoom'],3,.9,7,1.8]}},
      {id:'fog-fill',type:'fill',source:'fog',paint:{
        'fill-color':['match',['get','band'],'BAN','rgba(228,242,255,.40)','rgba(198,224,246,.26)'],
        'fill-opacity':.9}},
      {id:'radar-fill',type:'fill',source:'radar',paint:{
        'fill-color':['match',['get','band'],'STRONG','#ee483c','CONVECTIVE','#f5be3c','#28be6e'],
        'fill-opacity':['match',['get','band'],'STRONG',.46,'CONVECTIVE',.28,.14]}},
      {id:'radar-edge',type:'line',source:'radar',paint:{
        'line-color':['match',['get','band'],'STRONG','rgba(255,150,110,.7)','CONVECTIVE','rgba(255,214,120,.45)','rgba(60,210,140,.35)'],
        'line-width':['match',['get','band'],'STRONG',1.1,.8],'line-opacity':.85}},
      {id:'zone-wall',type:'fill-extrusion',source:'zones',paint:{
        'fill-extrusion-color':zoneColor,
        'fill-extrusion-height':['get','h'],'fill-extrusion-base':0,
        'fill-extrusion-opacity':.5,'fill-extrusion-vertical-gradient':true}},
      {id:'zone-ring',type:'line',source:'zones',paint:{
        'line-color':zonePolicy.value==='PROHIBITED'?'rgba(255,120,90,.8)':'rgba(255,208,120,.6)',
        'line-width':.8,'line-opacity':.7},
       layout:{'line-join':'round'}},
      {id:'corridor-line',type:'line',source:'corridors',paint:{
        'line-color':['case',['==',['get','blocked'],1],PAL.corridorBlocked,PAL.corridor],
        'line-width':['case',['==',['get','blocked'],1],1.1,1.4],
        'line-opacity':.92}},
      {id:'detour-line',type:'line',source:'detours',paint:{
        'line-color':PAL.detour,'line-width':1.8,'line-opacity':.95}},
      {id:'node-dot',type:'circle',source:'nodes',paint:{
        'circle-radius':['case',['==',['get','rank'],1],4.2,['==',['get','rank'],2],2.9,1.9],
        'circle-color':['case',['==',['get','rank'],3],PAL.nodeDim,PAL.node],
        'circle-stroke-color':PAL.nodeStroke,'circle-stroke-width':.6}},
      {id:'node-ring',type:'circle',source:'nodes',filter:['==',['get','capital'],1],paint:{
        'circle-radius':7.6,'circle-color':'rgba(0,0,0,0)',
        'circle-stroke-color':PAL.capitalRing,'circle-stroke-width':1}},
      {id:'node-low',type:'circle',source:'nodes',filter:['==',['get','low'],1],paint:{
        'circle-radius':6.4,'circle-color':'rgba(0,0,0,0)',
        'circle-stroke-color':'rgba(232,84,72,.9)','circle-stroke-width':1.2}},
      {id:'picked-line',type:'line',source:'picked',
       filter:['==',['get','kind'],'route'],paint:{
        'line-color':'#8ef0ff','line-width':2.2,'line-opacity':.95}},
      {id:'picked-end',type:'circle',source:'picked',
       filter:['==',['get','kind'],'end'],paint:{
        'circle-radius':5,'circle-color':'#8ef0ff',
        'circle-stroke-color':'#06202c','circle-stroke-width':1.2}},
    ],
  }
}
// 航班层单独建：图标是 canvas 现画的，必须**先 addImage 再加层**。
// 把 symbol 层写在 style.layers 里会让 maplibre 在样式编译阶段就去取图标，
// 那时还没 addImage，于是先刷一条 "Image could not be loaded" —— 功能不受影响，
// 但控制台里会被当成真错误。层后置就彻底没有这个顺序问题。
const FLIGHT_LAYER={
  id:'flight-icon',type:'symbol',source:'flights',layout:{
    'icon-image':['case',['==',['get','bad'],1],'plane-bad','plane'],
    'icon-size':.62,'icon-rotate':['get','heading'],
    'icon-rotation-alignment':'map','icon-allow-overlap':true},paint:{},
}

// 地名用 DOM Marker：glyph 瓦片是外部服务，说不准什么时候抽风，
// 而地名是这张图的"阅读骨架"，不能依赖它。
// 但也不能全省都挂 —— 省层 15 个名字会糊成一团，所以省级只标 rank<=2。
const markers=[]
function syncMarkers(){
  if(!map) return
  for(const marker of markers) marker.remove()
  markers.length=0
  const all=props.data?.nodes||[]
  const limit=level.value==='nation'?1:2
  let count=0
  for(const node of all){
    if(node.lon==null) continue
    const rank=node.rank||3
    if(rank>limit) continue
    if(count>=40) break
    count+=1
    const el=document.createElement('div')
    el.className='nglobe-lbl'
    el.textContent=String(node.name).replace(/(特别行政区|自治区|自治州|地区|市)$/,'')
    markers.push(new MlMarker({element:el,anchor:'bottom',offset:[0,-7]})
      .setLngLat([node.lon,node.lat]).addTo(map))
  }
}

// —— DEM：只在省/市层挂 ——
// 全国层地形起伏在屏幕上不到 2 px，挂了只是多拉十几张瓦片。
// terrarium 瓦片是可用的（实测 200 / 88 KB），但 maxzoom 压到 6，别为一座山拉上千张图。
function mountTerrain(want){
  if(!map||!map.isStyleLoaded()) return
  const near=want&&(level.value==='province'||level.value==='city')
  if(near===terrainOn.value) return
  if(!near){
    try{map.setTerrain(null)}catch(e){}
    terrainOn.value=false
    demInfo.value=''
    return
  }
  try{
    if(!map.getSource('dem')){
      map.addSource('dem',{
        type:'raster-dem',
        tiles:['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
        encoding:'terrarium',
        tileSize:256,
        maxzoom:6,
        attribution:'高程：Mapzen/Amazon Terrain Tiles（terrarium）',
      })
    }
    map.setTerrain({source:'dem',exaggeration:1.35})
    terrainOn.value=true
    demInfo.value='DEM z≤6'
  }catch(e){
    // 高程源挂了不能连累矢量层：三维照样看，只是不起伏
    terrainOn.value=false
    demInfo.value='地形不可用'
  }
}

// 增量更新：航班每分钟都变，但省界、航线、节点不变。
// 一个 applyData 把九份数据全 setData 一遍，在三维下足以把主线程堵住。
let nodeKey=''
let networkKey=''
let zoneKey=''
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

  const nextZone=`${level.value}|${props.audience}|${(props.zones?.bands?.LIMIT||[]).length}`
  if(force||nextZone!==zoneKey){
    zoneKey=nextZone
    put('zones',zoneFC.value)
  }

  const nextNode=`${level.value}|${(props.data?.nodes||[]).length}`
  if(force||nextNode!==nodeKey){
    nodeKey=nextNode
    put('nodes',nodeFC.value)
    syncMarkers()
  }
  put('flights',flightFC.value)
  put('picked',pickedFC.value)
}

function fitToData(animate){
  if(!map||!props.data) return
  if(level.value==='nation'){
    // 全国级用固定相机：fitBounds 会把相机抬高，算出来的 zoom 偏小，
    // 版图只剩中间一小块。这一级的视野是常量，直接给死更可靠。
    // padding.bottom：地图下方压着「越界监视」与图例两条浮层（约 80 px），
    // 不给这块内边距，海南与南海诸岛正好被它们盖住。
    const camera={center:[104.2,34.9],zoom:3.5,pitch:52,bearing:-8,padding:{top:0,bottom:92,left:0,right:0}}
    pitchNow.value=52
    if(animate) map.easeTo({...camera,duration:900})
    else map.jumpTo(camera)
    return
  }
  const b=lngLatBounds(bounds.value)
  // 关键：**不能用 fitBounds**。它只按屏幕矩形算，完全不管俯仰 ——
  // pitch 一开，屏幕上能装下的地面范围会缩小，fitBounds 给出的 zoom 仍是平面的，
  // 结果就是"整幅图缩在画面上半部分那一小块"。`cameraForBounds` 会把 bearing/pitch
  // 一起算进去，返回真正装得下的相机。
  const camera=map.cameraForBounds(b,{
    // 下边多留 96 px：地图底部压着「越界监视」和图层图例两条浮层，
    // 不留给它们，整幅图的下缘正好被盖住。
    padding:{top:20,bottom:96,left:30,right:30},
    bearing:-10,pitch:50,
  })
  if(camera){
    if(animate) map.easeTo({...camera,bearing:-10,pitch:50,duration:900})
    else map.jumpTo({...camera,bearing:-10,pitch:50})
    pitchNow.value=50
    return
  }
  map.fitBounds(b,{
    padding:{top:44,bottom:36,left:44,right:44},
    pitch:50,bearing:-10,duration:animate?900:0,animate:!!animate,
  })
}

// 主题切换：只改 paint，不重建样式 —— 重建会丢图层顺序与相机，还会闪一帧白
function applyPalette(){
  if(!map) return
  const PAL=mapPalette()
  const set=(layer,prop,value)=>{try{if(map.getLayer(layer)) map.setPaintProperty(layer,prop,value)}catch(_){}}
  set('bg','background-color',PAL.background)
  set('land','fill-color',PAL.land)
  set('land','fill-opacity',PAL.landOpacity)
  set('province-line','line-color',PAL.provinceLine)
  set('jiuduan-line','line-color',PAL.boundaryLine)
  set('node-dot','circle-color',['case',['==',['get','rank'],3],PAL.nodeDim,PAL.node])
  set('node-dot','circle-stroke-color',PAL.nodeStroke)
  set('node-ring','circle-stroke-color',PAL.capitalRing)
  set('corridor-line','line-color',['case',['==',['get','blocked'],1],PAL.corridorBlocked,PAL.corridor])
  set('detour-line','line-color',PAL.detour)
}

function applyAudience(){
  if(!map) return
  const air=props.audience==='airspace'
  // 空域视角看的是"哪些点禁飞、边界在哪"，在飞的班次先让开（不是删掉，是隐藏）
  for(const [id,visible] of [['flight-icon',!air],['detour-line',!air]]){
    if(map.getLayer(id)) map.setLayoutProperty(id,'visibility',visible?'visible':'none')
  }
  if(map.getLayer('corridor-line')){
    map.setPaintProperty('corridor-line','line-opacity',air?.42:.92)
  }
  if(map.getLayer('zone-wall')){
    map.setPaintProperty('zone-wall','fill-extrusion-opacity',air?.62:.45)
  }
}

onMounted(()=>{
  if(!host.value) return
  // ① 能力探测。软件渲染直接不建 map —— 建了就是给主线程上刑。
  if(!gpu.ok){
    failed.value=gpu.reason||'本机 WebGL 不可用'
    emit('unsupported',gpu)
    return
  }
  // 飞机图标是运行时画出来的，样式里的 symbol 层在 'load' 之前就引用了它们。
  // 只靠 load 里 addImage 会先报一次 "Image could not be loaded"（虽然之后能补上）。
  // 用 styleimagemissing 按需补，才是顺序安全做法 —— 但必须在 map 建好之后再挂。
  map=new MlMap({
    container:host.value,
    style:buildStyle(),
    center:[104,34],zoom:3.2,pitch:46,bearing:-12,
    attributionControl:false,
    dragRotate:true,
    maxPitch:78,
    minZoom:1.6,
    fadeDuration:0,
    refreshExpiredTiles:false,
    maxTileCacheSize:96,
    // 软件渲染下 MSAA 是纯浪费；这里也不是写实渲染，关掉更稳
    antialias:false,
    pixelRatio:Math.min(typeof window!=='undefined'?(window.devicePixelRatio||1):1,1.5),
  })
  map.on('styleimagemissing',event=>{
    if(disposed||!map) return
    if(event.id==='plane'&&!map.hasImage('plane')) map.addImage('plane',planeImage('#e8f6ff'))
    if(event.id==='plane-detour'&&!map.hasImage('plane-detour')) map.addImage('plane-detour',planeImage('#ffc857'))
  })
  // maplibre 6 在样式编译阶段就会去取图标，比 styleimagemissing 更早；
  // 官方给的入口是 setMissingStyleImageResolver —— 用它才不会先刷一条警告。
  if(typeof map.setMissingStyleImageResolver==='function'){
    map.setMissingStyleImageResolver(id=>{
      if(id==='plane') return planeImage('#e8f6ff')
      if(id==='plane-detour') return planeImage('#ffc857')
      return null
    })
  }
  map.on('load',()=>{
    if(disposed) return
    if(!map.hasImage('plane')) map.addImage('plane',planeImage('#e8f6ff'))
    if(!map.hasImage('plane-detour')) map.addImage('plane-detour',planeImage('#ffc857'))
    if(!map.getLayer('flight-icon')) map.addLayer(FLIGHT_LAYER)
    ready.value=true
    applyData(true)
    applyPalette()
    applyAudience()
    // 先挂地形再取景：terrain 会把相机抬起来，先取景后挂地形会让版图缩成一小块
    mountTerrain(true)
    setTimeout(()=>fitToData(false),350)
    // ③ 帧率看门狗：宽限期 2.5 s（样式编译/瓦片解码会掉帧），之后连续 3 秒 <20 fps 就降级
    if(watchdog) watchdog.stop()
    watchdog=startFpsWatch({
      threshold:20,seconds:3,grace:2500,
      onSample:(fps)=>{
        fpsNow.value=fps
        emit('fps',fps)
        // 省/市层第一次进山，掉帧了就先把地形摘掉再试一次（地形是最大开销）
        if(fps<20&&terrainOn.value) mountTerrain(false)
      },
      onLow:(fps)=>{
        emit('degrade',{fps,gpu})
      },
    })
  })
  // 样式编译失败的表现很误导：不报错、不白屏，只是 'load' 永不触发，
  // 界面一直停在"初始化"。所以 6 秒还没就绪且有样式类错误，就直接说出来。
  setTimeout(()=>{
    if(disposed||ready.value||failed.value) return
    if(diag.value&&/style|expression|layer|paint|layout|filter/i.test(diag.value)){
      failed.value=`样式未通过校验：${diag.value}`
    }
  },6000)
  // 20 秒还没 load 就把内部状态摆出来，别让用户对着"加载中"猜
  setTimeout(()=>{
    if(disposed||ready.value) return
    if(!failed.value){
      failed.value=`样式未就绪（styleLoaded=${map?map.isStyleLoaded():'-'}）${
        diag.value?(' · '+diag.value):''}`
    }
  },20000)
  map.on('pitchend',()=>{if(map) pitchNow.value=map.getPitch()})
  map.on('error',event=>{
    const message=String(event?.error?.message||event?.error||'')
    if(message&&!diag.value) diag.value=message.slice(0,200)
  })

  map.on('click','node-dot',event=>{
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

  window.addEventListener('alc-theme',applyPalette)
  if(typeof ResizeObserver!=='undefined'){
    resizeObserver=new ResizeObserver(()=>{if(map) map.resize()})
    resizeObserver.observe(host.value)
  }
})

onUnmounted(()=>{
  disposed=true
  window.removeEventListener('alc-theme',applyPalette)
  if(watchdog) watchdog.stop()
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
  if(switched){lastScope=scope; fitToData(true); mountTerrain(true)}
})
watch(()=>props.flights,()=>{if(map) applyData(false)},{deep:false})
watch(()=>props.selectedId,()=>{
  if(map) applyData(false)
  if(!map||!props.selectedId) return
  const f=(props.flights||[]).find(x=>x.id===props.selectedId)
  if(!f) return
  const row=(props.data?.corridors||[]).find(c=>c.id===f.corridor)
  const path=(row?.path&&row.path.length>1)?row.path:(f.fromLonLat&&f.toLonLat?[f.fromLonLat,f.toLonLat]:null)
  if(!path) return
  let b=[1e9,1e9,-1e9,-1e9]
  for(const [lon,lat] of path){
    b[0]=Math.min(b[0],lon);b[1]=Math.min(b[1],lat)
    b[2]=Math.max(b[2],lon);b[3]=Math.max(b[3],lat)
  }
  const pad=Math.max(.18,(b[2]-b[0])*.45,(b[3]-b[1])*.45)
  map.fitBounds([[b[0]-pad,b[1]-pad],[b[2]+pad,b[3]+pad]],{
    padding:{top:60,bottom:80,left:60,right:60},pitch:50,bearing:-10,duration:900})
})
watch(()=>props.radarOn,()=>{if(map) applyData(true)})
watch(()=>props.fogOn,()=>{if(map) applyData(true)})
watch(()=>props.audience,()=>{applyAudience(); applyData(true)})
watch(()=>props.zones,()=>{applyData(true)})

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
  const target=[[b[0],b[1]],[b[2],b[3]]]
  // 同 fitToData：带俯仰取景必须走 cameraForBounds，否则定位到的回波只剩小小一块
  const camera=map.cameraForBounds(target,{padding:36,bearing:-10,pitch:50})
  if(camera){map.easeTo({...camera,duration:900})}
  else{map.fitBounds(target,{padding:40,pitch:50,duration:900})}
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
      d+='Z'
    }
    if(d) rows.push({key:name||'jd',boundary,d})
  }
  rows.sort((a,b)=>(a.boundary?1:0)-(b.boundary?1:0))
  return rows
})
const levelLabel=computed(()=>({nation:'全国',region:'大区',province:'省域',city:'城市'}[level.value]||level.value))
const scaleNote=computed(()=>({
  nation:'城市用点+环标记；全国层与二维图一致，不画航线',
  region:'本区省界与航路；城市用点+环标记',
  province:'地形高程（DEM，z≤6）+ 机场净空柱（垂直放大 10×）',
  city:'地形高程 + 机场净空柱（垂直放大 10×）',
}[level.value]||''))
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

  <div class="nglobe-tip" v-if="!ready&&!failed">三维视图初始化（首次约 2–4 秒）…</div>
  <div class="nglobe-tip bad" v-if="failed&&!ready">三维不可用：{{ failed }}（已可退回倾斜/平面视图）</div>
  <div class="nglobe-note">
    {{ levelLabel }} · 俯角 {{ Math.round(pitchNow) }}° 可旋转 · <template v-if="fpsNow">{{ fpsNow }} fps · </template>{{ scaleNote }}
    <template v-if="terrainOn"> · 地形 {{ demInfo }}</template>
  </div>
  <div class="nglobe-gpu" :title="gpuLabel(gpu)">{{ gpuLabel(gpu) }}</div>
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
.nglobe-note{position:absolute;left:10px;bottom:8px;right:150px;font-size:10.5px;color:#7d9cb3;
  background:rgba(6,16,25,.72);border-radius:5px;padding:2px 8px;pointer-events:none;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nglobe-gpu{position:absolute;right:10px;top:10px;max-width:220px;font-size:10px;color:#6f92a8;
  background:rgba(6,16,25,.7);border-radius:5px;padding:2px 7px;pointer-events:none;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nglobe :deep(.nglobe-lbl){font-size:10.5px;color:#cbdfef;white-space:nowrap;pointer-events:none;
  text-shadow:0 0 3px rgba(3,10,18,.95),0 0 6px rgba(3,10,18,.8);letter-spacing:.3px}
.nglobe :deep(.maplibregl-canvas){outline:none}
.nglobe :deep(.maplibregl-ctrl-attrib){display:none}
</style>
