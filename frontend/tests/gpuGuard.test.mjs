import test from 'node:test'
import assert from 'node:assert/strict'
import {probeGPU, gpuLabel, classifyRenderer, startFpsWatch} from '../src/traffic/gpu.js'
import {readFileSync} from 'node:fs'

// 三维护栏（V1.0.2 T19/T20）。
//
// 这一组钉的不是"三维好不好看"，而是**能不能进三维**。V1.0.1 两次把 Edge 主线程
// 拖到完全无响应，事后只能手动关标签页：那台机器跑在 SwiftShader（软件光栅化）上，
// WebGL 每帧的深度缓冲都在 CPU 上算。教训不是"三维太难"，是"进门之前没问一句"。
//
//   ① 软件渲染一律不进 —— 靠 getContext({failIfMajorPerformanceCaveat:true})
//      拿不到上下文来判，比字符串匹配权威；名字匹配只作补充；
//   ② 进了也要有看门狗 —— 连续 3 秒 <20 fps 自行降级，不让人在卡死里等；
//   ③ 降级要有出路 —— 必须有倾斜视图兜底，否则"不能看"等于"这页废了"。

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('software rasterizers are recognised by name', () => {
  const software = [
    'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)',
    'Google SwiftShader',
    'llvmpipe (LLVM 15.0.7, 256 bits)',
    'Microsoft Basic Render Driver',
    'Mesa OffScreen',
  ]
  for (const name of software) {
    assert.equal(classifyRenderer(name), true, `${name} 应判为软件渲染`)
  }
  const hardware = [
    'ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)',
    'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',
    'Apple M2 Pro',
    'AMD Radeon RX 7800 XT',
  ]
  for (const name of hardware) {
    assert.equal(classifyRenderer(name), false, `${name} 应判为硬件加速`)
  }
})

test('an empty renderer string is not silently treated as hardware', () => {
  // 拿不到名字时，判定必须靠 failIfMajorPerformanceCaveat 的上下文结果，
  // 不能因为"没匹配上"就放行。这里只钉住纯函数不会把空串说成硬件。
  assert.equal(classifyRenderer(''), false)
  // 而 probeGPU 在无 DOM 环境必须明确不可用，而不是默认 true
  const probe = probeGPU()
  assert.equal(probe.ok, false)
  assert.ok(probe.reason)
})

test('the probe is cached so a page never re-creates a GL context per render', () => {
  assert.equal(probeGPU(), probeGPU())
})

test('gpuLabel degrades gracefully when the renderer is hidden', () => {
  assert.equal(gpuLabel({renderer:'', cores:0, memory:0}), '未识别')
  const label = gpuLabel({renderer:'ANGLE (NVIDIA, RTX 4060, D3D11)', cores:16, memory:8})
  assert.match(label, /16 线程/)
  assert.match(label, /8 GB/)
})

test('the fps watchdog is a real function, not a placeholder', () => {
  assert.equal(typeof startFpsWatch, 'function')
})

test('the 3D component refuses to build a map on a failed probe', () => {
  const source = read('../src/components/traffic/NationGlobe.vue')
  // 探测必须在 new MlMap 之前，且失败直接 return —— 建了就是给主线程上刑
  const probeAt = source.indexOf('probeGPU()')
  const mapAt = source.indexOf('new MlMap(')
  assert.ok(probeAt > 0 && mapAt > probeAt, '能力探测必须排在创建地图之前')
  assert.match(source, /if\s*\(!gpu\.ok\)[\s\S]{0,240}return/, '探测不通过时不得继续建图')
  assert.match(source, /startFpsWatch\(/, '三维必须挂帧率看门狗')
  assert.match(source, /terrain/, '省/市层要挂 DEM 地形')
})

test('towers are culled per level instead of drawing all 319 cities', () => {
  const source = read('../src/components/traffic/NationGlobe.vue')
  // 全国层只留省会（rank 1），否则 319 个方块铺满全国变成棋盘
  assert.match(source, /nation:\{maxRank:1/, '全国层必须把体块限制在省会一级')
  assert.match(source, /maxRank/, '塔高/范围要按层级配置')
})

test('the panel falls back to the tilt view with a stated reason', () => {
  const panel = read('../src/components/traffic/NationPanel.vue')
  assert.match(panel, /if\s*\(!probe\.ok\)/, '面板在探测失败时必须拦下三维')
  assert.match(panel, /tilt\.value=true/, '拦下之后要有倾斜视图兜底')
  assert.match(panel, /liftNote/, '降级必须写明原因，不能静默失败')
  assert.match(panel, /onGlobeDegrade/, '看门狗回调要接上')
})

test('map paths are closed so no layer loses its last edge', () => {
  const map = read('../src/components/traffic/NationMap.vue')
  assert.match(map, /d\+='Z'/, 'toPath 必须显式闭合（fill 会封口，stroke 不会）')
})
