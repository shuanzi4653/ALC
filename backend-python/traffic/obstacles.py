SOURCE_VERSION = 'no-local-dem-or-building-catalog-v1'

def evaluate(points, route_id):
    return {
        'routeId': route_id,
        'status': 'SIMULATION_ASSUMPTION_UNVERIFIED',
        'terrainCoverage': 'UNAVAILABLE',
        'buildingCoverage': 'UNAVAILABLE',
        'verticalDatum': 'AGL_ASSUMED_FLAT_REFERENCE',
        'message': '当前本地没有覆盖该航迹的 DEM 与建筑高度数据；该航迹仅通过模拟高度、边界、天气和四维间隔检查。',
    }
