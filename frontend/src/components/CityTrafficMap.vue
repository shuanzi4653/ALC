<script setup>
import {computed,ref,onMounted,onUnmounted,watch} from 'vue'
import * as THREE from 'three'
import {Line2} from 'three/addons/lines/Line2.js'
import {LineGeometry} from 'three/addons/lines/LineGeometry.js'
import {LineMaterial} from 'three/addons/lines/LineMaterial.js'
import {Map,NavigationControl,ScaleControl,MercatorCoordinate,setWorkerUrl} from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import cityStyle from '../map/city-map-style.json'
const INTRUSION_TINT={PROHIBITED:0xe08a45,APPROVAL_REQUIRED:0xff9a3c,NONE:null}
const FIXED_ZONE_COLORS={
  line:'#a5b4fc',
  lineStrict:'#d8b4fe',
  footprint:.06,
  footprintStrict:.30,
  width:2.4,
  widthStrict:3.4,
  haloWidth:6,
  haloOpacity:.10,
}
const RISK_COLORS={
  fill:['#ffc107','#d9a968'],
  fillOpacity:.26,
  coreFill:'#e08a45',
  coreOpacity:.46,
  line:'#ffb300',
  lineCore:'#e08a45',
  width:2,
  widthCore:3,
}
const RADAR_COLORS={
  fill:'#ffc107',
  coreFill:'#e08a45',
  fillOpacity:.34,
  coreOpacity:.6,
  line:'#ffb300',
  lineCore:'#e0803c',
  width:3,
  widthCore:4,
  watchFill:'#5b6ecf',
  watchFillOpacity:.2,
  watchLine:'#8b9ee8',
  watchWidth:2.2,
  watchOpacity:.7,
  haloWidth:11,
}
const RADAR_STALE_MINUTES=90
const MAP_ERROR_THRESHOLD=6
import { FOG_RING_KM,FOG_SIGN_KM,FOG_SIGN_NOTE,fogRing,fogFeatureCollection,fogRingLayers,altitudeText,atTime,trajectoryOf,flightState,splitTrajectoryAt,splitTrajectoryInto,weatherBucket,classifyMapError,MAP_ERROR_TEXT,mapErrorSummary,staticZoneSurfaces,zoneIntrusionAt,zoneIntrusionRank,ZONE_INTRUSION,modeNames,radarState,radarSurfaces,radarFeatureGeometry,radarBanSurfaces,radarCoreIntrusionAt,radarSummaryText,radarFrozenNote,fixedZoneFrozenNote,RADAR_STATE,RADAR_PENDING_TIMEOUT_MS,radarUnavailable,lowVisibilitySurfaces,lowVisibilityState,lowVisibilitySummaryText,LOW_VISIBILITY_COLORS,LOW_VISIBILITY_STATE,BASEMAP_CHANNEL_ONLINE,BASEMAP_CHANNEL_OFFLINE,BASEMAP_CHANNEL_PENDING,basemapChannelAfterSignal,basemapChannelLabel,basemapFallbackVisible,basemapIsOffline,basemapSignalFromError,basemapStatusText,OFFLINE_BASEMAP_COLORS,OFFLINE_BASEMAP_NOTICE,normalizeBasemapChannel,vehicleLabelText,vehicleLabel,selectVehicleLabels,routeBasisNote,alertEventLayer,observationPoints,isOfflineMode} from '../traffic/runtime.js'
import {lngLat,localGeometry,geographicGeometry,geographicGeoJson,collection,feature} from '../traffic/geography.js'
import offlineBasemap from '../assets/northeast-offline.json'
const props=defineProps({
  stationVisibility:{type:Array,default:()=>[]},network:Object,flights:Array,minute:Number,city:String,selected:Object,weather:Object,playing:Boolean,showCar:Boolean,showDelivery:Boolean,showWeather:Boolean,showWind:Boolean,showFixedZones:Boolean,showRadar:Boolean,
  showFog:Boolean,
  showEvents:Boolean,showObservations:Boolean,
  alertFlights:{type:Array,default:()=>[]},
  ribbon:{type:Array,default:()=>[]},
  initialBasemapChannel:{type:String,default:BASEMAP_CHANNEL_PENDING}})
const emit=defineEmits(['select-city','select-flight','map-status','select-event','open-corridor'])
setWorkerUrl(mapWorkerUrl)
const selectedScreen=ref(null)
const vehicleLabels=ref([])
let vehicleLabelKey=''
const MAX_VEHICLE_LABELS=40
const labelProject=new THREE.Vector3()
const labelSlots=[]
const labelCandidates=[]
const host=ref(null),error=ref(''),following=ref(false),buildingCount=ref(0),mapStatus=ref('')
const intrusions=ref([])
const intrusionApprovals=ref(0)
const radarIntrusions=ref([])
let radarIntrusionKey=''
const mapIssues=ref({})
const basemapChannel=ref(normalizeBasemapChannel(props.initialBasemapChannel))
let basemapTileFailures=0
const basemapLabel=computed(()=>basemapChannelLabel(basemapChannel.value))
function refreshMapStatus(){
  if(error.value)return
  mapStatus.value=basemapStatusText(basemapChannel.value,{buildingCount:buildingCount.value,city:props.city})
}
watch(basemapChannel,refreshMapStatus)
refreshMapStatus()
const issueSummary=computed(()=>mapErrorSummary(mapIssues.value))
const hiddenProhibited=computed(()=>intrusions.value.reduce((sum,row)=>sum+row.hidden,0))
const radarBanList=computed(()=>radarBanSurfaces(props.weather?.radar,localGeometry))
const intrusionTotal=computed(()=>intrusions.value.length+radarIntrusions.value.length)
const intrusionUnlisted=computed(()=>intrusionTotal.value
  -Math.min(4,intrusions.value.length)-Math.min(4,radarIntrusions.value.length))
const radarWaited=ref(null)
let radarWaitTimer=null
function stopRadarWait({keepMs=false}={}){
  if(radarWaitTimer){clearInterval(radarWaitTimer);radarWaitTimer=null}
  if(!keepMs)radarWaited.value=null
}
function startRadarWait(){
  stopRadarWait()
  const started=Date.now()
  radarWaited.value=0
  radarWaitTimer=setInterval(()=>{
    const waited=Date.now()-started
    radarWaited.value=waited
    if(waited>=RADAR_PENDING_TIMEOUT_MS)stopRadarWait({keepMs:true})
  },250)
}
watch([()=>props.showRadar,()=>props.weather?.radar],([show,radar])=>{
  if(!show||radar){stopRadarWait();return}
  if(radarWaitTimer===null&&radarWaited.value===null)startRadarWait()
},{immediate:true})
onUnmounted(()=>stopRadarWait())

