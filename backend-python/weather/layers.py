"""Compatibility DTOs: a live point is not a regional weather field."""
from datetime import datetime, timedelta
import math
from .engine import WeatherWorld


def from_dashboard(dash):
    snapshot = dash['current']['snapshot']
    valid = datetime.fromisoformat(dash['obsTime'])
    is_sim = dash.get('effectiveSource') == 'sim'
    origin = datetime(2026, 1, 1, tzinfo=valid.tzinfo)
    world = WeatherWorld(42, dash.get('appliedScenario', 'clear'), origin.isoformat())
    frame = world.frame((valid - origin).total_seconds() / 60) if is_sim else None
    def layer(id, kind, status, data):
        return {'id':id, 'kind':kind, 'regionId':dash['regionId'], 'runId':dash['runId'], 'revision':dash['revision'],
                'source':'SIMULATION' if is_sim else 'POINT_OBSERVATION', 'isSimulated':is_sim, 'validTime':valid.isoformat(),
                'expiresAt':(valid + timedelta(minutes=20)).isoformat(), 'crs':'EPSG:4326', 'units':'m/s' if kind=='WIND' else 'mm/h' if kind=='PRECIPITATION' else 'probability_0_1' if kind=='THUNDER_PROBABILITY' else 'flight_level',
                'bbox':[118,38,136,54], 'geometry':None, 'data':data,
                'quality':{'spatialMeaning':'SIMULATED_FIELD' if is_sim else 'POINT_ONLY'}, 'status':status, 'errorCode':None}
    result=[]
    for id,kind,key in [('wind','WIND','windSpeed'),('precipitation','PRECIPITATION','precipMmh'),('thunder-probability','THUNDER_PROBABILITY','thunderProb')]:
        value=snapshot.get(key)
        status='NO_DATA' if value is None else 'ERROR' if not isinstance(value,(float,int)) or not math.isfinite(value) or value<0 or (key=='thunderProb' and value>1) else 'READY'
        if kind=='WIND' and (snapshot.get('windDeg') is None or not 0<=snapshot['windDeg']<360): status='ERROR'
        data={'value':value,'lon':snapshot.get('lon'),'lat':snapshot.get('lat'),'windSpeed':snapshot.get('windSpeed'),'windDeg':snapshot.get('windDeg'),'cells':[],'samples':[],'points':[]}
        if is_sim and status=='READY':
            if kind=='WIND':
                data['samples']=[{'name':'模拟风场采样','lon':p['coord'][0],'lat':p['coord'][1],'windSpeed':p['speed'],'windDeg':p['direction']} for p in frame['wind']]
            else:
                for c in frame['cells']:
                    if c['kind']!=kind or c['value']<=0: continue
                    g=c['geometry'];polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates'] if g['type']=='MultiPolygon' else []
                    for p in polys: data['cells'].append({'cellId':c['cellId'],'name':'移动气象单体','lon':c['center'][0],'lat':c['center'][1],'value':c['value'],'polygon':p[0]})
        elif not is_sim:
            data['points']=[{'name':'真实点观测',**{k:data[k] for k in ('lon','lat','windSpeed','windDeg')}}] if status=='READY' else []
        result.append(layer(id,kind,status,data))
    areas=[]
    if frame:
        for a in frame['areas']:
            g=a['geometry'];polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates'] if g['type']=='MultiPolygon' else []
            for p in polys: areas.append({'name':'气象运行限制','zoneType':a['zoneType'],'polygon':p[0],'sourceCellId':a['sourceCellId'],'reason':a['reason']})
    known=is_sim and all(l['status']=='READY' for l in result) and dash.get('dataStatus')=='FRESH'
    result.append(layer('risk-area','RISK_AREA','READY' if known else 'NO_DATA',{'areas':areas if known else [],'assessmentStatus':'VALID' if known else 'UNKNOWN','level':dash['current'].get('level'),'sfi':dash['current'].get('sfi')}))
    return result
