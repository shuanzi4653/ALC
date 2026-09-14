export const modeNames={CAR:'飞行汽车',DELIVERY:'无人机外卖'}
export function effectiveFlights(flights,operations,minute){
  const state=new Map()
  for(const op of operations)if(op.minute<=minute)state.set(op.flightId,op.action)
  return flights.map(f=>state.get(f.id)==='SUSPEND'?{...f,status:'CLOSED',reason:'MANUAL_SUSPEND',manuallySuspended:true,points:[]}:f)
}
export const reasonNames={MANUAL_SUSPEND:'人工暂停，原时隙保留',NO_GEOMETRIC_PATH:'边界内无可用路径',WEATHER_UNAVAILABLE:'气象数据中断，暂停放行',WEATHER_BLOCKED:'未来气象风险阻断路径',SEPARATION_OR_TIME_LIMIT:'间隔、续航或额外耗时超过限制',FINAL_WEATHER_CHECK_FAILED:'最终气象复核未通过',WEATHER_DETOUR:'已绕开未来风险范围',CLEAR:'按分层走廊运行'}
export const actionNames={NONE:'未放行',LAYERED:'按高度层运行',CROSSING_RAMP:'交汇区升降',ALTITUDE:'调整高度层',SLOT:'错时放行',ALTITUDE_AND_SLOT:'调高并错时'}
export function flightState(f,minute){
  if(f.status==='CLOSED')return 'CLOSED'
  if(minute<f.departureMinute)return minute>=f.scheduledMinute?'HOLD':'PENDING'
  return minute>=f.arrivalMinute?'ARRIVED':'AIRBORNE'
}
export function atTime(points,minute){
  if(!points?.length)return null
  if(minute<=points[0][3])return points[0].slice(0,3)
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i]
    if(minute<=b[3]){const f=(minute-a[3])/(b[3]-a[3]);return a.slice(0,3).map((v,k)=>v+(b[k]-v)*f)}
  }
  return points.at(-1).slice(0,3)
}
export function profile(points){
  if(!points?.length)return ''
  const start=points[0][3],duration=points.at(-1)[3]-start,max=Math.max(600,...points.map(p=>p[2]))
  return points.map(p=>`${10+280*(p[3]-start)/duration},${90-75*p[2]/max}`).join(' ')
}
