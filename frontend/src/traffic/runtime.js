export const modeNames={CAR:'飞行汽车',DELIVERY:'无人机外卖'}
export const reasonNames={
  MANUAL_SUSPEND:'人工暂停，原计划保留以供追溯',NO_GEOMETRIC_PATH:'边界内无可用路径',
  WEATHER_UNAVAILABLE:'气象数据中断，暂停放行',WEATHER_BLOCKED:'未来气象风险阻断路径',
  SEPARATION_RESOURCE_OR_TIME_LIMIT:'已声明高度层、起降与交叉资源或额外耗时均无法满足',
  FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED:'最终气象或边界复核未通过',WEATHER_DETOUR:'已绕开未来风险范围',
  STATIC_AIRSPACE_BLOCKED:'起降点位于固定管制区内，未获批准不得进入',
  CLEAR:'按已声明高度层与时隙运行',TURN_RADIUS_OR_BOUNDARY_LIMIT:'转弯半径或边界限制',ALTITUDE_PROFILE_LIMIT:'高度剖面超过机型限制',
}
export const actionNames={
  NONE:'未放行',LAYERED_CORRIDOR:'按已声明高度层走廊运行',SLOT_AND_LAYER:'错时与高度层协同',
  ALTERNATE_LAYER:'改用备用已声明高度层',GROUND_HOLD_AND_LAYER:'地面等待并改用高度层',
}
export const closureReasons=new Set([
  'MANUAL_SUSPEND','NO_GEOMETRIC_PATH','WEATHER_UNAVAILABLE','WEATHER_BLOCKED',
  'SEPARATION_RESOURCE_OR_TIME_LIMIT','FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED',
  'STATIC_AIRSPACE_BLOCKED','TURN_RADIUS_OR_BOUNDARY_LIMIT','ALTITUDE_PROFILE_LIMIT',
  'BEYOND_PLANNING_HORIZON',
])
export const weatherClosureReasons=new Set([
  'WEATHER_UNAVAILABLE','WEATHER_BLOCKED','FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED',
])
export const closureShortNames={
  MANUAL_SUSPEND:'人工暂停',NO_GEOMETRIC_PATH:'无可用路径',
  WEATHER_UNAVAILABLE:'气象中断',WEATHER_BLOCKED:'气象阻断',
  SEPARATION_RESOURCE_OR_TIME_LIMIT:'资源或耗时不足',
  FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED:'复核未通过',
  STATIC_AIRSPACE_BLOCKED:'固定管制区',TURN_RADIUS_OR_BOUNDARY_LIMIT:'转弯或边界受限',
  ALTITUDE_PROFILE_LIMIT:'超机型高度',BEYOND_PLANNING_HORIZON:'超出推演时段',
}
export function closureBreakdown(stats){
  if(!stats)return '等待计划'
  const closed=stats.closed||0
  if(!closed)return '本轮无关闭'
  const tally=stats.closedByClosureReason||stats.closedByReason||{}
  const weather=stats.closedByWeather||0
  const parts=Object.entries(tally).filter(([reason])=>closureReasons.has(reason))
    .sort((a,b)=>b[1]-a[1]).slice(0,2)
    .map(([reason,count])=>`${closureShortNames[reason]||reasonNames[reason]||reason} ${count}`)
  const listed=parts.reduce((sum,part)=>sum+(Number(part.split(' ').pop())||0),0)
  const other=Math.max(0,closed-listed)
  const tail=[parts.length?parts.join(' · '):'',other?`其他 ${other}`:''].filter(Boolean).join(' · ')
  return (weather?`气象 ${weather} 班`:'无气象原因')+(tail?' · '+tail:'')
}

export function dispositionSummary(stats){
  if(!stats)return '等待计划'
  const delayed=Number(stats.groundHolds)||0
  const detoured=Number(stats.detours)||0
  const closed=Number(stats.closed)||0
  const accepted=Number(stats.accepted)||0
  if(!accepted&&!closed)return '等待计划'
  const weatherClosed=Number(stats.closedByWeather)||0
  const closedPart=closed?`停止放行 ${closed}（气象 ${weatherClosed}）`:'停止放行 0'
  const parts=[`时隙重排 ${delayed}`, `改航绕飞 ${detoured}`, closedPart]
  const total=accepted+closed
  const share=total?Math.round(accepted/total*100):0
  return `放行率 ${share}% · ${parts.join(' · ')}`
}

export function delaySpread(flights){
  const values=(flights||[]).map(f=>Number(f?.delayMinutes)||0).filter(v=>v>0).sort((a,b)=>a-b)
  if(!values.length)return {count:0,median:0,p90:0,max:0}
  const at=fraction=>values[Math.min(values.length-1,Math.floor(values.length*fraction))]
  return {count:values.length,median:at(.5),p90:at(.9),max:values[values.length-1]}
}

export function representativeFlightId(flights){
  const list=(Array.isArray(flights)?flights:[]).filter(f=>f&&f.id)
  if(!list.length)return ''
  const num=f=>Number(f.detourMinutes)||0
  const detoured=list.filter(f=>num(f)>0.01).sort((a,b)=>num(b)-num(a))
  if(detoured.length)return detoured[0].id
  const delay=f=>Number(f.delayMinutes)||0
  const delayed=list.filter(f=>delay(f)>0.01).sort((a,b)=>delay(b)-delay(a))
  if(delayed.length)return delayed[0].id
  const open=list.find(f=>f.status!=='CLOSED')
  return (open||list[0]).id
}

export function clearanceLines(clearance){
  if(!clearance)return []
  const level=Number(clearance.assignedLevelAglM)
  const ctot=clearance.ctot||null
  const lines=[
    {label:'呼号',value:clearance.callsign||'—'},
    {label:'放行界限',value:clearance.limit||'—'},
    {label:'航路',value:clearance.route||'—'},
    {label:'指派高度层',value:Number.isFinite(level)&&level>0?`${Math.round(level)} m AGL`:'未指派高度层'},
  ]
  if(ctot&&ctot.from){
    const validity=Number(ctot.validityMinutes)
    const until=ctot.until?`（至 ${operationalTime(ctot.until,null)}）`:''
    lines.push({label:'离场时隙 CTOT',
      value:`${operationalTime(ctot.from,null)} 起${Number.isFinite(validity)?` ${validity} 分钟内有效`:''}${until}`})
  }else{
    lines.push({label:'离场时隙 CTOT',value:'未取得时隙'})
  }
  lines.push({label:'气象判据',value:clearance.weatherBasis||'未声明气象判据'})
  return lines
}
export function metarWindRows(observation){
  const speedRaw=observation?.windSpeed10mMps??observation?.windMps
  const speed=Number(speedRaw)
  if(!Number.isFinite(speed))return '//'
  const direction=Number(observation?.windDirection10mDeg??observation?.windDeg)
  const deg=Number.isFinite(direction)?Math.round(((direction%360)+360)%360):0
  return `${String(deg).padStart(3,'0')}${String(Math.round(speed)).padStart(2,'0')}MPS`
}

const METAR_PHENOMENA={
  0:'无显著天气',1:'云量递减',2:'云量递增',3:'雷暴',45:'雾',48:'雾凇',
  51:'轻度毛毛雨',53:'中度毛毛雨',55:'浓密毛毛雨',
  61:'小雨',63:'中雨',65:'大雨',66:'冻雨（轻）',67:'冻雨（强）',
  71:'小雪',73:'中雪',75:'大雪',77:'雪粒',
  80:'阵雨（小）',81:'阵雨（中）',82:'阵雨（强）',
  85:'阵雪（小）',86:'阵雪（强）',95:'雷暴',96:'雷暴伴冰雹（小）',99:'雷暴伴冰雹（强）',
}
export function metarPhenomenon(code){
  if(code===null||code===undefined||code==='')return '//'
  const named=METAR_PHENOMENA[Number(code)]
  return named||String(code)
}

export function observationVisibilityM(observation){
  const direct=observation?.visibilityM
  if(direct!==null&&direct!==undefined)return Number(direct)
  const hourly=observation?.hourly?.visibility
  if(!Array.isArray(hourly))return NaN
  const first=hourly.find(v=>v!==null&&v!==undefined)
  return first===undefined?NaN:Number(first)
}

export function metarLines(observation){
  if(!observation)return []
  const tempC=Number(observation.temperatureC??observation.tempC)
  const visibilityM=observationVisibilityM(observation)
  const station=observation.cityName||observation.cityId||observation.station||'—'
  const visibilityBound=observation.visibilityIsLowerBound===true&&!Number.isFinite(visibilityM)
  return [
    {label:'站名',value:String(station)},
    {label:'观测时刻',value:operationalTime(observation.validAt||observation.observedAt,null)},
    {label:'风向风速',value:metarWindRows(observation)},
    {label:'能见度',value:visibilityBound?'仅报下限（>6 mi）':(Number.isFinite(visibilityM)?`${(visibilityM/1000).toFixed(visibilityM>=10000?0:1)} km`:'//')},
    {label:'天气现象',value:metarPhenomenon(observation.weatherCode)},
    {label:'气温',value:Number.isFinite(tempC)?`${Math.round(tempC)} ℃`:'//'},
  ]
}

export function metarOrder(observations){
  const speedOf=o=>Number(o?.windSpeed10mMps??o?.windMps)
  return [...(observations||[])].sort((a,b)=>{
    const va=observationVisibilityM(a),vb=observationVisibilityM(b)
    const ha=Number.isFinite(va)?va:Infinity,hb=Number.isFinite(vb)?vb:Infinity
    if(ha!==hb)return ha-hb
    const sa=speedOf(a),sb=speedOf(b)
    const fa=Number.isFinite(sa)?sa:-1,fb=Number.isFinite(sb)?sb:-1
    if(fa!==fb)return fb-fa
    return String(a?.cityName||a?.cityId||'').localeCompare(String(b?.cityName||b?.cityId||''))
  })
}

const _isNum = value => typeof value === 'number' && Number.isFinite(value)

export function supplementCoverageNote(payload){
  if(!payload||payload.available===false){
    const code=payload&&payload.errorCode
    return code?`补充通道不可用（${code}）`:'补充通道不可用'
  }
  const coverage=(payload&&payload.coverage)||{}
  const asked=_isNum(coverage.requestedCities)?coverage.requestedCities:null
  const got=_isNum(coverage.returnedCities)?coverage.returnedCities:null
  const radius=_isNum(coverage.radiusKm)?coverage.radiusKm:null
  const missing=Array.isArray(coverage.citiesWithoutNearbyStation)?coverage.citiesWithoutNearbyStation:[]
  const head=asked===null?`${got===null?0:got} 个城市有邻近机场站`
    :`${got===null?0:got}/${asked} 个城市有邻近机场站`
  const radiusText=radius===null?'':`（半径 ${radius} km）`
  const named=missing.slice(0,12).join('、')
  const missingText=missing.length?` · 无邻近站 ${missing.length} 个：${named}${missing.length>12?' 等':''}`:''
  return `${head}${radiusText}${missingText} · 机场单点报文，不是面上的气象场`
}

export function supplementObservationRows(payload){
  const source=payload&&Array.isArray(payload.observations)?payload.observations:[]
  return metarOrder(source).map(observation=>({
    id:String(observation.cityId||observation.stationId||observation.cityName||''),
    cityName:String(observation.cityName||observation.cityId||'—'),
    stationId:String(observation.stationId||'—'),
    stationDistanceKm:_isNum(observation.stationDistanceKm)
      ?`${Math.round(observation.stationDistanceKm)} km`:'//',
    lines:metarLines(observation),
    rawText:observation.rawText?String(observation.rawText):'',
  }))
}

export function modelSpreadRows(payload){
  const rows=payload&&Array.isArray(payload.rows)?payload.rows:[]
  const text=(value,unit)=>_isNum(value)?`${value.toFixed(1)} ${unit}`:'仅一侧有值，不给差值'
  return rows.map(row=>({
    id:String(row.cityId||row.cityName||''),
    cityName:String(row.cityName||row.cityId||'—'),
    models:Object.keys((row&&row.models)||{}).sort().join(' / '),
    temperatureText:text(row.temperatureSpreadC,'℃'),
    windText:text(row.windSpreadMps,'m/s'),
  }))
}

export function sigmetRows(weather){
  const cells=(weather?.cells||[])
  if(!cells.length){
    return {heading:'WSIM 无危险天气情报（NIL）',note:'本帧未派生任何风险区。',entries:[]}
  }
  const kindNames={RAIN:'降水',STORM:'雷暴',WIND:'强风',LOW_VISIBILITY:'低能见度'}
  const entries=cells.map(cell=>{
    const merged=Number(cell.memberCount)>1
    const members=merged?(cell.sources||[]).map(s=>String(s).split('::')[0]).join('、'):''
    return {
      id:String(cell.id),
      kind:kindNames[cell.kind]||String(cell.kind||'未分类'),
      status:merged?'MERGED':'ACTIVE',
      body:merged?`由 ${cell.memberCount} 个单体合并（${members}）`:'单一单体，未合并',
      basis:cell.source==='OPEN_METEO_DERIVED_RISK'?'公开天气快照 + 项目阈值派生':'场区 / 谨慎外环 / 禁止内核分别计算后合并',
    }
  })
  return {
    heading:`WSIM 危险天气情报（系统派生 · ${entries.length} 条）`,
    note:'本情报由本系统按公开观测与下述阈值派生，不是任何气象中心发布的 SIGMET；'
      +'不得用于真实飞行放行依据。',
    rules:sigmetThresholdNote(weather?.extremeThresholds),
    entries,
  }
}

export function sigmetThresholdNote(thresholds){
  if(!thresholds)return ''
  const parts=[]
  const gust=Number(thresholds.gustMps)
  const visibility=Number(thresholds.visibilityM)
  const rain=Number(thresholds.hourlyRainMm)
  if(Number.isFinite(gust))parts.push(`阵风 ≥ ${gust} m/s`)
  if(Number.isFinite(visibility))parts.push(`能见度 < ${visibility/1000} km`)
  if(Number.isFinite(rain))parts.push(`小时雨量 ≥ ${rain} mm`)
  if(!parts.length)return ''
  const radius=Number(thresholds.coreRadiusM)
  return `判定阈值：${parts.join(' · ')}${Number.isFinite(radius)?`；触发后内核半径 ${radius/1000} km`:''}。`
}

export const layerStrategyNames={DIRECTION_LAYER:'主用已声明层',ALTERNATE_DECLARED_LAYER:'备用已声明层'}
export const orderFlow=['待备货','待分配','待起飞','配送中','已送达']
export const vehicleFlow=['可用','装载','飞行','返航','充电','停用']
export const orderOutcomeNames={
  ON_TIME:'窗口内送达',DELIVERED_BEYOND_TARGET_WINDOW:'超出目标窗口送达',ARRIVAL_BEYOND_TIMELINE:'预计到达超出观察时段',
  ENERGY_INSUFFICIENT_FOR_RETURN:'电量不足以返航',CANCELLED:'已取消',
}
export const riskLabels={BAN:'风险区核心',CAUTION:'风险区',FIELD:'气象影响范围'}
export const fixedZoneLabel='官方管制区域'
export const radarLabels={
  ban:'实测雷达强回波核心',
  caution:'实测雷达对流回波（可绕飞）',
  watch:'层状降水（可飞越，仅作可见性说明）',
  layer:'实测雷达回波',
}
export const radarLabelsVirtual={
  ban:'模拟回波强对流核心',
  caution:'模拟对流回波（可绕飞）',
  watch:'模拟层状降水（可飞越，仅作可见性说明）',
  layer:'模拟雷达回波',
}
export const RADAR_SOURCE_SYNTHETIC='SYNTHETIC_RADAR_CREF'
export const RADAR_SOURCE='CMA_DATA_NET_RADAR_CREF'

export function radarIsVirtual(radar){
  const region=(radar?.regions||[])[0]||radar?.watch
  if(!region)return false
  if(region.synthetic===true)return true
  return region.source===RADAR_SOURCE_SYNTHETIC
}

export function radarLabelsFor(radar){
  return radarIsVirtual(radar)?radarLabelsVirtual:radarLabels
}
export const WEATHER_MODE_MEASURED='measured'
export const WEATHER_MODE_VIRTUAL='virtual'
export const weatherModeNames={
  [WEATHER_MODE_MEASURED]:'实测气象',
  [WEATHER_MODE_VIRTUAL]:'虚拟气象',
}
export const weatherModeHints={
  [WEATHER_MODE_MEASURED]:'雷达回波取自公开实测拼图（国家组网 CREF）',
  [WEATHER_MODE_VIRTUAL]:'雷达回波由程序生成，形态仿主流气象产品，仅供演示与重现',
}
export function normalizeWeatherMode(mode){
  return mode===WEATHER_MODE_VIRTUAL?WEATHER_MODE_VIRTUAL:WEATHER_MODE_MEASURED
}
export function weatherModeIsVirtual(mode){
  return normalizeWeatherMode(mode)===WEATHER_MODE_VIRTUAL
}
export function weatherModeLabel(mode){
  return weatherModeNames[normalizeWeatherMode(mode)]
}
export function weatherModeButtonState(mode, target, busy=false){
  const active=normalizeWeatherMode(mode)
  const wanted=normalizeWeatherMode(target)
  return {
    active:active===wanted,
    disabled:Boolean(busy)||active===wanted,
    label:weatherModeNames[wanted],
    hint:weatherModeHints[wanted],
  }
}
export function weatherModeStatusText(mode, status){
  const active=normalizeWeatherMode(mode)
  const frames=status?.framesServed||{}
  if(active===WEATHER_MODE_VIRTUAL){
    const served=Number(frames.virtualFrames)
    return Number.isFinite(served)&&served>0
      ? `当前为虚拟气象（已生成 ${served} 帧），回波为程序生成，不是观测数据`
      : '当前为虚拟气象，回波为程序生成，不是观测数据'
  }
  const served=Number(frames.measuredFrames)
  const base=Number.isFinite(served)&&served>0?`当前为实测气象（已取 ${served} 帧）`:'当前为实测气象'
  return status?.available===false?`${base}，但实测源当前不可用`:`${base}，数据来自公开观测源`
}
export function planChannelMismatch(planMode,currentMode){
  if(!planMode)return ''
  const plan=normalizeWeatherMode(planMode)
  const live=normalizeWeatherMode(currentMode)
  if(plan===live)return ''
  return `本计划按「${weatherModeNames[plan]}」生成，而地图当前显示「${weatherModeNames[live]}」：`
    +'画面上的回波不是这份计划避让的那一片，绕飞的缺席属于口径差异，不是算法失效。'
    +'点击「重新调度」可按当前通道重建计划。'
}
export const DEFAULT_RISK_CEILING_AGL_M=620
export const WEATHER_CHANNEL_MODEL='model'
export const WEATHER_CHANNEL_RADAR='radar'
export function weatherChannelState({showWeather=true,showRadar=true}={}){
  const model=Boolean(showWeather)
  const radar=Boolean(showRadar)
  const active=model&&radar?WEATHER_CHANNEL_MODEL+'&'+WEATHER_CHANNEL_RADAR
    :radar?WEATHER_CHANNEL_RADAR
    :model?WEATHER_CHANNEL_MODEL
    :null
  return{active,modelVisible:model,radarVisible:radar,hiddenChannel:null}
}
export function weatherChannelLabel(mode){
  return weatherModeIsVirtual(mode)?'模拟雷达回波':'实测雷达回波'
}
export function weatherChannelNote(state){
  if(!state?.hiddenChannel)return ''
  return ''
}
export const stateMarks={PENDING:'◇',HOLD:'◆',AIRBORNE:'■',ARRIVED:'▪',CLOSED:'✕'}
export const stateNames={PENDING:'待执行',HOLD:'等待放行',AIRBORNE:'飞行中',ARRIVED:'已到达',CLOSED:'已关闭'}
export const phaseNames={CLIMB:'爬升',CRUISE:'巡航',DESCENT:'下降',AIRBORNE:'飞行中',PENDING:'待执行',HOLD:'待放行',ARRIVED:'已到达',CLOSED:'已关闭'}
export const groupNames=['待放行','运行中','受限异常','已完成']
export const releaseWindows=[{minutes:30,label:'未来 30 分钟'},{minutes:60,label:'未来 60 分钟'},{minutes:null,label:'全部班次'}]

export const MAP_ERROR_TEXT={
  NETWORK:'地图资源所在网络不可达，请检查网络或代理后重载地图。',
  TILE_404:'部分范围在底图数据源中没有覆盖（不是网络故障）。',
  GLYPH:'部分文字字形缺失，仅影响标注显示。',
  SPRITE:'地图图标资源缺失，仅影响图层图标。',
  STYLE:'地图样式读取失败，请重载地图。',
  ABORTED:'地图请求被取消（通常由缩放或平移引起）。',
  UNKNOWN:'部分城市地图资源载入失败。',
}
const NETWORK_HINTS=['failed to fetch','network','err_connection','econn','timeout','timed out','dns','enotfound']
const ABORT_HINTS=['abort','cancel','interrupted']
export function classifyMapError(message){
  const text=String(message||'').toLowerCase()
  if(ABORT_HINTS.some(hint=>text.includes(hint)))return 'ABORTED'
  if(text.includes('glyph')||(text.includes('.pbf')&&text.includes('font')))return 'GLYPH'
  if(text.includes('sprite'))return 'SPRITE'
  if(text.includes('style'))return 'STYLE'
  if(text.includes('404')||text.includes('not found')||text.includes('tile'))return 'TILE_404'
  if(NETWORK_HINTS.some(hint=>text.includes(hint)))return 'NETWORK'
  return 'UNKNOWN'
}
export function mapErrorSummary(issues){
  const entries=Object.entries(issues||{}).filter(([,count])=>count>0)
  if(!entries.length)return ''
  const parts=entries.sort((a,b)=>b[1]-a[1]).map(([label,count])=>`${MAP_ERROR_TEXT[label]||MAP_ERROR_TEXT.UNKNOWN}×${count}`)
  return parts.join('；')
}

export const BASEMAP_CHANNEL_ONLINE='online'
export const BASEMAP_CHANNEL_OFFLINE='offline'
export const BASEMAP_CHANNEL_PENDING='pending'
export const basemapChannelNames={
  [BASEMAP_CHANNEL_ONLINE]:'在线底图',
  [BASEMAP_CHANNEL_OFFLINE]:'离线底图',
  [BASEMAP_CHANNEL_PENDING]:'底图载入中',
}
export const OFFLINE_BASEMAP_COLORS={
  land:'#16283a', coast:'#2f5d75', boundary:'#5d8ba3',
  label:'#8fb6c9', labelHalo:'#08131e',
}
export const OFFLINE_BASEMAP_NOTICE='当前离线，底图使用随程序内置的低精度边界（约 1 km 简化），仅用于判断大致方位；在线后自动切回完整底图。'
export function normalizeBasemapChannel(channel){
  return channel===BASEMAP_CHANNEL_OFFLINE?BASEMAP_CHANNEL_OFFLINE
    :channel===BASEMAP_CHANNEL_PENDING?BASEMAP_CHANNEL_PENDING
    :BASEMAP_CHANNEL_ONLINE
}
export function basemapIsOffline(channel){ return normalizeBasemapChannel(channel)===BASEMAP_CHANNEL_OFFLINE }
export function basemapFallbackVisible(channel){ return basemapIsOffline(channel) }
export function basemapChannelLabel(channel){ return basemapChannelNames[normalizeBasemapChannel(channel)] }
export function basemapStatusText(channel,{error='',buildingCount=0,city=''}={}){
  const state=normalizeBasemapChannel(channel)
  if(state===BASEMAP_CHANNEL_OFFLINE){
    const where=city?'':'全域'
    return `离线底图已载入 · ${where}低精度边界（无在线底图）`
  }
  if(state===BASEMAP_CHANNEL_PENDING)return error||'正在载入城市地图'
  return error||(city?(buildingCount?`城市道路与立体建筑已载入`:`城市地图已载入 · 当前范围无建筑要素`):'全域城市地图已载入')
}
export function basemapSignalFromError(message){
  const label=classifyMapError(message)
  if(label==='TILE_404')return 'no-tiles'
  if(label==='NETWORK')return 'no-tiles'
  if(label==='STYLE')return 'no-tiles'
  if(label==='GLYPH'||label==='SPRITE')return null
  if(label==='ABORTED')return null
  return null
}
export const BASEMAP_OFFLINE_AFTER_FAILURES=6
export function basemapChannelAfterSignal(channel,failures){
  const state=normalizeBasemapChannel(channel)
  const numeric=typeof failures==='number'&&!Number.isNaN(failures)&&failures>0
  const count=numeric?(failures===Infinity?BASEMAP_OFFLINE_AFTER_FAILURES:failures):0
  if(count>=BASEMAP_OFFLINE_AFTER_FAILURES)return BASEMAP_CHANNEL_OFFLINE
  return state===BASEMAP_CHANNEL_OFFLINE?BASEMAP_CHANNEL_OFFLINE:state
}

export function markFor(state){
  return stateMarks[state]||'■'
}

let _effectiveKey=null
let _effectiveResult=null

export function effectiveFlights(flights,operations,minute){
  if(_effectiveKey
     &&_effectiveKey.flights===flights
     &&_effectiveKey.operations===operations
     &&_effectiveKey.minute===minute){
    return _effectiveResult
  }
  let state=null
  for(const op of operations||[]){
    if(op.minute<=minute){
      if(state===null)state=new Map()
      state.set(op.flightId,op.action)
    }
  }
  let suspended=null
  if(state!==null){
    for(const [flightId,action] of state){
      if(action==='SUSPEND'){
        if(suspended===null)suspended=new Set()
        suspended.add(flightId)
      }
    }
  }
  const result=(suspended===null)
    ?flights
    :flights.map(f=>suspended.has(f.id)?{...f,status:'CLOSED',reason:'MANUAL_SUSPEND',manuallySuspended:true,plannedPoints:f.points,points:[]}:f)
  _effectiveKey={flights,operations,minute}
  _effectiveResult=result
  return result
}

export function flightState(f,minute){
  if(f.status==='CLOSED')return 'CLOSED'
  if(minute<f.departureMinute)return minute>=f.scheduledMinute?'HOLD':'PENDING'
  return minute>=f.arrivalMinute?'ARRIVED':'AIRBORNE'
}

export function vehicleLabelText(f){
  if(!f)return ''
  const name=String(f.name||f.id||'')
  const parts=name.split(' · ')
  return (parts.length>1&&parts[1].startsWith(parts[0]))?parts[1]:name
}

export function labelWidth(text,{cjk=12.6,latin=6.6,pad=14}={}){
  let width=Number(pad)||0
  for(const ch of String(text==null?'':text)){
    width += /[\u2e80-\u9fff\uff00-\uffef\u3000-\u303f]/.test(ch)?cjk:latin
  }
  return width
}

export function altitudeText(altitudeM){
  if(altitudeM==null)return '高度未上报'
  const value=Number(altitudeM)
  if(!Number.isFinite(value))return '高度未上报'
  if(value<1)return '待起飞'
  return Math.round(value)+' m'
}

export function vehicleLabel(f,altitudeM){
  const name=vehicleLabelText(f)
  return name?name+' · '+altitudeText(altitudeM):''
}

