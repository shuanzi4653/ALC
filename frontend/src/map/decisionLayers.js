export const routeLabels = {DIRECT:'直接通行',DETOUR:'绕行',WAIT:'延后出发',CLOSED:'关闭',UNEVALUATED:'待评估'}
export const reasonLabels = {VALIDATED:'已通过时空约束检查',DATA_UNKNOWN:'数据不足，不能评估',ENDPOINT_OUTSIDE_REGION:'端点超出所选省界',ENDURANCE_EXCEEDED:'超过续航',FORECAST_HORIZON:'超出预测时域',DEADLINE_EXCEEDED:'无法按时完成',START_RESTRICTED:'出发时起点受限',NO_FEASIBLE_ROUTE:'候选图内无可行路线',PLANNER_TIMEOUT:'计算超时，未放行',DETOUR_OVER_60_MIN:'额外绕行超过60分钟',VERIFICATION_FAILED:'独立复核未通过'}
export const OPEN = new Set(['DIRECT','DETOUR','WAIT'])
// ECharts symbolRotate is counterclockwise; meteorological direction is clockwise FROM north.
export const windRotation = direction => (180 - direction + 360) % 360

function polygons(g) {
  if (g?.type === 'Polygon') return [g.coordinates]
  if (g?.type === 'MultiPolygon') return g.coordinates
  return []
}
function areaSeries(id, values, color, fill, dashed=false, z=2) {
  const records=values.flatMap(value=>polygons(value.geometry).map(rings=>({...value,rings})))
  return {id,type:'custom',coordinateSystem:'geo',z,silent:true,
    renderItem:(params,api)=>({type:'group',children:records[params.dataIndex].rings.map((ring,i)=>({type:'polygon',shape:{points:ring.map(p=>api.coord(p))},style:{fill:i?'#0c2036':fill,stroke:color,lineWidth:1.4,lineDash:dashed?[5,4]:null}}))}),data:records.map((_,i)=>[i])}
}

export function positionAt(candidate, minute) {
  if (!candidate || !OPEN.has(candidate.status) || !candidate.coords?.length) return null
  const times=candidate.arrivalMinutes
  if (minute<times[0] || minute>times.at(-1)) return null
  for(let i=1;i<times.length;i++) if(minute<=times[i]) {
    const f=(minute-times[i-1])/Math.max(.00001,times[i]-times[i-1])
    return candidate.coords[i-1].map((v,j)=>v+(candidate.coords[i][j]-v)*f)
  }
  return candidate.coords.at(-1)
}

export function decisionSeries(frame, decision, selectedId, enabled, minute, task) {
  const series=[]
  const cities=[{name:'沈阳',coord:[123.43,41.80]},{name:'长春',coord:[125.32,43.90]},{name:'哈尔滨',coord:[126.64,45.76]}]
  if(frame && frame.assessmentStatus==='VALID') {
    if(enabled.weather) {
      for(const [kind,color,fill] of [['PRECIPITATION','#53a9ff','rgba(61,143,255,.2)'],['THUNDER_PROBABILITY','#f7d36b','rgba(247,211,107,.15)'],['WIND','#77e2ca','rgba(119,226,202,.12)']]) {
        const cells=frame.cells.filter(c=>c.kind===kind&&c.value>0)
        series.push(areaSeries(kind,cells,color,fill,kind==='THUNDER_PROBABILITY'))
        series.push({id:`${kind}-centers`,type:'scatter',coordinateSystem:'geo',z:5,symbol:kind==='THUNDER_PROBABILITY'?'diamond':'circle',symbolSize:7,itemStyle:{color},
          label:{show:false},data:cells.map(c=>({name:`${c.cellId} · ${c.state} · ${c.value}`,value:c.center}))})
      }
    }
    if(enabled.risk) for(const [kind,color] of [['BAN','#ff756d'],['CAUTION','#edaa53']])
      series.push(areaSeries(`risk-${kind}`,frame.areas.filter(a=>a.zoneType===kind),color,kind==='BAN'?'rgba(230,80,70,.14)':'rgba(237,170,83,.08)',kind==='CAUTION',4))
    if(enabled.wind) series.push({id:'vectors',type:'scatter',coordinateSystem:'geo',z:3,silent:true,
      symbol:'path://M0,-6 L3,1 L1,0 L1,6 L-1,6 L-1,0 L-3,1 Z',symbolSize:[5,11],itemStyle:{color:'#68cdbd',opacity:.65},
      data:frame.wind.filter(p=>!cities.some(c=>Math.hypot(p.coord[0]-c.coord[0],p.coord[1]-c.coord[1])<.05)).map(p=>({value:p.coord,symbol:p.speed<=.2?'circle':undefined,symbolSize:p.speed<=.2?3:undefined,symbolRotate:windRotation(p.direction)}))})
  }
  if(decision && enabled.routes && frame?.assessmentStatus==='VALID') {
    const c=decision.candidates.find(x=>x.candidateId===selectedId)
    if(c && OPEN.has(c.status)) {
      series.push({id:'decision-route',type:'lines',coordinateSystem:'geo',polyline:true,z:8,lineStyle:{color:'#91e8ff',width:3,opacity:1},data:[{name:routeLabels[c.status],coords:c.coords}]})
      const point=positionAt(c,minute)
      if(point)series.push({id:'vehicle',type:'scatter',coordinateSystem:'geo',z:10,symbol:'triangle',symbolSize:12,itemStyle:{color:'#fff'},data:[{name:'该时刻预计位置',value:point}]})
    }
  }
  if(task){series.push({id:'cities',type:'scatter',coordinateSystem:'geo',z:6,symbolSize:4,itemStyle:{color:'#748f9b'},label:{show:true,position:'bottom',fontSize:10,color:'#819eac',formatter:p=>p.name},data:cities.map(c=>({name:c.name,value:c.coord}))});series.push({id:'task-points',type:'scatter',coordinateSystem:'geo',z:9,symbol:'pin',symbolSize:24,itemStyle:{color:'#d5efff'},label:{show:true,position:'right',color:'#fff',formatter:p=>p.name},data:[{name:'起点',value:task.from},{name:'终点',value:task.to}]})}
  return series
}
