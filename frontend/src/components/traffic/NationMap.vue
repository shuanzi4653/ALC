<script setup>
import {computed,nextTick,onMounted,onUnmounted,reactive,ref,watch} from 'vue'
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
  // 本地连续时刻（浮点分钟）。播放时它比 minute 大零点几分钟，用来把"每分钟一跳"
  // 的班次位置补成连续移动；不播放时等于 minute（-1 表示不启用本地推进）。
  frameMinute:{type:Number,default:-1},
  radarOn:{type:Boolean,default:true},
  fogOn:{type:Boolean,default:true},
  terrainOn:{type:Boolean,default:true},
  tilt:{type:Boolean,default:false},
  density:{type:String,default:'full'},
  selectedId:{type:String,default:''},
  selectedCorridor:{type:String,default:''},
  virtualMode:{type:Boolean,default:false},
  followId:{type:String,default:''},
  // 净空层（DERIVED）：bands.LIMIT / bands.RUNWAY 是已裁好的环，直接投影画圈。
  // 走独立接口按需取，故这里允许为 null —— 没取到就什么都不画，不假装有。
  zoneBands:{type:Object,default:null},
  zonePolicy:{type:String,default:'APPROVAL_REQUIRED'},
  // 'ops' 运行视角 | 'airspace' 空域视角：同一套几何，换主体（航线让位给净空圈）
  audience:{type:String,default:'ops'},
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
    const changed=VIEW.w!==Math.round(rect.width)||VIEW.h!==Math.round(rect.height)
    VIEW.w=Math.round(rect.width)
    VIEW.h=Math.round(rect.height)
    // 画布尺寸一变（最典型：选中班次后详情卡张开，把地图压矮一半），
    // 旧的 pan 就不再对应新的 viewBox，整幅图会飞出画布。
    // 选中态下重新聚焦；否则保持原样，别把用户手动缩放的视野偷偷重置。
    if(changed) requestAnimationFrame(()=>{
      if(props.selectedId&&pickedLine.value) focusPts(pickedLine.value.pts)
    })
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
    if(out.length>64) return out
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
  return tilesFor(t,4,5)
})

