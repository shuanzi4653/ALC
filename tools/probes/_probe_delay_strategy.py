"""验证「总延误最小」是否真的优于原来的「按延迟升序贪婪」。

这是用户 2026-10-01 第 2 条的核心改动，必须自证 —— 而且**不能靠 git 基线**：
该文件在工作区的演进远超仓库里最后一个提交（V1.2），`git diff` 里混着几十个版本
的差异，拿它当参照物只会得出错误结论（这正是 M-series 里"参照物过期"那一条）。

做法是**同一个天空、同一个种子，翻转一个具名常量**并排跑两种口径：

  greedy   0.9.22 及以前：从 delay=0 起按 5 分钟步进，第一个可行方案即采纳。
           它最小化的是 delay，不是总延误。
  minimal  当前：收集所有可行候选，按 `delay + 绕行增时` 取最小。

两种口径的可行性判据、天气、约束**完全相同**，唯一的差别是"在几个可行候选里选谁"，
所以任何差异都只能归因于选优本身。

跑法：
  python tools/probes/_probe_delay_strategy.py [seed]
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import service  # noqa: E402

OUT = ROOT / 'artifacts' / 'delay_strategy.json'


def measure(result):
    flights = result.get('flights') or []
    accepted = [f for f in flights if f.get('status') != 'CLOSED']
    delay = sum(float(f.get('delayMinutes') or 0) for f in accepted)
    detour = sum(float(f.get('detourMinutes') or 0) for f in accepted)
    slots = {f['id']: round(float(f.get('departureMinute') or 0), 3) for f in accepted}
    return {
        'accepted': len(accepted),
        'closed': len(flights) - len(accepted),
        'totalDelay': round(delay, 2),
        'totalDetour': round(detour, 2),
        'totalExtra': round(delay + detour, 2),
        'maxDelay': max((float(f.get('delayMinutes') or 0) for f in accepted), default=0.0),
        'slotTable': slots,
    }


def run(seed, strategy):
    original = service.DELAY_SELECTION_STRATEGY
    service.DELAY_SELECTION_STRATEGY = strategy
    try:
        return measure(service.simulate(seed=seed, scenario='live'))
    finally:
        service.DELAY_SELECTION_STRATEGY = original


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    print(f'延迟选优口径 A/B · seed={seed} · scenario=live')
    print('=' * 78)
    greedy = run(seed, 'greedy')
    print(f'[greedy ] 放行 {greedy["accepted"]:>5}  关闭 {greedy["closed"]:>4}'
          f'  延迟合计 {greedy["totalDelay"]:>10}  绕行合计 {greedy["totalDetour"]:>9}'
          f'  总延误 {greedy["totalExtra"]:>10}  最大延迟 {greedy["maxDelay"]:>5}')
    minimal = run(seed, 'minimal')
    print(f'[minimal] 放行 {minimal["accepted"]:>5}  关闭 {minimal["closed"]:>4}'
          f'  延迟合计 {minimal["totalDelay"]:>10}  绕行合计 {minimal["totalDetour"]:>9}'
          f'  总延误 {minimal["totalExtra"]:>10}  最大延迟 {minimal["maxDelay"]:>5}')
    print('=' * 78)

    delta = round(minimal['totalExtra'] - greedy['totalExtra'], 2)
    differing = [fid for fid, slot in minimal['slotTable'].items()
                 if fid in greedy['slotTable'] and greedy['slotTable'][fid] != slot]
    print(f'总延误变化：{greedy["totalExtra"]} → {minimal["totalExtra"]}（{delta:+.2f} 分钟）')
    print(f'延迟合计变化：{greedy["totalDelay"]} → {minimal["totalDelay"]}')
    print(f'绕行合计变化：{greedy["totalDetour"]} → {minimal["totalDetour"]}')
    print(f'最大延迟变化：{greedy["maxDelay"]} → {minimal["maxDelay"]}')
    print(f'放行变化：{minimal["accepted"] - greedy["accepted"]:+d}')
    print(f'时隙不同的班次：{len(differing)}')
    for fid in differing[:5]:
        print(f'   {fid}: {greedy["slotTable"][fid]} → {minimal["slotTable"][fid]} 分钟')

    payload = {'seed': seed,
               'greedy': {k: v for k, v in greedy.items() if k != 'slotTable'},
               'minimal': {k: v for k, v in minimal.items() if k != 'slotTable'},
               'totalExtraDelta': delta,
               'differingSlots': len(differing),
               'acceptedDelta': minimal['accepted'] - greedy['accepted']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已写入 {OUT.relative_to(ROOT)}')

    ok = delta <= 1e-6
    print(f'\nDELAY STRATEGY {"PASS" if ok else "FAIL"}'
          f'（总延误 {delta:+.2f} 分钟，放行 {payload["acceptedDelta"]:+d}，'
          f'时隙改变 {len(differing)} 架次）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