export function selectVehicleLabels(candidates,{max=40,height=18,gapAbove=24,margin=2,estimate=labelWidth}={}){
  const rows=Array.isArray(candidates)?candidates.filter(Boolean):[]
  const ranked=rows.slice().sort((a,b)=>
    (Number(b.priority)||0)-(Number(a.priority)||0)
    ||(Number(a.depth)-Number(b.depth))
    ||(String(a.id)<String(b.id)?-1:String(a.id)>String(b.id)?1:0))
  const kept=[],boxes=[]
  for(const row of ranked){
    if(kept.length>=max)break
    const width=Number(row.width)>0?Number(row.width):estimate(row.text)
    const half=width/2+margin
    const top=row.y-gapAbove-height/2-margin,bottom=row.y-gapAbove+height/2+margin
    const box={left:row.x-half,right:row.x+half,top,bottom}
    if(boxes.some(b=>!(box.right<b.left||box.left>b.right||box.bottom<b.top||box.top>b.bottom)))continue
    kept.push(row);boxes.push(box)
  }
  return kept
}

export function flightPhase(f,minute){
  const state=flightState(f,minute)
  if(state!=='AIRBORNE')return state
  const points=f.points||[]
  if(points.length<3)return 'AIRBORNE'
  const duration=f.arrivalMinute-f.departureMinute
  if(minute<f.departureMinute+Math.min(2,duration*.15))return 'CLIMB'
  if(minute>f.arrivalMinute-Math.min(2,duration*.15))return 'DESCENT'
  return 'CRUISE'
}

export function relativeClock(minute){
  if(!Number.isFinite(Number(minute)))return '—'
  const total=Math.max(0,Math.round(Number(minute)*60)),hours=Math.floor(total/3600),minutes=Math.floor(total%3600/60),seconds=total%60
  return `T+${String(hours).padStart(2,'0')}:${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}`
}

export function operationalTime(iso,minute){
  if(!iso)return '—'
  const date=new Date(iso)
  if(Number.isNaN(date.getTime()))return relativeClock(minute)
  const displayed=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date)
  return minute==null?displayed:`${displayed} · ${relativeClock(minute)}`
}

export function executionTimes(f,minute){
  if(!f?.points?.length)return {actualReleaseAt:null,actualTakeoffAt:null,actualArrivalAt:null}
  return {
    actualReleaseAt:minute>=f.departureMinute?f.plannedReleaseAt:null,
    actualTakeoffAt:minute>=f.departureMinute?f.plannedTakeoffAt:null,
    actualArrivalAt:minute>=f.arrivalMinute?f.estimatedArrivalAt:null,
  }
}

export function orderState(f,state,phase){
  if(f?.orderStatus==='取消'||state==='CLOSED')return '取消'
  if(state==='PENDING')return '待备货'
  if(state==='HOLD')return '待分配'
  if(state==='AIRBORNE')return phase==='CLIMB'?'待起飞':'配送中'
  if(state==='ARRIVED')return '已送达'
  return '待分配'
}

export function vehicleState(f,state,minute,settings){
  if(state==='CLOSED')return '停用'
  if(state==='PENDING'||state==='HOLD')return '装载'
  if(state==='AIRBORNE')return '飞行'
  if(state==='ARRIVED'){
    const charge=Number(settings?.chargeMinutes)||0
    const settle=Number(f.arrivalMinute||0)+(Number(f.returnLegMinutes)||0)
    if(minute<settle)return '返航'
    if(minute<settle+charge)return '充电'
    return '可用'
  }
  return '可用'
}

export function layerLabel(f){
  if(f?.assignedLayerAglM==null)return '未分配层'
  const strategy=layerStrategyNames[f.layerStrategy]||'已声明层'
  return `${Math.round(f.assignedLayerAglM)} m AGL · ${strategy}`
}

export function riskCeiling(weather,fallback=DEFAULT_RISK_CEILING_AGL_M){
  const value=weather?.riskRules?.ceilingAglM
  return Number.isFinite(Number(value))&&Number(value)>0?Number(value):fallback
}

export const RADAR_PENDING_TIMEOUT_MS=5000
export const RADAR_STATE={PENDING:'PENDING',READY:'READY',QUIET:'QUIET',DOWN:'DOWN'}

export function radarBandRow(radar,band){
  const row=(radar?.summary?.bands||{})[band]
  if(!row||typeof row!=='object')return {components:0,areaKm2:0}
  return {components:Number(row.components)||0,areaKm2:Number(row.areaKm2)||0}
}

export function radarState(radar,{waitedMs=null,timeoutMs=RADAR_PENDING_TIMEOUT_MS}={}){
  if(radar&&typeof radar==='object'&&radar.available===true){
    const regions=Array.isArray(radar.regions)?radar.regions:[]
    const drawn=regions.some(r=>['Polygon','MultiPolygon'].includes(r?.field?.type)
      &&(r.field.coordinates||[]).length)
    if(drawn)return RADAR_STATE.READY
    return RADAR_STATE.QUIET
  }
  if(radar!==null&&radar!==undefined)return RADAR_STATE.DOWN
  const waited=Number(waitedMs)
  if(waitedMs===null||!Number.isFinite(waited))return RADAR_STATE.PENDING
  return waited<Math.max(0,Number(timeoutMs)||RADAR_PENDING_TIMEOUT_MS)
    ?RADAR_STATE.PENDING:RADAR_STATE.DOWN
}

export function radarUnavailable(radar,options){
  const state=radarState(radar,options)
  return state!==RADAR_STATE.READY&&state!==RADAR_STATE.QUIET
}

export function radarSummaryText(radar,{waitedMs=null,timeoutMs=RADAR_PENDING_TIMEOUT_MS}={}){
  const state=radarState(radar,{waitedMs,timeoutMs})
  const virtual=radarIsVirtual(radar)
  const subject=virtual?'模拟雷达':'实测雷达'
  if(state===RADAR_STATE.PENDING){
    return `${subject}正在读取：请求已发出，尚未收到本帧数据（超过 ${Math.round((Number(timeoutMs)||RADAR_PENDING_TIMEOUT_MS)/1000)} 秒未到按不可用处理）`
  }
  if(state===RADAR_STATE.DOWN){
    return radar?.error?`${subject}不可用：${radar.error}`:`${subject}不可用：本帧未取得数据`
  }
  const convective=radarBandRow(radar,'CONVECTIVE')
  const strong=radarBandRow(radar,'STRONG')
  const stratiform=radarBandRow(radar,'STRATIFORM')
  const parts=[]
  if(strong.components)parts.push(`强回波（≥45 dBZ）${strong.areaKm2} km²`)
  if(convective.components)parts.push(`对流回波（35—45 dBZ）${convective.areaKm2} km²`)
  const prefix=virtual?'【模拟回波】':''
  if(!parts.length&&stratiform.components){
    return `${prefix}本作业区仅见层状降水（${stratiform.areaKm2} km²，15—35 dBZ），不构成飞行限制`
  }
  if(!parts.length)return `${prefix}本作业区内无达到 35 dBZ 的对流回波`
  const slot=radar?.summary?.slot||radar?.regions?.[0]?.slot||''
  const age=radar?.summary?.slotAgeMinutes
  const when=slot
    ?(virtual?`生成时次 ${formatRadarSlot(slot)}`
      :`观测时次 ${formatRadarSlot(slot)}${Number.isFinite(Number(age))?`（${Math.round(Number(age))} 分钟前）`:''}`)
    :''
  return `${prefix}${parts.join(' · ')}${when?`；${when}`:''}`
}

export function radarFrozenNote(radar,{playing=false,minute=0}={}){
  const state=radarState(radar)
  if(radarUnavailable(radar))return ''
  if(radarIsVirtual(radar))return ''
  if(!playing)return ''
  const age=Number(radar?.summary?.slotAgeMinutes)
  const aged=Number.isFinite(age)?`（当前帧为 ${Math.round(age)} 分钟前的观测）`:''
  return `实测回波为单次观测，推演中按设计保持不动${aged}；`
    +'需要看回波随时间的演变请切换到虚拟气象，或读取新的观测时次。'
}

export function fixedZoneFrozenNote(network,{playing=false}={}){
  if(!playing)return ''
  const zones=network?.staticAirspace?.zones||[]
  if(!zones.length)return ''
  return `固定管制区为法规静态数据（${zones.length} 处），其几何本身不随时间变化；`
    +'随时间变化的是各班次穿越管制区的时段，见地图越界监视条。'
}

export const WEATHER_BUCKET_MINUTES=2
export function weatherBucket(minute,bucketMinutes=WEATHER_BUCKET_MINUTES){
  const m=Number(minute)
  if(!Number.isFinite(m))return 0
  const size=Number(bucketMinutes)>0?Number(bucketMinutes):WEATHER_BUCKET_MINUTES
  return Math.floor(m/size)
}
export function weatherBucketChanged(previousMinute,currentMinute,bucketMinutes=WEATHER_BUCKET_MINUTES){
  return weatherBucket(previousMinute,bucketMinutes)!==weatherBucket(currentMinute,bucketMinutes)
}

