"""Virtual channel, full time axis: is the painted red inside what routing avoids?

Three questions, one sweep:

1. **Does the painted ``ban`` sit inside the painted ``field``?** The planner
   avoids ``field``; the map paints ``ban`` as 禁止进入. If ``ban`` escapes
   ``field``, an aircraft can sit inside red paint while the planner is behaving
   correctly -- i.e. the map would be wrong, not the planner.
2. **Is the published geometry valid?** A self-intersecting polygon is what
   MapLibre renders as a filled artefact, and what makes any downstream
   ``difference`` raise instead of answer.
3. **When does the echo reach Jilin city?** The operator's screenshot is at
   ~126.5E 43.85N, so the minute where the paint covers that point is the minute
   the screenshot must have been taken at -- which is what tells us whether the
   plan on disk could possibly have avoided what is on screen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend-python'))

from shapely.geometry import Point, shape  # noqa: E402
from shapely.validation import make_valid  # noqa: E402

from traffic import service, weather_control  # noqa: E402

JILIN = Point(126.55, 43.85)


def main():
    weather_control.set_mode('virtual')
    print(f'{"min":>4} {"CONV km2":>9} {"banBox":<28} {"ban⊄field":>9} '
          f'{"valid":>10} {"Jilin in ban":>12}')
    for minute in range(0, 481, 30):
        frame = service.weather_frame(42, 'live', minute)
        region = frame['radar']['regions'][0]
        ban = shape(region['ban'])
        field = shape(region['field'])
        valid = ban.is_valid, field.is_valid
        outside = None
        if not ban.is_empty:
            clean_ban, clean_field = make_valid(ban), make_valid(field)
            escaped = clean_ban.difference(clean_field.buffer(1e-9))
            outside = round(escaped.area / clean_ban.area, 4)
        box = tuple(round(v, 2) for v in ban.bounds) if not ban.is_empty else None
        print(f'{minute:>4} {region["bands"]["CONVECTIVE"]["areaKm2"]:>9,.0f} '
              f'{str(box):<28} {str(outside):>9} {str(valid):>10} '
              f'{str(bool(not ban.is_empty and ban.covers(JILIN))):>12}')


if __name__ == '__main__':
    main()
