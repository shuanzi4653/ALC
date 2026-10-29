"""Which painted layer can produce the red the operator is looking at?

The screenshot shows one large warm-red surface with a dashed amber edge, and a
corridor line plus an aircraft inside it. Exactly one layer can look like that
(``radar-footprint`` with ``tier == BAN``), but a *risk cell* of ``kind == BAN``
paints the same hue, so colour alone cannot separate them.

This probe prints, for both weather channels, the area of every geometry the map
is handed, so the culprit is identified by number rather than by eye.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend-python'))

from shapely.geometry import shape  # noqa: E402

from traffic import service, weather_control  # noqa: E402


def area_km2(geometry):
    return geometry.area / 1e6 if geometry is not None and not geometry.is_empty else 0.0


def describe_frame(label, frame):
    cells = frame.get('cells') or []
    print(f'--- {label} ---')
    print(f'  available={frame.get("available")} provider={frame.get("provider")} '
          f'dataType={frame.get("dataType")} weatherMode={frame.get("weatherMode")}')
    print(f'  cells={len(cells)}')
    for cell in cells:
        print(f'    {cell.get("id")} kind={cell.get("kind")} '
              f'field={area_km2(shape(cell["field"])):,.0f} '
              f'ban={area_km2(shape(cell["ban"])):,.0f} '
              f'caution={area_km2(shape(cell["caution"])):,.0f} km2')
    radar = frame.get('radar') or {}
    regions = radar.get('regions') or []
    print(f'  radar available={radar.get("available")} mode={radar.get("mode")} '
          f'error={radar.get("error")} regions={len(regions)}')
    for region in regions:
        print(f'    {region.get("id")} synthetic={region.get("synthetic")} '
              f'slot={region.get("slot")} age={region.get("slotAgeMinutes")} '
              f'field={area_km2(shape(region["field"])):,.0f} '
              f'ban={area_km2(shape(region["ban"])):,.0f} '
              f'caution={area_km2(shape(region["caution"])):,.0f} km2 '
              f'bands={json.dumps(region.get("bands"), ensure_ascii=False)}')
    watch = radar.get('watch')
    print(f'  radar.watch area={area_km2(shape(watch["field"])) if watch else 0:,.0f} km2 '
          f'summary={json.dumps(radar.get("summary"), ensure_ascii=False)[:200]}')


def main():
    print(f'== current channel ==  virtual={weather_control.is_virtual()} '
          f'mode={weather_control.mode()}')
    for virtual in (False, True):
        weather_control.set_mode('virtual' if virtual else 'measured')
        for minute in (0, 120):
            frame = service.weather_frame(42, 'live', minute)
            describe_frame(f'{"VIRTUAL" if virtual else "MEASURED"} minute={minute}', frame)
    print('== cached plan ==')
    path = sorted(Path(service.STORE).glob('*.json'))[-1]
    plan = json.loads(path.read_text(encoding='utf-8'))
    print(' ', json.dumps(plan.get('radarAvoidance'), ensure_ascii=False)[:400])
    print(' ', json.dumps(plan.get('coverage'), ensure_ascii=False)[:300])


if __name__ == '__main__':
    main()