export function formatRadarSlot(slot){
  if(typeof slot!=='string'||!slot)return ''
  const ms=Date.parse(slot)
  if(!Number.isFinite(ms))return slot
  const d=new Date(ms+8*3600*1000)
  const pad=value=>String(value).padStart(2,'0')
  return `${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

export function radarSurfaces(radar){
  const out=[]
  if(radarUnavailable(radar))return out
  for(const region of radar.regions||[]){
    for(const [tier,geometry] of [['FIELD',region.field],['BAN',region.ban],['CAUTION',region.caution]]){
      if(!geometry||!['Polygon','MultiPolygon'].includes(geometry.type))continue
      if(!(geometry.coordinates||[]).length)continue
      out.push({tier,geometry,id:region.id,source:region.source||RADAR_SOURCE,
        slot:region.slot||null,slotAgeMinutes:region.slotAgeMinutes??null})
    }
  }
  const watch=radar.watch
  if(watch?.field&&['Polygon','MultiPolygon'].includes(watch.field.type)&&(watch.field.coordinates||[]).length){
    out.push({tier:'WATCH',geometry:watch.field,id:watch.id,source:watch.source||RADAR_SOURCE,
      slot:watch.slot||null,slotAgeMinutes:null})
  }
  return out
}

export const LOW_VISIBILITY_TIERS=Object.freeze({BAN:'BAN',CAUTION:'CAUTION'})
export const LOW_VISIBILITY_STATE=Object.freeze({READY:'READY',QUIET:'QUIET',DOWN:'DOWN'})
export const LOW_VISIBILITY_COLORS=Object.freeze({
  cautionFill:'#8d94a3',cautionLine:'#b9c0ce',
  banFill:'#3f4653',banLine:'#6c7484',
  cautionOpacity:.3,banOpacity:.62,width:2.4,widthBan:3.4,
})

function _fogRegion(raw){
  if(!raw||typeof raw!=='object')return null
  const visibility=Number.isFinite(raw.visibilityM)?raw.visibilityM:null
  if(visibility===null)return null
  return {id:String(raw.id||''),cityId:String(raw.cityId||''),
    cityName:raw.cityName?String(raw.cityName):'',
    tier:raw.tier===LOW_VISIBILITY_TIERS.BAN?LOW_VISIBILITY_TIERS.BAN:LOW_VISIBILITY_TIERS.CAUTION,
    visibilityM:visibility,
    ban:raw.ban||null,caution:raw.caution||null,
    derivedFrom:_fogDerivedFrom(raw.derivedFrom)}
}

function _fogDerivedFrom(raw){
  if(!raw||typeof raw!=='object')return null
  const provider=raw.provider?String(raw.provider):''
  const dataType=raw.dataType?String(raw.dataType):''
  if(!provider&&!dataType)return null
  return {provider:provider||null,dataType:dataType||null}
}

export function lowVisibilityRegions(weather){
  const block=weather?.lowVisibility
  if(!block||block.available!==true)return []
  return (block.regions||[]).map(_fogRegion).filter(Boolean)
}

export function lowVisibilitySurfaces(weather){
  const out=[]
  for(const region of lowVisibilityRegions(weather)){
    for(const [tier,geometry] of [[LOW_VISIBILITY_TIERS.BAN,region.ban],
                                  [LOW_VISIBILITY_TIERS.CAUTION,region.caution]]){
      if(!geometry||!['Polygon','MultiPolygon'].includes(geometry.type))continue
      if(!(geometry.coordinates||[]).length)continue
      out.push({tier,geometry,id:region.id,cityId:region.cityId,cityName:region.cityName,
        visibilityM:region.visibilityM,derivedFrom:region.derivedFrom})
    }
  }
  return out
}

export function lowVisibilityState(weather){
  const block=weather?.lowVisibility
  if(!block||block.available!==true)return LOW_VISIBILITY_STATE.DOWN
  return lowVisibilitySurfaces(weather).length?LOW_VISIBILITY_STATE.READY:LOW_VISIBILITY_STATE.QUIET
}

export function lowVisibilitySummaryText(weather){
  const block=weather?.lowVisibility
  const state=lowVisibilityState(weather)
  if(state===LOW_VISIBILITY_STATE.DOWN){
    return block?.error?`低能见度图层不可用：${block.error}`:'低能见度图层不可用：本帧未取得站点读数'
  }
  const regions=lowVisibilityRegions(weather)
  const ban=regions.filter(r=>r.tier===LOW_VISIBILITY_TIERS.BAN)
  const caution=regions.filter(r=>r.tier===LOW_VISIBILITY_TIERS.CAUTION)
  const banM=Number.isFinite(block?.banVisibilityM)?block.banVisibilityM:null
  const cautionM=Number.isFinite(block?.cautionVisibilityM)?block.cautionVisibilityM:null
  const banR=Number.isFinite(block?.banRadiusM)?Math.round(block.banRadiusM/1000):null
  const cautionR=Number.isFinite(block?.cautionRadiusM)?Math.round(block.cautionRadiusM/1000):null
  if(state===LOW_VISIBILITY_STATE.QUIET){
    return `低能见度：本帧没有站点低于偏低档阈值${cautionM!==null?`（${cautionM} m）`:''}，未生成任何雾区几何`
  }
  const parts=[]
  if(ban.length)parts.push(`深灰 ${ban.length} 城（能见度 <${banM} m，禁止进入${banR?`，半径 ${banR} km`:''}）`)
  if(caution.length)parts.push(`浅灰 ${caution.length} 城（能见度 <${cautionM} m，须绕飞、可擦边${cautionR?`，半径 ${cautionR} km`:''}）`)
  const names=[...ban,...caution].map(r=>`${r.cityName||r.cityId} ${Math.round(r.visibilityM)} m`)
  return `低能见度：${parts.join('；')}。读数：${names.join('、')}。`
    +'范围由站点读数派生，是近似值，不是实测雾区边界。'
}

export function lowVisibilityRuleBlock(plan){
  const block=plan&&plan.lowVisibilityAvoidance
  if(!block||typeof block!=='object')return null
  return {
    cautionVisibilityM:Number.isFinite(block.cautionVisibilityM)?block.cautionVisibilityM:null,
    banVisibilityM:Number.isFinite(block.banVisibilityM)?block.banVisibilityM:null,
    cautionRadiusM:Number.isFinite(block.cautionRadiusM)?block.cautionRadiusM:null,
    banRadiusM:Number.isFinite(block.banRadiusM)?block.banRadiusM:null,
    hardTier:block.hardTier||null,softTier:block.softTier||null,
    padExemptTier:block.padExemptTier||null,
    thresholdSource:block.thresholdSource?String(block.thresholdSource):'',
    included:block.included===true,
    reason:block.reason?String(block.reason):'',
    cities:Number.isFinite(block.cities)?block.cities:null,
    padExemptFlights:Number.isFinite(block.padExemptFlights)?block.padExemptFlights:null,
  }
}

export const RADAR_BAN_TIER='BAN'

function _geometryBounds(geometry){
  let minLon=Infinity,minLat=Infinity,maxLon=-Infinity,maxLat=-Infinity
  const walk=value=>{
    if(typeof value?.[0]==='number'){
      const [lon,lat]=value
      if(lon<minLon)minLon=lon
      if(lon>maxLon)maxLon=lon
      if(lat<minLat)minLat=lat
      if(lat>maxLat)maxLat=lat
      return
    }
    if(Array.isArray(value))value.forEach(walk)
  }
  walk(geometry?.coordinates)
  return Number.isFinite(minLon)?[minLon,minLat,maxLon,maxLat]:null
}

function _insideRing(lon,lat,ring){
  let inside=false
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1]
    if(((yi>lat)!==(yj>lat))&&(lon<(xj-xi)*(lat-yi)/(yj-yi)+xi))inside=!inside
  }
  return inside
}

export function radarBanSurfaces(radar,toLocal){
  const out=[]
  for(const surface of radarSurfaces(radar)){
    if(surface.tier!==RADAR_BAN_TIER)continue
    const geometry=toLocal?toLocal(surface.geometry):surface.geometry
    const bounds=_geometryBounds(geometry)
    if(bounds)out.push({bounds,geometry,id:surface.id})
  }
  return out
}

export function insideRadarBan(point,ban){
  const bounds=ban?.bounds,lon=point?.[0],lat=point?.[1]
  if(!bounds||!Number.isFinite(lon)||!Number.isFinite(lat))return false
  if(lon<bounds[0]||lon>bounds[2]||lat<bounds[1]||lat>bounds[3])return false
  const coordinates=ban.geometry?.coordinates||[]
  const polygons=ban.geometry?.type==='Polygon'?[coordinates]:coordinates
  for(const rings of polygons){
    if(!rings||!rings.length||!rings[0]?.length)continue
    if(!_insideRing(lon,lat,rings[0]))continue
    let hole=false
    for(let index=1;index<rings.length;index++){
      if(_insideRing(lon,lat,rings[index])){hole=true;break}
    }
    if(!hole)return true
  }
  return false
}

export function radarCoreIntrusionAt(point,bans){
  if(!bans?.length)return null
  for(const ban of bans){
    if(insideRadarBan(point,ban))return ban
  }
  return null
}

export function radarFeatureGeometry(surface){
  return surface.geometry
}

export function geometryLooksGeographic(geometry,minSpanDeg=0){
  if(!geometry||!Array.isArray(geometry.coordinates))return false
  let seen=false,minLon=Infinity,maxLon=-Infinity,minLat=Infinity,maxLat=-Infinity
  const walk=value=>{
    if(typeof value?.[0]==='number'){
      seen=true
      const [lon,lat]=value
      if(lon<100||lon>150||lat<30||lat>60)return false
      if(lon<minLon)minLon=lon
      if(lon>maxLon)maxLon=lon
      if(lat<minLat)minLat=lat
      if(lat>maxLat)maxLat=lat
      return true
    }
    return Array.isArray(value)&&value.every(walk)
  }
  if(!walk(geometry.coordinates)||!seen)return false
  if(minSpanDeg>0)return maxLon-minLon>=minSpanDeg&&maxLat-minLat>=minSpanDeg
  return true
}

export function radarTopology(radar){
  if(radar?.regions?.length)return radar.regions[0].field?.type||''
  return radar?.watch?.field?.type||''
}

export function radarSource(radar){
  const region=(radar?.regions||[])[0]||radar?.watch
  if(region?.source)return region.source
  if(radarUnavailable(radar))return ''
  return radarIsVirtual(radar)?RADAR_SOURCE_SYNTHETIC:RADAR_SOURCE
}

export const staticZoneLabels={
  STATIC_PROHIBITED:'固定管制区（未获批准不得进入）',
  STATIC_APPROVAL_REQUIRED:'固定管制空域（须经批准）',
  STATIC_REGISTERED:'已登记待补范围',
}
export const STATIC_PROHIBITED='PROHIBITED'
export const STATIC_APPROVAL_REQUIRED='APPROVAL_REQUIRED'
export const STATIC_REGISTERED='REGISTERED_REVIEW_REQUIRED'
export const STATIC_ENFORCEMENTS=[STATIC_PROHIBITED,STATIC_APPROVAL_REQUIRED,STATIC_REGISTERED]

const STATIC_LABEL_BY_ENFORCEMENT={
  [STATIC_PROHIBITED]:staticZoneLabels.STATIC_PROHIBITED,
  [STATIC_APPROVAL_REQUIRED]:staticZoneLabels.STATIC_APPROVAL_REQUIRED,
  [STATIC_REGISTERED]:staticZoneLabels.STATIC_REGISTERED,
}
export function staticEnforcementLabel(enforcement){
  return STATIC_LABEL_BY_ENFORCEMENT[enforcement]||'固定管制区'
}

export function staticZoneSummary(staticAirspace){
  const zones=staticAirspace?.zones||[]
  const tally={PROHIBITED:0,APPROVAL_REQUIRED:0,REGISTERED_REVIEW_REQUIRED:0}
  const sectors=new Map(),clauses=new Set()
  let withGeometry=0
  for(const zone of zones){
    if(zone?.geometry)withGeometry++
    if(zone?.enforcement in tally)tally[zone.enforcement]++
    if(zone?.sector)sectors.set(zone.sector,(sectors.get(zone.sector)||0)+1)
    if(zone?.clause)clauses.add(zone.clause)
  }
  const audit=staticAirspace?.audit
  return {
    total:zones.length,
    withGeometry,
    registeredOnly:zones.length-withGeometry,
    prohibited:tally.PROHIBITED,
    approvalRequired:tally.APPROVAL_REQUIRED,
    registered:tally.REGISTERED_REVIEW_REQUIRED,
    sectors:[...sectors.entries()].sort((a,b)=>b[1]-a[1]),
    clauseCount:clauses.size,
    catalogVersion:staticAirspace?.status?.catalogVersion||audit?.catalogVersion||'',
    dataRetrievedAt:staticAirspace?.status?.dataRetrievedAt||'',
    policy:staticAirspace?.status?.policy||'',
  }
}

export function staticZoneBand(zone,fallbackCeiling=DEFAULT_RISK_CEILING_AGL_M){
  const floor=Number.isFinite(Number(zone?.floorAglM))?Number(zone.floorAglM):0
  const drawn=Number(zone?.displayCeilingAglM)
  const ceiling=Number.isFinite(drawn)&&drawn>floor?drawn:Math.max(Number(fallbackCeiling)||0,floor+1)
  return {floor,ceiling,openEndedAbove:zone?.openEndedAbove!==false}
}

export function staticZoneSurfaces(staticAirspace,fallbackCeiling=DEFAULT_RISK_CEILING_AGL_M){
  const volumes=[],references=[]
  for(const zone of staticAirspace?.zones||[]){
    const kind=zone?.geometry?.type
    if(kind==='Polygon'||kind==='MultiPolygon'){
      volumes.push({zone,...staticZoneBand(zone,fallbackCeiling),citation:zone.citation||''})
      continue
    }
    const coordinate=zone?.referencePoint?.coordinate
    if(Array.isArray(coordinate)&&coordinate.length>=2)references.push({zone,coordinate})
  }
  return {volumes,references}
}

export function staticCrossingSummary(flight){
  const crossing=flight?.staticAirspace
  if(!crossing?.zones)return ''
  const parts=(crossing.crossings||[]).map(record=>`${record.name} ${relativeClock(record.entryMinute)}—${relativeClock(record.exitMinute)}`)
  const more=crossing.zones-(crossing.crossings||[]).length
  return `${crossing.zones} 处固定管制区${crossing.prohibited?`（含 ${crossing.prohibited} 处禁入）`:''}：${parts.join('；')}${more>0?`；另有 ${more} 处未展开`:''}`
}

export const ZONE_INTRUSION={PROHIBITED:'PROHIBITED',APPROVAL_REQUIRED:'APPROVAL_REQUIRED',NONE:'NONE'}
export const zoneIntrusionLabels={
  [ZONE_INTRUSION.PROHIBITED]:'已进入禁入区',
  [ZONE_INTRUSION.APPROVAL_REQUIRED]:'已进入须批准管制空域',
  [ZONE_INTRUSION.NONE]:'',
}
const INTRUSION_RANK={[ZONE_INTRUSION.NONE]:0,[ZONE_INTRUSION.APPROVAL_REQUIRED]:1,[ZONE_INTRUSION.PROHIBITED]:2}
function intrusionLevel(enforcement){
  if(enforcement===STATIC_PROHIBITED)return ZONE_INTRUSION.PROHIBITED
  if(enforcement===STATIC_APPROVAL_REQUIRED)return ZONE_INTRUSION.APPROVAL_REQUIRED
  return ZONE_INTRUSION.NONE
}

function finiteMinute(value){
  if(value===null||value===undefined||value==='')return null
  const number=Number(value)
  return Number.isFinite(number)?number:null
}

export function zoneIntrusionAt(flight,minute){
  const crossing=flight?.staticAirspace||{}
  const records=crossing.crossings||[]
  if(records.length===0){
    return _noIntrusion(crossing,0)
  }
  const active=[],upcoming=[]
  let level=ZONE_INTRUSION.NONE
  let prohibitedReported=0
  for(const record of records){
    if(record?.enforcement===STATIC_PROHIBITED)prohibitedReported+=1
    const start=finiteMinute(record?.entryMinute),end=finiteMinute(record?.exitMinute)
    if(start===null||end===null)continue
    const candidate=intrusionLevel(record.enforcement)
    if(minute>=start&&minute<=end){
      active.push(record)
      if(INTRUSION_RANK[candidate]>INTRUSION_RANK[level])level=candidate
    }else if(start>minute){
      upcoming.push({record,minutesAway:start-minute})
    }
  }
  const reported=records.length
  const total=Number(crossing.zones)||0
  if(active.length===0&&upcoming.length===0){
    return _noIntrusion(crossing,reported,prohibitedReported)
  }
  if(upcoming.length>1)upcoming.sort((a,b)=>a.minutesAway-b.minutesAway)
  return {
    level,
    label:zoneIntrusionLabels[level],
    active,
    lead:active.find(record=>record.enforcement===STATIC_PROHIBITED)||active[0]||null,
    next:upcoming[0]||null,
    reported,
    total,
    truncated:total>reported,
    prohibitedHidden:Math.max(0,(Number(crossing.prohibited)||0)-prohibitedReported),
  }
}

function _noIntrusion(crossing,reported,prohibitedReported=0){
  const total=Number(crossing.zones)||0
  return {
    level:ZONE_INTRUSION.NONE,
    label:zoneIntrusionLabels[ZONE_INTRUSION.NONE],
    active:EMPTY_INTRUSION_LIST,
    lead:null,
    next:null,
    reported,
    total,
    truncated:total>reported,
    prohibitedHidden:Math.max(0,(Number(crossing.prohibited)||0)-prohibitedReported),
  }
}

const EMPTY_INTRUSION_LIST=[]

export function zoneIntrusionRank(level){
  return INTRUSION_RANK[level]||0
}

export function zoneIntrusions(flights,minute){
  const rows=[]
  for(const flight of flights||[]){
    const state=zoneIntrusionAt(flight,minute)
    if(state.level===ZONE_INTRUSION.NONE)continue
    rows.push({flight,state})
  }
  rows.sort((a,b)=>INTRUSION_RANK[b.state.level]-INTRUSION_RANK[a.state.level]
    ||String(a.flight?.id).localeCompare(String(b.flight?.id)))
  return rows
}

export function filterLedgerRows(flights,{showCar=true,showDelivery=true,city='',search='',status='ALL',minute=0}={}){
  const needle=(search||'').toLowerCase()
  const rows=[]
  for(const flight of flights||[]){
    if(flight.mode==='CAR'?!showCar:!showDelivery)continue
    if(city&&flight.fromCity!==city&&flight.toCity!==city)continue
    if(needle&&!(String(flight.name).toLowerCase().includes(needle)||String(flight.id).toLowerCase().includes(needle)))continue
    if(status!=='ALL'&&flightState(flight,minute)!==status)continue
    rows.push(flight)
  }
  return rows
}

export function releaseQueue(flights,minute,horizon=30,scope){
  const end=minute+horizon
  return (flights||[])
    .filter(f=>f.status==='SCHEDULED'&&f.departureMinute>=minute&&f.departureMinute<=end)
    .filter(f=>!scope||scope(f))
    .sort((a,b)=>a.departureMinute-b.departureMinute||a.id.localeCompare(b.id))
}

export function groupFlights(flights,minute){
  const groups={待放行:[],运行中:[],受限异常:[],已完成:[]}
  for(const f of flights||[]){
    const state=flightState(f,minute)
    if(state==='PENDING'||state==='HOLD')groups.待放行.push(f)
    else if(state==='AIRBORNE')groups.运行中.push(f)
    else if(state==='CLOSED')groups.受限异常.push(f)
    else groups.已完成.push(f)
  }
  return groups
}

export function trajectoryOf(flight){
  const points=flight&&flight.points
  return Array.isArray(points)?points:[]
}

export function atTime(points,minute){
  if(!points?.length)return null
  if(minute<=points[0][3])return points[0].slice(0,3)
  for(let index=1;index<points.length;index++){
    const a=points[index-1],b=points[index]
    if(minute<=b[3]){const fraction=(minute-a[3])/(b[3]-a[3]);return a.slice(0,3).map((value,key)=>value+(b[key]-value)*fraction)}
  }
  return points.at(-1).slice(0,3)
}

export function profile(points){
  if(!points?.length)return ''
  const start=points[0][3],duration=points.at(-1)[3]-start,max=Math.max(200,...points.map(point=>point[2]))
  return points.map(point=>`${10+280*(point[3]-start)/duration},${90-75*point[2]/max}`).join(' ')
}

export function splitTrajectoryAt(points,minute){
  if(!points?.length)return [[],[]]
  if(minute<=points[0][3])return [[],points]
  if(minute>=points.at(-1)[3])return [points,[]]
  let index=1
  while(index<points.length&&points[index][3]<minute)index++
  const a=points[index-1],b=points[index]
  const fraction=(minute-a[3])/(b[3]-a[3])
  const cut=a.map((value,key)=>value+(b[key]-value)*fraction)
  const ahead=cut[3]===b[3]?points.slice(index):[cut,...points.slice(index)]
  return [[...points.slice(0,index),cut],ahead]
}

export function splitTrajectoryInto(points,minute,out){
  const result=out||[[],[]]
  if(!points?.length){result[0]=[];result[1]=[];return result}
  if(minute<=points[0][3]){result[0]=[];result[1]=points;return result}
  if(minute>=points.at(-1)[3]){result[0]=points;result[1]=[];return result}
  let index=1
  while(index<points.length&&points[index][3]<minute)index++
  const a=points[index-1],b=points[index]
  const fraction=(minute-a[3])/(b[3]-a[3])
  const cut=[
    a[0]+(b[0]-a[0])*fraction,
    a[1]+(b[1]-a[1])*fraction,
    a[2]+(b[2]-a[2])*fraction,
    a[3]+(b[3]-a[3])*fraction,
  ]
  const flown=points.slice(0,index)
  flown.push(cut)
  result[0]=flown
  result[1]=cut[3]===b[3]?points.slice(index):[cut,...points.slice(index)]
  return result
}

export function virtualWindow(length,scrollTop,viewportHeight,rowHeight,overscan=0){
  const total=Math.max(0,Math.floor(length))
  if(!total)return {startIndex:0,endIndex:0}
  const height=rowHeight>0?rowHeight:1
  const startIndex=Math.max(0,Math.floor(Math.max(0,scrollTop)/height)-overscan)
  const endIndex=Math.min(total,Math.ceil((Math.max(0,scrollTop)+Math.max(0,viewportHeight))/height)+overscan)
  return {startIndex,endIndex:Math.max(startIndex,endIndex)}
}

export const WEATHER_CLOSURE_REASONS=new Set([
  'WEATHER_UNAVAILABLE','WEATHER_BLOCKED','FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED',
])

const AVOIDANCE_ABSENT_REASONS={
  SCENARIO_DOES_NOT_DECLARE_WEATHER:'本场景未声明气象，计划不加入回波避让几何',
  RADAR_UNAVAILABLE:'本次构建未取到可用的雷达回波，计划不加入回波避让几何',
  CHANNEL_CHANGED_DURING_BUILD:'构建期间气象通道被切换，本计划不使用回波避让几何',
  VIRTUAL_FRAME_NOT_SYNTHETIC:'虚拟通道取帧拿到的不是生成的模拟回波（取帧未走生成器），本计划不使用回波避让几何',
  VIRTUAL_FRAME_UNAVAILABLE:'虚拟通道取帧失败 —— 模拟回波本不应取不到，本计划不使用回波避让几何',
}
export function avoidanceAbsentReason(reason){
  if(!reason)return '本计划没有声明回波避让几何的来源'
  return AVOIDANCE_ABSENT_REASONS[reason]||String(reason)
}

export function weatherCorridorStory(plan,weather){
  const radar=(plan&&plan.radarAvoidance)||null
  const cells=Array.isArray(weather?.cells)?weather.cells.length:0
  if(!radar){
    return {
      included:false,
      headline:'本计划未声明回波避让几何',
      detail:avoidanceAbsentReason(null),
      rows:[],
      cells,
    }
  }
  const virtual=radar.mode==='virtual'
  const channel=virtual?'虚拟气象通道（程序生成回波）':'实测气象通道（公开观测）'
  const included=radar.included===true
  const rows=[
    {label:'避让几何来源',value:channel},
    {label:'判定档位',value:radar.tiers==='CONVECTIVE_AND_STRONG'
      ?'≥35 dBZ 起算，≥45 dBZ 内核不可触碰':'—'},
  ]
  if(virtual){
    const slots=Number(radar.sweepSlots)
    const stride=Number(radar.sweepStrideMinutes)
    rows.push({label:'避让采样',
      value:Number.isFinite(slots)&&slots>0
        ?`${slots} 个采样点 × 每 ${Number.isFinite(stride)?stride:'—'} 分钟`
        :(radar.reason==='NO_CONVECTIVE_ECHO'?'本窗口无 ≥35 dBZ 回波':'本帧无可用采样')})
    if(radar.slot)rows.push({label:'采样覆盖时段',
      value:radar.slotTo?`${operationalTime(radar.slot,null)} → ${operationalTime(radar.slotTo,null)}`
        :operationalTime(radar.slot,null)})
  }else{
    const age=Number(radar.slotAgeMinutes)
    rows.push({label:'观测时刻',
      value:radar.slot?`${operationalTime(radar.slot,null)}`
        +(Number.isFinite(age)?`（距今 ${age} 分钟）`:''):'未声明'})
    const area=Number(radar.areaKm2)
    if(Number.isFinite(area))rows.push({label:'回波覆盖面积',value:`${area} km²`})
    const tiers=[
      ['禁止进入内核',radar.coreAreaKm2],
      ['须绕飞场',radar.cautionAreaKm2],
      ['层状降水（可穿越）',radar.watchAreaKm2],
    ].filter(([,value])=>Number.isFinite(Number(value)))
    if(tiers.length===3)
      rows.push({label:'回波分级面积',
        value:tiers.map(([label,value])=>`${label} ${Number(value)} km²`).join(' · ')})
    rows.push({label:'时间口径',
      value:'单时刻观测驱动全窗口避让（不外推为预报）'})
  }
  const silentRadar=!included&&radar.reason==='NO_CONVECTIVE_ECHO'
  return {
    included,
    virtual,
    silentRadar,
    headline:included
      ?(virtual?'航路按随时间平移的模拟回波逐班避让':'航路按本次实测回波避让')
      :(silentRadar?'本帧无 ≥35 dBZ 回波，航路按直线走廊放行':'本次构建未纳入回波避让几何'),
    detail:included?(radar.note||'')
      :(silentRadar?(radar.detail||''):avoidanceAbsentReason(radar.reason)),
    rows,
    cells,
  }
}

export const TONE_FAMILY={
  normal:'flight',cyan:'flight',
  warn:'weather',alert:'weather',calm:'weather',
  good:'status',muted:'status',
}
export function toneFitsFamily(family,tone){
  const owner=TONE_FAMILY[tone]
  if(!owner)return false
  return owner==='status'||owner===family
}

export const routeBasisNames={
  CLEAR:'直飞段可用',
  STATIC_AIRSPACE:'固定管制区',
  POINT_WEATHER:'风险区核心',
  LOW_VISIBILITY:'低能见度（雾）',
  RADAR_CORE:'雷达 ≥45 dBZ 内核',
  RADAR_FIELD:'雷达 ≥35 dBZ 场',
  BOUNDARY:'作业区边界',
}
export const WEATHER_ROUTE_BASES=Object.freeze(['POINT_WEATHER','LOW_VISIBILITY','RADAR_CORE','RADAR_FIELD'])

export function isWeatherDetour(flight){
  return WEATHER_ROUTE_BASES.includes(String(flight?.routeBasis||''))
}

export function weatherDetourRows(flights){
  return (Array.isArray(flights)?flights:[]).filter(isWeatherDetour)
}

export function nonWeatherRouteRows(flights){
  return (Array.isArray(flights)?flights:[])
    .filter(f=>f&&f.routeBasis&&f.routeBasis!=='CLEAR'&&!isWeatherDetour(f))
}

export function routeBasisNote(flight){
  const name=routeBasisNames[String(flight?.routeBasis||'')]
  if(!name)return ''
  const raw=flight?.routeBasisFromMinute
  if(raw===null||raw===undefined||raw==='')return `成因：${name}（全时段）`
  const from=Number(raw)
  if(!Number.isFinite(from))return `成因：${name}（全时段）`
  return `成因：${name}（${relativeClock(from)} 起）`
}

export function stageKpis(flights,weather,plan,ai){
  const list=Array.isArray(flights)?flights:[]
  const total=list.length
  const closed=list.filter(f=>f&&f.status==='CLOSED')
  const weatherClosed=closed.filter(f=>WEATHER_CLOSURE_REASONS.has(f.reason))
  const detoured=weatherDetourRows(list)
  const otherCause=nonWeatherRouteRows(list)
  const delay=delaySpread(list)
  const radar=(plan&&plan.radarAvoidance)||null
  const slots=Number(radar?.sweepSlots)
  const cells=Array.isArray(weather?.cells)?weather.cells.length:0
  const virtualRadar=!!radar&&radar.mode==='virtual'
  const sampled=Number.isFinite(slots)&&slots>0
  const included=!!radar&&radar.included===true
  const clearSky=!!radar&&!included&&radar.reason==='NO_CONVECTIVE_ECHO'
  const sweep=virtualRadar
    ?{value:sampled?slots:0,unit:'点',
      note:sampled?`步长 ${radar.sweepStrideMinutes} 分钟 · 逐班取窗口并集`
        :clearSky?'判据已执行 · 本窗口无 ≥35 dBZ 回波，航路按直线走廊放行'
        :avoidanceAbsentReason(radar.reason),
      tone:sampled?'warn':(clearSky?'good':'muted')}
    :{value:(included||clearSky)?1:0,unit:'次观测',
      note:!radar?'无避让几何声明'
        :included?'单时刻观测驱动全窗口避让'
        :clearSky?'判据已执行 · 本帧无 ≥35 dBZ 回波，按直线走廊放行'
        :avoidanceAbsentReason(radar.reason),
      tone:included?'warn':(clearSky?'good':'muted')}
  const rows=[
    {key:'accepted',family:'flight',label:'受理班次',value:total-closed.length,unit:'班',
     note:`计划 ${total} 班 · 关闭 ${closed.length} 班`,tone:'normal'},
    {key:'detour',family:'flight',label:'受气象影响改航',value:detoured.length,unit:'班',
     note:detoured.length?'航路被气象推移'
       :otherCause.length?`本场景无气象改航 · 另有 ${otherCause.length} 班因作业区边界等非气象约束绕行`
       :'本场景无改航班次',
     tone:detoured.length?'cyan':'muted'},
    {key:'delay',family:'flight',label:'延误中位数',value:delay.median,unit:'分',
     note:delay.count?`受影响 ${delay.count} 班 · 最大 ${delay.max} 分`:'无延误班次',
     tone:delay.count?'cyan':'good'},
    {key:'weather',family:'weather',label:'气象关闭',value:weatherClosed.length,unit:'班',
     note:weatherClosed.length?'因气象不予放行':'无一班因气象停飞',
     tone:weatherClosed.length?'warn':'good'},
    {key:'risk',family:'weather',label:'派生风险区',value:cells,unit:'个',
     note:cells?'按公开观测与项目阈值派生':'本帧无风险区',tone:cells?'warn':'muted'},
    {key:'sweep',family:'weather',label:'避让采样',...sweep},
    {key:'ai',family:'flight',label:'AI 研判覆盖',...aiCell(ai,list.length)},
  ]
  return rows
}

function aiCell(ai,total){
  const reviewed=ai&&Number.isFinite(Number(ai.reviewed))?Number(ai.reviewed):0
  const vetoed=ai&&Number.isFinite(Number(ai.vetoed))?Number(ai.vetoed):0
  if(!total)return {value:0,unit:'班',note:'尚无班次可供研判',tone:'muted'}
  if(!reviewed)return {value:0,unit:'班',
    note:`本会话尚未手动发起逐班研判。全部 ${total} 班的放行结论由「规则 + 概率模型」两层给出：`
      + `规则可一票否决，模型只能更严；两者不一致时记入「④ 推演 · 第 8 步 复核」`,
    tone:'muted'}
  return {value:reviewed,unit:'班',
    note:`已研判 ${reviewed} / 共 ${total} 班${vetoed?` · 其中 ${vetoed} 班的模型作答被规则整条否决`:''}；其余由规则引擎直接产出`,
    tone:'cyan'}
}

export function dispatchSummaryRows(flights,minute){
  const list=(Array.isArray(flights)?flights:[]).filter(Boolean)
  const at=Number(minute)||0
  const counts={PENDING:0,HOLD:0,AIRBORNE:0,ARRIVED:0,CLOSED:0}
  const airborne={CAR:0,DELIVERY:0}
  for(const f of list){
    const state=flightState(f,at)
    if(!(state in counts))continue
    counts[state]+=1
    if(state==='AIRBORNE')airborne[f.mode==='DELIVERY'?'DELIVERY':'CAR']+=1
  }
  const total=counts.PENDING+counts.HOLD+counts.AIRBORNE+counts.ARRIVED+counts.CLOSED
  return {
    at,
    total,
    airborne,
    rows:[
      {key:'airborne',family:'flight',label:'在空',value:counts.AIRBORNE,unit:'架',
       note:`飞行汽车 ${airborne.CAR} · 配送无人机 ${airborne.DELIVERY}`,
       tone:counts.AIRBORNE?'cyan':'muted'},
      {key:'pending',family:'flight',label:'未起飞',value:counts.PENDING+counts.HOLD,unit:'班',
       note:counts.HOLD?`其中等待放行 ${counts.HOLD} 班`:'全部为待执行',tone:'muted'},
      {key:'arrived',family:'flight',label:'已到达',value:counts.ARRIVED,unit:'班',
       note:counts.ARRIVED?'本时刻已完成':'本时刻无到达',tone:counts.ARRIVED?'good':'muted'},
      {key:'closed',family:'flight',label:'已关闭',value:counts.CLOSED,unit:'班',
       note:counts.CLOSED?'不计入放行':'本时刻无关闭',
       tone:counts.CLOSED?'normal':'muted'},
    ],
    note:'全网络口径 · 与所选区域无关 · 图上标签按空间精简，不与「在空」相等',
  }
}

export function clearanceReport(clearance){
  if(!clearance)return []
  const level=Number(clearance.assignedLevelAglM)
  const ctot=clearance.ctot||null
  const lines=[
    `CLR ${clearance.callsign||'—'}`,
    `  LIM  ${clearance.limit||'未声明放行界限'}`,
    `  RTE  ${clearance.route||'未声明航路'}`,
    `  LVL  ${Number.isFinite(level)&&level>0?`${Math.round(level)} m AGL`:'未指派高度层'}`,
  ]
  if(ctot&&ctot.from){
    const validity=Number(ctot.validityMinutes)
    lines.push(`  CTOT ${operationalTime(ctot.from,null)}`
      +(Number.isFinite(validity)?` 有效 ${validity} 分钟`:'')
      +(ctot.until?` / 至 ${operationalTime(ctot.until,null)}`:''))
  }else{
    lines.push('  CTOT 未取得时隙')
  }
  lines.push(`  WX   ${clearance.weatherBasis||'未声明气象判据'}`)
  if(clearance.status)lines.push(`  ST   ${clearanceStatusName(clearance.status)}`)
  return lines
}

export function clearanceStatusName(status){
  const raw=status==null?'':String(status)
  if(!raw)return '未声明净空状态'
  if(raw==='SIMULATION_ASSUMPTION_UNVERIFIED')return '地形/建筑净空待验证'
  if(raw==='CLEARED'||raw==='VERIFIED')return '净空已检查'
  return raw
}

export function detourMinutesShort(minutes){
  const value=Math.abs(Number(minutes)||0)
  if(value<0.5)return '<1 分'
  return `${Math.round(value)} 分`
}

export function briefingTicker(weather,flights){
  const items=[]
  const entries=sigmetRows(weather).entries||[]
  for(const e of entries){
    items.push({id:'WX-'+e.id,kind:'SIGMET',tone:e.status==='MERGED'?'warn':'alert',
      title:e.kind,meta:e.id,body:e.body,foot:e.basis})
  }
  const rows=metarOrder(weather?.observations).map(o=>({
    id:'OB-'+String(o.cityId||o.cityName||o.station||''),
    kind:'观测',tone:tickerTone('观测',observationTone(o)),
    title:String(o.cityName||o.cityId||o.station||'—'),
    meta:metarWindRows(o),
    body:metarSummaryText(o),
    foot:`观测时刻 ${operationalTime(o.validAt||o.observedAt,null)}`,
  }))
  items.push(...rows)
  const detours=[]
  for(const f of weatherDetourRows(flights)){
    detours.push({f,detour:Number(f?.detourMinutes)||0})
  }
  detours.sort((a,b)=>b.detour-a.detour)
  for(const {f,detour} of detours){
    items.push({id:'FL-'+f.id,kind:'改航',tone:tickerTone('改航','cyan'),
      title:f.name||f.id,meta:`+${detourMinutesShort(detour)}`,
      body:f.atcClearance?.weatherBasis||'航路受气象影响推移',
      foot:`${f.fromPad||'—'} → ${f.toPad||'—'} · 航程 ${f.distanceKm??'—'} km · ${routeBasisNote(f)}`})
  }
  return items
}

export function tickerTone(kind,tone){
  const value=tone==null?'':String(tone)
  if(kind==='改航')return 'cyan'
  if(value==='normal')return 'calm'
  return value||'calm'
}

export function observationTone(observation){
  const visibility=observationVisibilityM(observation)
  if(Number.isFinite(visibility)&&visibility<5000)return 'alert'
  const speed=Number(observation?.windSpeed10mMps??observation?.windMps)
  if(Number.isFinite(speed)&&speed>=12)return 'warn'
  return 'normal'
}

export function metarSummaryText(observation){
  const visibility=observationVisibilityM(observation)
  const speed=Number(observation?.windSpeed10mMps??observation?.windMps)
  const temp=Number(observation?.temperatureC??observation?.tempC)
  const parts=[
    Number.isFinite(visibility)?`能见度 ${(visibility/1000).toFixed(visibility>=10000?0:1)} km`:'能见度 //',
    Number.isFinite(speed)?`风速 ${Math.round(speed)} m/s`:'风速 //',
    Number.isFinite(temp)?`${Math.round(temp)} ℃`:'气温 //',
    metarPhenomenon(observation?.weatherCode),
  ]
  return parts.join(' · ')
}

export function scrollCycle(count,rowHeight){
  const n=Math.max(0,Math.floor(Number(count)||0))
  const h=Number(rowHeight)
  if(!n||!(h>0))return 0
  return n*h
}
export function scrollWrap(offset,cycle){
  const span=Number(cycle)
  if(!(span>0))return 0
  const value=Number.isFinite(Number(offset))?Number(offset):0
  return ((value%span)+span)%span
}
export function scrollTarget(offset,steps,cycle){
  const span=Number(cycle)
  if(!(span>0))return 0
  const base=Number.isFinite(Number(offset))?Number(offset):0
  return base+(Number(steps)||0)
}

export function stageScale(containerW,containerH,stageW=1920,stageH=1080){
  const w=Number(containerW),h=Number(containerH),sw=Number(stageW),sh=Number(stageH)
  if(!(w>0)||!(h>0)||!(sw>0)||!(sh>0))return 0
  return Math.min(w/sw,h/sh)
}

export const STAGE_H=1080
export const STAGE_MIN_W=1660
export const STAGE_MAX_W=2560
export function stageBox(containerW,containerH){
  const w=Number(containerW),h=Number(containerH)
  if(!(w>0)||!(h>0))return {width:0,height:0,scale:0}
  const ideal=Math.round((h>0?w/h:16/9)*STAGE_H)
  const width=Math.max(STAGE_MIN_W,Math.min(STAGE_MAX_W,ideal))
  const scale=stageScale(w,h,width,STAGE_H)
  return {width,height:STAGE_H,scale}
}

export function wallClockText(date,{withSeconds=true}={}){
  const d=date instanceof Date?date:null
  if(!d||Number.isNaN(d.getTime()))return '—'
  const p=value=>String(value).padStart(2,'0')
  const hhmm=`${p(d.getHours())}:${p(d.getMinutes())}`
  return withSeconds?`${hhmm}:${p(d.getSeconds())}`:hhmm
}
export function wallDateText(date){
  const d=date instanceof Date?date:null
  if(!d||Number.isNaN(d.getTime()))return '—'
  const p=value=>String(value).padStart(2,'0')
  const week=['日','一','二','三','四','五','六'][d.getDay()]
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} 周${week}`
}

export const BUILD_NOTES=[
  '展开雷达回波时轴：把 8 小时窗口按时间片逐帧取回',
  '按 35 dBZ 以上回波重算航路：该绕的绕、该等的等',
  '逐班复核间隔：水平 250 m · 垂直 60 m 的模拟标准',
  '核对固定管制区穿越：只读官方目录，不做推断',
  '汇总放行队列：按计划放行时刻排序',
]
export function buildNote(seconds,{holdSeconds=4,notes=BUILD_NOTES}={}){
  const list=Array.isArray(notes)?notes.filter(n=>typeof n==='string'&&n):[]
  if(!list.length)return ''
  const hold=Number(holdSeconds)
  const elapsed=Math.max(0,Number(seconds)||0)
  if(!(hold>0))return list[0]
  return list[Math.floor(elapsed/hold)%list.length]
}

export function buildProgressView(session){
  const s=session&&typeof session==='object'?session:null
  const status=s&&typeof s.status==='string'?s.status:''
  const hasNumber=!!s&&typeof s.progress==='number'&&Number.isFinite(s.progress)
  const percent=hasNumber?Math.max(0,Math.min(100,Math.round(s.progress))):null
  const queued=status==='BUSY'
    ?(typeof s.message==='string'&&s.message?s.message:'已有模拟计划正在计算，当前请求正在排队')
    :''
  const stage=queued||(s&&typeof s.stage==='string'&&s.stage?s.stage
    :(s?'正在计算运行计划':'正在提交调度请求'))
  return {status,percent,stage,queued}
}

export function shortFingerprint(value,length=8){
  const text=typeof value==='string'?value.trim():''
  if(!/^[0-9a-f]{8,}$/i.test(text))return ''
  const wanted=Math.max(8,Math.min(16,Number(length)||8))
  if(text.length<wanted)return ''
  return text.slice(0,wanted)
}

export function algorithmIdentity(session){
  if(!session||session.status!=='READY')return ''
  const contract=typeof session.version==='string'?session.version.trim():''
  const fingerprint=shortFingerprint(session.fingerprint)
  if(!contract||!fingerprint)return ''
  return `算法 ${contract} · 指纹 ${fingerprint}`
}

export function algorithmIdentityTitle(session){
  const label=algorithmIdentity(session)
  if(!label)return ''
  const raw=session.planRevision
  const numeric=(typeof raw==='number'||(typeof raw==='string'&&raw.trim()!==''))?Number(raw):NaN
  const revisionText=Number.isFinite(numeric)?`计划修订 r${numeric}`:'计划修订未声明'
  return `${label} · ${revisionText}｜算法指纹是后端 traffic/*.py 全部字节的 SHA256 前 16 位：`
    +`改动任一算法文件即改变，改动产品版本号不会改变。同一指纹 + 同一数据快照编号 + 同一气象通道，`
    +`重跑得到逐字节相同的运行计划。`
}

export const MECHANISM_ELEMENTS=Object.freeze([
  Object.freeze({key:'criterion',label:'气象判据'}),
  Object.freeze({key:'geometry',label:'几何'}),
  Object.freeze({key:'window',label:'时间窗'}),
])

export const BASIS_MACHINERY=Object.freeze({
  CLEAR:Object.freeze({
    construction:'不做避让：直连段自身即航路',
    detail:'直连段没有碰到任何一块限制几何，因此没有第二条航路可讲。',
  }),
  STATIC_AIRSPACE:Object.freeze({
    construction:'法定固定管制区几何（静态目录数据，非气象）',
    detail:'固定管制区来自法规与公开数据，与气象无关；它使直连段不可用，与回波无关。',
  }),
  POINT_WEATHER:Object.freeze({
    construction:'点观测派生风险区（单次观测，无时间维度）',
    detail:'派生的禁止内核按该点观测推得；一次观测就是一次观测，不向时间轴外推。',
  }),
  LOW_VISIBILITY:Object.freeze({
    construction:'低能见度两档缓冲圆（站点读数派生，非实测雾区边界）',
    detail:'能见度低于禁飞阈值的一档是不可触碰的深灰内核；偏低一档只让航路绕开，'
      +'起降点落在该圆内时该圆不约束本班次 —— 否则"能见度偏低"会变成"不许起飞"。',
  }),
  RADAR_CORE:Object.freeze({
    construction:'回波内核几何，不可触碰',
    detail:'内核不是强对流原轮廓，而是危险外场向内收缩一段深度后得到的内部 ——'
      +'原轮廓在真实回波上是一圈碎点，画出来看不见。',
  }),
  RADAR_FIELD:Object.freeze({
    construction:'回波外场几何，允许有界擦边',
    detail:'外场可被航路擦过，但擦入深度有上限；上限与水平间隔同源，本项目不为此另立标准。',
  }),
  BOUNDARY:Object.freeze({
    construction:'作业区边界（范围划定，非气象）',
    detail:'直连段落在了允许作业范围之外，因此绕行是被范围逼出来的，不是被气象逼出来的。',
  }),
})

export function radarRuleBlock(plan){
  const avoidance=plan&&plan.radarAvoidance
  if(!avoidance||typeof avoidance!=='object')return null
  const nested=(avoidance.rule&&typeof avoidance.rule==='object')?avoidance.rule:null
  const num=raw=>(typeof raw==='number'&&Number.isFinite(raw))?raw:null
  const pick=key=>{
    const top=num(avoidance[key])
    return top!==null?top:num(nested?nested[key]:null)
  }
  const tierText=typeof avoidance.tiers==='string'&&avoidance.tiers?avoidance.tiers
    :(nested&&typeof nested.tiers==='string'?nested.tiers:'')
  const block={
    tiers:tierText,
    bandFloorDbz:pick('bandFloorDbz'),
    convectiveDbz:pick('convectiveDbz'),
    strongDbz:pick('strongDbz'),
    coreInsetM:pick('coreInsetM'),
    penetrationM:pick('penetrationM'),
  }
  const published=Object.keys(block).some(key=>key!=='tiers'&&block[key]!==null)
  return published?block:null
}

const SAMPLE_PER_BASIS=4

