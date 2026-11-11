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

// V1.0.5：三维视图整体下线（用户 2026-11-12：「地形和倾斜和三维删掉，对应的功能也删掉」）。
// 这一组原本钉的是"能不能安全地进三维"；组件删掉之后，判据反过来钉**不许悄悄加回来**——
// 材料里已经按"不用三维"写了，代码里若又长出入口，答辩现场会被问住。
test('三维视图已下线：组件删除、入口移除、无残留地形', () => {
  assert.throws(() => read('../src/components/traffic/NationGlobe.vue'), /ENOENT|no such file/i,
    'NationGlobe.vue 应已删除')
  const panel = read('../src/components/traffic/NationPanel.vue')
  assert.ok(!/threeD|toggle3d|onGlobeDegrade|probeGPU/.test(panel),
    '面板不应再有三维状态、回调或能力探测')
  assert.ok(!/terrainOn|toggleTilt|liftNote/.test(panel), '地形 / 倾斜入口应已移除')
  const map = read('../src/components/traffic/NationMap.vue')
  assert.ok(!/terrainTiles|terrainOn/.test(map), '地图不应再挂 DEM 地形图层')
  assert.ok(!/\btilt\b/.test(map), '地图不应再有倾斜（CSS 透视）分支')
})

// gpu.js 本身保留：城市地图（东北那套 maplibre 运行图）仍需要判断 WebGL 可用性。
// 这里只确认纯函数还在，避免"删三维时顺手把探测函数也删了"。
test('GPU 探测函数仍在（城市地图还在用）', () => {
  assert.equal(typeof probeGPU, 'function')
  assert.equal(typeof gpuLabel, 'function')
  assert.equal(typeof startFpsWatch, 'function')
})

test('map paths are closed so no layer loses its last edge', () => {
  const map = read('../src/components/traffic/NationMap.vue')
  assert.match(map, /d\+='Z'/, 'toPath 必须显式闭合（fill 会封口，stroke 不会）')
})
