<script setup>
import {ref,onMounted,onUnmounted,watch} from 'vue'
import * as THREE from 'three'
import {Map,NavigationControl,ScaleControl,MercatorCoordinate,setWorkerUrl} from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import cityStyle from '../map/city-map-style.json'
import {atTime,flightState} from '../traffic/runtime.js'
import {lngLat,geographicGeometry,collection,feature} from '../traffic/geography.js'
const props=defineProps({network:Object,flights:Array,minute:Number,city:String,selected:Object,weather:Object,showCar:Boolean,showDelivery:Boolean,showWeather:Boolean,showWind:Boolean})
const emit=defineEmits(['select-city','select-flight','map-status'])
setWorkerUrl(mapWorkerUrl)
const selectedScreen=ref(null)
const host=ref(null),error=ref(''),following=ref(false),buildingCount=ref(0),mapStatus=ref('正在载入城市地图'),heightFactor=ref(1)
let map,scene,renderer,camera,group,observer,origin,unit,models=[],ready=false,lastFollow=0,disposed=false,loadDeadline
function setData(id,data){map?.getSource(id)?.setData(data)}
function scoped(f){return (f.mode==='CAR'?props.showCar:props.showDelivery)&&(!props.city||[f.fromCity,f.toCity].includes(props.city))}
function world(p){const m=MercatorCoordinate.fromLngLat(lngLat(p),(p[2]||0)*heightFactor.value);return new THREE.Vector3((m.x-origin.x)/unit,-(m.y-origin.y)/unit,m.z/unit)}
function disposeGroup(){if(!group)return;group.traverse(o=>{o.geometry?.dispose();if(o.material)(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose())});group.clear();models=[]}
function addLine(points,color,opacity=1,thick=false){
  const positions=points.map(world)
  group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(positions),new THREE.LineBasicMaterial({color,transparent:true,opacity})))
  if(thick){
    const radius=props.city?2.4:200
    for(let i=1;i<positions.length;i++){
      const a=positions[i-1],b=positions[i],d=b.clone().sub(a);if(d.length()<.001)continue
      const tube=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,d.length(),6),new THREE.MeshBasicMaterial({color,transparent:true,opacity:.85}))
      tube.position.copy(a).add(b).multiplyScalar(.5);tube.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),d.normalize());group.add(tube)
    }
  }
}
function vehicle(mode){
  const g=new THREE.Group(),tint=mode==='CAR'?0x59e5ff:0xffce76
  g.add(new THREE.Mesh(new THREE.BoxGeometry(mode==='CAR'?7:3,3,1.5),new THREE.MeshBasicMaterial({color:tint})))
  if(mode==='CAR'){const cabin=new THREE.Mesh(new THREE.BoxGeometry(3.5,2.7,1.2),new THREE.MeshBasicMaterial({color:0x234957}));cabin.position.z=1;g.add(cabin)}
  for(const x of [-3.5,3.5])for(const y of [-3.5,3.5]){
    const arm=new THREE.Mesh(new THREE.CylinderGeometry(.16,.16,5,5),new THREE.MeshBasicMaterial({color:tint}));arm.position.set(x/2,y/2,0);arm.rotation.z=-Math.atan2(x,y);g.add(arm)
    const rotor=new THREE.Mesh(new THREE.TorusGeometry(mode==='CAR'?1.8:1.2,.12,5,16),new THREE.MeshBasicMaterial({color:tint}));rotor.position.set(x,y,.4);g.add(rotor)
  }
  g.scale.setScalar(props.city?3:350);return g
}
function rebuild(){
  if(!ready||!props.network)return
  disposeGroup()
  const c=props.network.cities.find(c=>c.id===props.city)
  origin=MercatorCoordinate.fromLngLat(c?.coordinate||[126,45],0);unit=origin.meterInMercatorCoordinateUnits()
  for(const r of props.network.routes){
    if(!r.path||(r.mode==='CAR'?!props.showCar:!props.showDelivery)||(props.city&&![r.fromCity,r.toCity].includes(props.city)))continue
    const f=(props.flights||[]).find(f=>f.routeId===r.id&&f.points.length&&f.direction===0)
    addLine(f?.points||r.path.map(p=>[...p,r.mode==='CAR'?400:90]),r.mode==='CAR'?0x51a3bf:0xb69b64,.35)
  }
  for(const f of props.flights||[]){
    if(!f.points.length||!scoped(f))continue
    const selected=f.id===props.selected?.id,airborne=flightState(f,props.minute)==='AIRBORNE'
    if(airborne||selected)addLine(f.points,selected?0xf2faff:f.mode==='CAR'?0x5cdbff:0xffd085,selected?1:.85,selected)
    if(airborne||selected||(f.departureMinute>=props.minute&&f.departureMinute<props.minute+2)){const model=vehicle(f.mode);model.userData.flight=f;group.add(model);models.push({f,model})}
  }
  setData('operation-cities',collection(props.network.cities.map(c=>feature({type:'Point',coordinates:c.coordinate},{id:c.id,name:c.name,capital:c.capital}))))
  const pads=[],seen=new Set()
  if(c)for(const r of props.network.routes.filter(r=>r.mode==='DELIVERY'&&r.fromCity===c.id))for(const [i,p] of [r.fromXY,r.toXY].entries()){
    const key=p.join(',');if(seen.has(key))continue;seen.add(key)
    pads.push(feature({type:'Point',coordinates:lngLat(p)},{name:r.name.split(' · ')[1].split('—')[i]}))
  }
  setData('operation-pads',collection(pads));drawWeather();map.triggerRepaint()
}
function drawWeather(){
  if(!ready)return
  const fields=[],risks=[],winds=[]
  if(props.showWeather)for(const c of props.weather?.cells||[])for(const [kind,geometry] of [['FIELD',c.field],['BAN',c.ban],['CAUTION',c.caution]]){
    if(!['Polygon','MultiPolygon'].includes(geometry.type))continue
    const f=feature(geographicGeometry(geometry),{id:c.id,kind,weather:c.kind,height:(kind==='BAN'?650:450)*heightFactor.value})
    if(kind==='FIELD')fields.push(f);else risks.push(f)
  }
  if(props.showWind)for(const w of props.weather?.winds||[]){
    const n=Math.hypot(w.u,w.v),size=props.city?120:4000,dx=w.u/n*size,dy=w.v/n*size,[x,y]=w.xy
    winds.push(feature({type:'MultiLineString',coordinates:[[[x,y],[x+dx,y+dy]],[[x+dx*.65-dy*.2,y+dy*.65+dx*.2],[x+dx,y+dy],[x+dx*.65+dy*.2,y+dy*.65-dx*.2]]].map(line=>line.map(lngLat))}))
  }
  setData('operation-fields',collection(fields));setData('operation-risks',collection(risks));setData('operation-wind',collection(winds))
}
function focus(){
  if(!map||!props.network)return
  following.value=false;map.setCenterClampedToGround(true);map.setCenterElevation(0)
  const c=props.network.cities.find(c=>c.id===props.city);heightFactor.value=c?1:60
  if(c)map.flyTo({center:c.coordinate,zoom:14.4,pitch:62,bearing:-22,duration:1000})
  else map.fitBounds([[118.7,38.6],[135.1,53.6]],{padding:45,pitch:20,bearing:0,duration:900})
  rebuild()
}
function follow(){
  if(!props.selected?.points.length)return
  following.value=!following.value
  if(following.value){const p=atTime(props.selected.points,props.minute);map.setCenterClampedToGround(false);map.setCenterElevation(p[2]*heightFactor.value);map.flyTo({center:lngLat(p),elevation:p[2]*heightFactor.value,zoom:16.5,pitch:62,bearing:-25,duration:900})}
  else{map.setCenterClampedToGround(true);map.setCenterElevation(0)}
}
function sourceLayers(){
  for(const id of ['operation-cities','operation-pads','operation-fields','operation-risks','operation-wind'])map.addSource(id,{type:'geojson',data:collection()})
  map.addLayer({id:'weather-fields',type:'fill',source:'operation-fields',paint:{'fill-color':['match',['get','weather'],'STORM','#ac81ff','WIND','#45c4a5','#368bdd'],'fill-opacity':.2}})
  map.addLayer({id:'weather-risk-columns',type:'fill-extrusion',source:'operation-risks',paint:{'fill-extrusion-color':['match',['get','kind'],'BAN','#ff6075','#ffbd57'],'fill-extrusion-height':['get','height'],'fill-extrusion-opacity':.19}})
  map.addLayer({id:'wind-arrows',type:'line',source:'operation-wind',paint:{'line-color':'#66b9aa','line-width':1.2,'line-opacity':.7}})
  map.addLayer({id:'cities-points',type:'circle',source:'operation-cities',paint:{'circle-radius':['case',['get','capital'],5,3],'circle-color':'#7acff2','circle-stroke-color':'#183b50','circle-stroke-width':2}})
  map.addLayer({id:'cities-labels',type:'symbol',source:'operation-cities',maxzoom:11,layout:{'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,-1],'text-anchor':'bottom'},paint:{'text-color':'#d7edff','text-halo-color':'#0c2031','text-halo-width':2}})
  map.addLayer({id:'pad-points',type:'circle',source:'operation-pads',paint:{'circle-radius':6,'circle-color':'#eec67d','circle-stroke-color':'#fff2d8','circle-stroke-width':1}})
  map.addLayer({id:'pad-labels',type:'symbol',source:'operation-pads',layout:{'text-field':['get','name'],'text-font':['Noto Sans Regular'],'text-size':12,'text-offset':[0,1.2]},paint:{'text-color':'#ffe4b1','text-halo-color':'#172a38','text-halo-width':2}})
  map.on('click','cities-points',e=>emit('select-city',e.features?.[0]?.properties.id))
}
onMounted(()=>{
  try{
    map=new Map({container:host.value,style:structuredClone(cityStyle),center:[126,45],zoom:4.5,pitch:20,maxPitch:80,maxBounds:[[117,37],[136,55]],minZoom:3,maxZoom:19,canvasContextAttributes:{antialias:true},localIdeographFontFamily:'Microsoft YaHei, sans-serif',attributionControl:{compact:true}})
    map.addControl(new NavigationControl({visualizePitch:true}),'top-right');map.addControl(new ScaleControl(),'bottom-right')
    map.on('click',e=>{
      if(!ready||!camera)return
      const x=e.point.x/map.getCanvas().clientWidth*2-1,y=1-e.point.y/map.getCanvas().clientHeight*2
      const inverse=camera.projectionMatrix.clone().invert(),near=new THREE.Vector3(x,y,-1).applyMatrix4(inverse),far=new THREE.Vector3(x,y,1).applyMatrix4(inverse)
      const ray=new THREE.Raycaster(near,far.sub(near).normalize())
      const hit=ray.intersectObjects(models.filter(m=>m.model.visible).map(m=>m.model),true)[0]
      if(hit){let o=hit.object;while(o&&!o.userData.flight)o=o.parent;if(o)emit('select-flight',o.userData.flight)}
    })
    loadDeadline=setTimeout(()=>{if(mapStatus.value==='正在载入城市地图'){error.value='城市地图载入超时，可重载地图；班次台账仍可使用。';mapStatus.value='地图载入超时'}},30000)
    map.on('styleimagemissing',e=>{if(map.hasImage(e.id))return;const data=new Uint8Array(8*8*4);for(let i=0;i<64;i++){data[i*4]=150;data[i*4+1]=180;data[i*4+2]=195;data[i*4+3]=Math.hypot(i%8-3.5,Math.floor(i/8)-3.5)<3?255:0}map.addImage(e.id,{width:8,height:8,data})})
    map.on('error',e=>{console.warn('City map resource:',e.error?.message);error.value='部分城市地图资源载入失败，请检查网络后重试。';mapStatus.value='地图资源异常';emit('map-status',{status:'ERROR',message:error.value})})
    function reportMap(){
      if(disposed||!map.getSource('openmaptiles'))return
      buildingCount.value=map.getLayer('building-3d')?map.queryRenderedFeatures({layers:['building-3d']}).length:0
      if(map.isSourceLoaded('openmaptiles')&&!error.value){mapStatus.value=props.city?(buildingCount.value?'城市道路与立体建筑已载入':'城市地图已载入 · 当前范围无建筑要素'):'全域城市地图已载入';emit('map-status',{status:'READY',buildings:buildingCount.value})}
    }
    map.on('idle',reportMap);map.on('sourcedata',reportMap)
    map.on('style.load',()=>{
      sourceLayers();map.setLight({anchor:'viewport',color:'#d9ebff',intensity:.65,position:[1.5,150,55]})
      map.addLayer({id:'traffic-airspace',type:'custom',renderingMode:'3d',onAdd(_map,gl){
        scene=new THREE.Scene();camera=new THREE.Camera();group=new THREE.Group();scene.add(group);scene.add(new THREE.AmbientLight(0xffffff,2))
        const sun=new THREE.DirectionalLight(0xffffff,2);sun.position.set(0,-100,200);scene.add(sun)
        renderer=new THREE.WebGLRenderer({canvas:map.getCanvas(),context:gl,antialias:true});renderer.autoClear=false;ready=true;rebuild()
      },render(gl,args){
        if(!ready)return
        for(const {f,model} of models){model.visible=flightState(f,props.minute)==='AIRBORNE';if(model.visible){const p=atTime(f.points,props.minute),next=atTime(f.points,props.minute+.01);model.position.copy(world(p));const d=world(next).sub(world(p));model.rotation.z=Math.atan2(d.y,d.x)}}
        const transform=new THREE.Matrix4().makeTranslation(origin.x,origin.y,origin.z).scale(new THREE.Vector3(unit,-unit,unit))
        camera.projectionMatrix=new THREE.Matrix4().fromArray(args.defaultProjectionData.mainMatrix).multiply(transform)
        const selectedModel=models.find(m=>m.f.id===props.selected?.id&&m.model.visible)
        if(selectedModel){const p=selectedModel.model.position.clone().project(camera);selectedScreen.value=Math.abs(p.x)<1&&Math.abs(p.y)<1&&p.z>-1&&p.z<1?{x:(p.x+1)/2*map.getCanvas().clientWidth,y:(1-p.y)/2*map.getCanvas().clientHeight}:null}else selectedScreen.value=null
        renderer.resetState();renderer.setViewport(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight);renderer.render(scene,camera)
      },onRemove(){disposeGroup();renderer?.dispose();ready=false}});focus()
    })
    observer=new ResizeObserver(()=>map.resize());observer.observe(host.value)
  }catch(e){error.value='无法创建三维城市地图：'+e.message;mapStatus.value='地图不可用'}
})
watch(()=>props.network,focus);watch(()=>props.city,focus)
watch(()=>[props.flights,props.selected,props.showCar,props.showDelivery],rebuild)
watch(()=>Math.floor(props.minute/2),rebuild)
watch(()=>props.minute,()=>{map?.triggerRepaint();if(following.value&&props.selected?.points.length&&performance.now()-lastFollow>900){lastFollow=performance.now();const p=atTime(props.selected.points,props.minute);map.setCenterElevation(p[2]*heightFactor.value);map.easeTo({center:lngLat(p),elevation:p[2]*heightFactor.value,duration:850})}})
watch(()=>[props.weather,props.showWeather,props.showWind],drawWeather)
watch(heightFactor,()=>{rebuild();drawWeather()})
function reloadMap(){error.value='';mapStatus.value='正在载入城市地图';map?.setStyle(structuredClone(cityStyle))}
onUnmounted(()=>{disposed=true;clearTimeout(loadDeadline);observer?.disconnect();map?.remove()})
defineExpose({reset:focus,follow})
</script>
<template><div class="city-map-shell"><div ref="host" class="city-map-canvas"/><button v-if="selectedScreen" class="selected-aircraft-label" :style="{left:selectedScreen.x+'px',top:selectedScreen.y+'px'}" @click="emit('select-flight',selected)">◉ {{selected.mode==='CAR'?'飞行汽车':'配送无人机'}} · {{Math.round(atTime(selected.points,minute)[2])}} m</button><div class="city-map-status" :class="{bad:!!error}">{{mapStatus}} <span v-if="city">· {{buildingCount}} 个可见建筑要素</span></div><div class="city-map-tools"><button @click="map?.easeTo({pitch:68,bearing:-25,duration:600})">立体视角</button><button @click="map?.easeTo({pitch:0,bearing:0,duration:600})">俯视</button><button @click="follow" :disabled="!selected?.points.length">{{following?'取消跟随':'跟随航班'}}</button><label>高度显示 <select v-model.number="heightFactor"><option :value="1">真实比例</option><option :value="3">3 倍</option><option :value="60">全域 60 倍</option></select></label></div><div class="city-map-note">真实城市矢量地图 · 运行数据模拟 · 飞行器符号放大<br>建筑缺失高度按地图源估算，未作为实机避障依据</div><div v-if="error" class="city-map-error" role="alert">{{error}}<button @click="reloadMap">重载地图</button></div></div></template>
<style>
.city-map-shell{position:relative;min-height:520px;flex:1;background:#102536;overflow:hidden}.city-map-canvas{position:absolute;inset:0}.city-map-status{position:absolute;top:12px;left:12px;background:#0a1d30d9;border:1px solid #335c6d;padding:7px 10px;border-radius:6px;color:#8ed5d6;font-size:11px;max-width:80%}.city-map-status.bad{color:#ffb4b4}.city-map-tools{position:absolute;bottom:52px;left:12px;display:flex;gap:5px;align-items:center;flex-wrap:wrap;font-size:10px;background:#0b1d2dd9;border-radius:7px;padding:5px}.city-map-tools button,.city-map-tools select{padding:6px 8px!important;font-size:10px!important}.city-map-tools label{display:flex;gap:4px;align-items:center;color:#b2cbdc}.city-map-note{position:absolute;bottom:7px;left:12px;color:#9db1c3;font-size:9px;line-height:1.6;pointer-events:none;background:#0d2230b5;padding:3px 5px}.city-map-error{position:absolute;top:65px;left:12px;right:50px;background:#532d37e6;color:#ffd6df;padding:12px;border-radius:6px;font-size:12px}.maplibregl-ctrl-attrib{font-size:9px!important}.maplibregl-canvas{outline:none}.maplibregl-popup-content{background:#142c3c;color:#dceafa}
.selected-aircraft-label{position:absolute;transform:translate(-50%,-140%);background:#103044e8!important;border:1px solid #ffcf83!important;color:#ffe5b4!important;font-size:10px!important;padding:5px 8px!important;pointer-events:auto;z-index:1}
</style>