export function routeBasisCensus(flights){
  const list=Array.isArray(flights)?flights:[]
  const rows=new Map()
  let unevaluated=0
  for(const flight of list){
    if(!flight||typeof flight!=='object'){unevaluated++;continue}
    const key=typeof flight.routeBasis==='string'?flight.routeBasis:''
    if(!Object.prototype.hasOwnProperty.call(routeBasisNames,key)){unevaluated++;continue}
    let row=rows.get(key)
    if(!row){
      row={key,name:routeBasisNames[key],construction:BASIS_MACHINERY[key].construction,
        weather:WEATHER_ROUTE_BASES.includes(key),total:0,detoured:0,delayed:0,sampleIds:[]}
      rows.set(key,row)
    }
    row.total++
    const detour=finiteMinute(flight.detourMinutes)
    if(detour!==null&&detour>0.01)row.detoured++
    const delay=finiteMinute(flight.delayMinutes)
    if(delay!==null&&delay>0)row.delayed++
    if(row.sampleIds.length<SAMPLE_PER_BASIS)row.sampleIds.push(flight.id)
  }
  const order=Object.keys(routeBasisNames)
  const sorted=[...rows.values()].sort((a,b)=>(b.weather-a.weather)||(b.total-a.total)
    ||(b.detoured-a.detoured)
    ||(order.indexOf(a.key)-order.indexOf(b.key)))
  return {total:list.length,unevaluated,rows:sorted}
}

export function mechanismChain(flight,plan){
  if(!flight||typeof flight!=='object')return null
  const key=typeof flight.routeBasis==='string'?flight.routeBasis:''
  const known=Object.prototype.hasOwnProperty.call(routeBasisNames,key)
  const machinery=known?BASIS_MACHINERY[key]:null
  const rule=radarRuleBlock(plan)
  const virtual=weatherModeIsVirtual(plan?.weatherMode)

  const criterion=known
    ? {absent:null,headline:routeBasisNames[key],
       lines:[routeBasisNote(flight),machinery.detail,thresholdText(key,rule)].filter(Boolean)}
    : {absent:'本班次没有成因判据：没有走到成因判定（未受理的班次在更早的判据处就结束了）。',
       headline:'',lines:[]}

  const distance=finiteMinute(flight.distanceKm)
  const detour=finiteMinute(flight.detourMinutes)
  const delay=finiteMinute(flight.delayMinutes)
  const crossings=Array.isArray(flight.crossingZones)?flight.crossingZones.length:null
  const statutory=(flight.staticAirspace&&Array.isArray(flight.staticAirspace.crossings))
    ?flight.staticAirspace.crossings.length:null
  const geometry=known
    ? {absent:null,
       headline:`${machinery.construction}${geometrySuffix(key,virtual,plan)}`,
       lines:[geometryEffect(detour,distance,delay),
         crossings===null?'':(crossings?`起降与交叉资源：已预约 ${crossings} 个交叉区`:'起降与交叉资源：无交叉区'),
         statutory===null?'':`固定管制区穿越记录 ${statutory} 条`].filter(Boolean)}
    : {absent:detour!==null&&detour>0.01
         ?'本班次航程确实增加了，但没有成因判据可引用：不要在缺少判据时倒推出一个成因。'
         :'本班次没有几何可讲：它没有被规划出一条替代航路。',
       headline:'',lines:detour===null?[]:[geometryEffect(detour,distance,delay)]}

  const from=finiteMinute(flight.departureMinute)
  const to=finiteMinute(flight.arrivalMinute)
  const cause=flight.routeBasisFromMinute
  const hasCause=cause!==null&&cause!==undefined&&cause!==''
    &&Number.isFinite(Number(cause))
  const window=known
    ? {absent:null,
       headline:(from!==null&&to!==null)
         ?`${relativeClock(from)} → ${relativeClock(to)}（本班次自身窗口）`
         :'本班次窗口未声明',
       lines:[windowNote(virtual,plan,hasCause,cause)]}
    : {absent:'本班次没有时间窗可讲：它没有起降计划。',headline:'',lines:[]}

  const missing=[]
  if(!known)missing.push('criterion')
  if(!known&&detour===null)missing.push('geometry')
  if(!known&&from===null)missing.push('window')

  const byKey={criterion,geometry,window}
  const steps=MECHANISM_ELEMENTS.map(element=>({...element,...byKey[element.key]}))

  return {
    id:flight.id||'',name:flight.name||flight.id||'',
    basisKey:known?key:'',basisIsWeather:known&&WEATHER_ROUTE_BASES.includes(key),
    steps,missing,ok:known,
  }
}

function geometrySuffix(key,virtual,plan){
  if(key!=='RADAR_CORE'&&key!=='RADAR_FIELD')return ''
  if(!virtual)return '；实测通道：单时刻观测驱动全窗口，不外推为预报'
  const stride=finiteMinute(plan?.radarAvoidance?.sweepStrideMinutes)
  const slots=finiteMinute(plan?.radarAvoidance?.sweepSlots)
  const parts=['虚拟通道：回波随推演时间轴平移']
  if(stride!==null)parts.push(`按 ${stride} 分钟分箱取并集`)
  if(slots!==null)parts.push(`本次共 ${slots} 个采样时次`)
  return `；${parts.join('，')}`
}

function thresholdText(key,rule){
  if(key!=='RADAR_CORE'&&key!=='RADAR_FIELD')return ''
  if(!rule)return '本计划未发布分级规则，此处不引用阈值'
  const parts=[]
  if(key==='RADAR_CORE'&&rule.strongDbz!==null){
    parts.push(`判据阈值 ≥${rule.strongDbz} dBZ，内核一律不可触碰（不得进入）`)
    if(rule.coreInsetM!==null)parts.push(`内核为外场向内收缩 ${rule.coreInsetM} m`)
  }
  if(key==='RADAR_FIELD'&&rule.convectiveDbz!==null){
    parts.push(`判据阈值 ≥${rule.convectiveDbz} dBZ，外场可擦边`)
    if(rule.penetrationM!==null)parts.push(`擦入深度上限 ${rule.penetrationM} m（与水平间隔同源）`)
  }
  return parts.join('；')
}

function geometryEffect(detour,distance,delay){
  const parts=[]
  if(detour===null){
    parts.push('航程变化未声明')
  }else if(detour>0.01){
    parts.push(`绕行增时 ${Math.round(detour)} 分钟`)
  }else{
    parts.push('航线长度未增加')
  }
  if(distance!==null)parts.push(`航程 ${distance} km`)
  if(delay!==null&&delay>0)parts.push(`地面等待 ${Math.round(delay)} 分钟`)
  return parts.join(' · ')
}

function windowNote(virtual,plan,hasCause,cause){
  const parts=[]
  parts.push(hasCause
    ?`成因回波自 ${relativeClock(Number(cause))} 起盖住直连段`
    :'该成因在整段计划窗口内一直成立，没有起始分钟')
  if(virtual){
    const stride=finiteMinute(plan?.radarAvoidance?.sweepStrideMinutes)
    parts.push(stride!==null
      ?`避让几何按 ${stride} 分钟分箱，只并本班次窗口内的时次`
      :'避让几何只并本班次窗口内的时次')
  }else{
    parts.push('实测通道只有一次观测：本班次窗口两端不改变几何，也不外推为预报')
  }
  return parts.join('；')
}

export function mechanismPickerRows(flights,{basis='',query='',limit=12}={}){
  const needle=String(query||'').trim().toLowerCase()
  const wanted=typeof basis==='string'?basis:''
  const order=Object.keys(routeBasisNames)
  const rows=[]
  for(const flight of (Array.isArray(flights)?flights:[])){
    if(!flight||typeof flight!=='object')continue
    const key=typeof flight.routeBasis==='string'?flight.routeBasis:''
    if(!Object.prototype.hasOwnProperty.call(routeBasisNames,key))continue
    if(wanted&&key!==wanted)continue
    if(needle&&![flight.id,flight.name,flight.fromCity,flight.toCity,flight.fromPad,flight.toPad]
      .filter(Boolean).some(value=>String(value).toLowerCase().includes(needle)))continue
    rows.push(flight)
  }
  rows.sort((a,b)=>
    (WEATHER_ROUTE_BASES.includes(b.routeBasis)-WEATHER_ROUTE_BASES.includes(a.routeBasis))
    ||((finiteMinute(b.detourMinutes)||0)-(finiteMinute(a.detourMinutes)||0))
    ||(order.indexOf(a.routeBasis)-order.indexOf(b.routeBasis))
    ||(finiteMinute(a.departureMinute)??1e9)-(finiteMinute(b.departureMinute)??1e9)
    ||String(a.id).localeCompare(String(b.id)))
  const cap=Math.max(1,Number(limit)||12)
  return {rows:rows.slice(0,cap),matched:rows.length,limit:cap}
}

const CAUSE_ADVICE={
  WEATHER_BLOCKED:'该走廊在班次经过时段被回波挡住。优先改时隙或改航绕飞，两者都不可行才停止放行。',
  WEATHER_UNAVAILABLE:'本轮没取到可核对的气象几何。先查气象源，不要在缺气象的情况下放行。',
  FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED:'最终复核未通过。核对班次经过时刻的回波与边界后再决定。',
  NO_GEOMETRIC_PATH:'这是<b>几何</b>结论，不是气象结论。可调整起降点或走廊，不要记到气象账上。',
  SEPARATION_RESOURCE_OR_TIME_LIMIT:'已声明高度层、起降与交叉资源或额外耗时均无法满足。先尝试改时隙或换备用高度层。',
  STATIC_AIRSPACE_BLOCKED:'起降点落在固定管制区（法规），只能等批准或改起降点，与气象无关。',
  TURN_RADIUS_OR_BOUNDARY_LIMIT:'转弯半径或边界限制。缩短航段或调整走廊走向。',
  ALTITUDE_PROFILE_LIMIT:'超过机型高度上限。换机型或拆分为多段。',
  BEYOND_PLANNING_HORIZON:'超出规划视界，在视界内无法完成。把班次移进视界内或另排一天。',
  MANUAL_SUSPEND:'人工暂停，原计划保留以供追溯。确认无需恢复后可在本页标记已处置。',
}
function corridorLabel(flight){
  const from=flight.fromCity||flight.fromPad||''
  const to=flight.toCity||flight.toPad||''
  return from||to?`${from||'—'} → ${to||'—'}`:''
}
export function groupAlerts(flights){
  const groups=new Map()
  let totalFlights=0,weatherFlights=0,nonWeatherFlights=0
  let closedFlights=0,weatherClosedFlights=0
  for(const flight of (Array.isArray(flights)?flights:[])){
    if(!flight||typeof flight!=='object')continue
    const closed=flight.status==='CLOSED'
    if(!closed&&!flight.delayMinutes&&!flight.detourMinutes)continue
    const reason=typeof flight.reason==='string'?flight.reason:''
    const routeKey=flight.routeId||flight.corridorId||'未知走廊'
    const key=`${routeKey}:${reason}:${closed}`
    let row=groups.get(key)
    if(!row){
      row={key,routeId:flight.routeId??'',reason,closed,
        weather:weatherClosureReasons.has(reason),
        name:reasonNames[reason]||reason,
        short:closureShortNames[reason]||reasonNames[reason]||reason,
        advice:CAUSE_ADVICE[reason]||'',
        count:0,closedCount:0,detoured:0,delayed:0,
        corridors:[],sample:flight}
      groups.set(key,row)
    }
    row.count++
    totalFlights++
    if(row.weather)weatherFlights++;else nonWeatherFlights++
    if(closed){row.closedCount++;closedFlights++;if(row.weather)weatherClosedFlights++}
    if((finiteMinute(flight.detourMinutes)||0)>0.01)row.detoured++
    if((finiteMinute(flight.delayMinutes)||0)>0)row.delayed++
    const corridor=corridorLabel(flight)
    if(corridor&&!row.corridors.includes(corridor)&&row.corridors.length<4)row.corridors.push(corridor)
  }
  const rows=[...groups.values()].sort((a,b)=>(b.closed-a.closed)||(b.weather-a.weather)
    ||(b.count-a.count)||String(a.key).localeCompare(String(b.key)))
  return {rows,total:rows.length,
    weatherEvents:rows.filter(r=>r.weather).length,
    nonWeatherEvents:rows.filter(r=>!r.weather).length,
    totalFlights,weatherFlights,nonWeatherFlights,closedFlights,weatherClosedFlights}
}

export const TIMELINE_SPAN_MINUTES=480

export const SECTION_CAN_DO=Object.freeze({
  home:['看哪条走廊最差（点结论条）','把时间轴拖到 T+3h 看风险变化','按 Ctrl+K 搜班次或走廊'],
  overview:['点地图上的载具看单班航迹','切换图层看雷达与风险区','导出本轮快照'],
  briefing:['挑一个班次看放行许可报文','按状态筛选待放行','跳到走廊剖面看判据'],
  schedule:['按城市或班次号搜索','翻页看全量台账','点行选中后看单班处置'],
  alerts:['按严重度筛选事件','定位到地图上的事件位置','把事件带进研判页'],
  weather:['切换实测/虚拟通道','看逐站 METAR 与风险区','导出本帧观测'],
  mechanism:['按 8 步看一条走廊怎么被判出来','换走廊或拖时间轴重算','看第 8 步的复核记录'],
  reference:['在总账表里查分母与来源','看来源角标的含义','核对边界声明'],
  assistant:['发起一次逐班研判','看模型档位与置信度','把否决理由写进台账'],
  history:['按时间倒着看运行日志','筛出人工干预','导出 CSV'],
  profile:['生成一句解读（模板或大模型）','看判据与来源站号','改风险偏好做反事实'],
  card:['看三条基线的胜负','看混淆矩阵与可靠性曲线','导出模型卡 JSON'],
  counterfactual:['切换三档风险偏好','看改判明细','导出对照结果'],
  ledger:['看模型与规则的分歧','按走廊筛选','导出分歧台账 CSV'],
})

export const CALIBER_LEDGER=Object.freeze([
  {key:'planned',name:'计划班次',definition:'情景基线内全部计划执行的班次',
   numerator:null,denominator:null,source:'建场输出 `session.stats.accepted`（交通为模拟）',
   refresh:'每次建场',owner:'后端'},
  {key:'releaseRate',name:'放行率',definition:'允许执行的班次占比',
   numerator:'放行班次',denominator:'计划班次',source:'规则引擎与模型融合后的处置结果',
   refresh:'每次建场（换情景 / 换气象通道时重算）',owner:'后端'},
  {key:'pending',name:'待处置走廊（观测判据命中）',
   definition:'能见度 <1000 m / 阵风 >阈值 / 云底 <300 m 任一条命中的城际走廊数（同一批走廊里最轻的一档）',
   numerator:'观测判据命中的走廊',denominator:'全部载客走廊（当前 53 条，另有 216 条货运走廊）',
   source:'<code>GET /api/traffic/v2/overview</code> 的 <code>kpis[pending]</code> 与 <code>kpiDetail.observations</code>',
   refresh:'每 5 分钟（页面轮询）',owner:'规则引擎'},
  {key:'high',name:'已触发停飞判据的走廊',
   definition:'观测判据或概率档（p ≥ 概率档阈值）任一命中的城际走廊数 —— 与下方「概率档高概率走廊」分开统计，不合并',
   numerator:'观测判据命中 ∪ p ≥ 概率档阈值',denominator:'全部城际走廊（53 条）',
   source:'同上 <code>kpis[high]</code>；阈值与分子见 <code>kpiDetail</code>',
   refresh:'每 5 分钟（页面轮询）',owner:'规则引擎'},
  {key:'probability',
   name:'概率档高概率走廊',
   definition:'不可飞概率 ≥ 概率档阈值（当前 0.25）的城际走廊数。**与上一条分开统计**：上一条说"规则判了几条"，这一条说"模型自己会判几条"',
   numerator:'p ≥ 0.25 的走廊',denominator:'全部城际走廊（53 条）',
   source:'<code>kpiDetail.probability</code> 与 <code>kpiDetail.probabilityThreshold</code>（后端常量 P_PROB_BLOCK）',
   refresh:'每 5 分钟（页面轮询）',owner:'模型'},
  {key:'lead',name:'平均提前量',definition:'离线回放中首次报警时刻到事件发生的时长中位数（不是本帧读数，本帧触发数见 `kpis[high]`）',
   numerator:'Σ 提前量',denominator:'跨阈事件数（vis3k 62 个 / 阵风 56 个）',
   source:'<code>model-v2-metrics.json</code> 的 <code>targets.vis3k.leadTime.medianMin</code>',
   refresh:'训练时计算，随模型发布',owner:'模型'},
  {key:'coverage',name:'模型覆盖',definition:'拿到概率输出的走廊占比',
   numerator:'有概率的走廊',denominator:'全部城际走廊',source:'`kpis[ai]`（后端算，前端不重算）',
   refresh:'每 5 分钟（页面轮询）',owner:'模型'},
  {key:'sigma',name:'插值不确定度 σ',definition:'σ = 0.05 + 0.02 × 最近站距(km)',
   numerator:null,denominator:null,source:'`traffic/v2.py::_idw()`，随每个采样点返回',
   refresh:'每次请求',owner:'后端'},
  {key:'ribbon',name:'可飞性带段数',definition:'沿走廊每 5 km 一段，颜色=该段不可飞概率',
   numerator:'采样段数',denominator:'走廊长度(km) ÷ 5',source:'`corridors[].samples`（含经纬度）',
   refresh:'每次进入页面 · 拖时轴重取',owner:'模型'},
  {key:'divergence',name:'分歧记录',definition:'规则与模型结论不一致且已留痕的条数',
   numerator:'台账行数',denominator:null,source:'`.run/traffic/decisions/<workspace>.jsonl`（按工作区隔离）',
   refresh:'每次裁决',owner:'后端'},
  {key:'cities',name:'地级行政区',definition:'覆盖范围内全部地级市',
   numerator:null,denominator:null,source:'`data/traffic/city-centers.json`（静态）',
   refresh:'静态',owner:'前端'},
])

export const SECTION_NAMES=Object.freeze({
  home:'运行首页',overview:'运行总览',briefing:'民航情报',schedule:'调度台账',
  alerts:'事件处置台',weather:'气象监测',mechanism:'算法机理',reference:'口径与来源',
  assistant:'大模型取证',history:'运行日志',
  profile:'走廊剖面',card:'推演',counterfactual:'反事实对照',ledger:'分歧台账',
})
export function sectionName(key){
  return SECTION_NAMES[key]||'未命名分节'
}

export const SOURCE_BADGES=Object.freeze({
  SIM:{key:'SIM',label:'模拟交通',tone:'sim',
    note:'班次、时刻、起降点与运行/操作记录全部由本地推演生成，不对应任何真实航班。'},
  PUBLIC:{key:'PUBLIC',label:'公开来源',tone:'public',
    note:'取自公开数据源，可回到原始报文与到达时刻逐项核对；不是本项目合成的数据。'},
  DERIVED:{key:'DERIVED',label:'系统派生',tone:'derived',
    note:'由公开来源按本项目阈值计算得到，可复算；不等于发布方自己的产品。'},
  OFFICIAL:{key:'OFFICIAL',label:'官方管制',tone:'official',
    note:'来自公布的空域几何；与气象派生风险区是两套东西，任何时候都不合并。'},
  MANUAL:{key:'MANUAL',label:'人工操作',tone:'manual',
    note:'由值班员在运行台发起并写入运行日志；只改变本地的执行时刻，不修改已发布的计划。'},
  ABSENT:{key:'ABSENT',label:'数据不可用',tone:'absent',
    note:'来源未返回、未配置或本帧确实没有。界面如实显示不可用，不以默认值填补。'},
})
export function sourceBadge(key){
  return SOURCE_BADGES[key]||SOURCE_BADGES.ABSENT
}

const WEATHER_DATA_TYPE_LABELS=Object.freeze({
  MODEL_ESTIMATE:'公开模型估算',
  SYNTHETIC_REPLAYABLE:'合成回放',
  PROVIDER_CURRENT_ESTIMATE_OR_OBSERVATION_UNVERIFIED:'来源未标注估算或观测',
  OBSERVATION:'来源实测观测',
  PROVIDER_OBSERVATION:'来源实测观测',
})
export function weatherDataTypeLabel(value){
  return WEATHER_DATA_TYPE_LABELS[typeof value==='string'?value:'']||'absent'
}

export function legalFrameworkText(value){
  if(typeof value==='string')return value.trim()||'absent'
  if(!value||typeof value!=='object')return 'absent'
  const instrument=typeof value.instrument==='string'?value.instrument.trim():''
  const clause=typeof value.clause==='string'?value.clause.trim():''
  if(instrument&&clause)return `${instrument} · ${clause}`
  return instrument||clause||'absent'
}

const absent=()=>'absent'
const countText=(list,unit)=>Array.isArray(list)?`${list.length} ${unit}`:absent()
const text=(value)=>typeof value==='string'&&value.trim()?value.trim():absent()
const numeric=value=>(typeof value==='number'&&Number.isFinite(value))?value:null
const quotedOr=(value,fallback)=>text(value)==='absent'?fallback:text(value)

export function caliberBlocks(plan,weather,network){
  const radar=(plan&&plan.radarAvoidance)||null
  const rule=radarRuleBlock(plan)
  const stats=(plan&&plan.stats)||null
  const snapshot=(plan&&plan.weatherSnapshot)||{}
  const airspace=(network&&network.staticAirspace)||null
  const airspaceRules=(airspace&&airspace.rules)||null
  const airspaceStatus=(airspace&&airspace.status)||null
  const catalogOwnerDisclaimer=text(airspaceRules&&airspaceRules.disclaimer)
  const cells=Array.isArray(weather&&weather.cells)?weather.cells:null
  const observations=Array.isArray(weather&&weather.observations)?weather.observations:null
  const winds=Array.isArray(weather&&weather.winds)?weather.winds:null
  const dataType=(weather&&weather.dataType)||snapshot.dataType||''
  const typeLabel=weatherDataTypeLabel(dataType)
  const provider=text((weather&&(weather.provider||weather.source))||snapshot.provider)
  const validAt=text((weather&&(weather.validAt||weather.retrievedAt))||snapshot.validAt)
  const coverage=text(weather&&weather.coverage&&weather.coverage.routeCoverage)
  const quality=Array.isArray(weather&&weather.qualityFlags)&&weather.qualityFlags.length
    ?weather.qualityFlags.join(' · '):absent()
  const weatherSource=provider==='absent'&&typeLabel==='absent'?SOURCE_BADGES.ABSENT
    :SOURCE_BADGES.PUBLIC
  const dbz=value=>value===null||value===undefined?absent():`${value} dBZ`
  const metres=value=>value===null||value===undefined?absent():`${value} m`

  return [
    {
      key:'weather',title:'气象数据',source:weatherSource,
      intro:'当前帧的气象由哪一条通道给出、覆盖到哪里。',
      rows:[
        {label:'来源',value:provider,note:'公开数据源名称，可回到该源的原始报文核对。'},
        {label:'数据类型',value:typeLabel==='absent'?'来源未标注':typeLabel,
          note:'公开模型估算 / 来源实测观测 / 合成回放 是三件不同的事，不合并成一个词。'},
        {label:'有效时刻',value:validAt,note:'数据自称的时刻，不等于本机取回的时刻。'},
        {label:'逐站观测',value:countText(observations,'站'),
          note:'本站帧的逐站观测条数；未返回时写不可用，不填 0。'},
        {label:'背景风场',value:countText(winds,'点'),note:'网格估算的箭头，不是实测风。'},
        {label:'航路覆盖',value:coverage,note:'气象场对计划航路的覆盖率。'},
        {label:'数据质量标记',value:quality,note:'来源自报的质量旗标，原样转述，不重新解释。'},
      ],
      boundary:'气象是<b>输入</b>，不是结论。本系统不会为了画面好看去合成天气：'
        +'来源失败时如实显示不可用，并说明是哪一类不可用。',
    },
    {
      key:'radar',title:'雷达回波与避让判据',source:rule?SOURCE_BADGES.DERIVED:SOURCE_BADGES.ABSENT,
      intro:'回波分级、扫描口径与两级两规则的取值。',
      rows:[
        {label:'回波分级',value:rule
          ?`无回波 < ${dbz(rule.bandFloorDbz)} · 对流 ${dbz(rule.convectiveDbz)} · 强对流 ${dbz(rule.strongDbz)}`
          :absent(),
          note:'层状降水（下界到对流阈值之间）只展示、不构成限制，也不进入避让几何。'},
        {label:'内核 · 禁止进入',value:rule?`外场向内收缩 ${metres(rule.coreInsetM)}`:absent(),
          note:'收缩量是<b>相对侵蚀深度</b>，不是内核到原轮廓的距离。'},
        {label:'外场 · 须绕飞',value:rule?`擦入深度上限 ${metres(rule.penetrationM)}`:absent(),
          note:'擦入深度与水平间隔同源，不为强回波另立第二套标准。'},
        {label:'扫描步长',value:numeric(radar&&radar.sweepStrideMinutes)!==null
          ?`${numeric(radar.sweepStrideMinutes)} 分钟`:absent(),
          note:'沿时间轴的采样间隔；通道为实测时只有一次观测，没有步长。'},
        {label:'避让采样点',value:numeric(radar&&radar.sweepSlots)!==null
          ?`${numeric(radar.sweepSlots)} 点`:absent(),
          note:'虚拟通道的量。实测通道没有"点"，术语与单位都不共用（M30）。'},
        {label:'通道',value:radar?(radar.mode==='virtual'?'虚拟（沿时间轴扫掠）':'实测（单时刻观测）'):absent(),
          note:'两通道的判据相同、输入不同，所以读数必须分开报。'},
      ],
      boundary:'<b>亮温不能换算成 dBZ</b>，本系统任何位置都不做这个换算；'
        +'<b>雷达回波不等于空域管制</b>——有回波只说明要绕飞，不说明这片空域被关闭。',
    },
    {
      key:'risk',title:'气象派生风险区',source:cells?SOURCE_BADGES.DERIVED:SOURCE_BADGES.ABSENT,
      intro:'由气象输入按本项目阈值算出来的风险几何。',
      rows:[
        {label:'区域数',value:countText(cells,'个'),note:'已合并后的区域数，不是单体数。'},
        {label:'合并口径',value:cells&&cells.some(c=>Number(c.memberCount)>1)
          ?'按种类合并，成员保留在区域记录里':'本帧无合并',
          note:'合并会把面积算小还是算大取决于成员是否相交，所以成员数单列。'},
        {label:'分档',value:'场区 / 谨慎外环 / 禁止进入核心',
          note:'四层几何（含监视层）都要发；缺席按原因拆开，不并进"必绕"。'},
      ],
      boundary:'<b>派生风险区不是管制命令</b>。暖色是系统按气象算的，冷色才是官方公布的；'
        +'两者在任何视图里都不合并，也不能互相顶替。',
    },
    {
      key:'airspace',title:'空域与固定管制区',source:SOURCE_BADGES.OFFICIAL,
      intro:'来自公布几何、不随天气变化的那一部分空域。',
      rows:[
        {label:'登记站点',value:numeric(airspaceStatus&&airspaceStatus.sites)!==null
          ?`${numeric(airspaceStatus.sites)} 处`:absent(),
          note:'含已登记但未取得定量范围的类别——那一类只登记、不生成几何。'},
        {label:'已有几何',value:numeric(airspaceStatus&&airspaceStatus.withGeometry)!==null
          ?`${numeric(airspaceStatus.withGeometry)} 处`:absent(),
          note:'能画出来的站点数；与登记数不等是正常的，差额就是"待补范围"。'},
        {label:'禁止进入 / 需审批',value:numeric(airspaceStatus&&airspaceStatus.prohibited)!==null
          ?`${numeric(airspaceStatus.prohibited)} / ${numeric(airspaceStatus.approvalRequired)||0} 处`:absent(),
          note:'进入"需审批"不等于违规；只有"禁止进入"的穿越才染色。'},
        {label:'默认处置',value:'需审批（APPROVAL_REQUIRED）',
          note:'进入需审批是默认口径；机场净空等被单独切成禁止进入的，由策略决定而不是隐藏常量。'},
        {label:'高度层',value:stats&&stats.noAltitudeStacking===true?'只使用已声明高度层':absent(),
          note:'冲突用已声明高度层、时隙或地面等待解决，不叠加高度。'},
        {label:'法规依据',value:airspaceRules?legalFrameworkText(airspaceRules.legalFramework):absent(),
          note:'管制的法源与具体条款；可据此逐条核对，而不是只给一个"依据相关规定"。'},
        {label:'目录版本 / 取回时刻',
          value:airspaceRules
            ?`${text(airspaceRules.catalogVersion)} · ${text(airspaceRules.dataRetrievedAt)}`:absent(),
          note:'空域目录自身的版本与取回时间——它不是推演数据，不随快照变化。'},
        {label:'发布方声明',value:text(catalogOwnerDisclaimer),
          note:'空域目录自带的声明，本页原样转述一次，不再第二处重写。'},
      ],
      boundary:quotedOr(airspaceRules&&airspaceRules.enforcementNote,
        '官方管制区不与气象派生区合并；两者在图上靠冷暖色区分，'
        +'任何"把两类风险加在一起算总数"的统计口径都不成立。'),
    },
    {
      key:'traffic',title:'交通与班次',source:SOURCE_BADGES.SIM,
      intro:'计划里那些看起来像真实航班的东西，来源是什么。',
      rows:[
        {label:'交通数据',value:'本地推演',note:'航线、时刻、载荷与订单状态均由推演生成。'},
        {label:'运行情景',value:text(plan&&plan.scenario),note:'计划生成时声明的情景。'},
        {label:'推演跨度',value:`${TIMELINE_SPAN_MINUTES} 分钟`,
          note:'所有时刻都是相对场景基准时刻的分钟偏移，不是墙钟。'},
      ],
      boundary:'<b>交通数据一律是模拟的</b>。本项目不声称任何一条航迹对应真实航班，'
        +'也不需要真实航班数据来演示——被验证的是调度算法，不是某一天的航班表。',
    },
    {
      key:'manual',title:'人工操作与留痕',source:SOURCE_BADGES.MANUAL,
      intro:'值班员做过的事，以及它们影响的是什么。',
      rows:[
        {label:'可写动作',value:'暂停 / 恢复 / 事件确认 / 事件处置 / 导出',
          note:'全部写入运行日志，可在「运行日志」按类型查、按关键词搜、导出 CSV。'},
        {label:'影响范围',value:'仅本地执行时刻',
          note:'人工操作改变的是"这一班什么时候放"，不改已发布的计划本身。'},
        {label:'处置对象',value:'事件（航线 + 成因 + 是否关闭）',
          note:'<b>按事件记，不按班次记</b>——同一成因影响多个班次时，处置一个事件等于处置一批班次。'},
      ],
      boundary:'人工操作不进入时间轴回放通道。回放只重演算法产出的计划与人工干预，'
        +'把"计划构建完成""导出"这类留痕混进去，回放会把日志当成一次班次操作。',
    },
    {
      key:'repro',title:'算法与复现',source:SOURCE_BADGES.DERIVED,
      intro:'凭什么说"重跑一次得到同一份计划"。',
      rows:[
        {label:'算法版本',value:text(plan&&plan.version),note:'产品版本号不参与指纹计算。'},
        {label:'算法指纹',value:text(plan&&plan.fingerprint),
          note:'由算法文件的字节内容算出，<b>改动任一算法文件即改变</b>。'},
        {label:'数据快照编号',value:Number.isInteger(plan&&plan.seed)?String(plan.seed):absent(),
          note:'复现参数之一，0—99999 的整数，只读。'},
        {label:'计划修订',value:plan&&plan.planRevision!==undefined&&plan.planRevision!==null
          ?String(plan.planRevision):absent(),
          note:'同一快照下重新构建会递增，用于区分"同一份计划"与"又跑了一次"。'},
        {label:'气象通道',value:'实测 / 虚拟',
          note:'<b>通道必须进缓存键</b>：同一快照在不同通道下是两个不同的问题，不能共用一个答案。'},
      ],
      boundary:'三者相同（数据快照编号 + 算法指纹 + 气象通道）重跑即得到逐字节相同的计划；'
        +'少任何一项，两个计划之间的差异都无法归因。',
    },
  ]
}

