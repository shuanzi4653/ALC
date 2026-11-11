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
  // 当前 flights 数组**自己对应的分钟**（后端回传的 payload.minute）。
  // V1.0.4：以前推进量按 `minute` 算，而 minute 是"请求的分钟"，比数据早一拍 ——
  // 分钟一翻、新数据还没到，advanceMin 就归零，飞机先倒退一分钟再被弹回来（录屏抖动）。
  // 以数据自己的时刻为基准，advanceMin 才会跨分钟连续。
  dataMinute:{type:Number,default:-1},
  radarOn:{type:Boolean,default:true},
  fogOn:{type:Boolean,default:true},
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
  // 全国层显示哪些航线：三档开关 + 条数上限（用户 2026-11-11 要"人工决定开多少个"）
  lineKinds:{type:Object,default:()=>({cross:true,feed:true,intra:false})},
  lineLimit:{type:Number,default:291},
  // 只画这一条走廊（走廊/推演页用）。给了就把其余航线全部滤掉。
  soloCorridor:{type:String,default:''},
  // 锁定视图：走廊页看的是"这条线连的是哪两座城"，缩放会把注意力挪走，
  // 所以那一页禁掉滚轮与拖拽，视野由 soloCorridor 自动 fit。
  lockView:{type:Boolean,default:false},
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
    // 尺寸一变就要重算 pan，否则旧 pan 对应新 viewBox，整幅图会飞出画布。
    // 以前这里只处理"选中班次"，漏了走廊页（soloCorridor 且没有 selectedId）——
    // 从列表切到走廊时地图高度会变，fit 用的是变之前的尺寸，航线就被推到视野下方
    // （实测容器 462 高、航线包围盒 top=509，整条线在可视区外）。
    if(changed) requestAnimationFrame(refitCurrent)
  }
}
// 当前视野该聚焦谁：单条走廊 > 选中班次。两处（尺寸变化 / 数据到达）共用，
// 避免"只在某一个入口调一次"这种漏。
function refitCurrent(){
  if(props.soloCorridor){
    const line=(corridors.value||[])[0]
    if(line&&line.pts) focusPts(line.pts)
    return
  }
  if(props.selectedId&&pickedLine.value) focusPts(pickedLine.value.pts)
}

/**
 * 双击标签复位。绑在 <svg> 上而不是每个 `<g>` 上：
 * `@dblclick` 直接绑 SVG 分组时，事件目标是里面的 `<rect>`，某些浏览器下
 * 分组收不到（实测 Playwright 双击命中 rect，分组的处理函数没跑）。
 * 这里从事件目标往上找 `.map-tag`，再读它的 data-key —— 稳且只有一份逻辑。
 */
function onSvgDblclick(ev){
  const host=ev.target&&ev.target.closest?ev.target.closest('.map-tag'):null
  if(!host) return
  const key=host.getAttribute('data-key')
  if(key) resetLabelOff(key)
}