const radarBadge=computed(()=>{
  const radar=props.weather?.radar
  const state=radarState(radar,{waitedMs:radarWaited.value})
  const rawAge=radar?.summary?.slotAgeMinutes
  const age=typeof rawAge==='number'?rawAge:null
  const stale=state===RADAR_STATE.READY&&age!==null&&age>RADAR_STALE_MINUTES
  const drawn=radarSurfaces(radar).length
  const frozen=radarFrozenNote(radar,{playing:!!props.playing,minute:Number(props.minute)||0})
  const stratiform=Number(radar?.summary?.bands?.STRATIFORM?.areaKm2)
  const stratArea=Number.isFinite(stratiform)?`${stratiform.toFixed(1)} km²`:''
  const echoFraction=Number(radar?.summary?.echoFraction)
  const echoNote=Number.isFinite(echoFraction)&&echoFraction>0&&echoFraction<0.01
    ? `（回波占本帧画面约 ${(echoFraction*100).toFixed(1)}%，全域缩放下基本看不见）` : ''
  const base=state===RADAR_STATE.READY?'风险区：雷达回波已叠加'
    :state===RADAR_STATE.PENDING
      ? `雷达：正在读取本帧数据${radarWaited.value!==null?`（已等 ${(radarWaited.value/1000).toFixed(1)} 秒）`:''}`
    :state===RADAR_STATE.QUIET?(drawn
      ? `雷达：仅层状降水${stratArea?` ${stratArea}`:''}（15–35 dBZ，可飞越）· 本帧无 ≥35 dBZ 对流，橙色按设计不出现${echoNote}`
      :'雷达：本作业区当前无回波（0 块 ≥35 dBZ）'):'雷达回波不可用'
  const short=frozen&&state!==RADAR_STATE.DOWN&&state!==RADAR_STATE.PENDING
    ?`${base} · 推演中保持不动`:base
  return {state,text:radarSummaryText(radar,{waitedMs:radarWaited.value}),short,stale,
    age:Number.isFinite(age)?age:null,
    frozen:!!frozen,frozenNote:frozen,
    source:radar?.summary?.channel||''}
})
const fixedZoneFrozen=computed(()=>fixedZoneFrozenNote(props.network,{playing:!!props.playing}))
const radarBounds=computed(()=>{
  const surfaces=radarSurfaces(props.weather?.radar)
  let lonMin=Infinity,latMin=Infinity,lonMax=-Infinity,latMax=-Infinity,found=false
  const walk=coords=>{
    if(typeof coords?.[0]==='number'){
      const [lon,lat]=coords
      if(Number.isFinite(lon)&&Number.isFinite(lat)){
        found=true
        if(lon<lonMin)lonMin=lon;if(lon>lonMax)lonMax=lon
        if(lat<latMin)latMin=lat;if(lat>latMax)latMax=lat
      }
      return
    }
    for(const part of coords||[])walk(part)
  }
  for(const surface of surfaces)walk(surface.geometry?.coordinates)
  return found?[[lonMin,latMin],[lonMax,latMax]]:null
})
function locateRadar(){
  if(!map||!radarBounds.value)return
  following.value=false
  map.flyTo({center:[(radarBounds.value[0][0]+radarBounds.value[1][0])/2,
    (radarBounds.value[0][1]+radarBounds.value[1][1])/2],zoom:7.2,duration:900})
}
const selectedAlert=computed(()=>{
  const state=zoneIntrusionAt(props.selected,props.minute)
  return state.level===ZONE_INTRUSION.NONE?null:state
})
const selectedBasisNote=computed(()=>{
  const basis=String(props.selected?.routeBasis||'')
  return basis&&basis!=='CLEAR'?routeBasisNote(props.selected):''
})
let map,scene,renderer,camera,group,observer,origin,unit,models=[],lineMaterials=[],ready=false,lastFollow=0,disposed=false,loadDeadline,intrusionKey=''
function setData(id,data){map?.getSource(id)?.setData(data)}
function drawRibbon(){
  if(!map)return
  const features=[]
  for(const line of props.ribbon||[]){
    const pts=line.points||[]
    for(let i=0;i<pts.length-1;i++){
      const segP=Number.isFinite(Number(pts[i].p))?Number(pts[i].p):Number(line.p)||0
      features.push({type:'Feature',
        properties:{id:line.id,p:segP,sigma:Number(line.sigma)||0,tier:line.verdict==='需谨慎'?'CAUTION':'CLEAR'},
        geometry:{type:'LineString',coordinates:[[pts[i].lng,pts[i].lat],[pts[i+1].lng,pts[i+1].lat]]}})
    }
  }
  setData('operation-ribbon',{type:'FeatureCollection',features})
}
function scoped(f){return (f.mode==='CAR'?props.showCar:props.showDelivery)&&(!props.city||[f.fromCity,f.toCity].includes(props.city))}
function ringSignedArea(ring){
  let total=0
  for(let i=0;i<ring.length-1;i++)total+=(ring[i+1][0]-ring[i][0])*(ring[i+1][1]+ring[i][1])
  return total
}
function oriented(ring,clockwise){
  const closed=ring.length>2&&ring[0][0]===ring.at(-1)[0]&&ring[0][1]===ring.at(-1)[1]?ring:[...ring,ring[0]]
  const isClockwise=ringSignedArea(closed)>0
  return isClockwise===clockwise?closed:[...closed].reverse()
}
function outsideMask(outline){
  const holes=[]
  const walk=geometry=>{
    if(!geometry)return
    if(geometry.type==='Polygon')holes.push(geometry.coordinates[0])
    else if(geometry.type==='MultiPolygon')geometry.coordinates.forEach(polygon=>holes.push(polygon[0]))
    else if(geometry.type==='GeometryCollection')geometry.geometries.forEach(walk)
  }
  walk(outline)
  if(!holes.length)return null
  return {
    type:'Feature',properties:{},
    geometry:{type:'Polygon',coordinates:[[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]],...holes.map(ring=>oriented(ring,true))]},
  }
}
function world(p){const m=MercatorCoordinate.fromLngLat(lngLat(p),p[2]||0);return new THREE.Vector3((m.x-origin.x)/unit,-(m.y-origin.y)/unit,m.z/unit)}
function disposeGroup(){if(!group)return;group.traverse(o=>{o.geometry?.dispose();if(o.material)(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose())});group.clear();models=[];lineMaterials=[]}
function lngLatPath(path){
  if(!Array.isArray(path))return []
  return path
    .filter(p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(Number(p[0]))&&Number.isFinite(Number(p[1])))
    .map(p=>{const q=lngLat([Number(p[0]),Number(p[1])]);q[2]=Number(p[2])||0;return q})
}
function addLine(points,color,opacity=1,width=2,dashed=false){
  if(!points||points.length<2)return
  const positions=points.map(world),geometry=new LineGeometry()
  geometry.setPositions(positions.flatMap(p=>[p.x,p.y,p.z]))
  const material=new LineMaterial({color,transparent:true,opacity,linewidth:width,worldUnits:false,dashed,dashSize:1.4,gapSize:1.1,depthWrite:false})
  material.resolution.set(map.getCanvas().clientWidth,map.getCanvas().clientHeight)
  const line=new Line2(geometry,material);line.computeLineDistances();group.add(line);lineMaterials.push(material)
}
const VEHICLE_SHAPES={
  CAR:{span:4.6,rotor:1.9,armLength:6.4,armRadius:.18,scale:.62,bodyLength:9.5,bodyWidth:3.6,bodyHeight:2.0,cabin:true},
  DELIVERY:{span:2.1,rotor:1.05,armLength:3.0,armRadius:.13,scale:.42,bodyLength:3.6,bodyWidth:1.9,bodyHeight:1.1,cabin:false},
}
function vehicle(mode){
  const g=new THREE.Group(),tint=mode==='CAR'?0x59e5ff:0xffce76
  const shape=VEHICLE_SHAPES[mode]||VEHICLE_SHAPES.DELIVERY
  const body=new THREE.MeshBasicMaterial({color:tint})
  g.add(new THREE.Mesh(new THREE.BoxGeometry(shape.bodyLength,shape.bodyWidth,shape.bodyHeight),body))
  const tintables=[body]
  if(shape.cabin){const cabin=new THREE.Mesh(new THREE.BoxGeometry(shape.bodyLength*.5,shape.bodyWidth*.9,shape.bodyHeight*.8),new THREE.MeshBasicMaterial({color:0x234957}));cabin.position.z=shape.bodyHeight*.85;g.add(cabin)}
  for(const x of [-shape.span,shape.span])for(const y of [-shape.span,shape.span]){
    const armMaterial=new THREE.MeshBasicMaterial({color:tint})
    const arm=new THREE.Mesh(new THREE.CylinderGeometry(shape.armRadius,shape.armRadius,shape.armLength,5),armMaterial)
    arm.position.set(x/2,y/2,0);arm.rotation.z=-Math.atan2(x,y);g.add(arm);tintables.push(armMaterial)
    const rotorMaterial=new THREE.MeshBasicMaterial({color:tint})
    const rotor=new THREE.Mesh(new THREE.TorusGeometry(shape.rotor,.12,5,16),rotorMaterial)
    rotor.position.set(x,y,shape.bodyHeight*.3);g.add(rotor);tintables.push(rotorMaterial)
  }
  g.scale.setScalar(shape.scale*(props.city?3:350))
  g.userData.tint={base:tint,materials:tintables}
  return g
}
function syncIntrusions(rows,approvalCount){
  rows.sort((a,b)=>zoneIntrusionRank(b.alert.level)-zoneIntrusionRank(a.alert.level)
    ||String(a.f.id).localeCompare(String(b.f.id)))
  const key=rows.map(row=>`${row.f.id}:${row.alert.level}:${row.alert.lead?.zoneId||''}`).join('|')+'#'+approvalCount
  if(key===intrusionKey)return
  intrusionKey=key
  intrusionApprovals.value=approvalCount
  intrusions.value=rows.map(row=>({
    id:row.f.id,mode:row.f.mode,name:row.f.name,level:row.alert.level,label:row.alert.label,
    zone:row.alert.lead?.name||'',clause:row.alert.lead?.clause||'',hidden:row.alert.prohibitedHidden,
  }))
}
function syncRadarIntrusions(rows){
  const key=rows.map(row=>`${row.f.id}#${row.banId}`).join('|')
  if(key===radarIntrusionKey)return
  radarIntrusionKey=key
  radarIntrusions.value=rows.map(row=>({id:row.f.id,mode:row.f.mode,name:row.f.name,banId:row.banId}))
}
function syncVehicleLabels(rows){
  const key=rows.map(row=>`${row.id}@${Math.round(row.x)},${Math.round(row.y)}${row.bad?'!':''}`).join('|')
  if(key===vehicleLabelKey)return
  vehicleLabelKey=key
  vehicleLabels.value=rows.map(row=>({id:row.id,x:Math.round(row.x),y:Math.round(row.y),text:row.text,bad:!!row.bad}))
}
function rebuild(){
  if(!ready||!props.network)return
  disposeGroup()
  setData('operation-provinces',props.network.administrativeBoundaries||collection())
  const outline=props.network.boundary
  setData('operation-outline',outline?collection([feature(outline)]):collection())
  const mask=outline?outsideMask(outline):null
  setData('operation-mask',mask?collection([mask]):collection())
  const c=props.network.cities.find(c=>c.id===props.city)
  origin=MercatorCoordinate.fromLngLat(c?.coordinate||[126,45],0);unit=origin.meterInMercatorCoordinateUnits()
  for(const r of props.network.routes){
    if(!r.path||(r.mode==='CAR'?!props.showCar:!props.showDelivery)||(props.city&&![r.fromCity,r.toCity].includes(props.city)))continue
    addLine(lngLatPath(r.referencePath),r.mode==='CAR'?0x347c99:0xa77935,.26,r.mode==='CAR'?2.8:2,true)
  }
  const ARRIVED_KEEP_MINUTES=8,MAX_ARRIVED_LINES=100
  let arrivedDrawn=0
  const trajectorySlot=[[],[]]
  for(const f of props.flights||[]){
    if(!Array.isArray(f.points)||f.points.length<2||!scoped(f))continue
    const selected=f.id===props.selected?.id
    const state=flightState(f,props.minute)
    const flying=state==='AIRBORNE',landed=state==='ARRIVED'
    const imminent=state==='PENDING'||state==='HOLD'?(f.departureMinute>=props.minute&&f.departureMinute<props.minute+2):false
    if(!selected&&!flying&&!landed&&!imminent)continue
    if(landed&&!selected){
      if(props.minute-f.arrivalMinute>ARRIVED_KEEP_MINUTES||arrivedDrawn>=MAX_ARRIVED_LINES)continue
      arrivedDrawn++
    }
    const detoured=(Number(f.detourMinutes)||0)>0.01
    const color=selected?0xf2faff:(detoured?(f.mode==='CAR'?0x5cdbff:0xffd085):(f.mode==='CAR'?0x5cdbff:0xb9b2e8))
    const baseWidth=f.mode==='CAR'?4.5:3
    const width=selected?(f.mode==='CAR'?6:4.5):(detoured?baseWidth*0.62:baseWidth)
    const [flown,ahead]=flying||landed?splitTrajectoryInto(f.points,props.minute,trajectorySlot):[[],f.points]
    if(flown.length>1)addLine(flown,color,selected?.55:.32,width)
    if(ahead.length>1)addLine(ahead,color,selected?1:(detoured?.5:(imminent?.6:.88)),width)
    if(flying||selected||imminent){
      const model=vehicle(f.mode)
      model.userData.flight=f;group.add(model);models.push({f,model})
    }
  }
  setData('operation-cities',collection(props.network.cities.map(c=>feature({type:'Point',coordinates:c.coordinate},{id:c.id,name:c.name,capital:c.capital}))))
  const pads=(props.network.pads||[]).filter(p=>!c||p.cityId===c.id).map(p=>feature({type:'Point',coordinates:p.coordinate||lngLat(p.xy)},{name:p.name,kind:p.kind,status:p.status}))
  setData('operation-pads',collection(pads));drawWeather();drawRadar();drawFog();drawFixedZones();drawEvents();drawObservations();drawRibbon();syncRibbonLabels();paintFogCircles();map.triggerRepaint()
}
function drawWeather(){
  if(!ready)return
  const fields=[],risks=[],winds=[]
  if(props.showWeather)for(const c of props.weather?.cells||[])for(const [kind,geometry] of [['FIELD',c.field],['BAN',c.ban],['CAUTION',c.caution]]){
    if(!['Polygon','MultiPolygon'].includes(geometry.type))continue
    const f=feature(geographicGeometry(geometry),{id:c.id,kind,weather:c.kind})
    if(kind==='FIELD')fields.push(f);else risks.push(f)
  }
  if(props.showWind)for(const w of props.weather?.winds||[]){
    const n=Math.hypot(w.u,w.v);if(!n)continue
    const base=props.city?120:2600
    const stretch=Math.min(1,0.45+n/12)
    const size=base*stretch,dx=w.u/n*size,dy=w.v/n*size,[x,y]=w.xy
    winds.push(feature({type:'MultiLineString',coordinates:[[[x,y],[x+dx,y+dy]],[[x+dx*.65-dy*.2,y+dy*.65+dx*.2],[x+dx,y+dy],[x+dx*.65+dy*.2,y+dy*.65-dx*.2]]].map(line=>line.map(lngLat))},{interpolated:!!w.interpolated}))
  }
  setData('operation-fields',collection(fields));setData('operation-risks',collection(risks));setData('operation-wind',collection(winds))
}
function drawRadar(){
  if(!ready)return
  const radar=props.weather?.radar
  const rawAge=radar?.summary?.slotAgeMinutes
  const age=typeof rawAge==='number'?rawAge:null
  const stale=age!==null&&age>RADAR_STALE_MINUTES
  if(!props.showRadar||stale||radarUnavailable(radar)){
    setData('operation-radar',collection());setData('operation-radar-watch',collection())
    return
  }
  const surfaces=[],watches=[]
  for(const surface of radarSurfaces(radar)){
    const properties={id:surface.id,tier:surface.tier,source:surface.source,
      slot:surface.slot,slotAgeMinutes:surface.slotAgeMinutes}
    const f=feature(radarFeatureGeometry(surface),properties)
    if(surface.tier==='WATCH')watches.push(f);else surfaces.push(f)
  }
  setData('operation-radar',collection(surfaces));setData('operation-radar-watch',collection(watches))
}
function drawFog(){
  if(!ready)return
  if(!props.showFog||lowVisibilityState(props.weather)===LOW_VISIBILITY_STATE.DOWN){
    setData('operation-fog-caution',collection());setData('operation-fog-ban',collection())
    return
  }
  const caution=[],ban=[]
  for(const surface of lowVisibilitySurfaces(props.weather)){
    const properties={id:surface.id,cityId:surface.cityId,cityName:surface.cityName,
      tier:surface.tier,visibilityM:surface.visibilityM,
      provider:surface.derivedFrom?.provider||null,
      dataType:surface.derivedFrom?.dataType||null}
    const f=feature(geographicGeometry(surface.geometry),properties)
    if(surface.tier==='BAN')ban.push(f);else caution.push(f)
  }
  setData('operation-fog-caution',collection(caution));setData('operation-fog-ban',collection(ban))
}
const caseFogRows=computed(()=>fogFeatureCollection(props.stationVisibility).features.map(f=>f.properties))

