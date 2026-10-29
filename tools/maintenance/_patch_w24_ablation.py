# -*- coding: utf-8 -*-
"""W-24（0.11.4）：给反事实加一层**可开关的消融**，让四层各自的贡献能被真跑出来。

为什么先加开关而不是先做表：四行消融表里只有第一行是现成的，其余三行要
"去掉某一层再跑"。没有开关时，那三行只能靠推导写 —— 而推导出来的数字放在
答辩的表格里，就是一张看起来有出处、其实没人跑过的表。**宁可这一轮交白卷，
不交一张假表。**

开关（`?ablate=obs|prob|loss`）：
  obs  —— 去掉观测档：`obs_ban` 恒 False（回到 0.11.2 的"只看未来概率"）
  prob —— 去掉概率层：`p_unsafe` 不参与暴露判定与改判
  loss —— 去掉期望损失决策：退化成"p≥0.5 一律延误"的一刀切
"""
from pathlib import Path

V2 = Path(__file__).resolve().parents[2] / 'backend-python' / 'traffic' / 'v2.py'
MAIN = Path(__file__).resolve().parents[2] / 'backend-python' / 'main.py'

text = V2.read_text(encoding='utf-8')

old_sig = """def counterfactual(seed: int = 42, scenario: str = 'live', policy: str = 'balanced',
                   case_id: Optional[str] = None) -> Dict[str, Any]:"""
new_sig = """def counterfactual(seed: int = 42, scenario: str = 'live', policy: str = 'balanced',
                   case_id: Optional[str] = None,
                   ablate: str = '') -> Dict[str, Any]:
    \"\"\"`ablate` 是**消融开关**（0.11.4 / W-24），只用于生成消融表。

    它不是给业务用的：`ablate` 一旦非空，返回里的 `ablation` 会写明关掉了哪一层，
    页面据此必须打标（"这是消融实验，不是本系统的结论"）。
    允许值见 `main.py` 的 pattern；未知值一律当空串（不做任何消融）。
    \"\"\""""
if old_sig not in text:
    raise SystemExit('counterfactual 签名锚点不存在')
text = text.replace(old_sig, new_sig, 1)

# 在归零变量处加消融开关的解析
old_vars = "    exposure_a = exposure_b = 0\n    cancelled = delayed = rerouted = 0"
new_vars = """    # 消融开关：三个布尔量，默认全开（= 完整系统）
    use_obs = ablate != 'obs'
    use_prob = ablate != 'prob'
    use_loss = ablate != 'loss'
    exposure_a = exposure_b = 0
    cancelled = delayed = rerouted = 0"""
if old_vars not in text:
    raise SystemExit('归零变量锚点不存在')
text = text.replace(old_vars, new_vars, 1)

# 观测档可被关掉
old_obs = "        obs_ban = _nearest_observation_level(route, field_payload) == 'BAN'"
new_obs = ("        obs_ban = use_obs and _nearest_observation_level(route, field_payload) == 'BAN'")
if old_obs not in text:
    raise SystemExit('obs_ban 锚点不存在')
text = text.replace(old_obs, new_obs, 1)

# 概率层可被关掉（暴露判定与改判条件都要一起关，否则只关一半）
old_ban = "        ban_hit = obs_ban or p_unsafe >= 0.8"
new_ban = ("        ban_hit = obs_ban or (use_prob and p_unsafe >= 0.8)\n"
           "        prob_change = use_prob and confidence >= 0.65 and p_unsafe >= 0.5")
if old_ban not in text:
    raise SystemExit('ban_hit 锚点不存在')
text = text.replace(old_ban, new_ban, 1)

old_cond = "        if obs_ban or (fused >= 1 and confidence >= 0.65 and p_unsafe >= 0.5):"
new_cond = "        if obs_ban or (fused >= 1 and prob_change):"
if old_cond not in text:
    raise SystemExit('改判条件锚点不存在')
text = text.replace(old_cond, new_cond, 1)

# 决策层可被换成"一刀切"
old_dec = ("            decision = _decision(p_unsafe, None, best_alt[1] if best_alt else None, params,\n"
           "                                 observed_ban=obs_ban)")
new_dec = ("            if use_loss:\n"
           "                decision = _decision(p_unsafe, None, best_alt[1] if best_alt else None, params,\n"
           "                                     observed_ban=obs_ban)\n"
           "            else:\n"
           "                # 消融：去掉期望损失，退化成\"概率过 0.5 一律延误\"。\n"
           "                # 这条不是简化，是**另一种决策**：它不看绕飞成本、不看取消代价。\n"
           "                decision = {'chosen': 'DELAY', 'losses': {}, 'eligible': ['DELAY'],\n"
           "                            'excluded': {'LOSS_MODEL': '本轮为消融实验，期望损失未参与'},\n"
           "                            'delayMinutes': DELAY_STEP_MIN}")
if old_dec not in text:
    raise SystemExit('decision 调用锚点不存在')
text = text.replace(old_dec, new_dec, 1)

# 返回里带上消融标记
old_ret = "        'case': traffic_cases.describe(case_id) if case_id else None,"
new_ret = ("        'case': traffic_cases.describe(case_id) if case_id else None,\n"
           "        'ablation': ({'disabled': ablate,\n"
           "                     'label': {'obs': '去掉观测档', 'prob': '去掉概率层',\n"
           "                               'loss': '去掉期望损失决策'}.get(ablate, '')}\n"
           "                     if ablate else None),")
if old_ret not in text:
    raise SystemExit('返回 case 锚点不存在')
text = text.replace(old_ret, new_ret, 1)

V2.write_text(text, encoding='utf-8')
print('v2.py 消融开关已加')

# ---- main.py 路由参数 ----
main = MAIN.read_text(encoding='utf-8')
old_route = """                              case: str = Query('')):
    from traffic import v2 as traffic_v2
    return traffic_v2.counterfactual(seed=seed, scenario=scenario, policy=policy,
                                     case_id=case or None)"""
new_route = """                              case: str = Query(''),
                              ablate: str = Query('', pattern='^(obs|prob|loss)$')):
    from traffic import v2 as traffic_v2
    return traffic_v2.counterfactual(seed=seed, scenario=scenario, policy=policy,
                                     case_id=case or None, ablate=ablate)"""
if old_route not in main:
    raise SystemExit('counterfactual 路由锚点不存在')
main = main.replace(old_route, new_route, 1)
MAIN.write_text(main, encoding='utf-8')
print('main.py 路由已加 ablate')
