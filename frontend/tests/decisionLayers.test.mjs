import test from 'node:test'
import assert from 'node:assert/strict'
import {decisionSeries,positionAt,windRotation} from '../src/map/decisionLayers.js'
import {buildRouteSeries,buildWeatherSeries} from '../src/map/layerRenderers.js'
const candidate={candidateId:'c',status:'DETOUR',coords:[[1,1],[2,3],[4,4]],arrivalMinutes:[0,10,20]}
test('任务路线保留全部拐点，按时间计算位置',()=>{
 const series=decisionSeries({assessmentStatus:'VALID'},{candidates:[candidate]},'c',{routes:true},5,null)
 assert.equal(series[0].polyline,true)
 assert.deepEqual(series[0].data[0].coords,candidate.coords)
 assert.deepEqual(positionAt(candidate,5),[1.5,2])
 assert.equal(positionAt(candidate,21),null)
})
test('关闭及待评估不产生路线或动画',()=>{
 for(const status of ['CLOSED','UNEVALUATED'])assert.deepEqual(decisionSeries(null,{candidates:[{...candidate,status}]},'c',{routes:true},5,null),[])
 assert.deepEqual(buildRouteSeries(null,'blue',true,null),[])
 assert.deepEqual(buildRouteSeries(null,'blue',true,{status:'EXPIRED',data:{areas:[]}}),[])
})
test('零降雨零雷暴不制造天气区域',()=>{
 const findLayer=kind=>({kind,status:'READY',data:{cells:[{lon:123,lat:42,value:0}]}})
 assert.deepEqual(buildWeatherSeries({findLayer,enabled:{precipitation:true,thunder:true}}),[])
})
test('缺少当前气象时撤下已有路线',()=>{
 assert.deepEqual(decisionSeries(null,{candidates:[candidate]},'c',{routes:true},5,null),[])
 assert.deepEqual(decisionSeries({assessmentStatus:'UNKNOWN'},{candidates:[candidate]},'c',{routes:true},5,null),[])
})
test('风符号从来向转换为去向，并适配逆时针旋转',()=>{
 assert.deepEqual([0,90,180,270].map(windRotation),[180,90,0,270])
})