export const GLOSSARY=Object.freeze([
  {group:'气象与回波',term:'dBZ',plain:'回波强不强的刻度，数越大雨越猛。',
   full:'雷达反射率因子，单位 dBZ。本项目取四个阈值：15（无回波下界）、35（对流）、45（强对流内核）、60（严重）。'},
  {group:'气象与回波',term:'亮温',plain:'卫星看到的"冷热程度"，只能说明云顶高不高。',
   full:'卫星通道的等效黑体温度。<b>它不能被换算成 dBZ</b>，本项目任何位置都不做这一换算，两者也不共用同一条阈值。'},
  {group:'气象与回波',term:'层状降水',plain:'一大片、比较均一的降水，通常可以穿。',
   full:'低于对流阈值的回波（本项目为 15—35 dBZ）。只展示，不构成运行限制，也不进入避让几何。'},
  {group:'气象与回波',term:'内核 / 外场',plain:'内核是"绝对不许碰"，外场是"可以擦一点边"。',
   full:'两级两规则：内核（≥45 dBZ）不可触碰；外场（≥35 dBZ）允许有界擦入。内核由外场向内收缩得到，不是强对流原轮廓。'},
  {group:'气象与回波',term:'擦入深度',plain:'允许蹭进外场多深，超过就要绕。',
   full:'外场允许的穿入深度上限。它与水平间隔<b>同源</b>（都取分离标准里的水平分量），不为强回波另立第二套标准。'},
  {group:'气象与回波',term:'避让采样',plain:'沿着时间轴每隔一段看一眼，把这段时间的回波并起来算。',
   full:'虚拟气象通道按固定步长沿时间轴扫掠，每班次取窗口内回波的并集作为避让几何；"点"是采样次数。实测通道只有一次观测，没有点。'},
  {group:'运行与处置',term:'资源或耗时不足',plain:'不是天气，是这个班次在时隙、高度层或总耗时上排不进。',
   full:'<b>一个名字对应五类拒绝</b>，按规划器检查的先后：①加完地面等待后总延误超过上限；'
     +'②单班飞行时长超过该机型上限；③起降时隙（同一起降点的间隔）排不进；'
     +'④交叉管制区的时间窗排不进；⑤与已接受班次产生分离冲突。'
     +'它<b>晴天一样会发生</b>，所以不计入"气象造成"的统计。要判断具体是哪一类，看该事件卡的关联班次与处置建议。'},
  {group:'空域与风险',term:'固定管制区',plain:'官方划的、不随天气变的禁区（图上冷色）。',
   full:'来自公布几何的静态空域。默认处置是"需审批"，机场净空等被策略切成"禁止进入"。它与气象派生风险区不合并。'},
  {group:'空域与风险',term:'气象派生风险区',plain:'按天气算出来的危险区（图上暖色）。',
   full:'由气象输入按本项目阈值派生，可复算。四层几何：监视层、场区、谨慎外环、禁止进入核心。它<b>不是</b>管制命令。'},
  {group:'空域与风险',term:'需审批 / 禁止进入',plain:'进去要批 / 进去不行。',
   full:'APPROVAL_REQUIRED 与 PROHIBITED。只有"禁止进入"的穿越才染色；"需审批"是默认口径，由空域策略切换而不是隐藏常量。'},
  {group:'空域与风险',term:'雷达保护区',plain:'雷达站边上不能靠太近的一圈。',
   full:'以雷达站为中心的圆形保护范围。它是设备保护范围，不画成飞行管制几何，也不参与航路避让判据。'},
  {group:'调度与间隔',term:'走廊',plain:'起点到终点留出来的那条可以走的带子。',
   full:'计划航路的空间范围。走廊是算法的产出：直线走廊是最简单的解，被气象推开之后才变成折线。'},
  {group:'调度与间隔',term:'受气象影响改航',plain:'因为天气把路线绕弯了。',
   full:'航路被气象推移。成员资格来自<b>成因</b>（点位气象 / 雷达内核 / 雷达外场），不来自"绕行时长大不大"——长度只是几何差异的代理量。'},
  {group:'调度与间隔',term:'停止放行',plain:'这一班今天不飞了。',
   full:'CLOSED。它是硬约束的结果，不是建议。预警中心里"深橙"必须能被拆成气象成因与非气象成因两类，否则一整屏深橙会被读成"天气导致停飞"。'},
  {group:'调度与间隔',term:'时隙重排',plain:'往后面挪一挪再飞。',
   full:'把冲突班次移到另一个时间片上。与"改航"是两种不同的处置：改航动的是空间，时隙重排动的是时间。'},
  {group:'调度与间隔',term:'地面等待',plain:'在地面上等着，不起飞。',
   full:'三类冲突处置之一（另两类是已声明高度层与时隙）。本项目<b>不叠加高度</b>来解决冲突。'},
  {group:'算法与复现',term:'算法指纹',plain:'算法本身的"身份证号"，改一行代码它就变。',
   full:'由算法文件内容计算出的十六进制摘要。改算法会变，改产品版本号不会变。界面上只显示前 8 位，完整值在「运行设置 → 工程信息 · 复现参数」里。'},
  {group:'算法与复现',term:'数据快照编号',plain:'这一次用的是哪一份数据。',
   full:'生成计划时使用的数据快照标识。与算法指纹、气象通道三者相同，重跑即得到逐字节相同的计划。'},
  {group:'算法与复现',term:'气象通道',plain:'用的是真天气还是排练用的天气。',
   full:'measured（实测，默认）与 virtual（虚拟）。<b>通道必须进缓存键</b>——同一份快照在两个通道下是两个不同的问题，共用一个答案就会把 A 的结论答给 B。'},
  {group:'算法与复现',term:'单一求值',plain:'一个数只在一个地方算一次，别处只许拿来用。',
   full:'同一个量在整个系统里只有一个产出点，其余位置只做导航与呈现。违反它的症状是"同一屏两个数"，而这类错误不会让构建与测试变红。'},
])
export function glossaryGroups(){
  const groups=new Map()
  for(const entry of GLOSSARY){
    if(!groups.has(entry.group))groups.set(entry.group,[])
    groups.get(entry.group).push(entry)
  }
  return [...groups.entries()].map(([group,terms])=>({group,terms}))
}
export function glossaryLookup(term){
  const key=String(term||'').trim().toLowerCase()
  if(!key)return null
  return GLOSSARY.find(entry=>entry.term.toLowerCase()===key)||null
}

export const DENSITY_TIERS=Object.freeze([
  {key:'duty',label:'值班员',note:'原始要素全开：值班员要逐条核对报文、编号与时刻。'},
  {key:'command',label:'指挥',note:'收起原始报文与工程参数，只留结论、成因与影响面。'},
  {key:'demo',label:'演示',note:'默认展开术语释义与因果链，隐藏工程参数与审计明细。'},
])
const DENSITY_POLICY=Object.freeze({
  duty:{raw:true,engineering:true,glossary:false,audit:true,ledger:true,replay:true},
  command:{raw:false,engineering:false,glossary:false,audit:false,ledger:true,replay:true},
  demo:{raw:false,engineering:false,glossary:true,audit:false,ledger:false,replay:false},
})
export function densityTier(key){
  return DENSITY_TIERS.find(tier=>tier.key===key)||DENSITY_TIERS[0]
}
export function densityPolicy(key){
  return DENSITY_POLICY[key]||DENSITY_POLICY.duty
}

export function replayMinuteOf(row){
  const value=row&&row.minute
  return typeof value==='number'&&Number.isFinite(value)?value:null
}
export function replayMarks(journal,span=TIMELINE_SPAN_MINUTES){
  const rows=Array.isArray(journal)?journal.filter(Boolean):[]
  const marks=new Map()
  const always=[]
  for(const row of rows){
    const minute=replayMinuteOf(row)
    if(minute===null){always.push(row);continue}
    if(!marks.has(minute))marks.set(minute,{minute,count:0,kinds:new Set(),rows:[]})
    const mark=marks.get(minute)
    mark.count++
    if(row.kind)mark.kinds.add(row.kind)
    mark.rows.push(row)
  }
  const ordered=[...marks.values()]
    .sort((a,b)=>a.minute-b.minute)
    .map(mark=>({...mark,kinds:[...mark.kinds].sort()}))
  return {span,marks:ordered,always,count:rows.length}
}
export function replaySlice(journal,minute){
  const rows=Array.isArray(journal)?journal.filter(Boolean):[]
  const now=Number.isFinite(Number(minute))?Number(minute):0
  const past=[],here=[],upcoming=[],always=[]
  for(const row of rows){
    const at=replayMinuteOf(row)
    if(at===null){always.push(row);continue}
    if(at<now)past.push(row)
    else if(at===now)here.push(row)
    else upcoming.push(row)
  }
  const byMinute=(a,b)=>(replayMinuteOf(a)-replayMinuteOf(b))
    ||String(a.id).localeCompare(String(b.id))
  past.sort(byMinute);here.sort(byMinute);upcoming.sort(byMinute)
  return {minute:now,past,here,upcoming,always,
    total:past.length+here.length+upcoming.length}
}
export function replayBuckets(journal,{span=TIMELINE_SPAN_MINUTES,step=60}={}){
  const rows=Array.isArray(journal)?journal.filter(Boolean):[]
  const width=Number.isFinite(Number(step))&&Number(step)>0?Number(step):60
  const total=Number.isFinite(Number(span))&&Number(span)>0?Number(span):TIMELINE_SPAN_MINUTES
  const count=Math.max(1,Math.ceil(total/width))
  const buckets=[]
  for(let i=0;i<count;i++){
    buckets.push({index:i,from:i*width,to:Math.min(total,(i+1)*width),rows:[],count:0})
  }
  for(const row of rows){
    const at=replayMinuteOf(row)
    if(at===null)continue
    const index=Math.min(count-1,Math.max(0,Math.floor(at/width)))
    buckets[index].rows.push(row)
    buckets[index].count++
  }
  return {span:total,step:width,buckets,count:rows.length,
    peak:buckets.reduce((best,b)=>b.count>(best?best.count:-1)?b:best,null)}
}

export function receiptText(entry,{sessionId=''}={}){
  if(!entry||typeof entry!=='object')return ''
  const at=entry.at?new Date(entry.at).toLocaleString('zh-CN',{hour12:false}):absent()
  const minute=Number.isFinite(Number(entry.minute))?`T+${Number(entry.minute).toFixed(0)} 分`:absent()
  const target=entry.eventKey?(entry.name||entry.eventKey):(entry.name||entry.flightId||absent())
  const parts=[
    `对象：${target}`,
    `时刻：${at}（${minute}）`,
    `动作：${entry.actionLabel||entry.action||absent()}`,
    `人物：${entry.actor||absent()}`,
    `明细：${entry.detail||absent()}`,
  ]
  if(sessionId)parts.push(`计划：${String(sessionId).slice(0,12)}`)
  return parts.join(' · ')
}

export function timelineIntel(plan,weather,journal){
  const radar=(plan&&plan.radarAvoidance)||null
  const rows=[]
  const push=(key,label,value,note,source,tone)=>{
    rows.push({key,label,value:value||absent(),note,source:source||SOURCE_BADGES.DERIVED,tone:tone||'normal'})
  }
  push('scene','场景基准时刻',
    text(plan&&plan.baseTime),
    '所有推演时刻都是相对这一刻的分钟偏移，不是墙钟。',
    SOURCE_BADGES.SIM)
  push('valid','气象有效时刻',
    text((weather&&(weather.validAt||weather.retrievedAt))),
    '气象帧自称的时刻；与场景基准时刻不一致时要说明差多少。',
    SOURCE_BADGES.PUBLIC)
  if(radar){
    const slots=numeric(radar.sweepSlots),stride=numeric(radar.sweepStrideMinutes)
    push('sweep','回波扫描窗口',
      slots!==null&&stride!==null
        ?`${(slots-1)*stride} 分钟（${slots} 点 × ${stride} 分）`
        :absent(),
      '虚拟通道才有窗口长度；实测通道是一次观测，没有窗口。',
      SOURCE_BADGES.DERIVED)
  }else{
    push('sweep','回波扫描窗口',absent(),'本计划未声明雷达避让几何，因此没有可报的窗口。',
      SOURCE_BADGES.ABSENT,'muted')
  }
  const list=Array.isArray(journal)?journal.filter(Boolean):[]
  const manual=list.filter(row=>row.kind==='MANUAL'&&replayMinuteOf(row)!==null)
    .map(row=>replayMinuteOf(row))
  push('ops','人工操作',
    manual.length?`${manual.length} 次 · 最早 T+${Math.min(...manual).toFixed(0)} 分`:'0 次',
    '只统计"人工干预"类里带推演分钟的记录；系统决策、通道切换这类不计入。',
    SOURCE_BADGES.MANUAL,manual.length?'normal':'muted')
  push('revision','计划修订',
    plan&&plan.planRevision!==undefined&&plan.planRevision!==null?String(plan.planRevision):absent(),
    '同一快照下重新构建会递增；它的作用是区分"同一份计划"与"又跑了一次"。',
    SOURCE_BADGES.DERIVED)
  return rows
}

export function airspaceIntel(plan,flights,weather,network){
  const list=Array.isArray(flights)?flights.filter(Boolean):[]
  const cells=Array.isArray(weather&&weather.cells)?weather.cells:null
  const airspace=(network&&network.staticAirspace)||null
  const status=(airspace&&airspace.status)||null
  const zones=Array.isArray(airspace&&airspace.zones)?airspace.zones:null
  const rows=[]
  const push=(key,label,value,note,source,tone)=>{
    rows.push({key,label,value:value||absent(),note,source:source||SOURCE_BADGES.DERIVED,tone:tone||'normal'})
  }
  push('official','官方固定管制区',
    numeric(status&&status.sites)!==null
      ?`登记 ${numeric(status.sites)} 处 · 有几何 ${numeric(status.withGeometry)||0} 处`:absent(),
    '冷色。来自公布几何，不随天气变化；与气象派生风险区分开统计，不合并。登记多于几何是正常的 —— 差额是"未取得公开定量范围"。',
    SOURCE_BADGES.OFFICIAL,numeric(status&&status.sites)?'normal':'muted')
  push('enforcement','其中禁入 / 需审批',
    numeric(status&&status.prohibited)!==null
      ?`${numeric(status.prohibited)} / ${numeric(status.approvalRequired)||0} 处`:absent(),
    '"需审批"是默认口径；只有"禁止进入"的穿越才染色。',
    SOURCE_BADGES.OFFICIAL,numeric(status&&status.prohibited)?'warn':'good')
  push('derived','气象派生风险区',
    cells?`${cells.length} 个`:absent(),
    '暖色。按气象输入派生，可复算；四层几何（监视 / 场区 / 谨慎 / 核心）缺席要说明原因。',
    SOURCE_BADGES.DERIVED,cells&&cells.length?'warn':'muted')
  const pads=new Set()
  for(const flight of list){
    if(flight.fromPad)pads.add(flight.fromPad)
    if(flight.toPad)pads.add(flight.toPad)
  }
  push('pads','在用的起降点',pads.size?`${pads.size} 个`:absent(),
    '本帧计划里被实际引用的起降点数量，不是网络里的全部起降点。',
    SOURCE_BADGES.SIM)
  const corridors=new Set(list.map(f=>corridorLabel(f)).filter(Boolean))
  push('corridors','在用的走廊',corridors.size?`${corridors.size} 条`:absent(),
    '按"起点 → 终点"去重；同一条走廊上的多班次只算一条。',
    SOURCE_BADGES.SIM)
  const guarded=list.filter(f=>Number(f&&f.staticAirspace&&f.staticAirspace.zones)>0)
  const forbidden=guarded.filter(f=>Number(f.staticAirspace.prohibited)>0)
  push('crossings','穿越固定管制区的班次',
    !Array.isArray(flights)?absent()
      :guarded.length?`${guarded.length} 班（其中触及禁入 ${forbidden.length} 班）`:'0 班',
    '只有"禁止进入"的穿越才染色；"需审批"是默认口径，进入并不等于违规。',
    SOURCE_BADGES.DERIVED,forbidden.length?'warn':(guarded.length?'normal':'good'))
  push('catalog','空域目录',
    text((zones&&status&&status.catalogVersion)||(airspace&&airspace.rules&&airspace.rules.catalogVersion)),
    '目录有自己的版本与取回时刻；它不是推演数据，不随数据快照变化。',
    SOURCE_BADGES.OFFICIAL)
  return rows
}

export const DRILL_TARGETS=Object.freeze({
  accepted:{section:'schedule',status:'ALL',hint:'「调度台账」逐条列出全部受理班次'},
  detour:{section:'briefing',hint:'「民航运行情报」里的「改航依据 · 逐班复诵」逐班给出气象判据'},
  delay:{section:'schedule',status:'HOLD',hint:'「调度台账」按运行状态筛出等待放行的班次，逐班看延误是怎么来的'},
  weather:{section:'alerts',cause:'weather',hint:'「预警中心 · 事件处置台」只留气象成因的事件，每条带走廊与建议'},
  risk:{section:'weather',hint:'「气象监测」逐区域列出成员、来源与合并口径'},
  alerts:{section:'alerts',hint:'「预警中心 · 事件处置台」按成因列出待处置事件，每条带一键处置'},
  sweep:{section:'mechanism',hint:'「算法机理」给出判据、几何与时间窗三要素'},
  ai:{section:'assistant',hint:'「大模型取证」逐条列出五种结局，含默认的那一种（未经模型取证）'},
  model:{section:'mechanism',hint:'「算法机理」的三列对照：规则 / 模型 / 人工仲裁的训练期指标，含分母与来源'},
})
const DRILL_FALLBACK=Object.freeze({section:'overview',hint:'总览给出本数与规模'})
export function drillTarget(key){
  return DRILL_TARGETS[key]||DRILL_FALLBACK
}
export function drillable(key){
  return Object.prototype.hasOwnProperty.call(DRILL_TARGETS,key)
}

export const MAP_LAYERS=Object.freeze([
  {key:'car',label:'飞行汽车',dot:'d-car',rowDot:'car-dot',
   title:'飞行汽车城际通勤航迹：实线＝已检查航迹，暗色＝已飞段落，虚线＝走廊参考'},
  {key:'delivery',label:'配送无人机',dot:'d-del',rowDot:'delivery-dot',
   title:'城区外卖配送无人机航迹（琥珀色）'},
  {key:'weather',label:'气象风险区',dot:'d-wx',rowDot:'risk-dot',
   title:'气象派生的飞行风险区（暖色）。不等同于官方空域管制命令'},
  {key:'fog',label:'低能见度（雾）',dot:'d-fog',rowDot:'fog-dot',
   title:'站点能见度读数派生的两档缓冲圆（灰阶）：深灰＝低于禁飞阈值，禁止进入；'
     +'浅灰＝能见度偏低，须绕飞。范围是近似值、不是实测雾区边界；与雷达回波是两套来源'},
  {key:'wind',label:'背景风向',dot:'d-wind',rowDot:'wind-dot',
   title:'背景风场箭头，取自公开天气模型的网格估算（非观测），仅作参考'},
  {key:'radar',label:'雷达回波',dot:'d-radar',rowDot:'radar-dot',
   title:'雷达回波：≥45 dBZ 内核禁止进入，35–45 dBZ 须绕飞'},
  {key:'zones',label:'固定管制区',dot:'d-zone',rowDot:'fixed-zone-dot',
   title:'官方固定管制区（冷色），与气象派生风险区不是一回事'},
  {key:'events',label:'运行事件',dot:'d-event',rowDot:'event-dot',
   title:'预警中心同一份合并事件（同一次 groupAlerts 求值）：深橙＝停止放行、橙＝气象成因、蓝＝非气象成因。点事件节点跳到预警中心那一条'},
  {key:'observations',label:'观测等级点',dot:'d-obs',rowDot:'obs-dot',
   title:'按地级行政区代表中心发布的公开观测等级点。点值，不是面值；点环半径是声明常量，不由数值推导'},
])

export const EVENT_LAYER_LIMIT=96
export const EVENT_TONES=Object.freeze({CLOSED:'alert',WEATHER:'warn',OTHER:'cyan'})
export const EVENT_COLORS=Object.freeze({alert:'#e08a45',warn:'#d98a2b',cyan:'#3d8bff'})
export const EVENT_TONE_LABELS=Object.freeze({
  alert:'停止放行',warn:'气象成因',cyan:'非气象成因'})

export function eventTone(row){
  if(row&&row.closed)return EVENT_TONES.CLOSED
  if(row&&row.weather)return EVENT_TONES.WEATHER
  return EVENT_TONES.OTHER
}
export function eventColor(row){return EVENT_COLORS[eventTone(row)]||EVENT_COLORS.cyan}

function corridorLine(network,routeId){
  const routes=Array.isArray(network&&network.routes)?network.routes:[]
  const route=routes.find(item=>item&&item.id===routeId)
  const path=route&&(route.referencePath||route.path)
  if(!Array.isArray(path))return []
  return path
    .filter(point=>Array.isArray(point)&&point.length>=2
      &&Number.isFinite(Number(point[0]))&&Number.isFinite(Number(point[1])))
    .map(point=>[Number(point[0]),Number(point[1])])
}

export function alertEventLayer(flights,network,{limit=EVENT_LAYER_LIMIT}={}){
  const groups=groupAlerts(flights)
  const lines=[],nodes=[]
  let missingCorridor=0
  for(const row of groups.rows){
    if(lines.length>=limit)break
    const coordinates=corridorLine(network,row.routeId)
    if(coordinates.length<2){missingCorridor++;continue}
    const tone=eventTone(row)
    const properties={
      key:row.key,routeId:row.routeId,reason:row.reason,cause:row.short||row.name,
      weather:!!row.weather,closed:!!row.closed,count:row.count,
      closedCount:row.closedCount,detoured:row.detoured,delayed:row.delayed,
      tone,color:EVENT_COLORS[tone],corridors:row.corridors.join(' · '),
    }
    const middle=coordinates[Math.floor(coordinates.length/2)]
    lines.push({type:'Feature',properties,
      geometry:{type:'LineString',coordinates}})
    nodes.push({type:'Feature',properties,
      geometry:{type:'Point',coordinates:[middle[0],middle[1]]}})
  }
  const shown=lines.length
  const truncated=groups.total-shown-missingCorridor>0
  const note=[
    `与预警中心同一次求值：共 ${groups.total} 个合并事件（气象 ${groups.weatherEvents} · 非气象 ${groups.nonWeatherEvents}）`,
    `停止放行 ${groups.closedFlights} 班`,
    shown<groups.total?`地图绘制前 ${shown} 条`:null,
    missingCorridor?`其中 ${missingCorridor} 条取不到走廊几何（该路由不在本次网络载荷里），已跳过而不是用直线顶替`:null,
    truncated&&!missingCorridor?'其余事件请在「预警中心」查看':null,
  ].filter(Boolean).join(' · ')+'。'
  return {
    lines:{type:'FeatureCollection',features:lines},
    nodes:{type:'FeatureCollection',features:nodes},
    total:groups.total,shown,missingCorridor,
    weatherEvents:groups.weatherEvents,nonWeatherEvents:groups.nonWeatherEvents,
    closedEvents:groups.rows.filter(row=>row.closed).length,
    closedFlights:groups.closedFlights,note,
  }
}