// —— 回波环：按屏幕尺寸分流 ——
// 这里踩过一个坑：强回波是按 0.14° 网格聚出来的，最小的环只有 0.17°×0.39°，
// 在国家级缩放下不足 2×4 px。这种尺寸再按 0.9 px 描边，描边宽度已经接近环本身，
// 画出来就是一个**空心小方框**——地图上看着像贴了个红标签，完全不像回波。
// 所以分两路：屏幕上够大的环才描边（等值线），小到看不出形状的直接填实。
const radarRings=computed(()=>{
  if(!props.radarOn) return []
  const bands=props.data?.radar?.bands||{}
  const out=[]
  for(const level of ['CONVECTIVE','STRONG']){
    for(const ring of bands[level]||[]){
      if(!ring||ring.length<3) continue
      let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9
      for(const [lon,lat] of ring){
        const [x,y]=project(lon,lat)
        if(x<minX)minX=x; if(x>maxX)maxX=x
        if(y<minY)minY=y; if(y>maxY)maxY=y
      }
      const size=Math.max(maxX-minX,maxY-minY)
      out.push({
        level,
        d:toPath({type:'Polygon',coordinates:[ring]},project),
        small:size<15,
      })
    }
  }
  return out
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

// —— 净空层：287 个限制区 + 10 条跑道梯形（DERIVED，规则化生成） ——
// 只有切到空域视角、或三维省/市层才取几何，取不到就返回空数组：
// 空图层和"没有净空"是两回事，界面上另有 zoneErr 说明，不在这里编。
const zonePolys=computed(()=>{
  const bands=props.zoneBands
  if(!bands) return []
  const v=box.value
  const out=[]
  const push=(rows,kind)=>{
    let count=0
    for(const ring of rows||[]){
      if(!ring||ring.length<3) continue
      // 只画落在当前视口里的：全国层 287 个圈全画也行，但视野外的路径纯浪费
      let hit=false
      for(const [lon,lat] of ring){
        if(lon>=v.lon0-.4&&lon<=v.lon1+.4&&lat>=v.lat0-.4&&lat<=v.lat1+.4){hit=true;break}
      }
      if(!hit) continue
      if(count>=160) break
      count+=1
      out.push({kind,d:toPath({type:'Polygon',coordinates:[ring]},project)})
    }
  }
  push(bands.LIMIT,'LIMIT')
  push(bands.RUNWAY,'RWY')
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
    // 必须显式闭合：SVG 的 fill 会自动封口，但 stroke 不会。
    // 少了这一条，省界、回波环、雾区、南海小图四处都会缺最后一条边 ——
    // 省界被邻省盖住看不出来，回波环本来就小，缺一条边就完全不成形。
    d+='Z'
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
const INSET={x:8,y:99999,w:120,h:120,lon0:105.5,lon1:124.5,lat0:3.2,lat1:24.8}
// 右下角、位于浮层监视条之上：这块小图只证明版图完整，不承载业务，
// 所以能做小就做小，别占主图的注意力。
const insetBox=computed(()=>({...INSET,
  x:Math.max(8,VIEW.w-INSET.w-10),
  y:Math.max(8,VIEW.h-INSET.h-96)}))
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
const lineWidth=computed(()=>({nation:.62,region:.95,province:1.6,city:1.4}[level.value]||1))

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
  // 航线方向箭头：取约 48% 处那一段的切线角。整条线只放一个，
  // 多了会和"航班图标"抢注意力 —— 箭头说明的是"这条线往哪飞"，不是"现在在哪"。
  // 箭头只在"看得见方向"的线段上放：全国层 492 条线平均只有 20–40 px，
  // 每条都插箭头等于在图上撒三角。所以按屏幕长度取阈值，级别越近阈值越低。
  let arrow=null
  const arrowMin=level.value==='nation'?34:(level.value==='region'?18:5)
  let screenLen=0
  for(let i=1;i<points.length;i++){
    screenLen+=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1])
  }
  if(points.length>=2&&screenLen>=arrowMin){
    const at=Math.round((points.length-1)*0.5)
    const a=points[Math.max(0,at-1)], b=points[Math.min(points.length-1,at)]
    const dx=b[0]-a[0], dy=b[1]-a[1]
    if(Math.hypot(dx,dy)>0.8){
      arrow={x:points[at][0],y:points[at][1],angle:Math.atan2(dy,dx)*180/Math.PI}
    }
  }
  return {id:row.id,d,pts:points,arrow,detour,blocked:!!row.borderBlocked,
    fromName:row.fromName,toName:row.toName,kindLabel:row.kindLabel,lengthKm:row.lengthKm,
    selected:props.selectedCorridor===row.id}
}))

// —— 节点与建筑 ——
function shortName(name){
  // 省级与市级共用一个规则：先剥自治区/特区/省，再剥市/地区/盟/自治州。
  // 两处（地图标签、右栏列表）必须一致，否则同一个省在图上叫"新疆"、在右栏叫"新疆维吾尔自治区"。
  return (name||'')
    .replace(/维吾尔自治区$/,'').replace(/壮族自治区$/,'').replace(/回族自治区$/,'')
    .replace(/特别行政区$/,'').replace(/自治区$/,'').replace(/省$/,'')
    .replace(/(市|地区|盟|自治州|自治县)$/,'')
    .replace(/(朝鲜族|蒙古族|藏族|苗族|侗族|彝族|哈尼族|壮族|傣族|白族|土家族|布依族|傈僳族|景颇族|羌族|回族|维吾尔族)$/,'')
}
const nodes=computed(()=>{
  const all=(props.data?.nodes||[])
  // 全国层把 319 个城市全部画出来：这一层不画航线之后，城市点就是主角。
  // 三级用大小区分（省会 > 机场城市 > 一般），不再靠"藏起来"减噪。
  const list=all
  return list.map(node=>{
    const [x,y]=project(node.lon,node.lat)
    return {...node,x,y,short:shortName(node.name),
      tower:node.rank===1?17:(node.rank===2?11:7)}
  })
})
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
// —— 航班 ——
// 本地推进量（分钟）：把两次后端快照之间的空档补上，位置才连续。
// 上限 6 分钟 —— 再多就是外推，不是数据了；超过就让后端快照接管。
const advanceMin=computed(()=>{
  const base=props.frameMinute>=0?props.frameMinute:props.minute
  const adv=base-props.minute
  return adv>0?Math.min(6,adv):0
})

