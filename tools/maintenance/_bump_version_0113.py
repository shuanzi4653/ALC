# -*- coding: utf-8 -*-
"""0.11.3 版本落点（docs/NAMING.md §7：只递增第三位 z；文件带 -beta，界面不带）。

五处落点 + UA + README 标题，一次改完再核：
  VERSION / backend-java/pom.xml / frontend/package.json /
  frontend/package-lock.json（两处）/ backend-python/traffic/weather_sources.py
历史上漏过的就是 package-lock 的第二处与 UA —— 前者让 `npm ci` 报版本不一致，
后者让服务器日志里两个版本同时存在。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = '0.11.2'
NEW = '0.11.3'

targets = {
    'VERSION': [('0.11.2-beta', '0.11.3-beta')],
    'backend-java/pom.xml': [('<version>0.11.2-beta</version>', '<version>0.11.3-beta</version>')],
    'frontend/package.json': [('"version": "0.11.2-beta"', '"version": "0.11.3-beta"')],
    'frontend/package-lock.json': [('"version": "0.11.2-beta"', '"version": "0.11.3-beta"')],
    'backend-python/traffic/weather_sources.py': [
        ('tianchuang-alc/0.11.2 (low-altitude traffic research)',
         'tianchuang-alc/0.11.3 (low-altitude traffic research)')],
    'README.md': [('# 天窗智巡 · 低空交通协同运行管理系统 0.11.2（Beta）',
                   '# 天窗智巡 · 低空交通协同运行管理系统 0.11.3（Beta）')],
}

for relative, pairs in targets.items():
    path = ROOT / relative
    text = path.read_text(encoding='utf-8')
    hits = 0
    for old, new in pairs:
        count = text.count(old)
        if count == 0:
            raise SystemExit('%s 里找不到 %r —— 版本落点缺失，先查清再改' % (relative, old))
        text = text.replace(old, new)
        hits += count
    path.write_text(text, encoding='utf-8')
    print('%-46s %d 处' % (relative, hits))
print('done')