const fogLabels=ref([])
let fogLabelKey=''
function syncFogLabels(){
  if(!map||!props.showFog){
    if(fogLabels.value.length){fogLabels.value=[];fogLabelKey=''}
    return
  }
  const rows=[]
  for(const f of fogFeatureCollection(props.stationVisibility).features){
    const center=f.properties.center
    if(!Array.isArray(center))continue
    const point=map.project(center)
    if(!Number.isFinite(point?.x)||!Number.isFinite(point?.y))continue
    rows.push({id:f.properties.station,x:Math.round(point.x),y:Math.round(point.y),
      text:f.properties.label,tier:f.properties.tier,level:f.properties.level})
  }
  const key=rows.map(r=>`${r.id}@${r.x},${r.y}`).join('|')
  if(key===fogLabelKey)return
  fogLabelKey=key
  fogLabels.value=rows
}

const ribbonLabels=ref([])
let ribbonLabelKey=''
function syncRibbonLabels(){
  if(!map||!(props.ribbon||[]).length){
    if(ribbonLabels.value.length){ribbonLabels.value=[];ribbonLabelKey=''}
    return
  }
  const rows=[]
  for(const line of (props.ribbon||[]).slice(0,6)){
    const pts=line.points||[]
    if(pts.length<2)continue
    const mid=pts[Math.floor(pts.length/2)]
    if(!Number.isFinite(mid?.lng)||!Number.isFinite(mid?.lat))continue
    const point=map.project([mid.lng,mid.lat])
    if(!Number.isFinite(point?.x)||!Number.isFinite(point?.y))continue
    rows.push({
      id:line.id,x:Math.round(point.x),y:Math.round(point.y),
      name:line.name||line.id,
      p:Math.round((Number(line.p)||0)*100),
      caution:line.verdict==='需谨慎',
    })
  }
  const key=rows.map(r=>`${r.id}@${r.x},${r.y}`).join('|')
  if(key===ribbonLabelKey)return
  ribbonLabelKey=key
  ribbonLabels.value=rows
}

