"""One authorized real call using synthetic decision evidence; never print configuration."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import DS_CFG
from decision_service import assess
from agent_tools import explain
from weather.engine import REGIONS

region = REGIONS['liaoning']
record = assess(dict(scenario='crossing', seed=42, origin='2026-09-13T00:00:00+08:00',
    task=dict(regionId='liaoning', **{'from':region['from'], 'to':region['to']},
              speedKmh=90, departureMinute=0, enduranceMinutes=100,
              latestArrivalMinute=180, workMinutes=5, bufferM=500)))
answer = explain(record['decisionId'], '为什么选择此方案？晚20分钟出发是否更好？', DS_CFG)
safe_result = {k: answer[k] for k in ('source', 'errorCode', 'decisionId', 'explanationId', 'latencyMs')}
safe_result['toolCount'] = len(answer['toolTrace'])
safe_result['citationCount'] = len(answer['citations'])
safe_result['citationsValid'] = all(c in record['evidence'] for c in answer['citations'])
out = Path(__file__).resolve().parents[2] / 'docs' / 'evaluation-v1' / 'ai-real-call.json'
out.write_text(json.dumps(safe_result, indent=2), encoding='utf-8')
print(json.dumps(safe_result, indent=2))
