"""G-2 线上验收：虚拟通道下 radar.summary 是否跟着通道走。

用**独立工作区**（probe-g2），改完立刻切回 —— 不动页面正在看的那个工作区。
判据：summary.channel == watch.source；slotAgeMinutes is None；slot 带 SYNTHETIC@ 前缀。
"""
import json
import time
import urllib.request

BASE = 'https://tianchuang.shuanzi.site'
WS = 'probe-g2-0111'


def req(path, method='GET', body=None, role='admin'):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header('X-ALC-Workspace', WS)
    request.add_header('X-ALC-Operator', role)
    if data:
        request.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(request, timeout=60) as resp:
        raw = resp.read().decode()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw[:200]


def radar_of(payload):
    return (payload.get('radar') or {}), (payload.get('watch') or {})


def main():
    st, mode = req('/api/traffic/weather/mode')
    print('初始 mode =', mode.get('mode'), st)

    st, res = req('/api/traffic/weather/mode', 'POST', {'mode': 'virtual', 'actor': 'probe', 'reason': 'G-2 验收'})
    print('切虚拟   =', st, res.get('mode'), 'changed=', res.get('changed'))
    time.sleep(2)

    st, frame = req('/api/traffic/weather?seed=42&scenario=live&minute=60')
    radar = frame.get('radar') or {}
    summary = radar.get('summary') or {}
    watch = radar.get('watch') or {}
    print('\n--- 虚拟通道 ---')
    print('weatherMode          =', frame.get('weatherMode'))
    print('radar.mode           =', radar.get('mode'))
    print('radar.summary.channel=', summary.get('channel'))
    print('radar.watch.source   =', watch.get('source'))
    print('radar.summary.slot   =', summary.get('slot'))
    print('slotAgeMinutes       =', summary.get('slotAgeMinutes'))
    print('note                 =', (summary.get('note') or '')[:60])
    ok_virtual = (
        summary.get('channel') == 'SYNTHETIC_RADAR_CREF'
        and summary.get('channel') == watch.get('source')
        and summary.get('slotAgeMinutes') is None
        and str(summary.get('slot') or '').startswith('SYNTHETIC@')
    )
    print('VIRTUAL 判据         =', 'PASS' if ok_virtual else 'FAIL')

    time.sleep(2)
    st, res = req('/api/traffic/weather/mode', 'POST', {'mode': 'measured', 'actor': 'probe', 'reason': 'G-2 验收回滚'}, role='observer')
    print('\n切回实测 =', st, res.get('mode'), 'changed=', res.get('changed'))
    time.sleep(2)

    st, frame = req('/api/traffic/weather?seed=42&scenario=live&minute=60')
    radar = frame.get('radar') or {}
    summary = radar.get('summary') or {}
    print('\n--- 实测通道（回归） ---')
    print('radar.summary.channel=', summary.get('channel'))
    print('slot                 =', summary.get('slot'))
    print('slotAgeMinutes       =', summary.get('slotAgeMinutes'))
    print('note                 =', (summary.get('note') or '')[:60])
    # 实测侧的判据**不能要求 slotAgeMinutes 有值**：服务端取不到瓦片时（源站对
    # 数据中心出口整站 403，实测常态），summary 走 unavailable 分支，本来就没有时次。
    # 那条路上只要求 channel 仍是 CMA —— 它说的是"这条通道是谁"，不是"这一帧有没有"。
    ok_measured = summary.get('channel') == 'CMA_RADAR_TILES' and (
        summary.get('available') is False or summary.get('slotAgeMinutes') is not None
    )
    print('MEASURED 判据        =', 'PASS' if ok_measured else 'FAIL',
          '（available=%s）' % summary.get('available'))


if __name__ == '__main__':
    main()