const fogBadge=computed(()=>{
  const rows=caseFogRows.value
  if(rows.length){
    const ban=rows.filter(r=>r.level==='BAN').length
    const worst=rows.reduce((a,b)=>(Number(a.visM)<=Number(b.visM)?a:b))
    return {
      state:ban?'BAN':'CAUTION',
      short:`实测 ${rows.length} 站 · 最低 ${Math.round(Number(worst.visM))} m`,
      text:`${rows.map(r=>`${r.station} ${Math.round(Number(r.visM))} m`).join(' / ')}`
        + ` · 不可飞 ${ban} 处 / 需谨慎 ${rows.length-ban} 处 · ${FOG_SIGN_NOTE}`,
    }
  }
  const state=lowVisibilityState(props.weather)
  const surfaces=lowVisibilitySurfaces(props.weather)
  const ban=surfaces.filter(s=>s.tier==='BAN').length
  const short=state===LOW_VISIBILITY_STATE.DOWN?'低能见度不可用'
    :state===LOW_VISIBILITY_STATE.QUIET?'低能见度：本帧无'
      :`低能见度：深灰 ${ban} 处`
  return {state,short,text:lowVisibilitySummaryText(props.weather)}
})
const fogBounds=computed(()=>{
  let lonMin=Infinity,latMin=Infinity,lonMax=-Infinity,latMax=-Infinity,found=false
  const walk=coords=>{
    if(typeof coords?.[0]==='number'){
      const [lon,lat]=coords
      if(Number.isFinite(lon)&&Number.isFinite(lat)){
        found=true
        if(lon<lonMin)lonMin=lon;if(lon>lonMax)lonMax=lon
        if(lat<latMin)latMin=lat;if(lat>latMax)latMax=lat
      }
      return
    }
    for(const part of coords||[])walk(part)
  }
  for(const surface of lowVisibilitySurfaces(props.weather)){
    const geo=geographicGeometry(surface.geometry)
    walk(geo?.coordinates)
  }
  for(const feature of fogFeatureCollection(props.stationVisibility).features){
    walk(feature.geometry?.coordinates)
  }
  return found?[[lonMin,latMin],[lonMax,latMax]]:null
})
function locateFog(){if(fogBounds.value)map?.fitBounds(fogBounds.value,{padding:80,duration:700})}
function drawFixedZones(){
  if(!ready)return
  const source=props.showFixedZones?staticZoneSurfaces(props.network?.staticAirspace,props.network?.riskRules?.ceilingAglM):{volumes:[],references:[]}
  const volumes=[],references=[]
  for(const {zone,citation} of source.volumes){
    const props_={id:zone.id,name:zone.name,clause:zone.clause,sector:zone.sector,
      sectorLabel:zone.sectorLabel,enforcement:zone.enforcement,geometryStatus:zone.geometryStatus,
      citation}
    volumes.push(feature(zone.geometry,props_))
  }
  for(const {zone,coordinate} of source.references){
    references.push(feature({type:'Point',coordinates:coordinate},{id:zone.id,name:zone.name,
      clause:zone.clause,sector:zone.sector,sectorLabel:zone.sectorLabel,
      geometryStatus:zone.geometryStatus,status:'已登记待补范围'}))
  }
  setData('operation-fixed-zones',collection(volumes));setData('operation-fixed-refs',collection(references))
}
const eventLayer=computed(()=>alertEventLayer(props.alertFlights,props.network))
const eventGeo=computed(()=>({
  lines:geographicGeoJson(eventLayer.value.lines),
  nodes:geographicGeoJson(eventLayer.value.nodes),
}))
const observationLayer=computed(()=>observationPoints(props.weather,props.network))
function drawEvents(){
  if(!ready)return
  if(!props.showEvents){setData('operation-events',collection());setData('operation-event-nodes',collection());return}
  setData('operation-events',eventGeo.value.lines)
  setData('operation-event-nodes',eventGeo.value.nodes)
}
function drawObservations(){
  if(!ready)return
  if(!props.showObservations){setData('operation-observations',collection());return}
  setData('operation-observations',collection(observationLayer.value.features))
}
const eventBadge=computed(()=>{
  const layer=eventLayer.value
  const scope=props.city?'本城':''
  if(!layer.total)return {short:`${scope}运行事件 0 个`,text:'本次计划没有合并出任何调度事件。',state:'QUIET'}
  const parts=[`${scope}运行事件 ${layer.total} 个（气象 ${layer.weatherEvents} · 非气象 ${layer.nonWeatherEvents}）`,
    `停止放行 ${layer.closedFlights} 班`]
  if(layer.missingCorridor)parts.push(`${layer.missingCorridor} 条取不到走廊几何，未绘制`)
  return {short:`${scope}运行事件 ${layer.total} 个 · 停止放行 ${layer.closedFlights} 班`,
    text:parts.join('；')+'。'+layer.note,state:layer.closedEvents?'DOWN':'QUIET'}
})
function focusEvent(key){
  if(!map||!key)return
  const row=eventGeo.value.nodes.features.find(item=>item.properties.key===key)
  const line=eventGeo.value.lines.features.find(item=>item.properties.key===key)
  const coordinates=line?line.geometry.coordinates:(row?[row.geometry.coordinates]:null)
  if(!coordinates||!coordinates.length)return
  let lonMin=Infinity,latMin=Infinity,lonMax=-Infinity,latMax=-Infinity,found=false
  for(const [lon,lat] of coordinates){
    if(!Number.isFinite(lon)||!Number.isFinite(lat))continue
    found=true
    if(lon<lonMin)lonMin=lon;if(lon>lonMax)lonMax=lon
    if(lat<latMin)latMin=lat;if(lat>latMax)latMax=lat
  }
  if(!found)return
  following.value=false
  if(lonMax-lonMin<0.05&&latMax-latMin<0.05){
    map.flyTo({center:[(lonMin+lonMax)/2,(latMin+latMax)/2],zoom:8.4,duration:900})
    return
  }
  map.fitBounds([[lonMin,latMin],[lonMax,latMax]],{padding:70,duration:900})
}
function focus(){
  if(!map||!props.network)return
  following.value=false;map.setCenterClampedToGround(true);map.setCenterElevation(0)
  const c=props.network.cities.find(c=>c.id===props.city)
  if(c)map.flyTo({center:c.coordinate,zoom:14.4,pitch:62,bearing:-22,duration:1000})
  else map.fitBounds([[118.7,38.6],[135.1,53.6]],{padding:45,pitch:38,bearing:0,duration:900})
  rebuild()
}
function follow(){
  const pts=trajectoryOf(props.selected)
  if(!pts.length)return
  following.value=!following.value
  if(following.value){const p=atTime(pts,props.minute);map.setCenterClampedToGround(false);map.setCenterElevation(p[2]);map.flyTo({center:lngLat(p),elevation:p[2],zoom:16.5,pitch:62,bearing:-25,duration:900})}
  else{map.setCenterClampedToGround(true);map.setCenterElevation(0)}
}
function offlineBasemapLayers(){
  const source='offline-basemap'
  if(!map.getSource(source))map.addSource(source,{type:'geojson',data:structuredClone(offlineBasemap)})
  map.addLayer({id:'offline-basemap-land',type:'fill',source,paint:{
    'fill-color':OFFLINE_BASEMAP_COLORS.land,'fill-opacity':.85}},firstOperationLayer())
  map.addLayer({id:'offline-basemap-coast',type:'line',source,paint:{
    'line-color':OFFLINE_BASEMAP_COLORS.coast,'line-width':1.1,'line-opacity':.9}},firstOperationLayer())
  return [source]
}
function firstOperationLayer(){
  for(const layer of map.getStyle().layers||[]){
    if(layer.id.startsWith('province-')||layer.id.startsWith('fixed-')||layer.id.startsWith('weather-')||layer.id.startsWith('radar-'))return layer.id
  }
  return undefined
}
function setOfflineBasemapVisibility(){
  const visible=basemapFallbackVisible(basemapChannel.value)
  for(const id of ['offline-basemap-land','offline-basemap-coast']){
    if(map?.getLayer(id))map.setLayoutProperty(id,'visibility',visible?'visible':'none')
  }
}
function sourceLayers(){
  for(const id of ['operation-cities','operation-pads','operation-fields','operation-risks','operation-wind','operation-provinces','operation-outline','operation-mask','operation-fixed-zones','operation-fixed-refs','operation-radar','operation-radar-watch','operation-fog-caution','operation-fog-ban','operation-events','operation-event-nodes','operation-observations','operation-ribbon'])map.addSource(id,{type:'geojson',data:collection()})
  setData('operation-provinces',props.network?.administrativeBoundaries||collection())
  map.addLayer({id:'ribbon-halo',type:'line',source:'operation-ribbon',paint:{
    'line-color':['match',['get','tier'],'CAUTION','#E8A33D','#4C8DFF'],
    'line-width':['interpolate',['linear'],['get','sigma'],0,6,1,18],
    'line-opacity':.16,'line-blur':2}})
  map.addLayer({id:'ribbon-line',type:'line',source:'operation-ribbon',paint:{
    'line-color':['match',['get','tier'],'CAUTION','#E8A33D','#4C8DFF'],
    'line-width':['interpolate',['linear'],['get','sigma'],0,2.5,1,7],
    'line-opacity':.92}})
  map.addLayer({id:'province-mask',type:'fill',source:'operation-mask',paint:{'fill-color':'#050b13','fill-opacity':.5}})
  map.addLayer({id:'province-area',type:'fill',source:'operation-provinces',paint:{'fill-color':'#9b91d6','fill-opacity':.05}})
  map.addLayer({id:'province-outline-shadow',type:'line',source:'operation-outline',paint:{'line-color':'#06101a','line-width':10,'line-opacity':.95}})
  map.addLayer({id:'province-shadow',type:'line',source:'operation-provinces',paint:{'line-color':'#0a1522','line-width':5,'line-opacity':.9}})
  map.addLayer({id:'province-boundary',type:'line',source:'operation-provinces',paint:{'line-color':'#b9b2e8','line-width':2.8,'line-opacity':.96}})
  map.addLayer({id:'province-outline',type:'line',source:'operation-outline',paint:{'line-color':'#efe9ff','line-width':4.4,'line-opacity':.99}})
  map.addLayer({id:'fixed-zone-footprint',type:'fill',source:'operation-fixed-zones',paint:{
    'fill-color':FIXED_ZONE_COLORS.line,
    'fill-opacity':['match',['get','enforcement'],'PROHIBITED',FIXED_ZONE_COLORS.footprintStrict,FIXED_ZONE_COLORS.footprint]}})
  map.addLayer({id:'weather-fields',type:'fill',source:'operation-fields',paint:{'fill-color':['match',['get','weather'],'THUNDERSTORM','#ac81ff','HEAVY_RAIN','#4f9dff','EXTREME_WIND','#45c4a5','STORM','#ac81ff','WIND','#45c4a5','#368bdd'],'fill-opacity':.12}})
  map.addLayer({id:'weather-risk-footprint',type:'fill',source:'operation-risks',paint:{
    'fill-color':['match',['get','kind'],'BAN',RISK_COLORS.coreFill,RISK_COLORS.fill[0]],
    'fill-opacity':['case',['==',['get','kind'],'BAN'],RISK_COLORS.coreOpacity,RISK_COLORS.fillOpacity]}})
  map.addLayer({id:'weather-risk-outline-core',type:'line',source:'operation-risks',
    filter:['==',['get','kind'],'BAN'],paint:{
      'line-color':RISK_COLORS.lineCore,'line-width':RISK_COLORS.widthCore,
      'line-opacity':.95,'line-dasharray':[1,0]}})
  map.addLayer({id:'weather-risk-outline',type:'line',source:'operation-risks',
    filter:['!=',['get','kind'],'BAN'],paint:{
      'line-color':RISK_COLORS.line,'line-width':RISK_COLORS.width,
      'line-opacity':.95,'line-dasharray':[2,1]}})
  map.addLayer({id:'fog-caution-fill',type:'fill',source:'operation-fog-caution',paint:{
    'fill-color':LOW_VISIBILITY_COLORS.cautionFill,'fill-opacity':LOW_VISIBILITY_COLORS.cautionOpacity}})
  map.addLayer({id:'fog-caution-outline',type:'line',source:'operation-fog-caution',paint:{
    'line-color':LOW_VISIBILITY_COLORS.cautionLine,'line-width':LOW_VISIBILITY_COLORS.width,
    'line-opacity':.9,'line-dasharray':[3,2]}})
  map.addLayer({id:'fog-ban-fill',type:'fill',source:'operation-fog-ban',paint:{
    'fill-color':LOW_VISIBILITY_COLORS.banFill,'fill-opacity':LOW_VISIBILITY_COLORS.banOpacity}})
  map.addLayer({id:'fog-ban-outline',type:'line',source:'operation-fog-ban',paint:{
    'line-color':LOW_VISIBILITY_COLORS.banLine,'line-width':LOW_VISIBILITY_COLORS.widthBan,
    'line-opacity':.95}})
  map.addLayer({id:'radar-halo',type:'line',source:'operation-radar',paint:{
    'line-color':RADAR_COLORS.lineCore,'line-width':RADAR_COLORS.haloWidth,'line-opacity':.18}})
  map.addLayer({id:'radar-watch-fill',type:'fill',source:'operation-radar-watch',paint:{
    'fill-color':RADAR_COLORS.watchFill,'fill-opacity':RADAR_COLORS.watchFillOpacity}})
  map.addLayer({id:'radar-watch-outline',type:'line',source:'operation-radar-watch',paint:{
    'line-color':RADAR_COLORS.watchLine,'line-width':RADAR_COLORS.watchWidth,
    'line-opacity':RADAR_COLORS.watchOpacity,'line-dasharray':[3,3]}})
  map.addLayer({id:'radar-footprint',type:'fill',source:'operation-radar',paint:{
    'fill-color':['match',['get','tier'],'BAN',RADAR_COLORS.coreFill,RADAR_COLORS.fill],
    'fill-opacity':['case',['==',['get','tier'],'BAN'],RADAR_COLORS.coreOpacity,RADAR_COLORS.fillOpacity]}})
  map.addLayer({id:'radar-outline-core',type:'line',source:'operation-radar',
    filter:['==',['get','tier'],'BAN'],paint:{
      'line-color':RADAR_COLORS.lineCore,'line-width':RADAR_COLORS.widthCore,
      'line-opacity':.95,'line-dasharray':[1,0]}})
  map.addLayer({id:'radar-outline',type:'line',source:'operation-radar',
    filter:['!=',['get','tier'],'BAN'],paint:{
      'line-color':RADAR_COLORS.line,'line-width':RADAR_COLORS.width,
      'line-opacity':.95,'line-dasharray':[4,2]}})
  map.addLayer({id:'fixed-zone-halo',type:'line',source:'operation-fixed-zones',paint:{
    'line-color':FIXED_ZONE_COLORS.line,'line-width':FIXED_ZONE_COLORS.haloWidth,
    'line-opacity':FIXED_ZONE_COLORS.haloOpacity}})
  map.addLayer({id:'fixed-zone-outline',type:'line',source:'operation-fixed-zones',paint:{
    'line-color':['match',['get','enforcement'],'PROHIBITED',FIXED_ZONE_COLORS.lineStrict,FIXED_ZONE_COLORS.line],
    'line-width':['match',['get','enforcement'],'PROHIBITED',FIXED_ZONE_COLORS.widthStrict,FIXED_ZONE_COLORS.width],
    'line-opacity':.92}})
  map.addLayer({id:'fixed-zone-refs',type:'circle',source:'operation-fixed-refs',paint:{
    'circle-radius':6,'circle-color':'#0f1b2a','circle-opacity':.55,
    'circle-stroke-color':'#c4b5fd','circle-stroke-width':2}})
  map.addLayer({id:'fixed-zone-ref-labels',type:'symbol',source:'operation-fixed-refs',minzoom:7,layout:{
    'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':11,'text-offset':[0,1.2],'text-anchor':'top'},
    paint:{'text-color':'#ddd6fe','text-halo-color':'#150f27','text-halo-width':2}})
  map.addLayer({id:'fixed-zone-labels',type:'symbol',source:'operation-fixed-zones',minzoom:6,layout:{
    'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':11,'text-offset':[0,-1.1],'text-anchor':'bottom'},
    paint:{'text-color':'#f0e6ff','text-halo-color':'#170f2c','text-halo-width':2}})
  map.addLayer({id:'wind-arrows-halo',type:'line',source:'operation-wind',
    paint:{'line-color':'#0d2b2a','line-width':5,'line-opacity':.35}})
  map.addLayer({id:'wind-arrows',type:'line',source:'operation-wind',paint:{'line-color':'#78e5cf','line-width':2,'line-opacity':.92}})
  map.addLayer({id:'cities-points',type:'circle',source:'operation-cities',paint:{'circle-radius':['case',['get','capital'],5,3],'circle-color':'#7acff2','circle-stroke-color':'#183b50','circle-stroke-width':2}})
  map.addLayer({id:'cities-labels',type:'symbol',source:'operation-cities',maxzoom:11,layout:{'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,-1],'text-anchor':'bottom'},paint:{'text-color':'#d7edff','text-halo-color':'#0c2031','text-halo-width':2}})
  map.addLayer({id:'pad-points',type:'circle',source:'operation-pads',minzoom:7.2,paint:{'circle-radius':['match',['get','kind'],'CITY_HUB',7,5],'circle-color':['match',['get','kind'],'CITY_HUB','#72e2ff','MERCHANT','#ffcb76','#eec67d'],'circle-stroke-color':'#fff2d8','circle-stroke-width':1}})
  map.addLayer({id:'pad-labels',type:'symbol',source:'operation-pads',minzoom:7.2,layout:{'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,1.2]},paint:{'text-color':'#ffe4b1','text-halo-color':'#172a38','text-halo-width':2}})
  map.addLayer({id:'event-lines',type:'line',source:'operation-events',
    filter:['!=',['get','closed'],true],
    layout:{'line-cap':'round','line-join':'round'},paint:{
      'line-color':['get','color'],'line-width':3.4,'line-opacity':.72,
      'line-dasharray':[3,1.6]}})
  map.addLayer({id:'event-lines-closed',type:'line',source:'operation-events',
    filter:['==',['get','closed'],true],
    layout:{'line-cap':'round','line-join':'round'},paint:{
      'line-color':['get','color'],'line-width':5.5,'line-opacity':.95,
      'line-dasharray':[1,0]}})
  map.addLayer({id:'event-halo',type:'circle',source:'operation-event-nodes',minzoom:7.2,paint:{
    'circle-radius':16,'circle-color':['get','color'],'circle-opacity':.14}})
  map.addLayer({id:'event-nodes',type:'circle',source:'operation-event-nodes',minzoom:7.2,paint:{
    'circle-radius':['case',['==',['get','closed'],true],8,6.5],
    'circle-color':'#0b1622','circle-stroke-color':['get','color'],
    'circle-stroke-width':['case',['==',['get','closed'],true],3.4,2.6]}})
  map.addLayer({id:'event-node-labels',type:'symbol',source:'operation-event-nodes',minzoom:7.2,layout:{
    'text-field':['concat',['get','cause'],' · ',['to-string',['get','count']],' 班'],
    'text-font':['Noto Sans Regular'],'text-size':11,'text-offset':[0,1.6],'text-anchor':'top'},
    paint:{'text-color':['get','color'],'text-halo-color':'#0b1622','text-halo-width':2.4}})
  map.addLayer({id:'observation-points',type:'circle',source:'operation-observations',paint:{
    'circle-radius':['case',['==',['get','level'],'NOMINAL'],3,5],
    'circle-color':['get','color'],'circle-stroke-color':'#0b1622','circle-stroke-width':1.4}})
  map.addLayer({id:'observation-labels',type:'symbol',source:'operation-observations',minzoom:5.6,filter:['!=',['get','level'],'NOMINAL'],layout:{
    'text-field':['get','station'],
    'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,-1.5],'text-anchor':'bottom'},
    paint:{'text-color':'#dff1fb','text-halo-color':'#0b1622','text-halo-width':2.2}})
  map.on('click','cities-points',e=>emit('select-city',e.features?.[0]?.properties.id))
  map.on('click','event-nodes',e=>{
    const key=e.features?.[0]?.properties?.key
    if(key)emit('select-event',key)
  })
  map.on('mouseenter','event-nodes',()=>{if(map?.getCanvas())map.getCanvas().style.cursor='pointer'})
  map.on('mouseleave','event-nodes',()=>{if(map?.getCanvas())map.getCanvas().style.cursor=''})
}
onMounted(()=>{
  try{
    map=new Map({container:host.value,style:structuredClone(cityStyle),center:[126,45],zoom:4.5,pitch:38,maxPitch:80,maxBounds:[[117,37],[136,55]],minZoom:3,maxZoom:19,canvasContextAttributes:{antialias:true},localIdeographFontFamily:'Microsoft YaHei, sans-serif',attributionControl:false})
    map.addControl(new NavigationControl({visualizePitch:true}),'top-right');map.addControl(new ScaleControl(),'bottom-right')
    map.on('click',e=>{
      if(!ready||!camera)return
      const x=e.point.x/map.getCanvas().clientWidth*2-1,y=1-e.point.y/map.getCanvas().clientHeight*2
      const inverse=camera.projectionMatrix.clone().invert(),near=new THREE.Vector3(x,y,-1).applyMatrix4(inverse),far=new THREE.Vector3(x,y,1).applyMatrix4(inverse)
      const ray=new THREE.Raycaster(near,far.sub(near).normalize())
      const hit=ray.intersectObjects(models.filter(m=>m.model.visible).map(m=>m.model),true)[0]
      if(hit){let o=hit.object;while(o&&!o.userData.flight)o=o.parent;if(o)emit('select-flight',o.userData.flight)}
    })
    map.on('dblclick',e=>{
      if(!ready||!camera)return
      const x=e.point.x/map.getCanvas().clientWidth*2-1,y=1-e.point.y/map.getCanvas().clientHeight*2
      const inverse=camera.projectionMatrix.clone().invert(),near=new THREE.Vector3(x,y,-1).applyMatrix4(inverse),far=new THREE.Vector3(x,y,1).applyMatrix4(inverse)
      const ray=new THREE.Raycaster(near,far.sub(near).normalize())
      const hit=ray.intersectObjects(models.filter(m=>m.model.visible).map(m=>m.model),true)[0]
      if(!hit)return
      let o=hit.object;while(o&&!o.userData.flight)o=o.parent
      const f=o?.userData?.flight
      if(f&&f.fromCity&&f.toCity)emit('open-corridor',{from:f.fromCity,to:f.toCity,mode:f.mode||''})
    })
    if(isOfflineMode()){
      basemapChannel.value=BASEMAP_CHANNEL_OFFLINE
      mapStatus.value=basemapStatusText(BASEMAP_CHANNEL_OFFLINE,{})
    }else{
      loadDeadline=setTimeout(()=>{
        if(basemapChannel.value!==BASEMAP_CHANNEL_PENDING)return
        basemapChannel.value=BASEMAP_CHANNEL_OFFLINE
        mapStatus.value=basemapStatusText(BASEMAP_CHANNEL_OFFLINE,{})
      },30000)
    }
    map.on('styleimagemissing',e=>{if(map.hasImage(e.id))return;const data=new Uint8Array(8*8*4);for(let i=0;i<64;i++){data[i*4]=150;data[i*4+1]=180;data[i*4+2]=195;data[i*4+3]=Math.hypot(i%8-3.5,Math.floor(i/8)-3.5)<3?255:0}map.addImage(e.id,{width:8,height:8,data})})
    map.on('error',e=>{
      const message=String(e?.error?.message||e?.error||'')
      const label=classifyMapError(message)
      mapIssues.value={...mapIssues.value,[label]:(mapIssues.value[label]||0)+1}
      console.warn(`City map resource [${label}]:`,message)
      const signal=basemapSignalFromError(message)
      if(signal==='no-tiles'){
        basemapTileFailures+=1
        const next=basemapChannelAfterSignal(basemapChannel.value,basemapTileFailures)
        if(next!==basemapChannel.value){
          basemapChannel.value=next
          setOfflineBasemapVisibility()
          error.value=''
          refreshMapStatus()
          emit('map-status',{status:basemapIsOffline(next)?'OFFLINE':'READY',channel:next,message:OFFLINE_BASEMAP_NOTICE})
        }
      }
      if(label==='TILE_404'||label==='GLYPH'||label==='ABORTED')return
      const total=Object.values(mapIssues.value).reduce((sum,n)=>sum+n,0)
      if(total<MAP_ERROR_THRESHOLD)return
      error.value=`${MAP_ERROR_TEXT[label]||MAP_ERROR_TEXT.UNKNOWN}（已记录 ${total} 次）`
      mapStatus.value='地图资源异常'
      emit('map-status',{status:'ERROR',message:error.value,issues:{...mapIssues.value}})
    })
    function reportMap(){
      if(disposed||!map.getSource('openmaptiles'))return
      if(map.isSourceLoaded('openmaptiles')){
        basemapTileFailures=0
        if(basemapChannel.value!==BASEMAP_CHANNEL_ONLINE){
          basemapChannel.value=BASEMAP_CHANNEL_ONLINE
          setOfflineBasemapVisibility()
          emit('map-status',{status:'READY',channel:BASEMAP_CHANNEL_ONLINE,buildings:buildingCount.value})
        }
      }
      buildingCount.value=map.getLayer('building-3d')?map.queryRenderedFeatures({layers:['building-3d']}).length:0
      if(map.isSourceLoaded('openmaptiles')&&!error.value){refreshMapStatus();emit('map-status',{status:'READY',buildings:buildingCount.value})}
      else if(basemapIsOffline(basemapChannel.value)&&!error.value){refreshMapStatus()}
    }
    map.on('idle',reportMap);map.on('sourcedata',reportMap)
map.on('move',()=>{syncFogLabels();syncRibbonLabels()})
    map.on('style.load',()=>{
      offlineBasemapLayers();setOfflineBasemapVisibility();sourceLayers();map.setLight({anchor:'viewport',color:'#d9ebff',intensity:.65,position:[1.5,150,55]})
      map.addLayer({id:'traffic-airspace',type:'custom',renderingMode:'3d',onAdd(_map,gl){
        scene=new THREE.Scene();camera=new THREE.Camera();group=new THREE.Group();scene.add(group);scene.add(new THREE.AmbientLight(0xffffff,2))
        const sun=new THREE.DirectionalLight(0xffffff,2);sun.position.set(0,-100,200);scene.add(sun)
        renderer=new THREE.WebGLRenderer({canvas:map.getCanvas(),context:gl,antialias:true});renderer.autoClear=false
        if(!origin){origin=MercatorCoordinate.fromLngLat([126,45],0);unit=origin.meterInMercatorCoordinateUnits()}
        ready=true;rebuild()
      },      render(gl,args){
        if(!ready||!origin)return
        const flagged=[],approvals=[],radarHits=[],bans=radarBanList.value
        labelSlots.length=0
        for(const {f,model} of models){
          const state=flightState(f,props.minute)
          const visible=state==='AIRBORNE'||state==='HOLD'||state==='PENDING'||f.id===props.selected?.id
          model.visible=visible
          if(!visible)continue
          const t=state==='PENDING'||state==='HOLD'?Math.max(f.departureMinute,props.minute):props.minute
          const p=atTime(f.points,t),next=atTime(f.points,t+.01);model.position.copy(world(p));const d=world(next).sub(world(p));if(d.lengthSq()>1e-12)model.rotation.z=Math.atan2(d.y,d.x)
          const alert=zoneIntrusionAt(f,props.minute),tint=model.userData.tint
          const ban=state==='AIRBORNE'&&bans.length?radarCoreIntrusionAt(p,bans):null
          const override=alert.level===ZONE_INTRUSION.PROHIBITED||ban?INTRUSION_TINT.PROHIBITED:tint.base
          for(const material of tint.materials)material.color.setHex(override)
          if(ban)radarHits.push({f,banId:ban.id})
          if(alert.level===ZONE_INTRUSION.PROHIBITED)flagged.push({f,alert})
          else if(alert.level===ZONE_INTRUSION.APPROVAL_REQUIRED)approvals.push(f.id)
          if(state==='AIRBORNE'&&f.id!==props.selected?.id){
            const text=vehicleLabel(f,p[2])
            if(text)labelSlots.push({id:f.id,model,bad:!!ban||alert.level===ZONE_INTRUSION.PROHIBITED,text})
          }
        }
        syncIntrusions(flagged,approvals.length)
        syncRadarIntrusions(radarHits)
        const transform=new THREE.Matrix4().makeTranslation(origin.x,origin.y,origin.z).scale(new THREE.Vector3(unit,-unit,unit))
        camera.projectionMatrix=new THREE.Matrix4().fromArray(args.defaultProjectionData.mainMatrix).multiply(transform)
        const selectedModel=models.find(m=>m.f.id===props.selected?.id&&m.model.visible)
        if(selectedModel){const p=selectedModel.model.position.clone().project(camera);selectedScreen.value=Math.abs(p.x)<1&&Math.abs(p.y)<1&&p.z>-1&&p.z<1?{x:(p.x+1)/2*map.getCanvas().clientWidth,y:(1-p.y)/2*map.getCanvas().clientHeight}:null}else selectedScreen.value=null
        const cw=map.getCanvas().clientWidth,ch=map.getCanvas().clientHeight
        labelCandidates.length=0
        for(const slot of labelSlots){
          const sp=labelProject.copy(slot.model.position).project(camera)
          if(!(Math.abs(sp.x)<1&&Math.abs(sp.y)<1&&sp.z>-1&&sp.z<1))continue
          labelCandidates.push({id:slot.id,text:slot.text,bad:slot.bad,
            x:(sp.x+1)/2*cw,y:(1-sp.y)/2*ch,priority:slot.bad?1:0,depth:sp.z})
        }
        syncVehicleLabels(selectVehicleLabels(labelCandidates,{max:MAX_VEHICLE_LABELS}))
        for(const material of lineMaterials)material.resolution.set(cw,ch)
        renderer.resetState();renderer.setViewport(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight);renderer.render(scene,camera)
      },onRemove(){disposeGroup();renderer?.dispose();ready=false}});focus()
    })
    observer=new ResizeObserver(()=>map.resize());observer.observe(host.value)
  }catch(e){error.value='无法创建三维城市地图：'+e.message;mapStatus.value='地图不可用'}
})
watch(()=>props.network,focus);watch(()=>props.city,focus)
watch(()=>[props.flights,props.selected,props.showCar,props.showDelivery],rebuild)
watch(()=>weatherBucket(props.minute),rebuild)
watch(()=>props.minute,()=>{map?.triggerRepaint();const followPts=trajectoryOf(props.selected);if(following.value&&followPts.length&&performance.now()-lastFollow>900){lastFollow=performance.now();const p=atTime(followPts,props.minute);map.setCenterElevation(p[2]);map.easeTo({center:lngLat(p),elevation:p[2],duration:850})}})
watch(()=>[props.weather,props.showWeather,props.showWind,props.showFog],()=>{drawWeather();paintFogCircles()})
watch(()=>[props.weather?.radar,props.showRadar],drawRadar)
watch(()=>[props.weather?.lowVisibility,props.showFog],drawFog)
watch(()=>[props.network,props.showFixedZones],drawFixedZones)
watch(()=>[props.alertFlights,props.network,props.showEvents],drawEvents)
watch(()=>[props.weather,props.network,props.showObservations],drawObservations)
watch(()=>props.ribbon,()=>{drawRibbon();syncRibbonLabels()},{deep:true})
function reloadMap(){error.value='';mapIssues.value={};basemapTileFailures=0;basemapChannel.value=BASEMAP_CHANNEL_PENDING;mapStatus.value=basemapStatusText(BASEMAP_CHANNEL_PENDING,{city:props.city});map?.setStyle(structuredClone(cityStyle))}
onUnmounted(()=>{disposed=true;clearTimeout(loadDeadline);observer?.disconnect();map?.remove()})
defineExpose({
  reset:focus,follow,
  focusEvent,
  basemapChannel:computed(()=>basemapChannel.value),
})

function paintFogCircles() {
  if (!map) return
  const data = props.showFog
    ? fogFeatureCollection(props.stationVisibility)
    : { type: 'FeatureCollection', features: [] }
  if (map.getSource('fog-rings')) {
    map.getSource('fog-rings').setData(data)
    syncFogLabels()
    syncRibbonLabels()
    return
  }
  map.addSource('fog-rings', { type: 'geojson', data })
  for (const layer of fogRingLayers()) map.addLayer(layer)
  syncFogLabels()
}

</script>
<template><div class="city-map-stack"><div class="city-map-shell"><div ref="host" class="city-map-canvas"/><div v-if="fogLabels.length" class="city-map-fog-labels" aria-hidden="true"><span v-for="l in fogLabels" :key="l.id" class="fog-label" :class="{ban:l.level==='BAN'}" :style="{left:l.x+'px',top:l.y+'px'}"><b>{{l.text}}</b><i>{{l.tier}}</i></span></div><div v-if="ribbonLabels.length" class="city-map-ribbon-labels" aria-hidden="true"><span v-for="l in ribbonLabels" :key="l.id" class="ribbon-label" :class="{caution:l.caution}" :style="{left:l.x+'px',top:l.y+'px'}"><b>{{l.p}}%</b><i>{{l.name}}</i></span></div><div v-if="vehicleLabels.length" class="city-map-labels" aria-hidden="true"><span v-for="l in vehicleLabels" :key="l.id" class="vehicle-label" :class="{intruding:l.bad}" :style="{left:l.x+'px',top:l.y+'px'}">{{l.text}}</span></div><button v-if="selectedScreen" class="selected-aircraft-label" :class="{intruding:!!selectedAlert}" :style="{left:selectedScreen.x+'px',top:selectedScreen.y+'px'}" @click="emit('select-flight',selected)">◉ {{selected.mode==='CAR'?'飞行汽车':'配送无人机'}} · {{altitudeText(atTime(selected.points,minute)[2])}} AGL<span v-if="selectedAlert"> · {{selectedAlert.label}}</span><span v-if="selectedBasisNote"> · {{selectedBasisNote}}</span></button><div v-if="intrusionTotal" class="city-map-intrusion" role="alert"><strong>▲ 本视图内 {{intrusionTotal}} 架载具位于禁入区<template v-if="intrusions.length&&radarIntrusions.length">（固定管制区 {{intrusions.length}} · 雷达内核 {{radarIntrusions.length}}）</template></strong><span v-for="row in intrusions.slice(0,4)" :key="'zone-'+row.id"><code>{{row.id}}</code> {{modeNames[row.mode]}} · {{row.label}}<template v-if="row.zone">（{{row.zone}}）</template></span><span v-for="row in radarIntrusions.slice(0,4)" :key="'radar-'+row.id"><code>{{row.id}}</code> {{modeNames[row.mode]}} · 位于雷达禁止进入内核（≥45 dBZ，{{row.banId}}）</span><span v-if="intrusionUnlisted>0">另有 {{intrusionUnlisted}} 架未列出</span><span v-if="hiddenProhibited" class="warn">有 {{hiddenProhibited}} 处禁入记录未随计划返回，须在班次详情逐条核对</span><span class="quiet">载具已在图上转为深橙色。固定管制区为本系统按已发布范围的比对；雷达内核为本系统对气象回波的比对（非官方空域管制命令）。两者均不构成飞行许可结论。</span></div><div v-else-if="showFixedZones||radarBanList.length" class="city-map-zone-monitor">越界监视：本视图内 0 架位于禁入区<span v-if="intrusionApprovals">；另有 {{intrusionApprovals}} 架位于须批准管制空域（按第十九条属可飞行，不计入告警）</span><span>；比对范围：<template v-if="showFixedZones">固定管制区</template><template v-if="showFixedZones&&radarBanList.length"> + </template><template v-if="radarBanList.length">雷达禁止进入内核 {{radarBanList.length}} 处（≥45 dBZ）</template></span><span v-if="fixedZoneFrozen" class="frozen-note" :title="fixedZoneFrozen">{{fixedZoneFrozen}}</span></div><div v-if="error" class="city-map-error" role="alert">{{error}}<span v-if="issueSummary" class="city-map-issue-breakdown">{{issueSummary}}</span><button @click="reloadMap">重载地图</button></div></div><div class="city-map-info"><div class="city-map-info-status" :class="{bad:!!error,offline:basemapIsOffline(basemapChannel)}"><span class="dot"/><span class="text">{{mapStatus}} <template v-if="city">· {{buildingCount}} 个可见建筑要素</template></span><span v-if="basemapIsOffline(basemapChannel)" class="badge">离线底图</span><span v-if="showRadar" class="radar-inline" :title="radarBadge.text" :class="{down:radarBadge.state==='DOWN',quiet:radarBadge.state==='QUIET',pending:radarBadge.state==='PENDING'}">{{radarBadge.short}}</span><span v-if="showFog" class="fog-inline" :title="fogBadge.text" :class="{down:fogBadge.state==='DOWN',quiet:fogBadge.state==='QUIET'}">{{fogBadge.short}}</span><span v-if="showEvents" class="event-inline" :title="eventBadge.text" :class="{down:eventBadge.state==='DOWN',quiet:eventBadge.state==='QUIET'}">{{eventBadge.short}}</span><button v-if="basemapIsOffline(basemapChannel)" @click="reloadMap">重试在线底图</button></div><div class="city-map-tools"><button @click="map?.easeTo({pitch:68,bearing:-25,duration:600})">立体视角</button><button @click="map?.easeTo({pitch:0,bearing:0,duration:600})">俯视</button><button @click="follow" :disabled="!trajectoryOf(selected).length">{{following?'取消跟随':'跟随航班'}}</button><button v-if="showRadar" :disabled="!radarBounds" :title="radarBounds?'放大到本帧回波所在范围':'本帧没有可定位的回波几何'" @click="locateRadar">定位回波</button><button v-if="showFog" :disabled="!fogBounds" :title="fogBounds?'放大到本帧雾区所在范围':'本帧没有可定位的雾区几何（既无雾区面，也无带坐标的实测站）'" @click="locateFog">定位雾区</button></div></div></div></template>
<style>
.city-map-stack{display:flex;flex-direction:column;min-height:0;flex:1}
.city-map-shell{position:relative;min-height:420px;flex:1;background:#102536;overflow:hidden}
.city-map-canvas{position:absolute;inset:0}
.city-map-info{flex:none;display:flex;align-items:center;gap:10px;flex-wrap:wrap;max-width:100%;overflow:hidden;
  padding:7px 12px;background:#0b1a28;border-top:1px solid #233848;font-size:10px}
.city-map-info-status{display:flex;align-items:center;gap:6px;row-gap:2px;flex-wrap:wrap;
  min-width:0;flex:1 1 320px;color:#8ed5d6;line-height:1.5}
.city-map-info-status .dot{width:6px;height:6px;border-radius:50%;background:#4fb8c9;flex:none}
.city-map-info-status.bad{color:#ffd0a8}.city-map-info-status.bad .dot{background:#e08a45}
.city-map-info-status.offline{color:#ffd9a3}.city-map-info-status.offline .dot{background:#d9963f}
.city-map-info-status .text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1 1 140px;
  min-width:0;flex:1 1 auto}
.city-map-info-status .badge{padding:1px 5px;border-radius:3px;background:#6b3d12;border:1px solid #d9963f;color:#ffe4bd;font-size:9px;white-space:nowrap;flex:none}
.city-map-info-status .radar-inline{padding:1px 6px;border-radius:3px;background:#241a4d;border:1px solid #6d5cc4;color:#cdbdfa;font-size:11px;line-height:15px;white-space:nowrap;flex:none}
.city-map-info-status .radar-inline.quiet{background:#101a2d;border-color:#33506d;color:#9fb6c9}
.city-map-info-status .radar-inline.down{background:#2a1f10;border-color:#8a5a2a;color:#e8c69a}
.city-map-info-status .radar-inline.pending{background:#141c24;border-color:#3c4a57;border-style:dashed;color:#a9b8c4}
.city-map-info-status .fog-inline{padding:1px 6px;border-radius:3px;background:#2a1a3d;border:1px solid #8b5cf6;color:#e9d5ff;font-size:11px;line-height:15px;white-space:nowrap;flex:none}
.city-map-info-status .fog-inline.quiet{background:#161a20;border-color:#3a4250;color:#98a2b3}
.city-map-info-status .fog-inline.down{background:#2a1f10;border-color:#8a5a2a;color:#e8c69a}
.city-map-info-status .event-inline{padding:1px 6px;border-radius:3px;background:#33230f;border:1px solid #a8712f;color:#ffd9a8;font-size:11px;line-height:15px;white-space:nowrap;flex:none}
.city-map-info-status .event-inline.quiet{background:#101a2d;border-color:#33506d;color:#9fb6c9}
.city-map-info-status .event-inline.down{background:#3a2712;border-color:#e08a45;color:#ffe0b8}
.city-map-info-status button{padding:3px 8px!important;font-size:10px!important;flex:none}
.city-map-tools{display:flex;gap:5px;align-items:center;flex-wrap:wrap;flex:none}
.city-map-tools button{padding:5px 9px!important;font-size:10px!important}
.city-map-error{position:absolute;top:12px;left:12px;right:12px;max-height:38%;overflow:auto;background:#4a3418e6;color:#ffe6cc;padding:12px;border-radius:6px;font-size:12px;display:flex;flex-direction:column;gap:6px;align-items:flex-start;z-index:4}
.city-map-issue-breakdown{font-size:10px;color:#e6c39a;line-height:1.6}
.maplibregl-ctrl-attrib{font-size:9px!important}.maplibregl-canvas{outline:none}.maplibregl-popup-content{background:#142c3c;color:#dceafa}
.selected-aircraft-label{position:absolute;transform:translate(-50%,-140%);background:#103044e8!important;border:1px solid #ffcf83!important;color:#ffe5b4!important;font-size:10px!important;padding:5px 8px!important;pointer-events:auto;white-space:nowrap;max-width:230px;overflow:hidden;text-overflow:ellipsis;z-index:6}
.city-map-intrusion{position:absolute;top:12px;right:60px;width:min(340px,44%);max-height:44%;overflow:auto;background:#4a3418f2;border:1px solid #e08a45;border-radius:7px;padding:9px 11px;display:flex;flex-direction:column;gap:4px;font-size:10px;line-height:1.6;color:#ffe6cc;z-index:5}
.city-map-intrusion strong{font-size:11px;color:#ffc98a;letter-spacing:.5px}
.city-map-intrusion code{font-size:9px;color:#ffd9a8}
.city-map-intrusion .warn{color:#ffd27a}
.city-map-intrusion .quiet{color:#e6c39a;font-size:9px;border-top:1px solid #8a5a2a;padding-top:5px}
.selected-aircraft-label.intruding{background:#4a3418f2!important;border-color:#e08a45!important;color:#ffe6cc!important}
.city-map-labels{position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:3}
.vehicle-label{position:absolute;transform:translate(-50%,-140%);background:#0d2436d9;border:1px solid #3d6b86;border-radius:3px;color:#bfe3f2;font-size:10px;line-height:1;padding:3px 5px;white-space:nowrap;font-variant-numeric:tabular-nums}
.vehicle-label.intruding{background:#4a3418eb;border-color:#e08a45;color:#ffe6cc}
.city-map-fog-labels{position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:4}
.city-map-ribbon-labels{position:absolute;inset:0;pointer-events:none}
.ribbon-label{position:absolute;transform:translate(-50%,-50%);display:flex;align-items:baseline;gap:4px;
  padding:1px 6px;border-radius:3px;background:rgba(6,18,28,.78);border:1px solid rgba(76,141,255,.45);
  font-size:10.5px;line-height:1.5;white-space:nowrap;color:#cfe4f5}
.ribbon-label b{font-weight:600;color:#9fc8ff;font-variant-numeric:tabular-nums}
.ribbon-label i{font-style:normal;font-size:10px;color:#8fb3c9}
.ribbon-label.caution{border-color:rgba(232,163,61,.5)}
.ribbon-label.caution b{color:#f0c07a}
.fog-label{position:absolute;transform:translate(-50%,-50%);display:flex;flex-direction:column;
  align-items:center;gap:1px;padding:2px 6px;border-radius:4px;
  background:rgba(24,12,38,.78);border:1px solid rgba(139,92,246,.55);
  color:#e9d5ff;font-size:10px;line-height:1.25;white-space:nowrap;
  font-variant-numeric:tabular-nums;text-shadow:0 1px 2px rgba(0,0,0,.85)}
.fog-label b{font-weight:600}
.fog-label i{font-style:normal;font-size:9px;color:#c4b5fd;letter-spacing:.02em}
.fog-label.ban{border-color:rgba(139,92,246,.95);background:rgba(38,16,60,.86)}
.city-map-zone-monitor{position:absolute;top:12px;right:60px;max-width:min(340px,44%);background:#0b1d2dcc;border:1px solid #335c6d;border-radius:6px;padding:5px 9px;color:#8fb6c4;font-size:10px;line-height:1.6;pointer-events:none;z-index:5}
@media(max-width:1180px){
  .city-map-intrusion,.city-map-zone-monitor{top:12px;right:12px;left:12px;width:auto;max-width:none;max-height:36%}
  .city-map-error{top:auto;bottom:12px;max-height:32%}
  .city-map-info-status .text{white-space:normal}
}
</style>