export const SEVERITY_CLASSES=Object.freeze([
  {key:'SEVERE',label:'高影响',tone:'alert',color:EVENT_COLORS.alert},
  {key:'CAUTION',label:'需谨慎',tone:'warn',color:EVENT_COLORS.warn},
  {key:'NOMINAL',label:'正常',tone:'normal',color:'#3d8bff'},
  {key:'UNKNOWN',label:'不可判定',tone:'muted',color:'#6f95c4'},
])
export const SEVERITY_RING_M=12000

export function severityClass(observation){
  const tone=observationTone(observation)
  const found=SEVERITY_CLASSES.find(item=>item.tone===tone)
  return found||SEVERITY_CLASSES[SEVERITY_CLASSES.length-1]
}

export function observationReading(observation){
  const temperature=Number(observation&&(observation.temperatureC??observation.tempC))
  const speed=Number(observation&&(observation.windSpeed10mMps??observation.windMps))
  const gust=Number(observation&&(observation.windGusts10mMps??observation.gustMps))
  const precipitation=Number(observation&&observation.precipitationMm)
  const visibility=observationVisibilityM(observation)
  const parts=[
    Number.isFinite(temperature)?`气温 ${Math.round(temperature)} ℃`:'气温 '+absent(),
    Number.isFinite(speed)?`风速 ${Math.round(speed)} m/s`:'风速 '+absent(),
    Number.isFinite(gust)?`阵风 ${Math.round(gust)} m/s`:'阵风 '+absent(),
    Number.isFinite(visibility)?`能见度 ${(visibility/1000).toFixed(visibility>=10000?0:1)} km`:'能见度 '+absent(),
    Number.isFinite(precipitation)?`降水 ${precipitation} mm`:'降水 '+absent(),
    metarPhenomenon(observation&&observation.weatherCode),
  ]
  return parts.join(' · ')
}

export function observationPoints(weather,network){
  const cities=Array.isArray(network&&network.cities)?network.cities:[]
  const observations=Array.isArray(weather&&weather.observations)?weather.observations:[]
  const features=[]
  let missingLocation=0
  for(const observation of observations){
    if(!observation||typeof observation!=='object')continue
    const city=cities.find(item=>item&&item.id===observation.cityId)
    const coordinate=city&&Array.isArray(city.coordinate)?city.coordinate:null
    if(!coordinate||!Number.isFinite(Number(coordinate[0]))||!Number.isFinite(Number(coordinate[1]))){
      missingLocation++
      continue
    }
    const level=severityClass(observation)
    features.push({type:'Feature',
      properties:{
        cityId:String(observation.cityId||''),
        station:String(observation.cityName||observation.cityId||'—'),
        level:level.key,levelLabel:level.label,tone:level.tone,color:level.color,
        reading:observationReading(observation),
        validAt:observation.validAt||observation.observedAt||null,
      },
      geometry:{type:'Point',coordinates:[Number(coordinate[0]),Number(coordinate[1])]}})
  }
  const counts={SEVERE:0,CAUTION:0,NOMINAL:0,UNKNOWN:0}
  for(const feature of features)counts[feature.properties.level]++
  return {features,counts,total:features.length,missingLocation,
    note:features.length
      ?`按地级行政区代表中心发布的公开观测；点值不是面值，点环半径 ${Math.round(SEVERITY_RING_M/1000)} km 是声明常量。`
      :(observations.length
        ?`本帧有 ${observations.length} 条观测，但都没有可用的行政区坐标。`
        :'本帧未发布任何点观测（场景未声明气象或数据源不可用）。')}
}

export function severityBands(weather,network){
  const points=observationPoints(weather,network)
  const rank={SEVERE:0,CAUTION:1,NOMINAL:2,UNKNOWN:3}
  const visibility=properties=>{
    const match=(weather&&weather.observations||[]).find(item=>
      String(item&&item.cityId||'')===properties.cityId)
    return observationVisibilityM(match)
  }
  const rows=[...points.features]
    .sort((a,b)=>(rank[a.properties.level]-rank[b.properties.level])
      ||(visibility(a.properties)-visibility(b.properties))
      ||String(a.properties.station).localeCompare(String(b.properties.station)))
    .map(feature=>feature.properties)
  const band=rows.map(row=>({key:row.cityId,label:row.station,level:row.level,
    levelLabel:row.levelLabel,color:row.color,reading:row.reading}))
  return {rows:band,counts:points.counts,total:points.total,
    missingLocation:points.missingLocation,note:points.note}
}

export const OBSERVATION_COLUMNS=Object.freeze([
  {key:'station',label:'站名',numeric:false},
  {key:'temperatureC',label:'气温 ℃',numeric:true},
  {key:'windSpeed',label:'风速 m/s',numeric:true},
  {key:'gust',label:'阵风 m/s',numeric:true},
  {key:'visibilityM',label:'能见度 m',numeric:true},
  {key:'precipitationMm',label:'降水 mm',numeric:true},
  {key:'phenomenon',label:'天气现象',numeric:false},
  {key:'level',label:'等级',numeric:false},
])
export function observationRows(weather){
  const observations=Array.isArray(weather&&weather.observations)?weather.observations:[]
  return metarOrder(observations).map(observation=>{
    const level=severityClass(observation)
    const temperature=Number(observation&&(observation.temperatureC??observation.tempC))
    const speed=Number(observation&&(observation.windSpeed10mMps??observation.windMps))
    const gust=Number(observation&&(observation.windGusts10mMps??observation.gustMps))
    const precipitation=Number(observation&&observation.precipitationMm)
    const visibility=observationVisibilityM(observation)
    const finite=value=>Number.isFinite(value)?value:null
    return {
      id:String(observation.cityId||observation.cityName||''),
      cityId:String(observation.cityId||''),
      station:String(observation.cityName||observation.cityId||'—'),
      cityName:String(observation.cityName||observation.cityId||'—'),
      validAt:observation.validAt||observation.observedAt||null,
      temperatureC:finite(temperature),
      windSpeed:finite(speed),
      gust:finite(gust),
      visibilityM:finite(visibility),
      precipitationMm:finite(precipitation),
      phenomenon:metarPhenomenon(observation.weatherCode),
      level:level.key,levelLabel:level.label,tone:level.tone,
      reading:observationReading(observation),
    }
  })
}

export function sortObservationRows(rows,key,dir='asc'){
  const column=OBSERVATION_COLUMNS.find(item=>item.key===key)
  if(!column)return [...(rows||[])]
  const sign=dir==='desc'?-1:1
  return [...(rows||[])].sort((a,b)=>{
    const left=a?.[key],right=b?.[key]
    if(column.numeric){
      const l=Number.isFinite(left)?left:null,r=Number.isFinite(right)?right:null
      if(l===null&&r===null)return String(a?.station||'').localeCompare(String(b?.station||''))
      if(l===null)return 1
      if(r===null)return -1
      if(l!==r)return (l-r)*sign
      return String(a?.station||'').localeCompare(String(b?.station||''))
    }
    const l=String(left??''),r=String(right??'')
    if(l!==r)return l.localeCompare(r)*sign
    return String(a?.station||'').localeCompare(String(b?.station||''))
  })
}

