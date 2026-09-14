"""Finite scenario sensitivity, never a probability or calibrated uncertainty estimate."""
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weather.engine import WeatherWorld, REGIONS
from planning.router import evaluate, OPEN

rows = []
for rid, region in REGIONS.items():
    for seed in range(40, 45):
        for buffered in (False, True):
            task = dict(regionId=rid, **{'from':region['from'], 'to':region['to']}, speedKmh=90,
                        departureMinute=0, enduranceMinutes=100, latestArrivalMinute=180, workMinutes=5, bufferM=500)
            candidates = evaluate(WeatherWorld(seed, 'crossing', uncertainty=buffered), task)
            available = [c for c in candidates if c['status'] in OPEN]
            chosen = min(available, key=lambda c:c['arrivalMinute']) if available else candidates[0]
            rows.append(dict(region=rid, seed=seed, uncertaintyBufferM=800 if buffered else 0,
                             status=chosen['status'], arrivalMinute=chosen.get('arrivalMinute'),
                             extraMinutes=chosen.get('extraMinutes'), waitMinutes=chosen.get('waitMinutes')))
out = Path(__file__).resolve().parents[2] / 'docs' / 'evaluation-v1' / 'sensitivity.csv'
with out.open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
print(f'{len(rows)} sensitivity evaluations saved')
