"""延迟预算 A/B：60 分钟 vs 120 分钟，以及"总延误最小"选优的效果。

用户 2026-10-01 的要求（第 2 条）：
  「我要求尽可能不要做禁飞处理，可以用延迟起飞来安排，即延迟多长时间起飞，
    而不是直接关闭。」
以及选定的口径：「延迟与绕行取**总延误最小**」，上限 **120 分钟**。

这个探针要回答三个可证伪的问题，同一个天空下：

  Q1 把 `maxExtraMinutes` 从 60 提到 120，关闭数降了多少？被救回来的班次
     拿到的是**延迟**还是**绕行**？
  Q2 关闭原因的结构怎么变？（`WEATHER_BLOCKED` 应该显著下降，其他原因不动）
  Q3 总延误口径下，平均延误有没有失控？（救回来的班次成本必须被看见，
     否则"关闭少了"可以靠把飞机都推迟两小时换来，那不是改善）

改的是**配置**而不是代码分支：两个臂都用当前（总延误最小）的规划器，
只翻 `maxExtraMinutes`。这样对比的是"预算"，不是"两套规划器"。

跑法：
  python tools/probes/_probe_delay_budget_ab.py [seed]
"""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import service, weather_control  # noqa: E402

PROFILE_FILE = ROOT / 'backend-python' / 'data' / 'traffic' / 'aircraft-profiles.json'
OUT = ROOT / 'artifacts' / 'delay_budget_ab.json'

BUDGETS = (60, 120)


def _patch_budget(budget):
    """Rewrite the separation budget in-process.

    ``service.profiles()`` is wrapped in ``@lru_cache(maxsize=1)``. Rewriting the
    file without clearing that cache makes both arms read the *same* value, which
    turns the A/B into a comparison of one thing against itself — it will report
    "no difference" no matter what the budget is. That mistake was made once while
    building this probe (both arms returned the pre-existing 7031/729 plan), so
    the clear is not optional.
    """
    original = PROFILE_FILE.read_text(encoding='utf-8')
    data = json.loads(original)
    data['separation']['maxExtraMinutes'] = budget
    PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    service.profiles.cache_clear()
    return original


def _run(seed, scenario='live', weather_mode='virtual'):
    result = service.simulate(seed=seed, scenario=scenario, weather_mode=weather_mode)
    stats = dict(result.get('stats') or {})
    flights = result.get('flights') or []
    closed = [f for f in flights if f.get('status') == 'CLOSED']
    accepted = [f for f in flights if f.get('status') != 'CLOSED']
    delays = [float(f.get('delayMinutes') or 0) for f in accepted]
    detours = [float(f.get('detourMinutes') or 0) for f in accepted]
    reasons = {}
    for f in closed:
        reasons[f.get('reason') or 'UNKNOWN'] = reasons.get(f.get('reason') or 'UNKNOWN', 0) + 1
    return {
        'stats': stats,
        'total': len(flights),
        'closed': len(closed),
        'accepted': len(accepted),
        'closedReasons': reasons,
        'delayed': sum(1 for d in delays if d > 0),
        'detoured': sum(1 for d in detours if d > 0.5),
        # 总延误：地面等待 + 绕行增时。与规划器内部选优用的是同一口径。
        'totalExtraMinutes': round(sum(delays) + sum(detours), 1),
        'totalDelayMinutes': round(sum(delays), 1),
        'totalDetourMinutes': round(sum(detours), 1),
        'maxDelayMinutes': max(delays) if delays else 0.0,
        'meanExtraWhenAffected': round(
            sum(d + t for d, t in zip(delays, detours) if d or t) / max(1, sum(1 for d, t in zip(delays, detours) if d or t)), 2),
    }


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    mode = sys.argv[2] if len(sys.argv) > 2 else 'virtual'
    print(f'延迟预算 A/B · seed={seed} · scenario=live · 气象模式={mode}')
    print('=' * 72)
    previous_mode = weather_control.mode()
    weather_control.set_mode(mode)
    arms = {}
    original = PROFILE_FILE.read_text(encoding='utf-8')
    try:
        for budget in BUDGETS:
            _patch_budget(budget)
            arm = _run(seed, weather_mode=mode)
            arms[budget] = arm
            print(f'[{budget:>3} 分钟] 关闭 {arm["closed"]:>5}  放行 {arm["accepted"]:>5}'
                  f'  延迟 {arm["delayed"]:>5}  绕行 {arm["detoured"]:>5}'
                  f'  总延误 {arm["totalExtraMinutes"]:>9} 分钟  最大延迟 {arm["maxDelayMinutes"]:>5}')
    finally:
        weather_control.set_mode(previous_mode)
        PROFILE_FILE.write_text(original, encoding='utf-8')
        service.profiles.cache_clear()

    lo, hi = arms[BUDGETS[0]], arms[BUDGETS[1]]
    print('=' * 72)
    saved = lo['closed'] - hi['closed']
    print(f'救回班次：{saved}（{lo["closed"]} → {hi["closed"]}）')
    print(f'放行变化：{hi["accepted"] - lo["accepted"]:+d}')
    print(f'总延误变化：{lo["totalExtraMinutes"]} → {hi["totalExtraMinutes"]} 分钟 '
          f'（{hi["totalExtraMinutes"] - lo["totalExtraMinutes"]:+.1f}）')
    print(f'平均受影响增时：{lo["meanExtraWhenAffected"]} → {hi["meanExtraWhenAffected"]} 分钟')
    print(f'最大延迟：{lo["maxDelayMinutes"]} → {hi["maxDelayMinutes"]} 分钟')
    print('\n关闭原因对比（仅列有差别的）：')
    keys = sorted(set(lo['closedReasons']) | set(hi['closedReasons']))
    for key in keys:
        a, b = lo['closedReasons'].get(key, 0), hi['closedReasons'].get(key, 0)
        mark = '' if a == b else '  <-- 变化'
        print(f'  {key:<44} {a:>5} → {b:>5}{mark}')

    payload = {'seed': seed, 'scenario': 'live', 'weatherMode': mode, 'budgets': arms,
               'saved': saved,
               'totalExtraDelta': round(hi['totalExtraMinutes'] - lo['totalExtraMinutes'], 1),
               'meanExtraDelta': round(hi['meanExtraWhenAffected'] - lo['meanExtraWhenAffected'], 2)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已写入 {OUT.relative_to(ROOT)}')

    # 断言：预算翻倍**必须**减少关闭，否则第 2 条的改动没有效果，不该被报告为成功。
    # 注意这只在虚拟气象下成立 —— 实测气象下最大延迟远低于 60 分钟，预算不是约束，
    # 两个臂会给出完全相同的计划（实测 2026-10-01，seed 42：两臂都是 119 关闭）。
    # 一个"没有差别"的 A/B 不是通过，而是**探针选错了场景**，探针自己要说出来。
    ok = saved > 0
    if not ok:
        print('[NOTE] 两个臂完全一致 —— 在该气象模式下延迟预算不是约束。'
              '这不构成"通过"，请改用 virtual 模式重跑。')
    print(f'\nDELAY BUDGET A/B {"PASS" if ok else "FAIL"}（救回 {saved} 架次）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