const flightDots=computed(()=>{
  const out=[]
  const adv=advanceMin.value
  for(const f of props.flights||[]){
    // 延期的班次**不画**：它还没起飞，画在航路上等于告诉人"这架已经在飞"。
    // 它仍然在台账与处置页里，也仍然计入"延期 N 架"。
    if(f.decision==='HOLD') continue
    let lon=f.lon,lat=f.lat
    // 沿当前航向按速度外推：比"起点→终点直线插值"准，飞机不会飘离真实航路
    // （航路是弯的，直线插值在转弯段会明显错位）。
    if(adv>0&&Number.isFinite(lon)&&Number.isFinite(lat)&&f.speedKmh){
      const dKm=f.speedKmh*adv/60
      const h=(f.heading||0)*Math.PI/180
      lat-=dKm*Math.sin(h)/110.574
      lon+=dKm*Math.cos(h)/(111.32*Math.max(.2,Math.cos(lat*Math.PI/180)))
    }
    const [x,y]=project(lon,lat)
    // 当前进度：后端给的 progress + 本地推进的那一段
    const p=(f.progress||0)+adv/Math.max(1,f.durationMin||1)
    // 进站淡出、离站淡入 —— "飞出去就没了"，而不是从图上突然跳掉，
    // 这是 Flightradar24 那种"活的"观感的来源。命中判据只在这一小段里失效。
    const fade=p>=.985?Math.max(0,(1-p)/.015):(p<=.02?Math.max(.25,p/.02):1)
    out.push({...f,x,y,progressNow:Math.max(0,Math.min(1,p)),fade,
      selected:props.selectedId===f.id,
      detour:f.status==='DELAYED',bad:f.riskLevel==='HIGH'})
  }
  return out
})

