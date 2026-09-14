<script setup>
import {ref,onMounted} from 'vue'
import {requestJson} from '../api.js'
const data=ref(null),error=ref('')
const show=v=>v==null?'缺测':v
const clock=v=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—'
onMounted(async()=>{try{data.value=await requestJson('/api/observations')}catch(e){error.value=e.message}})
</script>
<template>
 <section class="work-panel regional-observations"><h2>三省独立观测台账</h2><p class="muted">NOAA ISD 中国境内气象站历史样本 · 2025年7月1日。每省独立质量状态；缺测不填零，不据此生成区域禁飞预报。</p><p v-if="error">{{error}}</p>
 <div class="station-cards"><article v-for="region in data?.regions||[]" :key="region.regionId"><h3>{{region.regionName}} · {{region.status==='HISTORICAL'?'历史观测':region.status==='ERROR'?'读取失败':'无数据'}}</h3><p v-for="s in region.stations">{{s.name}} / {{s.stationId}}<br>经纬度 {{s.coord.join(', ')}}</p>
 <template v-if="region.samples.length"><p>样本 {{region.samples.length}} 条 · 以下为首条</p><dl><dt>观测时间（北京时间）</dt><dd>{{clock(region.samples[0].observedAt)}}</dd><dt>风速 m/s</dt><dd>{{show(region.samples[0].windSpeedMps)}}</dd><dt>温度 ℃</dt><dd>{{show(region.samples[0].temperatureC)}}</dd><dt>能见度 m</dt><dd>{{show(region.samples[0].visibilityM)}}</dd><dt>累计降水 mm / 时段 h</dt><dd>{{show(region.samples[0].precipitationAccumulationMm)}} / {{show(region.samples[0].precipitationPeriodHours)}}</dd></dl><a :href="region.sourceUrl" target="_blank" rel="noopener noreferrer">官方原始数据</a></template>
 <p class="muted">雷暴概率：无数据 · 区域预报：未接入</p></article></div></section>
</template>
<style scoped>
.regional-observations{margin:14px 0}.station-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.station-cards article{padding:14px;border:1px solid #294657;border-radius:8px;line-height:1.8;overflow-wrap:anywhere}.station-cards h3{font-size:14px;color:#a6d6c9}.station-cards p{font-size:12px;color:#9ab3c4;margin:8px 0}dl{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px}dd{margin:0}a{color:#8dd1ca}@media(max-width:900px){.station-cards{grid-template-columns:1fr}}
</style>
