"""End-to-end check of the huafeng adapter against the live platform.

Unit tests use stubs, so they prove the shape of the code and not that the
contract holds. This calls the real service with the sealed key and prints what
came back, which is the only way to know the adapter is wired right. Costs six
live calls against a 500/day budget.

沈阳 is included deliberately: it carried an active 大风蓝色预警 when the alert
payload was first captured, so it is the best available chance of exercising the
alert normaliser against real data.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import json
from pathlib import Path

os.environ['NO_PROXY'] = '127.0.0.1,localhost'

from traffic import cma_radar, huafeng  # noqa: E402
from traffic.catalog import cities  # noqa: E402

lookup = {item['id']: item for item in cities()}

for city_id in ('2-01', '3-01'):
    city = lookup.get(city_id)
    if not city:
        continue
    print(f'=== {city["name"]} ({city_id}) ===')
    result = huafeng.observe_city(city)
    if result['error']:
        print('  失败:', result['error'])
        continue
    observation = result['observation']
    print(f'  定位 Key {observation["locationKey"]}  观测 {observation["validAt"]}')
    print(f'  {observation["conditionText"]} {observation["temperatureC"]}C  '
          f'风 {observation["windSpeed10mMps"]}m/s 阵风 {observation["windGusts10mMps"]}m/s  '
          f'能见度 {observation["visibilityM"]}m 云底 {observation["ceilingM"]}m')
    print(f'  官方预警 {len(result["alerts"])} 条')
    for alert in result['alerts']:
        print(f'    [{alert["level"]}/{alert["alarmLevel"]}] {alert["headline"]}'
              f'  类型 {alert["type"]}  来源 {alert["source"]}')
        print(f'    影响区 {alert["areaNames"]}  生效 {alert["areas"][0]["startAt"]}'
              f' → {alert["areas"][0]["endAt"]}')
        print(f'    {alert["areas"][0]["text"][:70]}...')

print('\n=== 分钟降水（按坐标）===')
now = huafeng.nowcast(38.914, 121.615)
print(f'  {now["description"]}  有无降水 {now["hasPrecipitation"]}  '
      f'样本 {len(now["intensityCodes"])} × {now["intervalMinutes"]} 分钟')
print(f'  单位标注 {now["units"]["intensity"]}')

print('\n=== 额度与数据源状态 ===')
print('华风爱科:', json.dumps({k: v for k, v in huafeng.status().items()
                              if k in ('ready', 'tier', 'dailyLimit', 'quota')}, ensure_ascii=False))
print('  路由:', json.dumps(huafeng.ROUTES, ensure_ascii=False))
print('  无此产品:', json.dumps(huafeng.ABSENT_PRODUCTS, ensure_ascii=False))
radar = cma_radar.status()
print('雷达(CMA):', json.dumps({k: v for k, v in radar.items()
                              if k in ('ready', 'datasets')}, ensure_ascii=False),
      '| 缺凭据' if not radar['ready'] else '')
