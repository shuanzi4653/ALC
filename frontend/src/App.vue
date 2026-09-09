<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { store, initRealtime, postAction } from './api.js'
import PanelTop from './components/PanelTop.vue'
import PanelWeather from './components/PanelWeather.vue'
import PanelSfi from './components/PanelSfi.vue'
import PanelAlerts from './components/PanelAlerts.vue'
import PanelMap from './components/PanelMap.vue'
import PanelTracks from './components/PanelTracks.vue'
import PanelAgent from './components/PanelAgent.vue'
import PanelFeed from './components/PanelFeed.vue'
import PanelPush from './components/PanelPush.vue'

const stage = ref(null)

// 1920x1080 舞台等比缩放适配
function fit() {
  if (!stage.value) return
  const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
  stage.value.style.transform = `scale(${s})`
}
onMounted(() => {
  fit()
  window.addEventListener('resize', fit)
  initRealtime()
})
onUnmounted(() => window.removeEventListener('resize', fit))

async function switchScenario(key) {
  store.scenario = key
  try {
    const r = await postAction('/api/sim/switch?scenario=' + key)
    if (r && r.current) store.dash = r   // 后端已跑完新一轮，直接刷新页面数据
  } catch (e) { console.warn(e) }
}
async function runNow() {
  try {
    const r = await postAction('/api/monitor/run-now')
    if (r && r.current) store.dash = r
  } catch (e) { console.warn(e) }
}
</script>

<template>
  <div class="stage-wrap">
    <div ref="stage" class="stage">

      <!-- 预警弹窗 -->
      <div v-if="store.alertFlash" class="alert-flash"
           :class="{ warn: store.alertFlash.level === 'DANGER' }">
        <span class="close" @click="store.alertFlash = null">关闭 ×</span>
        <div style="font-size:16px;font-weight:700;margin-bottom:8px">
          {{ store.alertFlash.levelLabel }}预警 · {{ store.dash.region }}
        </div>
        {{ store.alertFlash.text }}
      </div>

      <!-- 顶部 -->
      <PanelTop class="top" />

      <!-- 左栏 -->
      <div class="left-col">
        <div class="panel">
          <div class="panel-hd">实时气象观测
            <span style="margin-left:auto" class="status-item">
              {{ store.dash.mode === 'live' ? '数据源：和风实时' : '数据源：模拟' }}
            </span>
          </div>
          <div class="panel-bd"><PanelWeather /></div>
        </div>
        <div class="panel">
          <div class="panel-hd">适飞指数（SFI）</div>
          <div class="panel-bd"><PanelSfi /></div>
        </div>
        <div class="panel">
          <div class="panel-hd">预警列表</div>
          <div class="panel-bd"><PanelAlerts /></div>
        </div>
      </div>

      <!-- 中栏地图 -->
      <div class="center-col panel">
        <div class="panel-hd">风险热力与航线态势
          <span class="scenario-bar" style="margin-left:auto" v-if="store.dash.mode !== 'live'">
            <button v-for="s in ['clear','wind','rain','storm']" :key="s"
                    class="btn" :class="{ active: store.scenario === s }"
                    @click="switchScenario(s)">
              {{ { clear:'晴好', wind:'大风', rain:'强降水', storm:'雷暴' }[s] }}
            </button>
            <button class="btn" @click="runNow">立即监测</button>
          </span>
        </div>
        <div class="panel-bd" style="padding:4px"><PanelMap /></div>
      </div>

      <!-- 右栏：双轨对比 + 推送渠道状态（一次看全） -->
      <div class="right-col">
        <div class="panel">
          <div class="panel-hd">双轨推演对比</div>
          <div class="panel-bd"><PanelTracks /></div>
        </div>
        <div class="panel">
          <div class="panel-hd">推送渠道状态
            <span style="margin-left:auto" class="status-item">实时送达明细</span>
          </div>
          <div class="panel-bd" style="display:flex"><PanelPush /></div>
        </div>
      </div>

      <!-- 底部：预警信息流 + 智能体问答 -->
      <div class="bottom">
        <div class="panel">
          <div class="panel-hd">预警信息流</div>
          <div class="panel-bd feed-list"><PanelFeed /></div>
        </div>
        <div class="panel">
          <div class="panel-hd">智能体问答</div>
          <div class="panel-bd" style="display:flex;padding:8px 14px"><PanelAgent /></div>
        </div>
      </div>

    </div>
  </div>
</template>