// —— 选中的班次：把它那一条航线与起终点摊开 ——
// 全国层平时不画航线，但"我点了这架，它从哪来到哪去"必须答得出来，
// 所以这是唯一的例外：只为这一架画一条。
const pickedFlight=computed(()=>flightDots.value.find(f=>f.selected)||null)
const pickedLine=computed(()=>{
  const f=pickedFlight.value
  if(!f) return null
  const line=(corridors.value||[]).find(l=>l.id===f.corridor)
  if(line) return line
  // 库里查不到这条航路（改线/越界等极端情况）就退化成起终点直线，不假装有航路
  const a=f.fromLonLat,b=f.toLonLat
  if(!a||!b) return null
  const pts=arcPoints(project(a[0],a[1]),project(b[0],b[1]),.02)
  return {id:'pick-'+f.id,pts,d:pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ')}
})
const pickedMarks=computed(()=>{
  const f=pickedFlight.value,line=pickedLine.value
  if(!f||!line||!line.pts||line.pts.length<2) return []
  const [ax,ay]=line.pts[0]
  const [bx,by]=line.pts[line.pts.length-1]
  const gap=Math.hypot(bx-ax,by-ay)
  // 起点和终点同名（州内接驳航线）时只标一个点：
  // 两个一模一样的名字叠在一起，读者会以为是渲染错了。
  const sameName=f.fromName===f.toName||gap<6
  const a={key:'a',x:ax,y:ay,name:f.fromName,sub:sameName}
  if(sameName){
    Object.assign(a,{lx:-18,ly:-18,anchor:'end',line:true})
    return [a]
  }
  // 两点在屏幕上挨得近时把标签往外拉，用引线连回原点 —— 宁可多一根线，不要两行字糊在一起
  if(gap<76){
    Object.assign(a,{lx:-20,ly:-16,anchor:'end',line:true})
    return [a,{key:'b',x:bx,y:by,name:f.toName,sub:true,lx:20,ly:22,anchor:'start',line:true}]
  }
  Object.assign(a,{lx:0,ly:-10,anchor:'middle',line:false})
  return [a,{key:'b',x:bx,y:by,name:f.toName,sub:true,lx:0,ly:14,anchor:'middle',line:false}]
})

// 选中一架就把它那条航线摊到视野里：全国层一条航路只有十几像素，
// 不放大根本看不出"从哪到哪"。放大到航线占屏约六成就够，不顶边。
function focusPts(pts){
  if(!pts||pts.length<2) return false
  let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9
  for(const [x,y] of pts){
    minX=Math.min(minX,x);maxX=Math.max(maxX,x)
    minY=Math.min(minY,y);maxY=Math.max(maxY,y)
  }
  const w=Math.max(26,maxX-minX), h=Math.max(26,maxY-minY)
  const next=Math.max(1,Math.min(4.2,Math.min(VIEW.w*.62/w,VIEW.h*.5/h)))
  const cx=(minX+maxX)/2, cy=(minY+maxY)/2
  zoom.value=next
  pan.value={x:VIEW.w/2-cx*next,y:VIEW.h/2-cy*next}
  return next>1.02
}

// —— 交互 ——
const zoom=ref(1)
// 标记物反向缩放：放大看某条航线时，点、飞机、文字必须保持屏幕尺寸不变，
// 否则 8 倍放大后会变成"巨幅广告"（实测起终点地名比地图还大）。
const inv=computed(()=>1/zoom.value)
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

// 选中即聚焦：只跟 selectedId 走。若跟着 computed 走，飞机会每帧挪动零点几像素，
// 视野就会被每帧重算，画面像被人一直按住不放。
watch(()=>props.selectedId,id=>{
  if(!id) return
  // 两步：先等 Vue 把详情卡挂上，再等一帧让 grid 重新分配高度。
  // 只等 nextTick 会在"画布还没缩水"时算 pan，随后尺寸一变就偏。
  nextTick(()=>{
    if(pickedLine.value) focusPts(pickedLine.value.pts)
    setTimeout(()=>{ if(props.selectedId&&pickedLine.value) focusPts(pickedLine.value.pts) },180)
  })
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

    <!-- 世界层用 CSS transform 而不是 SVG transform 属性：
         属性变化浏览器不做插值，聚焦时会"啪"地跳过去；CSS 能过渡。 -->
    <g class="nmap-world" :style="{transform:`translate(${pan.x.toFixed(2)}px, ${pan.y.toFixed(2)}px) scale(${zoom})`}">
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
      <!-- 分档：屏幕上一眼能看出形状的环画等值线（外淡内实），小到只剩几个像素的直接填实 -->
      <g v-if="radarRings.length" :clip-path="'url(#nmap-china-clip)'">
        <template v-for="(ring,index) in radarRings" :key="'rr'+index">
          <path v-if="ring.small" :d="ring.d" stroke="none"
                :fill="ring.level==='STRONG'?'rgba(238,72,60,.58)':'rgba(245,190,60,.42)'"/>
          <template v-else>
            <path :d="ring.d" fill="none"
                  :stroke="ring.level==='STRONG'?'rgba(255,120,90,.30)':'rgba(245,190,60,.24)'"
                  :stroke-width="virtualMode?5:3.4"/>
            <path :d="ring.d" fill="none"
                  :stroke="ring.level==='STRONG'?'rgba(255,150,110,.85)':'rgba(255,214,120,.70)'"
                  :stroke-width="virtualMode?1.8:1.1"/>
          </template>
        </template>
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
              :style="{fill: shape.boundary?'var(--map-boundary)':'var(--map-land)',
                       stroke: shape.boundary?'none':'var(--map-line)'}"
              :opacity="shape.boundary||shape.live||level==='nation'?1:.55"
              stroke-width=".7" vector-effect="non-scaling-stroke" :class="{clickable:shape.live&&!shape.boundary}"
              @click="clickShape(shape)">
          <title>{{ shape.name }}{{ shape.boundary?' · 南海诸岛界线':(shape.live?'':(level==='nation'?' · 未纳入通航范围（台湾、西藏、香港、澳门）':' · 不在本级范围')) }}</title>
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
              style="fill:var(--map-inset-bg)" stroke="var(--map-inset-line)" stroke-width=".8"/>
        <g :clip-path="'url(#nmap-inset-clip)'">
          <path v-for="shape in insetShapes" :key="'i'+shape.key" :d="shape.d"
                :style="{fill: shape.boundary?'var(--map-boundary)':'var(--map-land-dim)'}"
                :stroke="shape.boundary?'none':'rgba(120,165,205,.45)'" stroke-width=".6"/>
        </g>
        <text :x="insetBox.x+7" :y="insetBox.y+insetBox.h-7" class="inset-lbl">南海诸岛</text>
      </g>

      <!-- 3.8 净空（DERIVED）：空域视角下是主体，运行视角只在省/市层做底图 -->
      <g v-if="zonePolys.length" class="nmap-zones">
        <path v-for="(zone,index) in zonePolys" :key="'z'+index" :d="zone.d"
              :fill="zone.kind==='LIMIT'
                ?(zonePolicy==='PROHIBITED'?'rgba(226,74,58,.20)':'rgba(245,190,60,.13)')
                :'rgba(160,220,120,.15)'"
              :stroke="zone.kind==='LIMIT'
                ?(zonePolicy==='PROHIBITED'?'rgba(255,110,85,.85)':'rgba(245,200,90,.66)')
                :'rgba(160,220,120,.55)'"
              stroke-width=".65">
          <title>{{ zone.kind==='LIMIT'?'机场净空限制区（规则化生成，非官方公布）':'跑道梯形净空（仅 10 站有跑道方位）' }}</title>
        </path>
      </g>

      <!-- 4 建筑：城市体块。立体模式下才立起来，平面模式只留底影 -->
      <g class="nmap-towers">
        <g v-for="node in nodes" :key="'b'+node.name">
          <rect v-if="tilt" :x="node.x-1.8" :y="node.y-node.tower*2.6" width="3.6"
                :height="node.tower*2.6" fill="url(#towerFace)" opacity=".5"/>
          <ellipse v-else :cx="node.x" :cy="node.y" :rx="2.6*inv" :ry="1.4*inv" class="node-shadow"/>
        </g>
      </g>

      <!-- 4.5 地面：倾斜时铺一层，避免透视看穿 -->
      <rect v-if="tilt" x="-400" y="-300" :width="VIEW.w+800" :height="VIEW.h+900"
            style="fill:var(--map-ground)" pointer-events="none"/>

      <!-- 5 航线：全国层不画。
           492 条线在全国缩放下平均只有 20–40 px，画出来就是一张蜘蛛网，
           而这一层要看的是"哪些城市有网络"，不是"每条线怎么走"。
           下钻到大区/省/市再画，那时一条线才占几十上百像素，方向也才读得出来。 -->
      <g v-if="level!=='nation'" fill="none" stroke-linecap="round"
         :opacity="audience==='airspace'?.3:1">
        <path v-for="line in corridors" :key="'c'+line.id" :d="line.d"
              :stroke="line.blocked?(virtualMode?'rgba(255,96,70,.95)':'var(--map-corridor-blocked)'):'var(--map-corridor)'"
              :stroke-width="line.blocked?lineWidth*(virtualMode?2.2:.8):lineWidth"
              :class="{hit:line.selected,clickable:true,'virt-alarm':virtualMode&&line.blocked}"
              @click="!moved&&emit('select-corridor',line)"/>
        <path v-for="line in corridors.filter(l=>l.detour)" :key="'d'+line.id" :d="line.detour"
              :stroke="virtualMode?'rgba(255,214,120,1)':'var(--map-detour)'"
              :stroke-width="lineWidth*(virtualMode?2.4:1.3)" class="hit"
              @click="!moved&&emit('select-corridor',line)"/>
      </g>

      <!-- 5.5 航线方向箭头：每条线一枚，说明"往哪飞"。
           全国层 492 条线如果每段都画箭头，会在图上撒满三角；
           所以只在 48% 处放一枚，并按当前级别缩放，省/市层才看得清。 -->
      <g v-if="level!=='nation'" class="nmap-arrows" :opacity="audience==='airspace'?.12:.9">
        <template v-for="line in corridors" :key="'a'+line.id">
          <path v-if="line.arrow"
                :transform="`translate(${line.arrow.x.toFixed(1)} ${line.arrow.y.toFixed(1)}) rotate(${line.arrow.angle.toFixed(1)}) scale(${(level==='nation'?0.62:(level==='region'?0.8:1))*inv})`"
                d="M-2.6 -1.8 L3 0 L-2.6 1.8 Z"
                :fill="line.blocked?'var(--map-corridor-blocked)':'var(--map-corridor)'"
                :stroke="line.blocked?'var(--map-corridor-blocked)':'var(--map-corridor)'"
                stroke-width=".2"/>
        </template>
      </g>

      <!-- 6 节点 -->
      <g class="nmap-nodes">
        <g v-for="node in nodes" :key="'n'+node.name" @click="clickNode(node)">
          <circle v-if="node.external" :cx="node.x" :cy="node.y" :r="(node.rank===1?3.4:2.4)*inv"
                  fill="none" stroke="rgba(160,200,235,.75)" stroke-width="1.1"/>
          <template v-else>
            <circle :cx="node.x" :cy="node.y" :r="(node.rank===1?3:(node.rank===2?2:1))*inv"
                    :style="{fill: node.rank===3?'var(--map-node-dim)':'var(--map-node)',
                            stroke: node.rank===3?'none':'var(--map-node-stroke)'}" stroke-width=".55"/>
            <circle v-if="node.capital" :cx="node.x" :cy="node.y" :r="5.8*inv" fill="none"
                    stroke="rgba(186,218,255,.40)" stroke-width=".9"/>
            <circle v-if="node.weather&&node.weather.low" :cx="node.x" :cy="node.y" :r="4.8*inv"
                    fill="none" stroke="rgba(226,75,74,.92)" stroke-width="1"/>
          </template>
          <title>{{ node.name }}{{ node.capital?' · 省会/首府':'' }}{{ node.hasAirport?' · 机场 '+node.airport:' · 无机场（有专用接驳）' }}<template v-if="node.weather"> · {{ node.weather.tempC==null?'—':node.weather.tempC+' °C' }}</template></title>
        </g>
      </g>

      <!-- 6.5 选中班次的航线。全国层平时不画航线，这一条是唯一的例外：
           "我点的这架，从哪来、到哪去"必须当场答得出来。
           已飞段实线、未飞段虚线 —— 用 pathLength=100 归一化后拿 dasharray 截断，
           比自己切路径稳（航路是贝塞尔弧，切不出干净的子路径）。 -->
      <g v-if="pickedFlight&&pickedLine" class="nmap-pick" fill="none" stroke-linecap="round">
        <path :d="pickedLine.d" class="pick-rest" pathLength="100" :style="{strokeWidth:1.1*inv}"/>
        <path :d="pickedLine.d" class="pick-done" pathLength="100"
              :style="{strokeWidth:1.9*inv}"
              :stroke-dasharray="`${(pickedFlight.progressNow*100).toFixed(2)} 1000`"/>
      </g>

      <!-- 7 航班：每架一个独立对象，点谁选谁。
           每架按自己的 fade 单独淡出 —— 到站的那一架会慢慢消失，
           而不是在整分钟刷新时从图上跳掉。 -->
      <g class="nmap-flights" :opacity="audience==='airspace'?.3:1">
        <g v-for="f in flightDots" :key="f.id"
           :opacity="f.fade*(f.selected||f.detour||f.bad?1:.82)"
           :transform="`translate(${f.x.toFixed(1)} ${f.y.toFixed(1)}) rotate(${f.heading.toFixed(0)}) scale(${(f.selected?1:(level==='nation'?0.6:0.92))*inv})`"
           @click.stop="!moved&&emit('select-flight',f)">
          <circle v-if="f.selected" class="pick-halo" r="9" fill="none"
                  stroke="#8ef0ff" stroke-width="1.6"/>
          <circle v-if="f.selected" r="9" fill="none" stroke="#8ef0ff" stroke-width="1.4" filter="url(#glow)"/>
          <path v-if="f.selected" d="M8.4 0 L-4.8 4.8 L-2.4 0 L-4.8 -4.8 Z" fill="#8ef0ff"
                stroke="rgba(10,30,45,.85)" stroke-width=".5"/>
          <template v-else>
            <!-- 三档颜色：常态浅蓝、绕飞琥珀、应急红（应急目前无数据触发，先占位）。
                 延期的班次不在这里 —— 它还没起飞，flightDots 已经过滤掉了。 -->
            <path d="M6 0 L-3.4 3.2 L-1.7 0 L-3.4 -3.2 Z"
                  :style="{fill: f.emergency?'var(--map-emergency)':(f.detour?'var(--map-fly-detour)':'var(--map-fly)')}"
                  :stroke="f.emergency?'var(--map-emergency)':'rgba(10,30,45,.55)'" stroke-width=".45"/>
          </template>
          <title>{{ f.callsign }} · {{ f.fromName }} → {{ f.toName }} · {{ f.altM }} m · {{ f.decisionLabel }}</title>
        </g>
      </g>

      <!-- 7.5 选中班次的起终点：这是全图唯一会出现的"地名"。
           省名已经全部撤掉 —— 地图上留字只留"这一架从哪到哪"，字才有信息量。 -->
      <g v-if="pickedMarks.length" class="nmap-pick-ends">
        <g v-for="end in pickedMarks" :key="end.key"
           :transform="`translate(${end.x.toFixed(1)} ${end.y.toFixed(1)}) scale(${inv})`">
          <line v-if="end.line" class="end-lead" x1="0" y1="0"
                :x2="end.lx" :y2="end.ly-(end.key==='a'?4:-4)"/>
          <circle class="end-ring" r="6.4" fill="none" stroke-width=".8"/>
          <circle class="end-dot" r="3" stroke-width=".7"/>
          <text class="end-lbl" :text-anchor="end.anchor"
                :x="end.lx" :y="end.ly">{{ end.name }}</text>
          <text v-if="end.sub&&pickedFlight" class="end-sub" :text-anchor="end.anchor"
                :x="end.lx" :y="end.ly+11.6">
            {{ pickedFlight.arriveAt }} 到达 · {{ pickedFlight.decisionLabel }}
            <template v-if="pickedFlight.exposure&&pickedFlight.exposure.directMin>0"> · 回波暴露 {{ Math.round(pickedFlight.exposure.directMin) }} 分</template>
          </text>
        </g>
      </g>

      <!-- 8 标注 -->
      <g class="nmap-labels">
        <text v-for="node in labels" :key="'l'+node.name"
              :x="node.x+((node.x>VIEW.w-90?-5.5:5.5)*inv)" :y="node.y+3.2*inv"
              :text-anchor="node.x>VIEW.w-90?'end':'start'" class="city"
              :style="{fontSize:(8.6*inv)+'px'}">{{ node.short }}</text>
      </g>
    </g>
  </svg>
</div>
</template>

<style scoped>
.nmap{position:absolute;inset:0;border-radius:10px;overflow:hidden;
  background:radial-gradient(120% 90% at 50% 0%,var(--map-bg-1) 0%,var(--map-bg-2) 70%)}
.nmap svg{display:block;width:100%;height:100%;cursor:grab;transition:transform .45s ease}
.nmap svg.dragging{cursor:grabbing;transition:none}
.nmap.tilt svg{transform:perspective(1150px) rotateX(39deg) scale(1.2) translateY(3%);transform-origin:50% 82%}
.nmap-terrain{opacity:.13;filter:grayscale(1) brightness(.75) contrast(1.1)}
.nmap-terrain image{mix-blend-mode:screen}
.nmap .clickable{cursor:pointer}
.nmap path.hit{filter:drop-shadow(0 0 2px rgba(255,206,90,.55))}
.nmap path.virt-alarm{filter:drop-shadow(0 0 4px rgba(255,90,60,.85))}
.nmap .inset-lbl{font-size:7.5px;fill:rgba(170,205,230,.85)}
.nmap .node-shadow{fill:rgba(8,20,32,.5)}
.nmap .city{font-size:8.6px;fill:#dceefb;paint-order:stroke;stroke:rgba(4,12,20,.85);stroke-width:2.4px;pointer-events:none}

/* 选中班次：已飞实线、未飞虚线；起终点用"环+点+地名"标出来 */
.nmap-world{transform-origin:0 0;transition:transform .55s cubic-bezier(.22,.85,.2,1)}
.nmap svg.dragging .nmap-world{transition:none}
.nmap-pick .pick-rest{stroke:var(--map-corridor);stroke-width:1.2;opacity:.62;stroke-dasharray:4 3}
.nmap-pick .pick-done{stroke:#8ef0ff;stroke-width:1.9;opacity:.95;
  filter:drop-shadow(0 0 3px rgba(120,235,255,.6))}
.nmap-pick-ends .end-dot{fill:#8ef0ff;stroke:rgba(6,20,32,.85)}
.nmap-pick-ends .end-ring{stroke:rgba(142,240,255,.55)}
.nmap-pick-ends .end-lbl{font-size:9.6px;font-weight:600;fill:#e6f9ff;paint-order:stroke;
  stroke:rgba(3,12,20,.92);stroke-width:2.8px;pointer-events:none}
.nmap-pick-ends .end-sub{font-size:8px;fill:#8fd8ea;paint-order:stroke;
  stroke:rgba(3,12,20,.9);stroke-width:2.6px;pointer-events:none}
.nmap-pick-ends .end-lead{stroke:rgba(142,240,255,.45);stroke-width:.7;stroke-dasharray:2 2}

/* 选中飞机的呼吸环：transform-box 必须给，否则 SVG 里 scale 会绕错原点 */
.pick-halo{transform-box:fill-box;transform-origin:center;animation:pick-halo 1.9s ease-out infinite}
@keyframes pick-halo{
  0%{transform:scale(.55);opacity:.9}
  100%{transform:scale(1.9);opacity:0}
}
@media (prefers-reduced-motion: reduce){.pick-halo{animation:none;opacity:.5}}
</style>