onMounted(()=>{
  window.addEventListener('pointermove',moveLabelDrag,{passive:false})
  window.addEventListener('pointerup',endLabelDrag)
  window.addEventListener('pointercancel',endLabelDrag)
  fitView()
  if(typeof ResizeObserver!=='undefined'&&host.value){
    ro=new ResizeObserver(fitView)
    ro.observe(host.value)
  }
})
onUnmounted(()=>{
  window.removeEventListener('pointermove',moveLabelDrag)
  window.removeEventListener('pointerup',endLabelDrag)
  window.removeEventListener('pointercancel',endLabelDrag)
  clearTimeout(dragState.timer)
  if(ro) ro.disconnect()
})
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
// 五角星（中心在原点，外接半径 6）：省会用，别拿它做别的标记
const STAR='M0,-6 L1.76,-2.43 L5.71,-1.85 L2.85,0.94 L3.53,4.85 L0,2.9 L-3.53,4.85 L-2.85,0.94 L-5.71,-1.85 L-1.76,-2.43 Z'

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
// —— 回波环 ——
// 几何在后端已经做过栅格闭运算（补孔）+ 几何闭运算（磨角）+ Chaikin（成曲线），
// 前端只负责上色。不再按屏幕尺寸分流画"填实小方块"：那是瓦片位图时代的补丁。
const radarRings=computed(()=>{
  if(!props.radarOn) return []
  const bands=props.data?.radar?.bands||{}
  // 帧标识：雷达帧号优先，没有就用推演分钟。它只进 key，用来触发淡入动画。
  const frame=String(props.data?.radar?.ts||props.minute||'')
  const out=[]
  for(const level of ['WEAK','CONVECTIVE','STRONG']){
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
        level, frame,
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

// —— 禁飞区：287 个机场限制区 + 10 条跑道梯形（非气象） ——
// 与气象禁飞（强回波轮廓）共用"红框"这一种标记：用户 2026-11-11 定"禁飞区就是红框"。
// 取不到几何就返回空数组：空图层和"没有禁飞区"是两回事，界面上另有 zoneErr 说明。
function zoneTitle(zone){
  return (zone.kind==='RWY' ? '禁飞区：跑道梯形净空（仅 10 站有方位）'
    : '禁飞区：机场净空限制区（规则化生成，非官方公布）')
}
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
      if(count>=400) break
      count+=1
      const pts=ring.map(([lon,lat])=>project(lon,lat))
      let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9
      for(const [x,y] of pts){
        if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y
      }
      const w=x1-x0,h=y1-y0
      // 太小就不画。国级 287 个机场限制区大多只有 1–2 px：
      // 画成点像红疹、强行放大成 8 px 方框又满屏红格子（用户两轮都否了）。
      // 现在的口径：按层级设**最小可显示尺寸**，小于阈值直接不出现 ——
      // 全国 14 px、大区 10 px、省 8 px、市 4 px。要看小禁区就下钻。
      const minPx={nation:14,region:10,province:8,city:4}[level.value]||8
      if(Math.max(w,h)<minPx) continue
      out.push({kind,cx:(x0+x1)/2,cy:(y0+y1)/2,w,h,
        d:toPath({type:'Polygon',coordinates:[ring]},project)})
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
// 走廊几何**只有一个来源：后端给的 path**。两点就是直线（后端 NationBasis 的约定：
// "两点直飞不重复传 path，前端用两端点"）。
//
// V1.0.4 删掉了这里原来的 `arcPoints(...)` 造弧：492 条走廊里 484 条只有端点，
// 前端按 bulge 画成二次弧，而后端 `flight_objects` 是按弦插值的 ——
// 画的是弯线、飞机走的是直线，越放大偏得越远（用户第 6 条：走廊和飞行汽车不匹配）。
// 现在的铁律：屏幕上这一条线，就是飞机脚下那一条线。
function linePath(row){
  const path=row?.path
  if(path&&path.length>1) return path
  if(row?.fromLonLat&&row?.toLonLat) return [row.fromLonLat,row.toLonLat]
  return null
}
// 在飞班次所在的走廊：这些线不受"三档筛选 / 条数上限"约束。
// 否则省内短途（INTRA 默认关）上的 37 架会变成"凭空出现的小箭头"。
const flyingCorridorIds=computed(()=>{
  const out=new Set()
  for(const f of props.flights||[]){
    if(f.decision==='HOLD') continue
    if(f.corridor) out.add(f.corridor)
  }
  return out
})
// 显示条数决定线宽与透明度：开得越多，单条越轻，避免"开全部就糊成蜘蛛网"
const lineStyle=computed(()=>{
  const n=props.lineLimit
  const nation=level.value==='nation'
  if(!nation) return {w:{region:.95,province:1.6,city:1.4}[level.value]||1,op:1,arrow:'all'}
  // 条数越多单条越轻，但不能轻到看不见：300 条时仍要能读出"网"的形状
  if(n<=60) return {w:1.3,op:.95,arrow:'all'}
  if(n<=300) return {w:1.15,op:.9,arrow:'cross'}
  return {w:.9,op:.72,arrow:'cross'}
})
const lineWidth=computed(()=>lineStyle.value.w)

// 一条走廊 → 可渲染的形状。抽成函数是因为"走廊页只画一条"要复用它：
// 之前 solo 分支想直接 map 一个新对象，字段一缺就画不出来（箭头/绕飞全丢）。
function toLineShape(row){
  const path=linePath(row)||[]
  const points=path.map(([lon,lat])=>project(lon,lat))
  const d='M'+points.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join('L')
  let detour=null
  if(row.detour?.path?.length>1){
    const dp=row.detour.path.map(([lon,lat])=>project(lon,lat))
    detour='M'+dp.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join('L')
  }
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
    fromName:row.fromName,toName:row.toName,kind:row.kind,kindLabel:row.kindLabel,lengthKm:row.lengthKm,
    detourKm:row.detourKm||(row.detour&&row.detour.shiftKm)||0,
    selected:props.selectedCorridor===row.id}
}

const corridors=computed(()=>{
  const all=props.data?.corridors||[]
  // 走廊页只画一条：其余全部滤掉，否则"这一条"会淹没在 291 条里。
  if(props.soloCorridor) return all.filter(r=>r.id===props.soloCorridor).map(toLineShape)
  let rows=all
  if(level.value==='nation'){
    const k=props.lineKinds||{}
    rows=all.filter(row=>{
      const kind=row.kind
      if(kind==='CROSS') return !!k.cross
      if(kind==='AIRPORT_FEED') return !!k.feed
      return !!k.intra
    })
    // 按航程降序截取：只开 50 条时看到的是骨架，而不是随机 50 条
    rows=[...rows].sort((a,b)=>(b.lengthKm||0)-(a.lengthKm||0)).slice(0,Math.max(0,props.lineLimit))
  }
  // 在飞必画（并集，不受筛选与上限约束）：屏幕上出现一架飞机，它脚下就必须有那条线。
  const shown=new Set(rows.map(r=>r.id))
  const flying=flyingCorridorIds.value
  for(const row of all){
    if(shown.has(row.id)||!flying.has(row.id)) continue
    shown.add(row.id)
    rows.push(row)
  }
  return rows.map(toLineShape)
})

// —— 节点与建筑 ——
function shortName(name){
  // 省级与市级共用一个规则：先剥自治区/特区/省，再剥市/地区/盟/自治州。
  // 两处（地图标签、右栏列表）必须一致，否则同一个省在图上叫"新疆"、在右栏叫"新疆维吾尔自治区"。
  const base=(name||'')
    .replace(/维吾尔自治区$/,'').replace(/壮族自治区$/,'').replace(/回族自治区$/,'')
    .replace(/特别行政区$/,'').replace(/自治区$/,'').replace(/省$/,'')
    .replace(/(市|地区|盟|自治州|自治县)$/,'')
  return trimEthnic(base)
}

// 民族名可能有两三个连着（"黔西南布依族苗族自治州" → 剥掉自治州还剩"布依族苗族"）。
// 只剥一次会留下"黔西南布依族"这种半截名字，看着像没写完 —— 循环剥到剥不动为止。
const ETHNIC=/(朝鲜族|蒙古族|藏族|苗族|侗族|彝族|哈尼族|壮族|傣族|白族|土家族|布依族|傈僳族|景颇族|羌族|回族|维吾尔族|哈萨克族|柯尔克孜族|锡伯族|达斡尔族|鄂温克族|鄂伦春族|满族|瑶族|畲族|黎族|水族|仡佬族|拉祜族|佤族|纳西族|普米族|阿昌族|怒族|独龙族|基诺族|德昂族|布朗族|撒拉族|东乡族|保安族|裕固族|土族|门巴族|珞巴族)$/
function trimEthnic(name){
  let out=name
  for(let i=0;i<4;i++){
    const next=out.replace(ETHNIC,'')
    if(next===out) break
    out=next
  }
  return out
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
// —— 地图文字统一成「椭圆底胶囊」（V1.0.4）——
// 以前城市名/航班参数/起终点名都用 `paint-order:stroke` 描边当底。字号被 inv 压到 2px 时，
// 2.4px 的描边比字还宽，几个字连成一坨、笔画末端伸出两个尖角 —— 用户看到的
// "带箭头的黑气泡"就是它，不是气泡，是字晕。现在改成地图标注最基础的画法：
// 实心底 + 无描边文字，短名字（≤4 字）看起来就是标准椭圆。
// 宽度用**估算**而不是 getBBox：每帧几十个标签量文字会掉帧，中文一律按一字宽、
// 拉丁数字按 0.56 字宽，再左右各留 0.6 字的内边距，误差 1–2px，肉眼无感。
// 标签规格（单位=SVG 世界单位，zoom=1 时 1 单位=1px）。
// 原来城市 8.6 / 航班 7.6：在 1366 和 1920 下都是这个值（缩放没参与），
// 也就是"地图文字本来就偏小"，不是某个分辨率的问题。8.6px 的中文在地图上是"能看出有字、读不出来"，
// 一律抬到 10 以上；胶囊宽高由 fs 推导（w=units*fs+pad*fs*2），改 fs 不会撑破底。
const TAG={city:{fs:10.2,pad:.55,h:1.5},flight:{fs:9.8,pad:.5,h:1.55},end:{fs:11.2,pad:.55,h:1.45}}
function textUnits(text){
  let units=0
  for(const ch of String(text||'')){
    units+=/[0-9A-Za-z·.．:：+\-/()（）\s]/.test(ch)?0.56:1
  }
  return units
}
function tagBox(text,kind){
  const spec=TAG[kind]||TAG.city
  return {w:textUnits(text)*spec.fs+spec.pad*spec.fs*2,h:spec.fs*spec.h,fs:spec.fs}
}

// 底图上"本来就该有名字"的城市：跨省航线端点 + 省会。
// 全国层标谁的名额是紧的，超出这个集合的名字不该为了标飞机而被塞进来。
const baseEndNames=computed(()=>{
  const out=new Set()
  for(const line of corridors.value){
    if(line.kind==='CROSS'){ out.add(line.fromName); out.add(line.toName) }
  }
  for(const node of props.data?.nodes||[]) if(node.capital) out.add(node.name)
  return out
})

const labels=computed(()=>{
  const list=(props.data?.nodes||[]).map(node=>{
    const [x,y]=project(node.lon,node.lat)
    return {...node,x,y,short:shortName(node.name)}
  })
  // 跨省航线的两端**提权**：它们不一定有机场（南通、锦州这类），rank 天然靠后，
  // 以前只取 rank<=2 且截断 12/40，于是"有航线、没地名"，读者只能对着一条线猜起讫。
  // 现在：凡是当前画出来的跨省航线端点，与省会同级参与排版。
  const ends=new Set()
  for(const line of corridors.value){
    if(line.kind==='CROSS'){ ends.add(line.fromName); ends.add(line.toName) }
  }
  // V1.0.4：带参数标签的那几架（notableFlights）的起降城市也要在地图上。
  // 全国层只**沿用**已有的名字（省会/跨省端点），不额外塞新的：
  // 实测给 8 架补 16 个地名会把全国层的城市名从 15 个顶到 36 个，
  // 图立刻变糊 —— 而全国层的读法是"看骨架"，不是"逐城读名"。
  // 下钻到大区/省/市才把端点全部提权，那一层一条线占几十上百像素，名字放得下。
  if(level.value!=='nation'){
    for(const f of notableFlights.value){
      if(f.fromName) ends.add(f.fromName)
      if(f.toName) ends.add(f.toName)
    }
  }
  // 悬停某条航线时，它两端的名字必须出现：只给一条线、不给两个地名，
  // 读者没法知道这条线连的是哪两座城。这是"强制显示"，不吃密度限制。
  const hl=(corridors.value||[]).find(l=>l.id===hoverLineId.value)
  if(hl){ ends.add(hl.fromName); ends.add(hl.toName) }
  // 走廊页（只画一条）同理：这一页讲的就是"这两座城之间怎么飞"，
  // 起降城市名必须在图上，否则右边的数据卡写着双鸭山、图上只有一个点。
  if(props.soloCorridor){
    const only=(corridors.value||[])[0]
    if(only){ ends.add(only.fromName); ends.add(only.toName) }
  }
  const rankOf=(node)=>ends.has(node.name)?0:(node.rank||3)
  // V1.0.5：**不再按密度截断**。以前的 limit（18/40/44）会让"为什么这个城市有名字、
  // 那个没有"变成一道猜谜；现在池子里的全部参与排布，放不下就降级形态（见 flightLabels），
  // 不再整条删掉。全国层池子实测 80 个（30 省会 + 57 跨省端点，有重叠）。
  const limit=999
  const ordered=list.filter(node=>level.value!=='nation'||rankOf(node)===0||node.capital)
    .sort((a,b)=>rankOf(a)-rankOf(b))
  // 避让判据用**真实胶囊矩形**，不再用"离点 48×10 的方框"。
  // 方框是旧字号（8.6px）时估出来的：名字两字和四字一样宽、高矮也不随字号变，
  // 字号抬到 10.2 之后要么放过近的、要么错杀远处能放下的（实测同屏 8 处重叠）。
  // 现在按 实际宽×实际高 判断，且把"离锚点 6 个单位"的偏移也算进去。
  const k=inv.value
  const placed=[]
  const boxes=[]
  const overlaps=(a,b,pad)=>!(a.x1+pad<b.x0||a.x0-pad>b.x1||a.y1+pad<b.y0||a.y0-pad>b.y1)
  // 两轮放置：先试"胶囊"（有底、好读），放不下再试"裸字"（无底、面积小一半）。
  // 全显之后必须允许降级形态，否则密集区会整片丢名 —— 用户要的是"都能看见"，
  // 不是"都能带框"。
  for(const node of ordered){
    const tag=tagBox(node.short,'city')
    const side=node.x>VIEW.w-90?-1:1
    let box=null, bare=false
    for(const attempt of [false,true]){
      const w=(attempt?tag.w*0.84:tag.w)*k
      const h=(attempt?tag.h*0.94:tag.h)*k
      const cx=node.x+side*(w/2+5)
      const cand={x0:cx-w/2,x1:cx+w/2,y0:node.y-h/2,y1:node.y+h/2}
      if(boxes.some(b=>overlaps(cand,b,attempt?1:2))) continue
      box=cand; bare=attempt; break
    }
    if(!box) continue
    boxes.push(box)
    placed.push({...node,tag,bare})
    if(placed.length>=limit) break
  }
  return placed
})
// —— 航班 ——
// 本地推进量（分钟）：把两次后端快照之间的空档补上，位置才连续。
// V1.0.4 两个改动：
//   ①基准从"请求的分钟"改成"这批数据自己的分钟"（dataMinute）。
//     以前 minute 一翻、新快照还在路上，adv 就从 0.99 归零 → 飞机倒退一分钟再弹回；
//   ②上限从 6 分钟压到 1.6 分钟：再多就是外推，不是数据，宁可站住等快照。
const advanceMin=computed(()=>{
  const base=props.frameMinute>=0?props.frameMinute:props.minute
  const from=props.dataMinute>=0?props.dataMinute:props.minute
  let adv=base-from
  if(adv<-720) adv+=1440
  else if(adv>720) adv-=1440
  return adv>0?Math.min(1.6,adv):0
})

// —— 走廊折线表：位置与绘制共用同一份顶点（V1.0.4）——
// 后端 `nation_ops.flight_objects` 的进度是"按顶点均分"（pos = progress*(n-1)），
// 前端照抄同一条规则。这样位置与画出来的那条线重合，误差是 0 而不是"大概齐"，
// 转弯处也不会漂出去再被快照拉回来（那是第二种抖动）。
const corridorById=computed(()=>{
  const map=new Map()
  for(const row of props.data?.corridors||[]) map.set(row.id,row)
  return map
})
function flightPathOf(f){
  const row=corridorById.value.get(f.corridor)
  if(row){
    // 绕飞的班次跟着绕飞航迹走（后端也是这么算的）：琥珀虚线画在哪，飞机就飞在哪
    if(f.status==='DELAYED'&&row.detour?.path?.length>1) return row.detour.path
    const p=linePath(row)
    if(p) return p
  }
  if(f.fromLonLat&&f.toLonLat) return [f.fromLonLat,f.toLonLat]
  return null
}
// t∈[0,1] → [lon,lat,方位角(数学角)]。按顶点均分，与后端逐位对齐。
function pointAt(path,t){
  const n=path.length
  if(!n) return null
  if(n===1) return [path[0][0],path[0][1],0]
  const pos=Math.max(0,Math.min(1,t))*(n-1)
  const i=Math.min(n-2,Math.floor(pos))
  const frac=pos-i
  const a=path[i],b=path[i+1]
  return [a[0]+(b[0]-a[0])*frac,a[1]+(b[1]-a[1])*frac,
    Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI]
}
// 机头角度：取前后各一小段的方向做**向量平均**。
// 直接用当前段的方位角的话，过顶点会瞬间转几十度（绕飞航迹尤其明显），
// 向量平均让转角在顶点附近平滑过渡；跨 ±180° 也不会翻跟头。
function headingAt(path,t,eps=.01){
  const a=pointAt(path,Math.max(0,t-eps)),b=pointAt(path,Math.min(1,t+eps)),c=pointAt(path,t)
  if(!c) return 0
  if(!a||!b) return c[2]
  const r=Math.PI/180
  const vx=Math.cos(a[2]*r)+Math.cos(b[2]*r)
  const vy=Math.sin(a[2]*r)+Math.sin(b[2]*r)
  if(Math.hypot(vx,vy)<1e-6) return c[2]
  return Math.atan2(vy,vx)/r
}

const flightDots=computed(()=>{
  const out=[]
  const adv=advanceMin.value
  for(const f of props.flights||[]){
    // 延期的班次**不画**：它还没起飞，画在航路上等于告诉人"这架已经在飞"。
    // 它仍然在台账与处置页里，也仍然计入"延期 N 架"。
    if(f.decision==='HOLD') continue
    const dur=Math.max(1,f.durationMin||1)
    // 当前进度 = 后端 progress + 本地推进的那一段（同一个 duration，单位一致）
    const p=(f.progress||0)+adv/dur
    const path=flightPathOf(f)
    let lon=f.lon,lat=f.lat,screen=-(f.heading||0)
    const at=path?pointAt(path,p):null
    if(at){
      lon=at[0];lat=at[1]
      // heading 是数学角（0=东、正=北），图标要屏幕角（0=东、正=南）→ 取负
      screen=-headingAt(path,p)
    }
    const [x,y]=project(lon,lat)
    // 进站淡出、离站淡入 —— "飞出去就没了"，而不是从图上突然跳掉，
    // 这是 Flightradar24 那种"活的"观感的来源。命中判据只在这一小段里失效。
    const fade=p>=.985?Math.max(0,(1-p)/.015):(p<=.02?Math.max(.25,p/.02):1)
    // 已经淡到看不见的班次直接不生成 DOM：只把 opacity 设 0 的话，
    // 每帧仍要重建这些节点（实测多出 10–20 个死节点），命中判据也还认它们。
    if(fade<=0.02) continue
    out.push({...f,x,y,lon,lat,headingScreen:screen,progressNow:Math.max(0,Math.min(1,p)),fade,
      selected:props.selectedId===f.id,
      detour:f.status==='DELAYED',bad:f.riskLevel==='HIGH'})
  }
  return out
})

// 值得标出来的几架：全国层只标"关键的那几架"，下钻到大区及以下才全标。
// 抽成 computed 是因为**城市名标注也要用它**（带标签的飞机必须有起降城市）。
//
// V1.0.4：补位时优先挑"起降城市本来就有名字"的那几架。
// 否则标出来的是 8 个随机地名上的飞机，为了给它配两个地名，
// 全国层的城市名会从 15 个涨到 40 多个 —— 把地图糊住的正是"标注互相追着长"。
const notableFlights=computed(()=>{
  const all=flightDots.value.filter(f=>f.fade>.4)
  const key=all.filter(f=>f.selected||f.detour||f.bad)
  let picked=key.slice()
  // 全国层只标"值得看的几架"，但**不能一个都没有**：
  // 实测 6 个时刻里有 4 个时刻绕飞 0 架、高风险的基本都在延期里（延期不画），
  // 于是标签长期为空 —— 用户要的"每个箭头旁边有高度/速度/编号"就落空了。
  if(level.value==='nation'&&picked.length<8){
    const rest=all.filter(f=>!key.includes(f))
    const named=(f)=>baseEndNames.value.has(f.fromName)||baseEndNames.value.has(f.toName)
    const prefer=rest.filter(named).sort((a,b)=>(b.riskP||0)-(a.riskP||0))
    const others=rest.filter(f=>!named(f)).sort((a,b)=>(b.riskP||0)-(a.riskP||0))
    picked=picked.concat(prefer,others).slice(0,8)
  }
  return level.value==='nation'?picked.slice(0,12):all
})

// 换帧过渡：新环淡入 260ms、旧环淡出 260ms 后销毁。
// 只做淡入也够软，但"旧图直接消失"仍是一次硬切，所以留一帧影子。
const echoGhost=ref([])
let ghostTimer=null
watch(()=>radarRings.value, (next,prev)=>{
  if(!prev||!prev.length) return
  echoGhost.value=prev
  if(ghostTimer) clearTimeout(ghostTimer)
  ghostTimer=setTimeout(()=>{ echoGhost.value=[] },260)
})
onUnmounted(()=>{ if(ghostTimer) clearTimeout(ghostTimer) })

// —— 选中的班次：把它那一条航线与起终点摊开 ——
// 全国层平时不画航线，但"我点了这架，它从哪来到哪去"必须答得出来，
// 所以这是唯一的例外：只为这一架画一条。
// —— 悬停：不点也能看这一架是谁 ——
// 用 clientX/clientY 定位一个 fixed 浮层，不去换算 SVG 坐标：
// 换算要乘 pan/zoom，还要处理 viewBox 缩放，容易差几个像素，而这里只要"跟着鼠标"。
// 浮层统一成「标题 + 若干行」，航班/城市/禁飞区/航线共用一块 DOM：
// 四套各自写一遍会出现"有的地方有浮层、有的地方还是浏览器原生 title"。
const tip=ref(null)
function showTip(event,title,rows){
  tip.value={x:event.clientX,y:event.clientY,title,rows}
}
function hoverMove(event){
  if(tip.value){ tip.value.x=event.clientX; tip.value.y=event.clientY }
}
function hoverLeave(){ tip.value=null }

function hoverEnter(f,event){
  showTip(event, f.callsign, [
    {text:`${f.fromName} → ${f.toName}`},
    {text:`${f.altM} m · ${f.speedKmh} km/h · 已飞 ${Math.round((f.progressNow||0)*100)}%`},
    {text:`${f.decisionLabel} · 风险 ${f.riskLevelLabel}`, cls:f.bad?'bad':''},
  ])
}
// 城市点：以前只有浏览器原生 <title>（1 秒延迟、样式不可控）。
// 这里给"这个点是什么"，不重复右栏的逐市气象表。
function hoverNode(node,event){
  const rows=[{text:node.capital?'省会 / 直辖市':'城市节点'}]
  if(node.airport) rows.push({text:`机场 ${node.airport}`})
  else rows.push({text:'无机场（专用接驳）'})
  if(node.pLowVis!=null) rows.push({text:`模型低能见概率 ${(node.pLowVis*100).toFixed(0)}%`,
    cls:node.pLowVis>=0.35?'bad':''})
  rows.push({text:`${node.short} · 点击下钻`})
  showTip(event,node.short,rows)
}
function hoverZone(zone,event){
  const rows=[{text:zone.kind==='RWY'?'跑道梯形净空':'机场净空限制区'},
    {text:'规则化生成，非官方公布'},
    {text:'边界按真实几何绘制'}]
  showTip(event,zone.kind==='RWY'?'禁飞区 · 跑道':'禁飞区 · 机场净空',rows)
}
// 航线：悬停时把两端城市名强制显示（labels 会把这两个名字提权），
// 否则全国层只有一条线，读者得拿尺子量它连的是哪两座城。
const hoverLineId=ref('')
function hoverLine(line,event){
  hoverLineId.value=line.id
  const rows=[{text:line.kindLabel||'航线'}]
  rows.push({text:`${line.lengthKm} km`})
  rows.push({text:line.blocked?'停飞':(line.detour?'绕飞放行':'直飞')},
    )
  showTip(event,`${shortName(line.fromName)} → ${shortName(line.toName)}`,rows)
}
function leaveLine(){ hoverLineId.value=''; hoverLeave() }

// 模板里不能直接写 window（表达式作用域只有组件实例），算在 computed 里
const tipFlip=computed(()=>!!tip.value&&tip.value.x>((typeof window!=='undefined'?window.innerWidth:1920)-260))

// 常显的文字标签：全国层只给"值得看的几架"（选中/绕飞/高风险），
// 下钻到大区及以下才全标 —— 106 行小字会把地图盖住，这是上一轮刚清理过的问题。
// —— 标签手工挪位（V1.0.5）——
// 城市名与航班标签会撞在一起，避让算法只能"少标一个"，不能"挪到我看得顺眼的地方"。
// 现在按住 300ms 可以拖：位置存 localStorage，刷新/切页仍然有效；双击复位。
// 用 getScreenCTM().inverse() 换算，是为了让拖动量自动跟随缩放（放大到 4 倍时，
// 屏幕拖 40px 与 1 倍时拖 40px 在图上不是同一段距离）。
const LABEL_OFF_KEY='alc.labelOff.v1'
const labelOff=ref(readLabelOff())
function readLabelOff(){
  try{ const raw=JSON.parse(localStorage.getItem(LABEL_OFF_KEY)||'{}'); return raw&&typeof raw==='object'?raw:{} }
  catch(e){ return {} }
}
function persistLabelOff(){
  try{ localStorage.setItem(LABEL_OFF_KEY, JSON.stringify(labelOff.value)) }catch(e){}
}
function offOf(key){
  const o=labelOff.value[key]
  return o&&Number.isFinite(o.dx)&&Number.isFinite(o.dy)?o:{dx:0,dy:0}
}
const dragState=reactive({key:'',active:false,moved:false,timer:0,pt:null,m:null})
function startLabelDrag(ev,key){
  if(ev.button!==0) return
  const host=ev.currentTarget
  const m=host&&host.getScreenCTM?host.getScreenCTM():null
  if(!m) return
  const inv=m.inverse()
  dragState.m=inv
  dragState.pt=new DOMPoint(ev.clientX,ev.clientY).matrixTransform(inv)
  dragState.key=key; dragState.active=false; dragState.moved=false
  clearTimeout(dragState.timer)
  // 300ms 内松手＝普通点击（点城市名下钻），超过才进入拖动
  dragState.timer=setTimeout(()=>{
    if(dragState.key!==key) return
    dragState.active=true
    document.body.style.cursor='grabbing'
  },300)
}
function moveLabelDrag(ev){
  if(!dragState.key||!dragState.active||!dragState.m) return
  ev.preventDefault()
  const p=new DOMPoint(ev.clientX,ev.clientY).matrixTransform(dragState.m)
  const dx=p.x-dragState.pt.x, dy=p.y-dragState.pt.y
  if(!dx&&!dy) return
  dragState.pt=p
  dragState.moved=true
  const cur=offOf(dragState.key)
  labelOff.value={...labelOff.value,[dragState.key]:{dx:cur.dx+dx,dy:cur.dy+dy}}
}
function endLabelDrag(){
  clearTimeout(dragState.timer)
  if(dragState.active&&dragState.moved){
    const cur=offOf(dragState.key)
    // 松手时几乎没挪动（<3 个世界单位）：当作误触，不往存储里塞一堆 dx:0.4
    if(Math.abs(cur.dx)+Math.abs(cur.dy)<3){
      const next={...labelOff.value}
      delete next[dragState.key]
      labelOff.value=next
    }
    persistLabelOff()
  }
  dragState.key=''; dragState.active=false; dragState.m=null
  document.body.style.cursor=''
}
function resetLabelOff(key){
  if(!labelOff.value[key]) return
  const next={...labelOff.value}
  delete next[key]
  labelOff.value=next
  persistLabelOff()
}
/** 拖动过后紧接着的那一次 click 要吃掉，否则"拖到一边"会顺带把城市选中。 */
function labelClickable(){ return !dragState.moved }

const flightLabels=computed(()=>{
  const list=notableFlights.value
  const k=inv.value
  // 与城市名互相避让：航班标签压在"西宁"上，两个都读不清。
  // 城市名先画，航班标签让路（城市名是底图，飞机数据是浮层）。
  const cityBoxes=(labels.value||[]).map(n=>{
    const right=n.x<=VIEW.w-90
    const x0=right?n.x+6*k:n.x-6*k-n.tag.w*k
    return {x0,x1:x0+n.tag.w*k,y0:n.y-n.tag.h*k/2,y1:n.y+n.tag.h*k/2}
  })
  const hit=(a,b,pad)=>a.x0<b.x1+pad&&a.x1>b.x0-pad&&a.y0<b.y1+pad&&a.y1>b.y0-pad
  const out=[]
  for(const f of list){
    // 精简档：不写任何航班标签，只留城市与航线
    if(props.density==='min') continue
    // "放大详细、缩小简略"用**能否放下**来实现，而不是按缩放比例硬切：
    // 放大后标签稀疏、地方大，长的就能放下；缩小后到处撞车，自动退到只写编号。
    // 手动选"详细"时把最短的候选也锁成"编号+高度"，不让它缩成光秃秃一个号。
    const cs=f.callsign
    const variants = props.density==='slim'
      ? [`${cs} · ${f.altM}m · ${Math.round(f.speedKmh||0)}km/h`, `${cs} · ${f.altM}m`]
      : [`${cs} · ${f.altM}m`, cs]
    let placed=null
    for(const text of variants){
      const tag=tagBox(text,'flight')
      const w=tag.w*k,h=tag.h*k
      // 四个候选：上 / 下 / 右 / 左。间距都是 10 个世界单位 —— 机身外接半径 6，留 4 的通气。
      const spots=[
        {x0:-w/2,y0:-(10+h)},
        {x0:-w/2,y0:10},
        {x0:10,y0:-h/2},
        {x0:-10-w,y0:-h/2},
      ]
      for(const spot of spots){
        const cand={x0:f.x+spot.x0,x1:f.x+spot.x0+w,y0:f.y+spot.y0,y1:f.y+spot.y0+h}
        if(cityBoxes.some(c=>hit(cand,c,2))) continue
        if(out.some(o=>hit(cand,o.box,3))) continue
        placed={text,tag,box:cand}
        break
      }
      if(placed) break
    }
    if(!placed) continue
    const w=placed.tag.w*k,h=placed.tag.h*k
    out.push({id:f.id,x:f.x,y:f.y,text:placed.text,important:f.selected||f.detour||f.bad,
      tag:placed.tag,box:placed.box,
      cxOff:(placed.box.x0-f.x+w/2)/k,cyOff:(placed.box.y0-f.y+h/2)/k})
  }
  return out
})

const pickedFlight=computed(()=>flightDots.value.find(f=>f.selected)||null)
const pickedLine=computed(()=>{
  const f=pickedFlight.value
  if(!f) return null
  const line=(corridors.value||[]).find(l=>l.id===f.corridor)
  if(line) return line
  // 库里查不到这条航路（改线/越界等极端情况）就退化成起终点直线，不假装有航路。
  // 也不在这里造弧：飞机是按弦走的，画一条弧又会变成"线和飞机不重合"。
  const a=f.fromLonLat,b=f.toLonLat
  if(!a||!b) return null
  const pts=[project(a[0],a[1]),project(b[0],b[1])]
  return {id:'pick-'+f.id,pts,d:pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ')}
})
const pickedMarks=computed(()=>{
  const f=pickedFlight.value,line=pickedLine.value
  if(!f||!line||!line.pts||line.pts.length<2) return []
  const [ax,ay]=line.pts[0]
  const [bx,by]=line.pts[line.pts.length-1]
  const gap=Math.hypot(bx-ax,by-ay)
  // 终点那行小字（到达时刻 · 裁决 · 回波暴露）现在也走胶囊底，
  // 与城市名同一套画法 —— 地图上不再有"描边糊出来的字"。
  const subText=`${f.arriveAt} 到达 · ${f.decisionLabel}`+
    (f.exposure&&f.exposure.directMin>0?` · 回波暴露 ${Math.round(f.exposure.directMin)} 分`:'')
  const subTag=tagBox(subText,'endsub')
  // 起点和终点同名（州内接驳航线）时只标一个点：
  // 两个一模一样的名字叠在一起，读者会以为是渲染错了。
  const sameName=f.fromName===f.toName||gap<6
  const a={key:'a',x:ax,y:ay,name:f.fromName,sub:sameName,tag:tagBox(f.fromName,'end'),
    subText,subTag}
  if(sameName){
    Object.assign(a,{lx:-18,ly:-18,anchor:'end',line:true})
    return [a]
  }
  // 两点在屏幕上挨得近时把标签往外拉，用引线连回原点 —— 宁可多一根线，不要两行字糊在一起
  if(gap<76){
    Object.assign(a,{lx:-20,ly:-16,anchor:'end',line:true})
    return [a,{key:'b',x:bx,y:by,name:f.toName,sub:true,lx:20,ly:22,anchor:'start',line:true,
      tag:tagBox(f.toName,'end'),subText,subTag}]
  }
  Object.assign(a,{lx:0,ly:-10,anchor:'middle',line:false})
  return [a,{key:'b',x:bx,y:by,name:f.toName,sub:true,lx:0,ly:14,anchor:'middle',line:false,
    tag:tagBox(f.toName,'end'),subText,subTag}]
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
  // 留边：左右各 6%、上下各 14%（底部有图例、顶部有工具条），
  // 以前用 62%/50% 的实际比例，短航线会被放大到贴边，长航线又偏到一侧。
  const w=Math.max(26,maxX-minX), h=Math.max(26,maxY-minY)
  const padX=.88, padY=.72
  const next=Math.max(1,Math.min(4.2,Math.min(VIEW.w*padX/w,VIEW.h*padY/h)))
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
  if(props.lockView) return
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
function onDown(e){
  if(props.lockView) return
  dragging.value=true;moved=false;dragStart={x:e.clientX,y:e.clientY,px:pan.value.x,py:pan.value.y}}
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

// 走廊页：只画一条时把视野 fit 到它，并且**不做过渡**（lockView 下没有手动缩放，
// 过渡只会让"点左边换右边"变成一段漂移）。
watch(()=>props.soloCorridor,(id)=>{
  if(!id) return
  // 数据可能还没到（组件先挂、payload 后到）：等两帧再看一次，仍没有就交给
  // 下面那条"走廊数据变化"的重试。
  nextTick(()=>{ requestAnimationFrame(refitCurrent) })
},{immediate:true})

// 走廊页的数据是异步来的：soloCorridor 先到、corridors 后到，
// 只在 id 变化时 fit 会扑空（实测进入页面后视野停在全国中心）。
watch(()=>corridors.value.length,()=>{
  if(props.soloCorridor) nextTick(()=>requestAnimationFrame(refitCurrent))
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
<div class="nmap" ref="host">
  <svg :viewBox="`0 0 ${VIEW.w} ${VIEW.h}`" role="img" aria-label="全国航线网"
       :class="{dragging}" @wheel.prevent="onWheel" @mousedown="onDown"
       @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp"
       @dblclick="onSvgDblclick">
    <defs>
      <linearGradient id="towerFace" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(150,210,245,.85)"/>
        <stop offset="100%" stop-color="rgba(38,86,120,.25)"/>
      </linearGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="1.6"/></filter>
      <filter id="nmap-fog-blur" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="3.2"/>
      </filter>
      <!-- 回波颗粒（V1.0.4）：真实雷达的色块内部是"杂色"的，不是一块纯色。
           做法是把噪声按 SourceGraphic 的形状裁进去，只留在回波内部；
           回波一分钟才换一帧，滤镜结果会被浏览器缓存，不吃 30fps 的预算。 -->
      <filter id="nmap-echo-grain" x="-3%" y="-3%" width="106%" height="106%"
              color-interpolation-filters="sRGB">
        <feGaussianBlur in="SourceGraphic" stdDeviation=".3" result="soft"/>
        <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="9" result="noise"/>
        <feColorMatrix in="noise" type="saturate" values="0" result="gray"/>
        <feComponentTransfer in="gray" result="speck">
          <feFuncA type="linear" slope=".16"/>
        </feComponentTransfer>
        <feComposite in="speck" in2="soft" operator="in" result="grain"/>
        <feMerge>
          <feMergeNode in="soft"/>
          <feMergeNode in="grain"/>
        </feMerge>
      </filter>
      <clipPath id="nmap-china-clip"><path :d="chinaClipD"/></clipPath>
    </defs>

    <!-- 世界层用 CSS transform 而不是 SVG transform 属性：
         属性变化浏览器不做插值，聚焦时会"啪"地跳过去；CSS 能过渡。 -->
    <g class="nmap-world" :style="{transform:`translate(${pan.x.toFixed(2)}px, ${pan.y.toFixed(2)}px) scale(${zoom})`}">
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

      <!-- 3.2 回波：**只画矢量轮廓**，不再叠原始瓦片位图。
           两套画法并存时，位图的像素块会和矢量边界互相打架，看着就是锯齿。
           几何由后端做过闭运算平滑（radar_field._smooth），这里只负责上色。
           V1.0.4：位置从"行政区下面"挪到"行政区上面" —— 之前回波被陆地填充盖住，
           深色主题下压掉一层（--map-land 13%），浅色主题下是 92% 的白，
           绿/黄/红几乎被冲干净（实测浅色下只剩一圈浅粉）。天气是主体，必须压在底图之上。 -->
      <g v-if="radarRings.length" :clip-path="'url(#nmap-china-clip)'">
        <!-- 回波（V1.0.4）：**实心填充、不描边**。
             以前每档都描一圈高亮边，三档又互不嵌套 → 画成了"等高线地图"。
             后端改成累计掩膜后，红⊂黄⊂绿是真的嵌套，只要按 绿→黄→红 的顺序叠色，
             就是真实雷达的读法。换帧时旧环淡出 260ms、新环淡入 260ms。 -->
        <g class="nmap-echo" :class="{'echo-virt':virtualMode}" filter="url(#nmap-echo-grain)">
          <g v-if="echoGhost.length" class="nmap-echo-ghost">
            <path v-for="(ring,index) in echoGhost" :key="'g'+index" :d="ring.d"
                  :class="'echo-out echo-'+ring.level.toLowerCase()"/>
          </g>
          <template v-for="(ring,index) in radarRings" :key="'rr'+index+'-'+ring.frame">
            <path :d="ring.d" :class="'echo-in echo-'+ring.level.toLowerCase()"/>
          </template>
        </g>
      </g>

      <!-- 3.3 雾区：低能见度面（DERIVED）。与回波同样压在底图之上 -->
      <g v-if="fogPolys.length" class="nmap-fog" filter="url(#nmap-fog-blur)">
        <path v-for="(poly,i) in fogPolys" :key="'fg'+i" :d="poly.d"
              :fill="poly.level==='BAN'?'rgba(226,240,252,.34)':'rgba(196,222,244,.22)'"
              stroke="rgba(206,232,255,.35)" stroke-width=".8"/>
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

      <!-- 3.8 禁飞区（DERIVED）：气象（回波轮廓）与非气象（机场限制区）用同一套红框。
           小到看不清的用 8 px 方框兜底 —— 图例是框，图上就必须是框，不能是点。 -->
      <g v-if="zonePolys.length" class="nmap-zones">
        <path v-for="(zone,index) in zonePolys" :key="'z'+index" :d="zone.d"
              class="no-fly-box"
              @mouseenter="hoverZone(zone,$event)" @mousemove="hoverMove" @mouseleave="hoverLeave"
              :style="{strokeWidth:(level==='nation'?1.1:1.6)*inv, opacity:level==='nation'?.85:.95}">
          <title>{{ zoneTitle(zone) }}</title>
        </path>
      </g>

      <!-- 4 建筑：城市点的底影（立体体块随三维一起下线了） -->
      <g class="nmap-towers">
        <g v-for="node in nodes" :key="'b'+node.name">
          <ellipse :cx="node.x" :cy="node.y" :rx="2.6*inv" :ry="1.4*inv" class="node-shadow"/>
        </g>
      </g>

      <!-- 5 航线：全国层不画。
           492 条线在全国缩放下平均只有 20–40 px，画出来就是一张蜘蛛网，
           而这一层要看的是"哪些城市有网络"，不是"每条线怎么走"。
           下钻到大区/省/市再画，那时一条线才占几十上百像素，方向也才读得出来。 -->
      <g v-if="corridors.length" fill="none" stroke-linecap="butt"
         :opacity="audience==='airspace'?.3:lineStyle.op">
        <path v-for="line in corridors" :key="'c'+line.id" :d="line.d" :data-line="line.id"
              :stroke="line.blocked?(virtualMode?'rgba(255,96,70,.95)':'var(--map-corridor-blocked)'):'var(--map-corridor)'"
              :stroke-width="(line.blocked?lineWidth*(virtualMode?2.2:.8):lineWidth)*inv"
              :class="{hit:line.selected,clickable:true,'virt-alarm':virtualMode&&line.blocked}"
              @mousemove="hoverMove" @mouseleave="leaveLine"
              @mouseenter="hoverLine(line,$event)"
              @click="!moved&&emit('select-corridor',line)"/>
        <path v-for="line in corridors.filter(l=>l.detour)" :key="'d'+line.id" :d="line.detour"
              :stroke="virtualMode?'rgba(255,214,120,1)':'var(--map-detour)'"
              class="hit detour-line"
              :style="{strokeWidth:lineWidth*(virtualMode?2.4:1.6)*inv}"
              :stroke-dasharray="`${5*inv} ${3.5*inv}`"
              @click="!moved&&emit('select-corridor',line)"/>
      </g>

      <!-- 5.5 航线方向箭头：每条线一枚，说明"往哪飞"。
           全国层 492 条线如果每段都画箭头，会在图上撒满三角；
           所以只在 48% 处放一枚，并按当前级别缩放，省/市层才看得清。 -->
      <g v-if="corridors.length" class="nmap-arrows"
         :opacity="audience==='airspace'?.12:(level==='nation'?lineStyle.op*.9:.9)">
        <template v-for="line in corridors" :key="'a'+line.id">
          <path v-if="line.arrow&&(lineStyle.arrow==='all'||line.kind==='CROSS')"
                :transform="`translate(${line.arrow.x.toFixed(1)} ${line.arrow.y.toFixed(1)}) rotate(${line.arrow.angle.toFixed(1)}) scale(${(level==='nation'?0.62:(level==='region'?0.8:1))*inv})`"
                d="M-2.6 -1.8 L3 0 L-2.6 1.8 Z"
                :fill="line.blocked?'var(--map-corridor-blocked)':'var(--map-corridor)'"
                :stroke="line.blocked?'var(--map-corridor-blocked)':'var(--map-corridor)'"
                stroke-width=".2"/>
        </template>
      </g>

      <!-- 6 节点 -->
      <g class="nmap-nodes">
        <g v-for="node in nodes" :key="'n'+node.name" @click="clickNode(node)"
           @mouseenter="hoverNode(node,$event)" @mousemove="hoverMove" @mouseleave="hoverLeave">
          <circle v-if="node.external" :cx="node.x" :cy="node.y" :r="(node.rank===1?3.4:2.4)*inv"
                  fill="none" stroke="rgba(160,200,235,.75)" stroke-width="1.1"/>
          <template v-else>
            <circle :cx="node.x" :cy="node.y" :r="(node.rank===1?3:(node.rank===2?2:1))*inv"
                    :style="{fill: node.rank===3?'var(--map-node-dim)':'var(--map-node)',
                            stroke: node.rank===3?'none':'var(--map-node-stroke)'}" stroke-width=".55"/>
            <!-- 只有**北京**用红色五角星（用户 2026-11-11 定）；其余省会维持"点 + 浅环" -->
            <path v-if="node.name==='北京市'" :d="STAR" class="cap-star"
                  :transform="`translate(${node.x.toFixed(1)} ${node.y.toFixed(1)}) scale(${1.5*inv})`"/>
            <circle v-else-if="node.capital" class="cap-ring" :cx="node.x" :cy="node.y"
                    :r="5.4*inv" fill="none" stroke-width=".9"/>
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
        <g v-for="f in flightDots" :key="f.id" :data-flight="f.id" :data-corridor="f.corridor"
           :opacity="f.fade*(f.selected||f.detour||f.bad?1:.82)"
           :transform="`translate(${f.x.toFixed(1)} ${f.y.toFixed(1)}) rotate(${(f.headingScreen!=null?f.headingScreen:-f.heading).toFixed(0)}) scale(${(f.selected?1.15:(level==='nation'?0.92:1.05))*inv})`"
           @mouseenter="hoverEnter(f,$event)" @mousemove="hoverMove"
           @mouseleave="hoverLeave" @click.stop="!moved&&emit('select-flight',f)">
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

      <!-- 7.2 班次常显标签：编号 + 高度。位置由 flightLabels 四向避让算好（上/下/右/左） -->
      <g class="nmap-flight-labels">
        <g v-for="row in flightLabels" :key="'fl'+row.id" class="map-tag flight-tag"
           :transform="`translate(${row.x+row.cxOff*inv+offOf('f:'+row.id).dx} ${row.y+row.cyOff*inv+offOf('f:'+row.id).dy})`"
           :class="{dragging:dragState.active&&dragState.key==='f:'+row.id}"
           :data-key="'f:'+row.id" @mousedown.stop
           @pointerdown="startLabelDrag($event,'f:'+row.id)">
          <rect :x="-row.tag.w*inv/2" :y="-row.tag.h*inv/2" :width="row.tag.w*inv" :height="row.tag.h*inv"
                :rx="row.tag.h*inv/2" :ry="row.tag.h*inv/2"
                class="tag-bg" :class="{key:row.important}"/>
          <text :y="row.tag.fs*inv*.36" text-anchor="middle" :class="{key:row.important}"
                :style="{fontSize:(row.tag.fs*inv)+'px'}">{{ row.text }}</text>
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
          <rect class="tag-bg" :x="end.anchor==='start'?end.lx:(end.anchor==='end'?end.lx-end.tag.w:end.lx-end.tag.w/2)"
                :y="end.ly-end.tag.h*.74" :width="end.tag.w" :height="end.tag.h"
                :rx="end.tag.h/2" :ry="end.tag.h/2"/>
          <text class="end-lbl" :text-anchor="end.anchor"
                :x="end.lx" :y="end.ly">{{ end.name }}</text>
          <rect v-if="end.sub" class="tag-bg sub"
                :x="end.anchor==='start'?end.lx:(end.anchor==='end'?end.lx-end.subTag.w:end.lx-end.subTag.w/2)"
                :y="end.ly+11.6-end.subTag.h*.78" :width="end.subTag.w" :height="end.subTag.h"
                :rx="end.subTag.h/2" :ry="end.subTag.h/2"/>
          <text v-if="end.sub" class="end-sub" :text-anchor="end.anchor"
                :x="end.lx" :y="end.ly+11.6">{{ end.subText }}</text>
        </g>
      </g>

      <!-- 8 标注：城市名走"胶囊底 + 无描边字"，短名看起来就是标准椭圆 -->
      <g class="nmap-labels">
        <g v-for="node in labels" :key="'l'+node.name" class="map-tag city-tag"
           :class="{dragging:dragState.active&&dragState.key==='c:'+node.name}"
           :data-key="'c:'+node.name"
           @pointerdown="startLabelDrag($event,'c:'+node.name)" @mousedown.stop
           :transform="`translate(${node.x+((node.x>VIEW.w-90?-1:1)*(node.tag.w/2+6)*inv)+offOf('c:'+node.name).dx} ${node.y+offOf('c:'+node.name).dy})`">
          <rect v-if="!node.bare" :x="-node.tag.w*inv/2" :y="-node.tag.h*inv/2"
                :width="node.tag.w*inv" :height="node.tag.h*inv"
                :rx="node.tag.h*inv/2" :ry="node.tag.h*inv/2" class="tag-bg"/>
          <text class="city" :y="node.tag.fs*inv*.36" text-anchor="middle"
                :style="{fontSize:(node.tag.fs*inv)+'px'}">{{ node.short }}</text>
        </g>
      </g>
    </g>
  </svg>
  <div v-if="tip" class="nmap-tip" :style="{left:tip.x+'px', top:tip.y+'px'}" :class="{flip:tipFlip}">
    <b>{{ tip.title }}</b>
    <span v-for="(row,i) in tip.rows" :key="'t'+i" :class="row.cls||''">{{ row.text }}</span>
  </div>
</div>
</template>

<style scoped>
.nmap{position:absolute;inset:0;border-radius:10px;overflow:hidden;
  background:radial-gradient(120% 90% at 50% 0%,var(--map-bg-1) 0%,var(--map-bg-2) 70%)}
.nmap svg{display:block;width:100%;height:100%;cursor:grab;transition:transform .45s ease}
.nmap svg.dragging{cursor:grabbing;transition:none}
.nmap .clickable{cursor:pointer}
.nmap path.hit{filter:drop-shadow(0 0 2px rgba(255,206,90,.55))}
.nmap path.virt-alarm{filter:drop-shadow(0 0 4px rgba(255,90,60,.85))}
.nmap .inset-lbl{font-size:9.5px;fill:rgba(178,210,232,.9)}
.nmap .node-shadow{fill:rgba(8,20,32,.5)}
.echo-in{animation:echoIn .26s ease-out both}
.echo-out{animation:echoOut .26s ease-out both;pointer-events:none}
.nmap-echo-ghost{pointer-events:none}
@keyframes echoIn{from{opacity:0}to{opacity:1}}
@keyframes echoOut{from{opacity:1}to{opacity:0}}
@media (prefers-reduced-motion: reduce){
  .echo-in,.echo-out{animation:none}
}
/* 回波配色：按 dBZ 色阶（绿→黄→红）实心填充，**不描边**。
   描边会让三档变成"等高线"，而真实雷达是色块。嵌套关系由后端累计掩膜保证，
   这里只要按 WEAK→CONVECTIVE→STRONG 叠色（模板顺序已固定）就是红⊂黄⊂绿。
   不透明度调高到 .72/.85/.95：三档是**叠**出来的，半透明叠色会把黄压成橄榄绿
   （实测 0.66 的黄压在 0.5 的绿上 → rgb(169,182,69)），而真实雷达的每一格是一个实色。 */
.echo-weak{fill:rgba(46,170,110,.72);stroke:none}
.echo-convective{fill:rgba(255,206,64,.85);stroke:none}
.echo-strong{fill:rgba(240,60,45,.95);stroke:none}
/* 虚拟增强：只加深红核的边，不三档全描边 */
.echo-virt .echo-strong{stroke:rgba(30,6,4,.5);stroke-width:.6}
/* 浅色底上要更实：白底会把半透明色块冲淡（实测 .34 的绿几乎看不见） */
html[data-theme="light"] .echo-weak{fill:rgba(46,150,95,.52);stroke:none}
html[data-theme="light"] .echo-convective{fill:rgba(232,170,26,.64);stroke:none}
html[data-theme="light"] .echo-strong{fill:rgba(206,44,32,.74);stroke:none}
html[data-theme="light"] .echo-virt .echo-strong{stroke:rgba(90,10,6,.45);stroke-width:.6}
.cap-star{fill:#ff4d4f;stroke:rgba(8,20,32,.85);stroke-width:.7;pointer-events:none}
.cap-ring{stroke:rgba(186,218,255,.42);pointer-events:none}
.no-fly-box{fill:rgba(224,49,49,.06);stroke:#e03131;pointer-events:stroke;cursor:help}

html[data-theme="light"] .no-fly-box{fill:rgba(224,49,49,.05);stroke:#c92a2a}
html[data-theme="light"] .cap-star{fill:#c92a2a;stroke:#ffffff}
html[data-theme="light"] .cap-ring{stroke:rgba(40,90,130,.5)}
.detour-line{stroke-opacity:.95}
/* —— 地图标注：胶囊底（V1.0.4）——
   用户两轮都否掉了"描边糊出来的字块"：那是 paint-order:stroke 的副产物。
   现在统一成"实心半透明底 + 无描边字"，短名（≤4 字）呈标准椭圆。 */
.nmap .tag-bg{fill:rgba(6,18,28,.72);stroke:none}
.nmap .tag-bg.key{fill:rgba(8,40,56,.86)}
.nmap .tag-bg.sub{fill:rgba(6,18,28,.58)}
.nmap-flight-labels text{fill:#e6f6ff;letter-spacing:.2px;opacity:.94}
.nmap-flight-labels text.key{fill:#9ff4ff;opacity:1;font-weight:600}
html[data-theme="light"] .nmap .tag-bg{fill:rgba(255,255,255,.9)}
html[data-theme="light"] .nmap .tag-bg.key{fill:rgba(233,247,255,.96)}
html[data-theme="light"] .nmap .tag-bg.sub{fill:rgba(255,255,255,.8)}
html[data-theme="light"] .nmap-flight-labels text{fill:#12314a}
html[data-theme="light"] .nmap-flight-labels text.key{fill:#0b6f95}
/* 用户点名"不要花哨气泡框"：去圆角、去投影、去卡片感，
   只留一条平贴的窄条 —— 它是指示，不是弹窗。 */
.nmap-tip{position:fixed;z-index:30;transform:translate(12px,10px);pointer-events:none;
  min-width:140px;max-width:230px;padding:4px 7px;border-radius:1px;
  background:rgba(6,18,28,.78);border-left:2px solid rgba(126,206,255,.7);
  box-shadow:none;font-size:10.5px;line-height:1.5;color:#bcd6e8}
.nmap-tip.flip{transform:translate(-100%,14px);margin-left:-14px}
.nmap-tip b{display:block;color:#eaf8ff;font-size:11.5px;letter-spacing:.3px}
.nmap-tip span{display:block;color:#9fc0d6}
.nmap-tip span.bad{color:#ff9c86}
html[data-theme="light"] .nmap-tip{background:rgba(255,255,255,.92);
  border-left-color:#0b7ea6;box-shadow:none;color:#3f5c76}
html[data-theme="light"] .nmap-tip b{color:#0f3550}
html[data-theme="light"] .nmap-tip span{color:#5b7a92}
html[data-theme="light"] .nmap-tip span.bad{color:#c0392b}
.nmap .city{font-size:8.6px;fill:#dceefb;pointer-events:none}
html[data-theme="light"] .nmap .city{fill:#12314a}

/* 选中班次：已飞实线、未飞虚线；起终点用"环+点+地名"标出来 */
.nmap-world{transform-origin:0 0;transition:transform .55s cubic-bezier(.22,.85,.2,1)}
.nmap svg.dragging .nmap-world{transition:none}
.nmap-pick .pick-rest{stroke:var(--map-corridor);stroke-width:1.2;opacity:.62;stroke-dasharray:4 3}
.nmap-pick .pick-done{stroke:#8ef0ff;stroke-width:1.9;opacity:.95;
  filter:drop-shadow(0 0 3px rgba(120,235,255,.6))}
.nmap-pick-ends .end-dot{fill:#8ef0ff;stroke:rgba(6,20,32,.85)}
.nmap-pick-ends .end-ring{stroke:rgba(142,240,255,.55)}
.nmap-pick-ends .end-lbl{font-size:9.6px;font-weight:600;fill:#e6f9ff;pointer-events:none}
.nmap-pick-ends .end-sub{font-size:8px;fill:#a7e2f0;pointer-events:none}
html[data-theme="light"] .nmap-pick-ends .end-lbl{fill:#0f3550}
html[data-theme="light"] .nmap-pick-ends .end-sub{fill:#3f6a80}
.nmap-pick-ends .end-lead{stroke:rgba(142,240,255,.45);stroke-width:.7;stroke-dasharray:2 2}

/* 选中飞机的呼吸环：transform-box 必须给，否则 SVG 里 scale 会绕错原点 */
.pick-halo{transform-box:fill-box;transform-origin:center;animation:pick-halo 1.9s ease-out infinite}
@keyframes pick-halo{
  0%{transform:scale(.55);opacity:.9}
  100%{transform:scale(1.9);opacity:0}
}
@media (prefers-reduced-motion: reduce){.pick-halo{animation:none;opacity:.5}}
</style>