export function observationCsv(rows){
  const escape=value=>{
    const text=value===null||value===undefined?'':String(value)
    return /[",\n]/.test(text)?`"${text.replace(/"/g,'""')}"`:text
  }
  const head=OBSERVATION_COLUMNS.map(column=>escape(column.label)).join(',')
  const body=(rows||[]).map(row=>OBSERVATION_COLUMNS
    .map(column=>escape(column.key==='level'?(row.levelLabel||row.level):row[column.key]))
    .join(',')).join('\n')
  return head+(body?'\n'+body:'')
}

// ---- P1-1 b：观测影响面（受影响走廊 / 班次 / 建议处置） ----------------------
//
// 一条"沈阳阵风 19 m/s"本身不是一个可执行的结论。要能行动，必须接上
// **哪些走廊从这里出发、上面有几班**。接法是已发布的字段：班次的
// `fromCity` / `toCity` 与路由的 `fromCity` / `toCity`。
//
// 「建议处置」**不由等级凭空生成**：它用的是本项目已经写在别处的处置次序
// （先改时隙、再改航绕飞，两者都不可行才停止放行）。所以这里给的是那一句话的
// 分支，不是新政策 —— 一条新的处置建议就是一条没人验证过的规则。
export function observationImpact(weather,flights,network){
  const rows=observationRows(weather)
  const routes=Array.isArray(network&&network.routes)?network.routes:[]
  const list=Array.isArray(flights)?flights:[]
  const cities=Array.isArray(network&&network.cities)?network.cities:[]
  const nameOf=id=>cities.find(city=>city&&city.id===id)?.name||id
  return rows
    .filter(row=>row.level!=='NOMINAL'&&row.level!=='UNKNOWN')
    .sort((a,b)=>a.level==='SEVERE'&&b.level!=='SEVERE'?-1:(b.level==='SEVERE'&&a.level!=='SEVERE'?1:0))
    .map(row=>{
      const corridors=routes
        .filter(route=>route&&(route.fromCity===row.cityId||route.toCity===row.cityId))
        .map(route=>route.name||route.id)
      const affected=list.filter(flight=>flight
        &&(flight.fromCity===row.cityId||flight.toCity===row.cityId))
      const closed=affected.filter(flight=>flight.status==='CLOSED')
      const detoured=affected.filter(isWeatherDetour)
      const delayed=affected.filter(flight=>(Number(flight.delayMinutes)||0)>0)
      const advice=row.level==='SEVERE'
        ?'高影响观测：先按已声明高度层与时隙重排（延迟起飞），改航绕飞次之；两者都不可行才停止放行。'
        :'需谨慎：优先按已声明高度层与时隙重排，不改变航路。'
      return {
        cityId:row.cityId,station:row.station,cityName:nameOf(row.cityId),
        level:row.level,levelLabel:row.levelLabel,tone:row.tone,reading:row.reading,
        corridors,corridorCount:corridors.length,
        flightCount:affected.length,closedCount:closed.length,
        detouredCount:detoured.length,delayedCount:delayed.length,
        sample:affected[0]||null,advice,
      }
    })
}

// ---- P1-1 c：批量放行许可复核 ------------------------------------------------
//
// 放行许可原来**只能一条一条看**（`clearanceReport` 挂在当前选中的班次上）。
// 交班前要核对"这一批到底多久"时，逐条点开是不现实的。
//
// 这里把每一班已经写定的许可要素摊成一张表，**不新增任何要素**：缺的写
// 「未指派」/「未取得」（与报文体同一约定），而不是留白。
export function batchClearanceRows(flights,{limit=40,sort='risk'}={}){
  const list=(Array.isArray(flights)?flights:[]).filter(flight=>flight&&flight.atcClearance)
  const weight=flight=>{
    if(flight.status==='CLOSED')return 3
    if(isWeatherDetour(flight))return 2
    if((Number(flight.delayMinutes)||0)>0)return 1
    return 0
  }
  const ordered=sort==='risk'
    ?[...list].sort((a,b)=>(weight(b)-weight(a))
      ||((Number(b.detourMinutes)||0)-(Number(a.detourMinutes)||0))
      ||String(a.id).localeCompare(String(b.id)))
    :[...list].sort((a,b)=>(a.departureMinute??0)-(b.departureMinute??0)
      ||String(a.id).localeCompare(String(b.id)))
  const rows=ordered.slice(0,limit).map(flight=>{
    const clearance=flight.atcClearance||{}
    const level=Number(clearance.assignedLevelAglM)
    const ctot=clearance.ctot||null
    return {
      id:flight.id,callsign:clearance.callsign||absent(),
      route:clearance.route||absent(),
      level:Number.isFinite(level)&&level>0?`${Math.round(level)} m AGL`:'未指派高度层',
      limit:clearance.limit||'未声明放行界限',
      ctot:ctot&&ctot.from?`${operationalTime(ctot.from,null)}`
        +(Number.isFinite(Number(ctot.validityMinutes))?` 有效 ${ctot.validityMinutes} 分钟`:'')
        :'未取得时隙',
      basis:clearance.weatherBasis||absent(),
      status:clearanceStatusName(clearance.status),
      flight,
    }
  })
  return {rows,total:list.length,shown:rows.length,
    truncated:list.length>rows.length,
    note:list.length
      ?`共 ${list.length} 班有放行许可，此处列 ${rows.length} 班${list.length>rows.length?'（按风险优先序）':''}。`
      :'本次计划尚未写出任何放行许可（计划未就绪或场景未声明放行时刻）。'}
}

// ---- P1-2 ①：AI 结论标记 -----------------------------------------------------
//
// 这一条的要点不是"标上 AI"，而是**把算法的地位说清楚**：本系统的每一个放行 /
// 关闭 / 改航结论都由**确定性规则引擎**直接产出，外部模型只在被问到某一条时
// 检索证据，而且它可以被规则整条否决。所以结论的默认标记必须是
// 「未经 AI 研判」，而**不是空白** —— 空白会被读成"忘了标"，而它其实是一个
// 真实的、每次都成立的事实。
//
// 标记的来源只有一处：`/traffic/explain` 返回的 `ai.outcome`。前端不自己判断
// "这次算不算用了 AI"。
export const AI_MARKS=Object.freeze({
  NOT_REVIEWED:{key:'NOT_REVIEWED',label:'未经 AI 研判',
    note:'数值判定由概率模型完成；本页是大模型的证据检索，按需触发。数值由模型算，语言由大模型说，规则负责兜底。',
    tone:'muted'},
  ADOPTED:{key:'ADOPTED',label:'AI 已研判 · 外模选取已采用',
    note:'外部模型在证据集合内选取了引用，且未被规则否决。放行结论本身仍由规则引擎给出。',
    tone:'cyan'},
  VETOED:{key:'VETOED',label:'AI 已研判 · 外模被规则否决',
    note:'外部模型越出证据集合，整条作答被退回，界面只呈现规则证据。',
    tone:'warn'},
  DEGRADED:{key:'DEGRADED',label:'AI 已研判 · 外模不可用（仅规则证据）',
    note:'外部模型调用失败，已降级为规则证据。结论未受影响。',
    tone:'muted'},
  RULE_ONLY:{key:'RULE_ONLY',label:'AI 已研判 · 未配置外模（仅规则证据）',
    note:'本机未配置外部模型，全部证据由规则引擎给出。',
    tone:'muted'},
})
/** `explain` 的四种结局 → 标记。未知结局**原样透出**，不猜、也不回落成"未经研判"。 */
export function aiMark(outcome){
  const map={ACCEPTED:'ADOPTED',VETOED:'VETOED',UNAVAILABLE:'DEGRADED',NOT_CONFIGURED:'RULE_ONLY'}
  const key=map[String(outcome||'')]
  if(!key)return {...AI_MARKS.NOT_REVIEWED}
  return {...AI_MARKS[key]}
}
/**
 * 一个班次的结论标记。`reviewed` 是本次会话里已经问过的 `flightId → outcome`。
 *
 * **没问过 = 未经研判**，不是"未配置"。这两个是不同的状态：前者是"模型没被叫到"，
 * 后者是"叫了但本机没配"。合并它们就等于把配置问题藏进一个默认值里。
 */
export function verdictMark(flightId,reviewed){
  const outcome=reviewed&&typeof reviewed==='object'?reviewed[String(flightId||'')]:null
  if(!outcome)return aiMark(null)
  return aiMark(outcome)
}
/** 覆盖率的数字型口径：分母是**全部班次**，不是"有许可的班次"。 */
export function aiCoverage(flights,reviewed){
  const list=Array.isArray(flights)?flights:[]
  const map=reviewed&&typeof reviewed==='object'?reviewed:{}
  const reviewedFlights=list.filter(flight=>flight&&map[String(flight.id||'')])
  const vetoed=reviewedFlights.filter(flight=>String(map[String(flight.id)])==='VETOED')
  return {
    total:list.length,reviewed:reviewedFlights.length,vetoed:vetoed.length,
    uncovered:list.length-reviewedFlights.length,
    ratio:list.length?reviewedFlights.length/list.length:0,
  }
}

// ---- P1-4：气象态势（分档统计 / 影响面 / 时间演变） --------------------------
//
// 「分档统计」的真源是雷达帧自身：`weather.radar.regions[0].bands`
// = `{STRATIFORM|CONVECTIVE|STRONG: {components, areaKm2}}`，边界 15/35/45 dBZ
// 由后端从 `cma_tiles` 再导出（`radar_field.py:64`）。两种通道都发。
//
// **缺席不得用并集顶替**（ADR-44）：某个档位本帧没有回波时，后端发的是
// `areaKm2: 0`；而某个档位**根本没被发布**（虚拟通道没有"某一帧的三档"这回事）
// 时字段缺失。前者是"量出来是 0"，后者是"没有这个东西" —— 两者显示成同一句话，
// 读者就无法判断是天气好还是数据没到。
export const RADAR_BANDS=Object.freeze([
  {key:'STRATIFORM',label:'15–35 dBZ 层状降水',transferable:true,
   note:'可飞越，仅作可见性说明，不构成限制'},
  {key:'CONVECTIVE',label:'35–45 dBZ 对流回波',transferable:false,
   note:'须绕飞；本系统按 250 m 擦边深度避让'},
  {key:'STRONG',label:'≥45 dBZ 对流内核',transferable:false,
   note:'禁止进入；路线不得与其相交'},
])
export function radarTierStats(weather,plan){
  const regions=weather&&weather.radar&&Array.isArray(weather.radar.regions)?weather.radar.regions:[]
  const record=regions.find(item=>item&&item.kind==='RADAR')||null
  const bands=record&&record.bands&&typeof record.bands==='object'?record.bands:null
  const summary=weather&&weather.radar&&weather.radar.summary
  const summaryBands=summary&&summary.bands&&typeof summary.bands==='object'?summary.bands:null
  // 两个来源取**同一个数**时优先 `bands`；只有在 `bands` 缺席时才读 `summary`，
  // 并把这件事写进 note。两个来源都在时绝不取平均或相加。
  const source=bands?'regions':(summaryBands?'summary':null)
  const table=source==='regions'?bands:(source==='summary'?summaryBands:null)
  const rows=RADAR_BANDS.map(item=>{
    const raw=table?(table[item.key]||null):null
    const area=raw&&Number.isFinite(Number(raw.areaKm2))?Number(raw.areaKm2):null
    const components=raw&&Number.isFinite(Number(raw.components))?Number(raw.components):null
    return {...item,areaKm2:area,components,
      published:raw!==null,
      // 三态：发布出来是 0 → 「本帧无」；发布了但值为 null → 「值非法」；
      // 压根没发布 → 「本帧未发布该档」。
      state:raw===null?'ABSENT':(area===null?'INVALID':(area>0?'PRESENT':'EMPTY')),
    }
  })
  const total=rows.reduce((sum,row)=>sum+(row.areaKm2||0),0)
  const hazardRows=rows.filter(row=>!row.transferable)
  const hazardArea=hazardRows.reduce((sum,row)=>sum+(row.areaKm2||0),0)
  const avoidance=(plan&&plan.radarAvoidance)||null
  return {
    rows,totalAreaKm2:Number(total.toFixed(1)),
    hazardAreaKm2:Number(hazardArea.toFixed(1)),
    source,
    // 避让几何的分档**另算**：它来自计划载荷，只对实测通道发布。虚拟通道的避让
    // 是沿时间轴逐帧并集，没有"瞬时三档"可言 —— 硬报一个数就等于把扫掠并集
    // 说成一次观测（ARCH 里那件事被明确否决过）。
    avoidance:avoidance?{
      mode:avoidance.mode||null,
      unionKm2:Number.isFinite(Number(avoidance.areaKm2))?Number(avoidance.areaKm2):null,
      coreKm2:Number.isFinite(Number(avoidance.coreAreaKm2))?Number(avoidance.coreAreaKm2):null,
      cautionKm2:Number.isFinite(Number(avoidance.cautionAreaKm2))?Number(avoidance.cautionAreaKm2):null,
      watchKm2:Number.isFinite(Number(avoidance.watchAreaKm2))?Number(avoidance.watchAreaKm2):null,
      perTier:Number.isFinite(Number(avoidance.coreAreaKm2)),
    }:null,
    echoFraction:summary&&Number.isFinite(Number(summary.echoFraction))?Number(summary.echoFraction):null,
    components:summary&&Number.isFinite(Number(summary.components))?Number(summary.components):null,
    mode:weather&&weather.radar?weather.radar.mode:null,
    available:!!(weather&&weather.radar&&weather.radar.available),
    note:source==='regions'
      ?'面积取自本帧雷达区域自身发布的分档（与判定同源）。'
      :(source==='summary'
        ?'本帧未发布分档区域，面积取自雷达通道摘要；两处同源，不叠加。'
        :'本帧没有可用的雷达分档：帧不可用或通道未纳入避让几何。这不是"面积 0"。'),
  }
}

/**
 * 气象影响面：**按成因归因**，不按几何相交。
 *
 * 归因的来源是班次自己的 `routeBasis` —— 后端在规划时就写下了"这条航路是什么被
 * 推弯的"。用几何去相交是另一套算法，会得出与计划不同的归属（那正是 0.9.26
 * 之前"42 班被记到气象账上"那件事的同型错误）。所以这里只做**统计**，
 * 不做第二遍判定。
 */
export const IMPACT_BASES=Object.freeze(['RADAR_CORE','RADAR_FIELD','LOW_VISIBILITY','POINT_WEATHER','STATIC_AIRSPACE','BOUNDARY'])
export function weatherImpact(plan,flights,network){
  const list=(Array.isArray(flights)?flights:[]).filter(Boolean)
  const routes=Array.isArray(network&&network.routes)?network.routes:[]
  const nameOf=routeId=>{
    const route=routes.find(item=>item&&item.id===routeId)
    return route?(route.name||route.id):routeId
  }
  const rows=IMPACT_BASES.map(basis=>{
    const members=list.filter(flight=>String(flight.routeBasis||'')===basis)
    const corridors=[...new Set(members.map(flight=>String(flight.routeId||'')).filter(Boolean))]
      .map(nameOf)
    const detours=members.map(flight=>Number(flight.detourMinutes)||0)
    return {
      basis,label:routeBasisNames[basis]||basis,
      weather:WEATHER_ROUTE_BASES.includes(basis),
      count:members.length,
      closedCount:members.filter(flight=>flight.status==='CLOSED').length,
      corridors:corridors.slice(0,6),corridorCount:corridors.length,
      maxDetourMinutes:detours.length?Number(Math.max(...detours).toFixed(1)):0,
    }
  }).filter(row=>row.count>0)
  const weatherRows=rows.filter(row=>row.weather)
  const otherRows=rows.filter(row=>!row.weather)
  return {
    rows,weatherRows,otherRows,
    weatherFlights:weatherRows.reduce((sum,row)=>sum+row.count,0),
    otherFlights:otherRows.reduce((sum,row)=>sum+row.count,0),
    note:rows.length
      ?'按各班次已写定的航路成因统计 —— 这是规划时写下的归属，不是事后用几何交出来的第二遍判定。'
      :'本次计划没有任何班次被改航：全部按直线走廊放行。',
  }
}

/**
 * 气象态势的时间演变：**两个轴分开**，因为它们的数据来源不同。
 *
 *   ① 运行结果轴：逐时段的起飞 / 受气象影响改航 / 因气象关闭。来源是班次自己的
 *      起降分钟；与推演指针无关，所以它是一份稳定情报，不会跟着播放条变。
 *   ② 避让几何轴：虚拟通道沿时间轴逐帧采样（步长 × 点数 + 起止时刻），
 *      实测通道**只有一次观测**、覆盖全窗口。
 *
 * 第二轴上**没有**"逐时回波序列"这个东西。所以这里在实测通道上写的是弃权，
 * 而不是画一条平线假装它没有变化 —— 一条平线是一句没人能核对的断言。
 */
export function weatherEvolution(plan,flights,{step=60,span=TIMELINE_SPAN_MINUTES}={}){
  const list=(Array.isArray(flights)?flights:[]).filter(Boolean)
  const buckets=[]
  const width=Math.max(1,Math.floor(Number(step)||60))
  for(let from=0;from<span;from+=width){
    const to=Math.min(span,from+width)
    const inside=minute=>Number.isFinite(Number(minute))&&Number(minute)>=from&&Number(minute)<to
    const departures=list.filter(flight=>inside(flight.departureMinute??flight.requestedDepartureMinute))
    const detoured=departures.filter(isWeatherDetour)
    const closed=list.filter(flight=>flight.status==='CLOSED'
      &&inside(flight.requestedDepartureMinute??flight.departureMinute))
    const weatherClosed=closed.filter(flight=>WEATHER_CLOSURE_REASONS.has(flight.reason))
    buckets.push({
      from,to,key:`${from}-${to}`,
      departures:departures.length,
      detoured:detoured.length,
      closed:closed.length,
      weatherClosed:weatherClosed.length,
      maxDetourMinutes:detoured.length
        ?Number(Math.max(...detoured.map(flight=>Number(flight.detourMinutes)||0)).toFixed(1)):0,
    })
  }
  const avoidance=(plan&&plan.radarAvoidance)||null
  const virtual=!!avoidance&&avoidance.mode==='virtual'
  const slots=Number(avoidance&&avoidance.sweepSlots)
  const stride=Number(avoidance&&avoidance.sweepStrideMinutes)
  const evolution=virtual&&Number.isFinite(slots)&&slots>0
    ? {state:'PER_SLOT',slots,strideMinutes:Number.isFinite(stride)?stride:null,
       from:avoidance.slot||null,to:avoidance.slotTo||null,
       note:`避让几何按 ${Number.isFinite(stride)?stride:'—'} 分钟步长沿时间轴取 ${slots} 帧，逐班取自身飞行窗口内的并集。`}
    : (avoidance&&avoidance.included
      ? {state:'SINGLE_OBSERVATION',slots:null,strideMinutes:null,
         from:avoidance.slot||null,to:null,
         note:`本通道只有一次实测观测${avoidance.slotAgeMinutes!=null?`（取回时已过期 ${avoidance.slotAgeMinutes} 分钟）`:''}，`
           +'按声明语义覆盖整个计划窗口。<b>本通道不提供逐时回波序列</b> —— 投影一张实测回波向前就是编造预报。'}
      : {state:'NOT_INCLUDED',slots:null,strideMinutes:null,from:null,to:null,
         note:'本计划未纳入雷达避让几何：'+(avoidanceAbsentReason(avoidance&&avoidance.reason)||'未声明原因')})
  const peak=buckets.reduce((best,row)=>(row.detoured>((best&&best.detoured)||0)?row:best),null)
  return {
    stepMinutes:width,spanMinutes:span,buckets,evolution,
    peak,bucketCount:buckets.length,
    note:'运行结果轴按班次自己的起降分钟分桶（与推演指针无关）；避让几何轴说的是这份计划的避让几何是怎么沿时间取得的。'
      +(peak&&peak.detoured?`受气象影响改航最集中的时段是 ${relativeClock(peak.from)}–${relativeClock(peak.to)}（${peak.detoured} 班）。`:''),
  }
}

// ---- P0-3：四态处置状态机与一键处置动作 ---------------------------------------
//
// 两态（已确认 / 已处置）表达不了"这件事我正在处理"。而"正在处理"是值班室里
// 最常发生的一种状态：把它并进"已确认"，交班时就无法区分"看了一眼"和"已经在
// 改时隙了"。
//
// **动作是否能执行，由已发布的事实决定，而不是由界面猜**：
//   · 延迟起飞 / 改航绕飞 —— 这两件事的产物在计划里是 `delayMinutes` /
//     `routeBasis`，它们由规划器在**构建时**写定，运行时无法对某一个事件重算；
//   · 停止放行 —— 才是运行时可执行的动作（对具体班次下 `SUSPEND`）。
// 所以「延迟」与「改航」在事件处置台上**必须显式回答"本系统不支持"**，
// 而不是发一个请求、收到一个失败、再把它渲染成"已处置"。
export const DISPOSAL_FLOW=Object.freeze([
  {key:'PENDING',label:'待确认',note:'尚无任何处置记录。'},
  {key:'ACKNOWLEDGED',label:'已确认',note:'已确认该事件，尚未给出处置动作。'},
  {key:'IN_PROGRESS',label:'处置中',note:'正在执行处置动作（改时隙 / 改航 / 停止放行）。'},
  {key:'HANDLED',label:'已处置',note:'处置动作已完成，等待复核。'},
  {key:'REVIEWED',label:'已复核',note:'交班或复盘时已复核该处置。'},
])
export const DISPOSAL_STATE_KEYS=Object.freeze(DISPOSAL_FLOW.map(item=>item.key))
export function disposalStateLabel(state){
  const found=DISPOSAL_FLOW.find(item=>item.key===String(state||''))
  return found?found.label:absent()
}
export const DISPOSAL_ACTIONS=Object.freeze([
  {key:'DELAY',label:'延迟起飞',supported:false,toState:'IN_PROGRESS',
   why:'本系统的改时隙在计划构建时写定（班次字段 `delayMinutes` 与 `groundWaitMinutes`），运行时不支持对已生成的一个事件重新排时隙。'},
  {key:'DETOUR',label:'改航绕飞',supported:false,toState:'IN_PROGRESS',
   why:'航路成因与绕行几何在计划构建时写定（班次字段 `routeBasis` 与 `points`），运行时不支持对已生成的一个事件重算航路。'},
  {key:'SUSPEND',label:'停止放行',supported:true,toState:'IN_PROGRESS',
   why:'对事件样本班次下达 `SUSPEND`，写回运行操作与决策日志；可在调度台账恢复原时隙。'},
  {key:'HANDLED',label:'标记已处置',supported:true,toState:'HANDLED',
   why:'处置动作完成，写一条留痕等待复核。'},
  {key:'REVIEWED',label:'复核',supported:true,toState:'REVIEWED',
   why:'交班或复盘时的复核留痕。'},
])
export function disposalAction(key){
  return DISPOSAL_ACTIONS.find(item=>item.key===String(key||''))||null
}
/** 下一步可用的动作。
 *
 * 0.11.3（W-06）改了这条接口的**契约**，不是改了文案：不再返回不支持的动作。
 * 原来的设计是"列出来但标注（不支持）"，理由是"藏起来等于骗人"；但在演示现场，
 * 一个写着「延迟起飞（不支持）」的按钮传达的是"这系统没做完"，而不是"这条能力
 * 边界在哪"。能力边界该由台账与口径页说明，不该长在按钮上。
 * 不支持的记录仍留在 `DISPOSAL_ACTIONS` 里（`supported:false` + `why`），
 * 因为**审计需要知道哪些动作被拒绝过**，只是不再渲染成可点击的入口。
 */
export function disposalNextActions(state){
  const current=String(state||'PENDING')
  if(current==='REVIEWED')return []
  if(current==='PENDING')return DISPOSAL_ACTIONS.filter(item=>item.supported&&['DELAY','DETOUR','SUSPEND'].includes(item.key))
  if(current==='ACKNOWLEDGED')return DISPOSAL_ACTIONS.filter(item=>item.supported&&['DELAY','DETOUR','SUSPEND'].includes(item.key))
  if(current==='IN_PROGRESS')return DISPOSAL_ACTIONS.filter(item=>item.supported&&['HANDLED'].includes(item.key))
  if(current==='HANDLED')return DISPOSAL_ACTIONS.filter(item=>item.supported&&['REVIEWED'].includes(item.key))
  return []
}

// ---- P2-3：回放带当时气象帧 --------------------------------------------------
//
// 复盘回放读的是**已经写下的日志**（`replaySlice`），不重跑算法。这一轮要补的是
// 同一时刻的**气象帧**：当时屏幕上那张回波图是什么样。
//
// 这里**只读取、不重算**：把当前气象帧按它自己的 `minute` 与回放时刻对齐，并明确
// 说出两者是否同一刻。对不上时说的是"该帧不是回放时刻的帧"，而不是把当前帧
// 当成当时的帧摆上去 —— 那正是 0.9.26 之前"计划与地图不是同一个世界"的同型错误。
export function replayWeatherFrame(weather,minute){
  const frame=weather&&typeof weather==='object'?weather:null
  // 0.11.25（B-4）：**ABSENT 也必须返回同一套键。**
  //
  // 原来这一支只给了 state/label/note，没有 `tiers` —— 而模板里写着
  // `replayWeather.tiers.stratiform`。于是"气象帧没取到"这一支一渲染就抛
  // `Cannot read properties of undefined (reading 'stratiform')`，
  // 整页渲染中断 ⇒ 复盘回放面板**整个不出现**，看起来像"功能没做"。
  // 缺值可以，缺键不行：调用方拿到的对象形状必须恒定。
  if(!frame)return {state:'ABSENT',label:'未取得气象帧',
    minute:null,requested:Number.isFinite(Number(minute))?Number(minute):null,
    cells:0,observations:0,provider:null,dataType:null,
    radarAvailable:false,radarSlot:null,
    tiers:{stratiform:null,convective:null,strong:null},
    note:'回放时刻没有可用的气象帧：读取失败或本帧已作废（推演继续）。'}
  const frameMinute=Number(frame.minute)
  const at=Number(minute)
  const radar=frame.radar||null
  const regions=radar&&Array.isArray(radar.regions)?radar.regions:[]
  const record=regions.find(item=>item&&item.kind==='RADAR')||null
  const bands=record&&record.bands&&typeof record.bands==='object'?record.bands:null
  const areaOf=key=>{
    const raw=bands?bands[key]:null
    return raw&&Number.isFinite(Number(raw.areaKm2))?Number(raw.areaKm2):null
  }
  const aligned=Number.isFinite(frameMinute)&&Number.isFinite(at)&&Math.abs(frameMinute-at)<0.5
  return {
    state:aligned?'ALIGNED':'MISALIGNED',
    minute:Number.isFinite(frameMinute)?frameMinute:null,
    requested:Number.isFinite(at)?at:null,
    cells:Array.isArray(frame.cells)?frame.cells.length:0,
    observations:Array.isArray(frame.observations)?frame.observations.length:0,
    provider:frame.provider||frame.source||null,
    dataType:frame.dataType||null,
    radarAvailable:!!(radar&&radar.available),
    radarSlot:record?record.slot:null,
    tiers:{stratiform:areaOf('STRATIFORM'),convective:areaOf('CONVECTIVE'),strong:areaOf('STRONG')},
    label:aligned
      ?`回放时刻的气象帧（T+${String(Math.floor((at||0)/60)).padStart(2,'0')}:${String(Math.round((at||0)%60)).padStart(2,'0')}）`
      :'页面持有的不是回放时刻的气象帧',
    note:aligned
      ?'本帧的观测与回波都是<b>当时那一次求值</b>的结果，没有按当前计划重算。'
      // 0.11.18（F-8 / 复测 N-8）：**未取得时不许按取到了写。**
      // `minute` 字段为 null（界面左侧因此显示「未取得」），而这里原来写
      // `Math.round(frameMinute||0)` —— `undefined||0` 就是 0，于是同一段文字里
      // 左边说「未取得」、右边说「本帧是 T+0 分钟的帧」。模板一套两种情况，必有一句是假话。
      :(Number.isFinite(frameMinute)
        ?`本帧是 T+${Math.round(frameMinute)} 分钟的帧，回放指针在 T+${Math.round(at||0)} 分钟 —— `
          +'两者不是同一刻。下面给出的仍是这一帧自己的数，请勿把它读成回放时刻的天气。'
        :`回放指针在 T+${Number.isFinite(at)?Math.round(at):'—'} 分钟；`
          +'<b>本帧气象帧未取得</b> —— 本段的气象数字不代表任何时刻的天气，要读数请先等到一帧。'),
  }
}

/** 中继取瓦片时要试的候选时次（**纯函数**，无 DOM、无网络，便于在套件里直接断言）。
 *
 * 为什么需要一个专门的函数、而不是在取图的地方随手 `new Date()`：
 * 路径里的时间字面值是**北京时**，与浏览器本地时区无关。若在非中国时区的
 * 浏览器里按本地时间拼路径，会稳定地取到另一个时次的图 —— 而"取到了"和
 * "取对了"在界面上长得一模一样（本轮服务端就踩过同一个坑：用 UTC 拼路径，
 * 每次都取 8 小时前的图，`slotAgeMinutes` 还自洽地报成 5 分钟）。
 *
 * 所以这里显式接收 `offsetMinutes`（服务端下发的口径，480 = UTC+8），
 * 用 UTC 取值器读"北京的墙钟"，绝不读本地时区。
 *
 * @param {number} nowMs                 当前时刻（ms epoch）
 * @param {number} offsetMinutes         路径字面值相对 UTC 的偏移，服务端下发 480
 * @param {number} cadenceMinutes        发布节奏
 * @param {number} steps                 往前回溯多少档（含当前档）
 * @returns {{path:string, iso:string, label:string}[]} 从最新到最旧
 */
export function radarRelaySlots(nowMs, offsetMinutes = 480, cadenceMinutes = 6, steps = 12) {
  const step = Math.max(1, Math.floor(cadenceMinutes))
  const offsetMs = offsetMinutes * 60_000
  const wall = new Date(nowMs + offsetMs)
  const alignedMinute = Math.floor(wall.getUTCMinutes() / step) * step
  // 把"北京的墙钟读数"当成 UTC 存进一个毫秒数：此后所有加减都在这条轴上做，
  // 不会被动过一次本地时区。绝对时刻 = 墙钟 - offset（见下）。
  const base = Date.UTC(wall.getUTCFullYear(), wall.getUTCMonth(), wall.getUTCDate(),
    wall.getUTCHours(), alignedMinute, 0, 0)
  const pad = value => String(value).padStart(2, '0')
  const out = []
  for (let index = 0; index < steps; index += 1) {
    const at = new Date(base - index * step * 60_000)
    const day = `${at.getUTCFullYear()}${pad(at.getUTCMonth() + 1)}${pad(at.getUTCDate())}`
    const hour = pad(at.getUTCHours())
    const minute = pad(at.getUTCMinutes())
    out.push({
      path: `${day}/${hour}/${minute}`,
      iso: new Date(at.getTime() - offsetMs).toISOString(),
      label: `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())} ${hour}:${minute}`,
    })
  }
  return out
}

/** 服务端下发的取图说明是否完整可用；不完整就不要发起中继（会白跑一轮网络）。 */
export function radarRelayReady(relay) {
  return !!(relay && relay.needed === true && relay.tileBase && Array.isArray(relay.grid)
    && relay.grid.length > 0 && Number.isFinite(relay.zoom))
}

// ---- 轨1 规则 × 模型（0.10.1（Beta））--------------------------------------
//
// 这一节回答的问题只有一个：**模型在这一次结论里的位置是什么**。
// 它不是"模型准不准"（那个问题的答案在成效页，且有分母），而是"这一屏该显示哪个档位"。
//
// 三条必须写死在代码里、不许交给模板判断的事：
//   1. 模型**不能**让结论更乐观。规则说 BAN、模型说 FIT ⇒ 仍然是 BAN。
//      这不是"权重问题"，所以这里没有加权：加权意味着高置信度可以翻案。
//   2. 模型缺席时显示"模型未参与"，**不显示"模型判 FIT"**。缺席与"判了适飞"
//      在界面上长得一样过一次，那次的表现是"模型一直在放行"，而真相是它根本没跑。
//   3. 四态（同档 / 模型更保守 / 规则否决 / 未参与）必须全列，当前的高亮 ——
//      只显示当前那一种，读者无从知道还有另外三种（同 `MARK_ROWS` 的理由）。

export const TRACK1_LEVELS = Object.freeze(['FIT', 'CAUTION', 'DANGER', 'BAN'])

export const TRACK1_LEVEL_LABELS = Object.freeze({
  FIT: '适飞', CAUTION: '谨慎', DANGER: '危险', BAN: '禁飞',
})

export const TRACK1_DECISIONS = Object.freeze({
  CONSISTENT: {
    key: 'CONSISTENT', label: '规则与模型同档', tone: 'ok',
    note: '两条路径给出同一个档位。这里能说的只有"一致"，不是"互相验证"——模型的标签本来就来自一份判据。',
  },
  MODEL_STICTER: {
    key: 'MODEL_STICTER', label: '模型更保守，已采纳', tone: 'warn',
    note: '模型看到了规则没有覆盖的组合（例如阵风因子、能见度与降水的叠加），因此<b>向上</b>采纳它的档位。',
  },
  RULE_OVERRIDES_MODEL: {
    key: 'RULE_OVERRIDES_MODEL', label: '规则否决模型', tone: 'veto',
    note: '模型给出的档位比规则更宽松。<b>档位不变</b>：模型不能把禁飞改成可飞，这一步没有加权，置信度再高也不翻案。',
  },
  MODEL_UNAVAILABLE: {
    key: 'MODEL_UNAVAILABLE', label: '模型未参与', tone: 'muted',
    note: '这一轮只有规则在工作。界面不显示"模型判了什么"——因为它没有判，编一个档位比留空更糟。',
  },
  UNKNOWN: {
    key: 'UNKNOWN', label: '无法判定', tone: 'muted',
    note: '规则与模型的档位没有同时到齐，且原因不在"模型缺席"这一类。此时不给结论，只列出已经拿到的部分。',
  },
})

/** 只认四个合法档位。其它一律 `null` —— 不把未知档位默认成 FIT。 */
function track1Level(value) {
  return TRACK1_LEVELS.includes(value) ? value : null
}

function track1Number(value) {
  // `Number(null) === 0` 与 `Number(undefined) => NaN` 这两条在这里都要挡住：
  // 「没有置信度」和「置信度是 0」在界面上是两句不同的话。
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * 轨1 研判卡的四块视图：规则 / 模型 / 融合 / 解释位。
 *
 * @param {object} options
 * @param {object|null} options.rule 规则结果（`/traffic/session` 里的 sfi/level 那一份）
 * @param {object|null} options.model `/track1/ml` 的响应（可为 `null` = 还没请求）
 * @returns {object} 视图模型，字段见下方 return
 */
export function buildTrack1View(options) {
  // 注意：**不能**写成 `{ rule, model } = {}` —— 默认值只在 `undefined` 时生效，
  // 传 `null` 会直接解构报错。而 `null` 恰恰是"还没请求过"的自然表示。
  const opts = options && typeof options === 'object' ? options : {}
  const ruleDoc = opts.rule && typeof opts.rule === 'object' ? opts.rule : null
  const ruleLevel = ruleDoc ? track1Level(ruleDoc.level) : null

  const modelDoc = opts.model && typeof opts.model === 'object' ? opts.model : null
  const modelAvailable = !!(modelDoc && modelDoc.available === true)
  const modelLevel = modelAvailable ? track1Level(modelDoc.level) : null

  const modelBlock = {
    requested: !!modelDoc,
    available: modelAvailable && !!modelLevel,
    level: modelLevel,
    levelLabel: modelLevel ? TRACK1_LEVEL_LABELS[modelLevel] : null,
    confidence: track1Number(modelDoc && modelDoc.confidence),
    margin: track1Number(modelDoc && modelDoc.margin),
    lowConfidence: !!(modelDoc && modelDoc.lowConfidence === true),
    degraded: !!(modelDoc && modelDoc.degraded && modelDoc.degraded.flag === true),
    degradedReason: (modelDoc && modelDoc.degraded && modelDoc.degraded.reason) || null,
    missingFeatures: Array.isArray(modelDoc && modelDoc.missingFeatures) ? modelDoc.missingFeatures.slice() : [],
    top3: Array.isArray(modelDoc && modelDoc.top3)
      ? modelDoc.top3.map(item => ({
        feature: String(item && item.feature || ''),
        featureLabel: TRACK1_FEATURE_LABELS[item && item.feature] || String(item && item.feature || ''),
        value: track1Number(item && item.value),
        score: track1Number(item && item.score),
      }))
      : [],
    modelVersion: (modelDoc && modelDoc.modelVersion) || null,
    labelsVersion: (modelDoc && modelDoc.labelsVersion) || null,
    // 缺席原因要能区分「还没问」与「问了但没有模型」。两者都显示"未参与"，
    // 但排查方向完全不同：前者是界面没接线，后者是这一版没带模型文件。
    absentReason: !modelDoc ? 'NOT_REQUESTED'
      : (modelAvailable && modelLevel ? null : (modelDoc.status || modelDoc.reason || 'MODEL_UNAVAILABLE')),
  }

  let decision = 'UNKNOWN'
  if (ruleLevel && modelBlock.available) {
    const diff = TRACK1_LEVELS.indexOf(modelLevel) - TRACK1_LEVELS.indexOf(ruleLevel)
    decision = diff === 0 ? 'CONSISTENT' : (diff > 0 ? 'MODEL_STICTER' : 'RULE_OVERRIDES_MODEL')
  } else if (ruleLevel) {
    // 规则有结论、模型没有 —— 无论原因是没请求还是没模型，都归"未参与"。
    decision = 'MODEL_UNAVAILABLE'
  }

  const meta = TRACK1_DECISIONS[decision]
  // 最终档位：只在模型更保守时被它抬高；其余情况一律是规则档位。
  const finalLevel = ruleLevel && modelBlock.available && decision === 'MODEL_STICTER'
    ? modelLevel : ruleLevel

  return {
    decision,
    decisionLabel: meta.label,
    decisionNote: meta.note,
    decisionTone: meta.tone,
    /** 四态全列，供「四种结局」那一排渲染（当前项由 `decision` 高亮）。 */
    decisions: ['CONSISTENT', 'MODEL_STICTER', 'RULE_OVERRIDES_MODEL', 'MODEL_UNAVAILABLE']
      .map(key => ({ key, label: TRACK1_DECISIONS[key].label, note: TRACK1_DECISIONS[key].note,
        tone: TRACK1_DECISIONS[key].tone })),
    rule: {
      level: ruleLevel,
      levelLabel: ruleLevel ? TRACK1_LEVEL_LABELS[ruleLevel] : null,
      sfi: ruleDoc ? track1Number(ruleDoc.sfi) : null,
      ruleVersion: (ruleDoc && ruleDoc.ruleVersion) || null,
      reasons: Array.isArray(ruleDoc && ruleDoc.reasons) ? ruleDoc.reasons.slice(0, 6) : [],
    },
    model: modelBlock,
    finalLevel,
    finalLabel: finalLevel ? TRACK1_LEVEL_LABELS[finalLevel] : null,
    /** 模型参与时才给归因说明。没参与却印一句"近似归因"，会把缺席讲成有结论。 */
    attributionNote: modelBlock.available
      ? 'Top3 为近似归因（全局分裂重要性 × 该样本偏离），不是逐条 SHAP。' : null,
    /** 这一屏可点到来源的三条路径，供"只导航不重算"。 */
    sources: [
      { label: '规则阈值与版本', path: 'config/rules-v1.json' },
      { label: '判据（训练标签来源）', path: 'config/labels-v1.json' },
      { label: '模型文件与训练溯源', path: 'models/ml-v1.json' },
    ],
  }
}

export const TRACK1_FEATURE_LABELS = Object.freeze({
  windSpeed: '平均风速', windGust: '阵风', precipMmh: '降水强度', visibilityM: '能见度',
  tempC: '温度', rhPct: '相对湿度', cloudPct: '云量', pressureHpa: '气压',
  gustFactor: '阵风因子', precipType: '降水类型',
  hourSin: '时刻（正弦）', hourCos: '时刻（余弦）', month: '月份',
})

// ---- 成效对比（规则 / 模型 / 独立标注员）----------------------------------
//
// 这一块最容易出事的地方不是数字算错，而是**同一件事被两个地方各算一遍**：
// 页面上印 0.977，报告里写 0.98，谁也没错，读者没法判断哪个是真的。
// 所以数字只在这里存一份，并带上它的出处文件；写测试时对着那份文件比对，
// 训练结果一换，页面与测试一起变红 —— 而不是页面继续印一个更好的旧数。
//
// ⚠️ 这三个数衡量的**不是"模型预测天气有多准"**：标签来自 `config/labels-v1.json`，
// 模型学的是那份判据。所以准确率说明的是"复现能力"。规则基线那一列用的是运行规则
// （另一套阈值与另一套聚合方式），两列回答的不是同一个问题，不可直接比优劣。
export const ML_EFFECT_SNAPSHOT = Object.freeze({
  source: 'data/training/model-v1-metrics.json',
  labelsSource: 'config/labels-v1.json',
  samples: 1133,
  trainSize: 793,
  validationSize: 170,
  testSize: 170,
  split: '按 timeLocal 升序 70/15/15，不打乱',
  modelVersion: 'ml-v1',
  parity: '导出后逐条比对，170/170 一致',
  columns: Object.freeze([
    Object.freeze({
      key: 'rule', label: '运行规则', source: 'config/rules-v1.json',
      macroF1: 0.3933, accuracy: 0.4412, dangerMiss: 23, dangerHit: 76,
      denominator: 99, note: '累减扣分 + 一票封顶；回答"这一轮能不能飞"',
    }),
    Object.freeze({
      key: 'model', label: '统计模型', source: 'models/ml-v1.json',
      macroF1: 0.977, accuracy: 0.9765, dangerMiss: 2, dangerHit: 97,
      denominator: 99, note: '随机森林 200 棵；学的是判据，不是天气',
    }),
    Object.freeze({
      key: 'manual', label: '人工仲裁', source: 'data/training/adjudication-sheet.jsonl',
      macroF1: null, accuracy: null, dangerMiss: null, dangerHit: null,
      denominator: 42, note: '判据与 DeepSeek 分歧样本的人工复核表；待填，不预估结果',
    }),
  ]),
  annotation: Object.freeze({
    tool: 'DeepSeek', count: 1133, failed: 0,
    raw: 0.6867, weightedKappa: 0.7946,
    note: '独立第二标注员，量的是"同一份判据换一个人按同样读法能否复现"；不作训练标签',
    source: 'data/training/label-agreement.json',
  }),
})

/** 比例统一四位小数；**分母为 0 返回 null**，不返回 0。 */
function mlRatio(part, whole) {
  return whole > 0 ? Math.round((part / whole) * 10000) / 10000 : null
}

/**
 * 成效页三列视图。
 *
 * @param {object} snapshot 默认为 `ML_EFFECT_SNAPSHOT`（测试可注入构造值以走负向对照）
 * @returns {object} 三列 + 汇总 + 空态标记
 */
export function buildMlEffectView(snapshot = ML_EFFECT_SNAPSHOT) {
  const doc = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const columns = Array.isArray(doc.columns) ? doc.columns : []

  const rows = columns.map(col => {
    const denominator = track1Number(col.denominator) ?? 0
    const dangerMiss = track1Number(col.dangerMiss)
    const dangerHit = track1Number(col.dangerHit)
    const dangerTotal = dangerMiss === null || dangerHit === null ? 0 : dangerMiss + dangerHit
    return {
      key: String(col.key || ''),
      label: String(col.label || ''),
      source: String(col.source || ''),
      note: String(col.note || ''),
      // macroF1 为 null 表示"这一列还没有结果"（人工仲裁表尚未填完），
      // 渲染成 '—' 而不是 0.000 —— 0.000 会被读成"表现极差"。
      macroF1: track1Number(col.macroF1),
      macroF1Text: track1Number(col.macroF1) === null ? '—' : track1Number(col.macroF1).toFixed(3),
      accuracy: track1Number(col.accuracy),
      accuracyText: track1Number(col.accuracy) === null ? '—'
        : `${(track1Number(col.accuracy) * 100).toFixed(1)}%`,
      denominator,
      dangerMiss,
      dangerHit,
      dangerTotal,
      // 危险漏报按"分母"给，同时给绝对值：只有百分比时，2/99 与 2/9 看起来一样严重。
      dangerMissText: dangerMiss === null ? '—' : `${dangerMiss}/${dangerTotal || denominator}`,
      dangerRecall: mlRatio(dangerHit === null ? 0 : dangerHit, dangerTotal),
      measured: track1Number(col.macroF1) !== null,
    }
  })

  const measurable = rows.filter(row => row.measured)
  const best = measurable.length
    ? measurable.reduce((a, b) => (b.macroF1 > a.macroF1 ? b : a)) : null

  return {
    empty: rows.length === 0,
    source: String(doc.source || ''),
    labelsSource: String(doc.labelsSource || ''),
    modelVersion: doc.modelVersion || null,
    parity: doc.parity || null,
    samples: track1Number(doc.samples),
    split: doc.split || null,
    sizes: {
      train: track1Number(doc.trainSize),
      validation: track1Number(doc.validationSize),
      test: track1Number(doc.testSize),
    },
    rows,
    best: best ? best.key : null,
    bestNote: best
      ? `${best.label} 的 macroF1 为三列中最高；这只是判据复现口径（谁更像那份判据），`
        + `0.11.1 的预测能力要看「模型卡」的 TS / Brier 与基线对照。`
      : '三列都还没有可比的 macroF1。',
    annotation: doc.annotation ? {
      tool: doc.annotation.tool,
      count: track1Number(doc.annotation.count),
      failed: track1Number(doc.annotation.failed),
      raw: track1Number(doc.annotation.raw),
      weightedKappa: track1Number(doc.annotation.weightedKappa),
      note: doc.annotation.note || '',
      source: doc.annotation.source || '',
    } : null,
    // 0.11.1（Beta）换芯后这句话必须改，而且必须**说清新旧两套不能并列**。
    // 原文案自曝「衡量的是复现判据的能力，不是预测天气的能力」—— 手册 §6 把它列为
    // 全站最贵的一句话：它等于替评委得出"这套 AI 没做气象"的结论。
    // 现在的口径是：本板块是本项目历史（轨1）指标，保留是为了可追溯；
    // 0.11.1 的模型能力看「检验 · 模型卡」，那页的标签是 METAR 实测、指标是气象圈那几个。
    caveat: '本板块是 0.10.1 轨1 的历史指标（macroF1 ＝ 复现判据），不代表 0.11.1 的预测能力；'
      + '0.11.1 改用 3 站 METAR 实测标签与概率输出，指标（TS / POD / FAR / Brier）与三条基线在「④ 检验 · 模型卡」。'
      + '两套指标的标签来源不同，不可并列比较；规则列用的又是运行规则（另一套阈值与聚合方式），与模型列也不可直接比优劣。',
  }
}

// ---- 观测条目 → 轨1 请求体 ------------------------------------------------
//
// 同一个物理量在载荷里有**四个名字**（`windMps` / `windSpeed10mMps` / `windSpeed`，
// 以及 `gustMps` / `windGusts10mMps` / `windGust`）。这不是笔误，是三条来源
// （open-meteo 批量、和风、AWC 报文）各自的历史命名。所以这里做**一次**归一化，
// 而不是让每个消费点各写一串 `??`：写在多处，下一处一定漏一个。
//
// 纪律：**缺失一律给 null，不给 0**。风速缺测填 0 会把"不知道"读成"无风"，
// 而这个读数恰好是判据里权重最高的一项 —— 填 0 等于替天气做了一次有利的伪证。
function track1Pick(...values) {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() !== '') {
      const num = Number(value)
      if (Number.isFinite(num)) return num
    }
  }
  return null
}

/**
 * 把一条观测归一成 `/track1/arbitrate` 期望的快照。
 *
 * @param {object|null} observation `weather.observations[]` 的一项
 * @returns {object} `{snapshot, cityId, sampleKey, timeBasis, present}`
 */
export function track1SnapshotOf(observation) {
  const o = observation && typeof observation === 'object' ? observation : {}
  const snapshot = {
    windSpeed: track1Pick(o.windSpeed10mMps, o.windMps, o.windSpeed),
    windGust: track1Pick(o.windGusts10mMps, o.gustMps, o.windGust),
    precipMmh: track1Pick(o.precipitationMm, o.precipMmh, o.precipitation),
    // 能见度有单独的取值路径（`visibilityM` → `hourly.visibility` 首个非空）。
    visibilityM: track1Pick(o.visibilityM, observationVisibilityM(o)),
    tempC: track1Pick(o.temperatureC, o.tempC, o.temperature),
    // 运行时的湿度/云量是 0–1 小数（与训练样本的 0–100 不同，换算在 `ml/features.py`）。
    humidity: track1Pick(o.humidity, o.relativeHumidity),
    cloudCover: track1Pick(o.cloudCover, o.cloud),
    pressureHpa: track1Pick(o.pressureHpa, o.pressureMslHpa, o.surfacePressureHpa, o.pressure),
    rainMmh: track1Pick(o.rainMmh, o.rain),
    snowfallCmh: track1Pick(o.snowfallCmh, o.snowfall),
  }

  const validAt = typeof o.validAt === 'string' ? o.validAt : (typeof o.observedAt === 'string' ? o.observedAt : '')
  const pad = value => String(value).padStart(2, '0')
  let sampleKey = null
  if (validAt) {
    const at = new Date(validAt)
    if (!Number.isNaN(at.getTime())) {
      // 用 UTC 字段拼，而不是 `toISOString().slice(0,13)` 之后再补分钟：
      // 后者在不同实现里对 `T` 与毫秒的处理不一致，拼出来会带 `:00:00.000`。
      sampleKey = `${o.cityId || 'UNKNOWN'}-${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}T${pad(at.getUTCHours())}${pad(at.getUTCMinutes())}`
    }
  }

  const present = Object.keys(snapshot).filter(key => snapshot[key] !== null)
  return {
    snapshot,
    cityId: o.cityId || null,
    sampleKey,
    // 观测条目没有"来源声明观测时刻"这一维时可传原值；后端会按 NOT_PROVIDED 处理。
    timeBasis: o.timeBasis || null,
    present,
    complete: present.length === Object.keys(snapshot).length,
  }
}

// =============================================================================
// 0.11.1（Beta）· 五页信息架构与概率层读数
// =============================================================================
//
// 手册 §2：10 个页签平铺会让"看态势 / 看走廊 / 做处置 / 验模型 / 查证据"五件事
// 挤在同一个层级上。这里不改老分节的名字（`SECTION_NAMES` 仍是子视图的唯一来源，
// 也是测试的锚点），而是额外声明**五个顶层入口**，每个入口带编号与一句说明。
//
// 为什么编号不是装饰：评委第一次打开时，"①②③④⑤"告诉他这是一个有顺序的故事，
// 而不是一堆功能。这一条零成本，但改变了整屏的读法。
//
// `subs[].label` 一律来自 `sectionName(key)`，**不在这里写第二份中文名**。理由和
// `SECTION_NAMES` 存在的理由是同一条：两份名字就是两个"哪个才对"的问题。这里只
// 声明"谁归到哪一组、组内什么顺序"，名字本身一个字都不重复写。
/**
 * 导航规格（0.11.4 / W-21b）。`subs` 的一项 = **一个入口**：
 *
 *   { key: 'alerts', members: ['alerts','schedule','assistant'] }
 *
 * `key` 是入口的**锚点视图**（点它时先打开这个）；`members` 是它包含的全部视图，
 * 页面内用一条 tab 条切换。`members` 省略 = 只有自己。
 *
 * 这样 `activeSection` 仍然只表示"现在渲染哪个视图"，而"入口"是展示层。
 * 反过来做（把 13 个视图真的删成 8 个）会把每个视图的判据、口径、下钻全重写一遍 ——
 * 那是重写，不是收拢。
 */
/**
 * 合并入口的显示名（0.11.4 / W-21b）。**只有合并过的入口才有条目** ——
 * 单视图入口的名字一律来自 `SECTION_NAMES`，不要在这里重复写一遍。
 *
 * 存在理由：一个入口装三个视图，用其中任何一个视图的名字当入口名都会误导
 * （叫"预警中心"却还装着调度台账）。所以入口要有自己的、上位一点的名字，
 * 而这个名字也必须有**唯一出处** —— 所以是表，不是散在 NAV_SPEC 里的字面量。
 */
export const ENTRY_LABELS = Object.freeze({
  card: '推演',
})

const NAV_SPEC = [
  { key: 'situation', no: 1, label: '态势', subtitle: '未来 6 小时，哪片天不能飞',
    subs: ['home', 'overview', 'weather'] },
  { key: 'corridor', no: 2, label: '走廊', subtitle: '这条走廊几点能飞，凭什么',
    subs: ['profile', 'briefing'] },
  { key: 'dispatch', no: 3, label: '处置', subtitle: 'AI 与规则谁说了算',
    subs: [{ key: 'alerts', label: ENTRY_LABELS.alerts, hint: '一批事件该怎么做、谁在什么时候飞',
              members: ['alerts', 'schedule', 'assistant'] }] },
  { key: 'verify', no: 4, label: '推演', subtitle: '一条走廊怎么被判成不可飞',
    subs: [{ key: 'card', label: ENTRY_LABELS.card, hint: '三个目标的指标，以及这些口径的依据',
              members: ['card', 'reference', 'mechanism'] }] },
  // 0.11.22：复盘对照与分歧台账**已并入「推演」**，这里只剩日志。
  // 但两者仍写进 `members` —— 归属要成立（否则"这个页面永远打不开"），
  // 显示靠 `HIDDEN_SECTIONS` 过滤：导航与 tab 都不出现，深链仍可达。
  { key: 'review', no: 5, label: '日志', subtitle: '按帧回放与操作留痕',
    subs: [{ key: 'history', members: ['history', 'counterfactual', 'ledger'] }] },
]
/**
 * 每个分节**自己**的一句话（0.11.4 / W-20）。
 *
 * 之前命令面板用的是**分组**副标，于是「复盘」组下四个子页显示同一句话
 * （"用 AI 和不用，差多少"）—— 一眼就能看出这份目录是手写的、而且没跟上。
 * 这里一句一页，判据是：把这句话念给没看过系统的人听，他能判断该不该点它。
 */
export const SECTION_HINTS = Object.freeze({
  home: '一屏结论：现在哪片天不能飞',
  overview: '按城市与走廊铺开的全域态势',
  weather: '逐站观测、派生风险区与数据来源',
  profile: '沿走廊逐公里的不可飞概率剖面',
  briefing: '放行许可、气象情报与管制边界',
  alerts: '预警事件的成因分布与处置状态',
  assistant: '大模型的证据检索与判定留痕',
  schedule: '逐班次的申请、计划与实际',
  card: '一条走廊从观测到裁决的完整链路',
  mechanism: '历史版本 0.10.1 的判据模型（非当前在跑的）',
  counterfactual: '同一份计划，AI 与规则各自处置了什么（已并入推演）',
  ledger: '人与系统判定不一致的逐条记录（已并入推演）',
  history: '运行日志与按帧回放',
  reference: '口径、阈值与每一条数据的来源',
})

/**
 * 不在导航里出现的分节（0.11.4 / W-20）。
 *
 * 「算法机理」没有下线 —— 它从「检验 · 模型卡」页脚的"历史版本 0.10.1"仍可进入。
 * 它不进导航的理由是**并排会互相拆台**：模型卡说 AUC 0.95 / TS 0.49，机理页说
 * "学的是判据、42 样本待填"，读者只会记住后者。
 *
 * 这个常量必须被**导航与命令面板同时读取**：只在一处过滤，就会出现"导航里没了、
 * Ctrl+K 里还在"（复测报告就是这么发现的）。
 */
export const HIDDEN_SECTIONS = Object.freeze(new Set(['mechanism', 'counterfactual', 'ledger']))

// 0.11.17（U-5）：13 个页面各自一个地址。**映射表只有这一份** ——
// 导航、深链接、探针、答辩时给评委的链接都读它，避免"同一个页面两个 slug"。
//
// 0.11.18（F-1）：**键必须是 `SECTION_NAMES` 里的 section key，一个不差。**
// 上一版有四个键写成了别的名字（`intel` / `model` / `caliber` / `divergence`），
// 而 `sectionHash()` 是 `SECTION_HASHES[section] || home` —— 查不到就**静默回落到首页**。
// 后果实测：13 个页面只产出 9 个不同 hash，民航情报／检验结论（现口径与来源）／
// 分歧台账四页点进去地址栏写着 `#/situation/home`；更进一步，`sectionFromHash('#/corridor/intel')`
// 会返回 `'intel'` 这个**不存在的 section**，直接刷新或别人给的链接就落不到页面。
// "少一维就静默共享那一维"在这里的形态是："少一个键就静默变成首页"。
export const SECTION_HASHES = Object.freeze({
  home: 'situation/home', overview: 'situation/overview', weather: 'situation/weather',
  profile: 'corridor/profile', briefing: 'corridor/briefing',
  alerts: 'dispatch/console', schedule: 'dispatch/ledger', assistant: 'dispatch/evidence',
  card: 'model/card', reference: 'model/reference', mechanism: 'model/mechanism',
  counterfactual: 'compare/counterfactual', ledger: 'compare/ledger',
  history: 'compare/log',
})

/** 视图 → hash（`#/situation/home`）。未知视图返回首页 hash。 */
export function sectionHash(section) {
  return '#/' + (SECTION_HASHES[section] || SECTION_HASHES.home)
}

/** hash → 视图。非法/空 hash 一律回落到 `home`（不要抛、不要留在空白页）。 */
export function sectionFromHash(hash) {
  const raw = String(hash || '').replace(/^#\/?/, '').replace(/\/+$/, '')
  for (const [key, path] of Object.entries(SECTION_HASHES)) {
    if (path === raw) return key
  }
  return 'home'
}

export const NAV_GROUPS = Object.freeze(NAV_SPEC.map(group => Object.freeze({
  ...group,
  subs: Object.freeze(group.subs.map(entry => {
    const spec = typeof entry === 'string' ? { key: entry } : entry
    const members = Object.freeze(spec.members ? [...spec.members] : [spec.key])
    return Object.freeze({
      key: spec.key,
      // 入口标签优先用入口自己的（"处置台"），否则就是锚点视图的名字
      label: spec.label || sectionName(spec.key),
      hint: spec.hint || SECTION_HINTS[spec.key] || group.subtitle,
      members,
      // 单视图入口没有 tab 条；多视图才有
      merged: members.length > 1,
    })
  })),
})))

/** 一个视图属于哪个**入口**（返回入口对象，找不到返回 null）。 */
export function entryOf(sectionKey) {
  for (const group of NAV_GROUPS) {
    for (const entry of group.subs) {
      if (entry.members.includes(sectionKey)) return entry
    }
  }
  return null
}

/** 入口里的 tab 列表：`[{key,label,active}]`。单视图入口返回空数组。
 *
 * 0.11.10：**锚点视图不再出现在 tab 条里**。
 * 入口按钮本身打开的就是锚点视图，而它的显示名与锚点视图名相同（W-33 要求
 * 「入口与页面同名」），于是「处置」下面曾经并排长出**两个一模一样的按钮**
 * （`事件处置台` `事件处置台` `调度台账` `大模型取证`）—— 一个亮、一个也亮，
 * 点哪个都一样。名字一致是对的，把同一个名字渲染两遍不是。
 * 现在 tab 条只列**锚点以外**的成员：`事件处置台 | 调度台账 大模型取证`。 */
export function entryTabs(sectionKey) {
  const entry = entryOf(sectionKey)
  if (!entry || !entry.merged) return []
  // 隐藏视图（mechanism）仍挂在入口下 —— 它是"可达但不并排"，
  // 所以 `navCoverageGap` 能看到它，而 tab 条里不出现它。
  return entry.members
    .filter(key => !HIDDEN_SECTIONS.has(key))
    .filter(key => key !== entry.key)
    .map(key => ({ key, label: sectionName(key) }))
}

/** 导航入口总数（W-21b 的目标是 8；这条会被测试钉住）。 */
export function navEntryCount() {
  return NAV_GROUPS.reduce((total, group) => total + group.subs.length, 0)
}

/** 顶层键 → 分组定义。未知键返回 `null`（不猜一个像样的分组）。 */
export function navGroup(key) {
  return NAV_GROUPS.find(group => group.key === key) || null
}

/** 分节的键 → 它所属的顶层分组键。未归组的分节返回空串（不硬塞进某一组）。 */
export function groupOfSection(key) {
  const group = NAV_GROUPS.find(g => g.subs.some(sub => sub.members.includes(key)))
  return group ? group.key : ''
}

/** 某个分组里**导航与面板都该显示**的子页（0.11.4 / W-20）。 */
export function visibleSubs(group) {
  if (!group) return []
  return (group.subs || []).filter(sub => !HIDDEN_SECTIONS.has(sub.key))
}

/**
 * 离线演示模式（0.11.4 / W-23）：`?offline=1`。
 *
 * 它不是"降级开关"，是**演出开关**：现场断网时底图要等 30 秒超时才挂离线层，
 * 而答辩只有 5 分钟。打开它，底图立刻用离线层，雷达层直接声明不可用 ——
 * 不用在台上等一次超时。
 *
 * 与其他开关一样读 URL，不写 localStorage：刷新就回到正常模式，
 * 不然"昨天开着 offline、今天忘了关"会被当成系统坏了。
 */
export function isOfflineMode() {
  try {
    return new URLSearchParams(window.location.search).get('offline') === '1'
  } catch (_) {
    return false
  }
}

/** 分组的默认子视图（第一个）。 */
export function defaultSub(key) {
  const group = navGroup(key)
  return group && group.subs.length ? group.subs[0].key : ''
}

/**
 * 分组自检：`NAV_GROUPS` 覆盖的键集合必须与 `SECTION_NAMES` 完全相等。
 *
 * 这条闸门防的是**最安静的一种漏**：新增一个分节，忘了把它挂进任何分组 ——
 * 于是那个页面永远打不开，而导航、构建、测试三处都不报错（它只是"少了一个
 * 入口"，不是"多了一个坏入口"）。返回 `null` 表示自洽，否则返回两边的差集。
 */
export function navCoverageGap() {
  const declared = new Set(Object.keys(SECTION_NAMES))
  // W-21b：入口是"折叠"过的，所以要**展开 members** 再比 ——
  // 只看 `subs[].key` 的话，被并进「处置台」的 schedule/assistant 会被算成"没归组"，
  // 而它们其实好端端地挂在入口里。这条闸门一旦按入口 key 比，就会误报三个缺口。
  const grouped = new Set(NAV_GROUPS.flatMap(g => g.subs.flatMap(s => s.members)))
  const missing = [...declared].filter(k => !grouped.has(k))
  const extra = [...grouped].filter(k => !declared.has(k))
  return missing.length || extra.length ? { missing, extra } : null
}

/**
 * 后端 `verdict` → 语气色（0.11.5 / W-32）。
 *
 * 走廊列表原来用 `riskTone(row.pMax)` 在前端**重算了一遍档位**，于是
 * 一条"观测档判不可飞、但概率只有 31%"的走廊在列表里显示成"留观"，
 * 而同一页的剖面头写"不可飞"——**同一件事两个来源**，正是项目纪律禁止的那种。
 *
 * 档位只有后端一个来源；前端只负责把三个档映射成颜色。
 */
export function verdictTone(verdict) {
  if (verdict === '不可飞') return 'danger'
  if (verdict === '需谨慎') return 'watch'
  if (verdict === '可飞') return 'ok'
  return 'unknown'
}

/** 概率 → 风险语义色。**与阈值写在一处**，界面不再各写一套 if。 */
export function riskTone(p) {
  if (typeof p !== 'number' || Number.isNaN(p)) return 'unknown'
  if (p >= 0.8) return 'danger'
  if (p >= 0.5) return 'watch'
  if (p >= 0.2) return 'info'
  return 'ok'
}

/** 概率 → 人话档位。与 `riskTone` 同一组阈值，避免"颜色说危险、文字说谨慎"。 */
export function riskLabel(p) {
  const tone = riskTone(p)
  return { danger: '不可飞', watch: '需谨慎', info: '留观', ok: '可飞', unknown: '无观测' }[tone]
}

/** 0.1234 → "12%"；null/undefined → "—"（**不把"没有数字"显示成 0%**）。 */
export function pct(value, digits = 0) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

// --- 判据行的一格值（0.11.16 / K-9）-------------------------------------------
//
// 后端从 0.11.1 起就给了 `display`（`≥ 9656 m（6+ 为下界）`），前端却一直自己拼
// `value + unit`，于是同一屏上判据行印「9656 m」、结论句印「≥ 9656 m」。
// METAR 的 `6+` 是"至少 6 英里"，9656 m 是**换算下界**，不是一次精确观测；
// 把它印成精确值，等于把"下限"读成"读数据"。
//
// 返回 `{text, lowerBound}`：`text` 直接可印，`lowerBound` 给样式留标记用的。
// 优先用后端的 `display`（单位与下界规则只有一份），没有才退回 `value+unit`。
export function criterionValueText(row) {
  const lowerBound = row?.lowerBound === true
  if (!row || row.value === null || row.value === undefined) return { text: '未取得', lowerBound }
  const display = typeof row.display === 'string' ? row.display.trim() : ''
  if (display) return { text: display, lowerBound }
  const unit = typeof row.unit === 'string' ? row.unit : ''
  return { text: `${row.value}${unit ? ' ' + unit : ''}`, lowerBound }
}

// 能见度一格（走廊列表 / 详情的 km 显示）。下界同样必须带出来，否则「9.7 km」
// 会被读成精确值。`visM` 缺失时返回空串 —— 不编「0 km」。
export function visibilityText(visM, lowerBound = false) {
  const metres = Number(visM)
  if (visM === null || visM === undefined || !Number.isFinite(metres)) return ''
  const prefix = lowerBound === true ? '≥' : ''
  // 1000 m 以下必须用米（与后端 `_vis_display` 同一条规则）：998 m 印成
  // 「1 km」会变成"满足 ≥1000 m"的样子，而判据恰恰是"<1000 m 即禁飞"。
  // 原来这里写 `Math.round(m/100)/10`，998 → 1 km —— 单位选择把一次正确的
  // 判定读成了一次错误的判定（M59：过滤阈值比显示精度更细时，屏幕上会出现
  // 自相矛盾的值）。
  if (metres < 1000) return `${prefix}${Math.round(metres)} m`
  return `${prefix}${(metres / 1000).toFixed(1)} km`
}

/** 小时索引 → 时钟文本（基准时刻 + h）。基准缺失时返回空串，不编一个时间。 */
export function hourLabel(baseIso, index) {
  // `new Date(null)` 是**合法**的（＝epoch 1970-01-01T00:00Z），所以先挡非字符串与非空串：
  // 否则"没有观测时刻"会被渲染成 1970 年的 00:00，而那种错误看起来只是一个正常时刻。
  if (typeof baseIso !== 'string' || baseIso.length < 8) return ''
  if (typeof index !== 'number' || !Number.isFinite(index)) return ''
  const at = new Date(baseIso)
  if (Number.isNaN(at.getTime())) return ''
  const t = new Date(at.getTime() + index * 3600 * 1000)
  return `${String(t.getUTCHours()).padStart(2, '0')}:00`
}

/** 置信度（0–1，离 0.5 越远越自信）→ 门限判定。0.65 是唯一门限，写在这里一次。 */
export const CONFIDENCE_GATE = 0.65
export function confidencePass(value) {
  return typeof value === 'number' && value >= CONFIDENCE_GATE
}

// ============================================================================
// 雾区影响圈（0.11.7 / B；0.11.8 从 CityTrafficMap.vue 搬到这里）
// ============================================================================
//
// 为什么在 runtime.js：这是**纯几何**，而纯几何必须能跑测试。它原来住在一个 .vue
// 里，于是"函数被写到 `</script>` 之后"这种事只能靠人眼发现（判据 0 条）。
//
// 半径不是"看着差不多"，是**判据阈值的派生量**：
//   rules-v1.json 的 banValue 1000 m  -> 6 km 深灰（BAN）
//                    warnValue 5000 m -> 12 km 浅灰（CAUTION）
// 这个映射不写在 rules 里（rules 是气象阈值，不是画图半径），所以由
// `frontend/tests/fogRings.test.mjs` 反向核对：配置里的阈值一改、档位名字变了，
// 测试必须红 —— 否则这两个常量会在无人察觉时变成"过期副本"。
// ---- 雾区影响圈（0.11.7 / B）------------------------------------------------
//
// 半径来源是**判据阈值**，不是"看着差不多"：
//   banValue 1000 m -> 6 km 深灰 ；warnValue 5000 m -> 12 km 浅灰
// 这两个数写在 FOG_RING_KM，改变它们等于改口径，要同步 rules-v1.json。
export const FOG_RING_KM = Object.freeze({ BAN: 6, CAUTION: 12 })

/**
 * **示意半径**（0.11.11 / G-1）。与 `FOG_RING_KM` 是两个东西，不要合并：
 *
 *   · `FOG_RING_KM`（6 / 12 km）来自 `config/rules-v1.json::visibilityM`，是**判据阈值**
 *     ——它决定"这站算禁飞还是偏低"，会进结论、进 KPI、进禁飞走廊计数；
 *   · `FOG_SIGN_KM`（60 / 36 km）是**画多大才看得见**的声明常量，只影响图形。
 *
 * 为什么要分开：0.11.9 那一版按判据阈值画圈，6 km 的圈落在东北三省全域视图里只有
 * 7–13 px —— 徽标写着"实测 4 站 · 最低 998 m"、KPI 写着 18 条禁飞，地图上却找不到雾
 * （0.11.10 复测靠在同帧开关图层做像素差分量出 60 px，等于没画）。那是**尺度**问题，
 * 不是数据问题。
 *
 * 放大半径**不会**让判据变松：判据仍按 6 / 12 km 算，圈只是"影响范围示意"。
 * 所以图例与图层说明里必须原样写出「半径 40 / 24 km 是声明常量，不是实测雾区边界」。
 */
export const FOG_SIGN_KM = Object.freeze({ BAN: 60, CAUTION: 36 })

/** 图层说明里那句话（唯一来源，图例、徽标、验收都读它）。 */
export const FOG_SIGN_NOTE = '按机场站的实测能见度画的影响范围示意，半径 60 / 36 km 是声明常量，'
  + '不是实测雾区边界。本案例无城市格点场，因此不产出雾区面。'

// 正 24 边形。用多边形而不是 MapLibre 的 circle 图层：circle 的半径单位是像素，
// 缩放时大小不变；而"雾区半径 6 km"是**地理距离**，必须随缩放变化。
export function fogRing(lat, lon, radiusKm, steps = 24) {
  const coords = []
  const dLat = radiusKm / 111.32
  const dLon = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180) || 1)
  for (let i = 0; i <= steps; i += 1) {
    const a = (i / steps) * Math.PI * 2
    coords.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)])
  }
  return coords
}

