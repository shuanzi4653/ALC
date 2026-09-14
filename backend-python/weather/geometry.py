"""All geometric predicates use metres in a local azimuthal projection."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape, mapping, Point
from shapely.ops import transform, unary_union
from shapely import make_valid

BOUNDARY_FILE = Path(__file__).resolve().parents[1] / 'data' / 'northeast.geojson'
BOUNDARY_VERSION = hashlib.sha256(BOUNDARY_FILE.read_bytes()).hexdigest()[:16]
FEATURES = json.loads(BOUNDARY_FILE.read_text(encoding='utf-8'))['features']
FORWARD = Transformer.from_crs('EPSG:4326', '+proj=aeqd +lat_0=45 +lon_0=126 +datum=WGS84 +units=m', always_xy=True)
INVERSE = Transformer.from_crs(FORWARD.target_crs, 'EPSG:4326', always_xy=True)


def project(point):
    return FORWARD.transform(*point)


def unproject(point):
    return list(INVERSE.transform(*point))


@lru_cache(maxsize=8)
def boundary(region=None):
    geoms = [make_valid(transform(FORWARD.transform, shape(f['geometry']))) for f in FEATURES
             if region is None or f['properties']['name'] == region]
    if not geoms:
        raise ValueError('Unknown region')
    return unary_union(geoms)


def geojson(geom):
    return mapping(transform(INVERSE.transform, geom))


def inside(point, region=None):
    return boundary(region).covers(Point(project(point)))