export function fogFeatureCollection(stations) {
  const features = []
  for (const s of Array.isArray(stations) ? stations : []) {
    // 只画"有实测且达到某一档"的站。CLEAR 的站不画 —— 那会让地图上
    // 出现一堆"雾区"，而它们恰恰是能见度良好的地方。
    const level = s.visLevel || (s.visM != null && s.visM <= 1000 ? 'BAN' : (s.visM != null && s.visM <= 5000 ? 'CAUTION' : 'CLEAR'))
    if (level !== 'BAN' && level !== 'CAUTION') continue
    if (typeof s.lat !== 'number' || typeof s.lon !== 'number') continue
    features.push({
      type: 'Feature',
      properties: {
        station: s.station,
        visM: s.visM,
        level,
        // 0.11.11（G-1）：圆心与一行标签随几何一起给出。
        // 地图的 style 里没有 `glyphs`，MapLibre 的 symbol 文字层不会渲染 ——
        // 中心标签只能走 HTML 覆盖层，而它需要**屏幕坐标**，所以圆心必须带上。
        center: [s.lon, s.lat],
        label: `${s.station} · ${Math.round(Number(s.visM))} m`,
        tier: level === 'BAN' ? '不可飞（示意）' : '需谨慎（示意）',
        title: `${s.station} 实测能见度 ${Math.round(s.visM)} m（${level === 'BAN' ? '低于禁飞阈值' : '偏低'}）· 圈为影响范围示意，非实测雾区边界`,
      },
      geometry: { type: 'Polygon', coordinates: [fogRing(s.lat, s.lon, FOG_SIGN_KM[level])] },
    })
  }
  return { type: 'FeatureCollection', features }
}

/**
 * 雾区圆圈的三层绘制定义（0.11.9）。
 *
 * **配色的来历（这一条是实测出来的，不是设计偏好）**：本项目底图是近黑（`#0b1220`），
 * 而 0.11.7 那一版用"深灰 `#4A5568` 描边 + 30% 黑灰填充"。在 53 条走廊的全域视图下，
 * 6 km / 12 km 的圈只有十几像素宽，深灰压在近黑上等于**看不见** —— 界面上徽标写着
 * "实测 4 站 · 最低 998 m"、KPI 写着 18 条禁飞，地图上却找不到雾。
 * 那是**对比度**问题，不是数据问题：全链路（`stationVisibility` → 圈几何 → 徽标 →
 * 定位按钮）当时都是通的。
 *
 * 所以两档仍是"深灰/浅灰"的语义（差的那档更亮、实线；轻的那档偏灰、虚线），
 * 但亮度按**深色底图**重新标定：`#D7DEE8` / `#9AA4B2`，填充降到 18%/12%
 * （填充只用来暗示范围，读的是描边）。
 *
 * 另外三层分档用 `filter` 拆开、dasharray 给常量：这不是因为数据驱动会抛错
 * （MapLibre 26 的 `line-dasharray` property-type 是 `cross-faded-data-driven`，
 * 数据驱动是**允许**的），而是因为两档的**线宽和虚实都要分**，拆开之后每一层
 * 读起来就是一句话，不用在脑子里求值 `['case', …]`。
 */
export function fogRingLayers() {
  return [
    {
      id: 'fog-rings-fill', type: 'fill', source: 'fog-rings',
      paint: {
        // 0.11.11（G-1）：改成紫色系。理由不是好看 —— 原来的灰阶与"层状降水可穿越"
        // 那层淡紫、以及城市光环的淡紫在深色底图上互相借色，读者分不清哪个是雾。
        // 紫色在本项目的色表里只服务"低能见度"这一件事。
        // 0.11.11（G-1 第二版）：第一版把填充压到 28%，实测全域视图下像素差分只有
        // 1834（判据是 3000）—— 圈在，但"存在"与"看得见"是两件事。这里提到 38%/20%，
        // 并把紫色往亮处挪一档（`139,92,246`）：底图是近黑，暗紫在缩放后会糊成底色。
        'fill-color': ['match', ['get', 'level'], 'BAN', 'rgba(241,245,249,0.30)', 'rgba(203,213,225,0.18)'],
        'fill-outline-color': 'rgba(0,0,0,0)',
      },
    },
    {
      id: 'fog-rings-ban', type: 'line', source: 'fog-rings',
      filter: ['==', ['get', 'level'], 'BAN'],
      paint: { 'line-color': '#FFFFFF', 'line-width': 4, 'line-opacity': 1, 'line-dasharray': [1, 0] },
    },
    {
      id: 'fog-rings-caution', type: 'line', source: 'fog-rings',
      filter: ['==', ['get', 'level'], 'CAUTION'],
      paint: { 'line-color': '#E2E8F0', 'line-width': 2.2, 'line-opacity': 0.92, 'line-dasharray': [4, 3] },
    },
  ]
}
