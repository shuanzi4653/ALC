"""Local command journal and network-context evidence, separate from frozen plans."""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx
from . import service
from .spatial import position

JOURNAL=Path(__file__).resolve().parents[2]/'.run'/'traffic-operations.json'
LOCK=threading.Lock()
REASONS={'WEATHER_BLOCKED':'未来气象阻断路径','SEPARATION_OR_TIME_LIMIT':'间隔、续航或额外耗时限制','FINAL_WEATHER_CHECK_FAILED':'最终气象复核未通过','WEATHER_UNAVAILABLE':'气象不可用','WEATHER_DETOUR':'已规划气象绕行','CLEAR':'按分层走廊运行','NO_GEOMETRIC_PATH':'边界内无可用路线'}


def records(session_id):
    with LOCK:
        try: data=json.loads(JOURNAL.read_text(encoding='utf-8'))
        except FileNotFoundError: data=[]
    return [r for r in data if r['sessionId']==session_id]


def ready_session(seed,scenario):
    s=service.session(seed,scenario)
    if s['status']!='READY': raise ValueError('运行计划尚未就绪')
    return s


def command(seed,scenario,flight_id,minute,action):
    s=ready_session(seed,scenario)
    f=next((f for f in s['flights'] if f['id']==flight_id),None)
    if not f: raise ValueError('班次不存在')
    if f['status']!='SCHEDULED': raise ValueError('算法关闭的班次不能人工放行，请重新调度')
    if minute>=f['departureMinute']: raise ValueError('仅能操作尚未起飞的班次；已起飞或已过原时隙的班次请重新调度')
    if action not in ('SUSPEND','RESUME'): raise ValueError('未知操作')
    with LOCK:
        try: data=json.loads(JOURNAL.read_text(encoding='utf-8'))
        except FileNotFoundError: data=[]
        relevant=[r for r in data if r['sessionId']==s['sessionId'] and r['flightId']==flight_id]
        if relevant and minute<relevant[-1]['minute']: raise ValueError('请将时间轴移至该班次最近操作时刻之后，再执行操作')
        current=relevant[-1]['action'] if relevant else 'RESUME'
        if current==action: raise ValueError('该班次已经处于此状态')
        record=dict(id=uuid.uuid4().hex,sessionId=s['sessionId'],flightId=flight_id,action=action,minute=minute,
                    at=datetime.now(timezone.utc).isoformat(),name=f['name'])
        data.append(record);JOURNAL.parent.mkdir(parents=True,exist_ok=True)
        temp=JOURNAL.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(JOURNAL)
    return record


def explain(seed,scenario,flight_id,minute,question,cfg):
    s=ready_session(seed,scenario)
    evidence=[dict(id='source',title='数据来源',text='城市道路与建筑底图来自 OpenFreeMap / OpenStreetMap；班次、载荷和天气场均为模拟数据。'),
              dict(id='network',title='全域运行计划',text=f"36 个地级行政区，{s['stats']['carRoutes']} 条汽车走廊、{s['stats']['deliveryRoutes']} 条城区配送走廊，{s['stats']['accepted']} 个班次通过算法评估，{s['stats']['closed']} 个关闭。"),
              dict(id='constraints',title='硬约束',text='跨省仅省会连接；配送限制在本城服务区。水平250米、垂直60米模拟分离；升降不超过3米/秒；额外耗时超过60分钟关闭。人工不能越过算法关闭结果。'),
              dict(id='weather',title='气象状态',text=f"场景 {scenario}，种子 {seed}，推演第 {minute:.1f} 分钟。未来气象包络参与整个飞行时间段的绕行检查。")]
    if flight_id:
        f=next((f for f in s['flights'] if f['id']==flight_id),None)
        if not f: raise ValueError('班次不存在')
        suspended=False
        for r in records(s['sessionId']):
            if r['flightId']==flight_id and r['minute']<=minute: suspended=r['action']=='SUSPEND'
        text=f"班次 {f['id']}，{f['name']}，{'人工暂停' if suspended else REASONS.get(f['reason'],f['reason'])}。计划起飞第 {f['scheduledMinute']} 分钟，等待 {f['delayMinutes']} 分钟，绕行增时 {f['detourMinutes']} 分钟。"
        if f['points']: text+=f"放行第 {f['departureMinute']:.1f} 分钟，到达第 {f['arrivalMinute']:.1f} 分钟，最高 {f['maxAltitudeM']} 米。调度处理 {f['separationAction']}。"
        evidence.append(dict(id='flight',title='当前班次证据',text=text))
    by_id={e['id']:e for e in evidence};chosen=list(by_id);source='rule';error='NOT_CONFIGURED'
    if cfg.get('api_key'):
        try:
            with httpx.Client(timeout=httpx.Timeout(20,connect=5),trust_env=False) as client:
                response=client.post(cfg['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+cfg['api_key']},json={
                    'model':cfg.get('model','deepseek-chat'),'temperature':0,'max_tokens':300,'response_format':{'type':'json_object'},
                    'messages':[{'role':'system','content':'根据问题从证据中选取相关id，返回JSON {"evidenceIds":[...]}。不得生成新事实或修改放行结论。'},
                                {'role':'user','content':json.dumps(dict(question=question,evidence=evidence),ensure_ascii=False)}]})
                response.raise_for_status();ids=json.loads(response.json()['choices'][0]['message']['content'])['evidenceIds']
            if not isinstance(ids,list) or not 1<=len(ids)<=5 or any(not isinstance(i,str) or i not in by_id for i in ids):raise ValueError('invalid references')
            chosen=list(dict.fromkeys((['flight'] if flight_id else ['network'])+ids+['constraints','source']));source='deepseek';error=None
        except Exception as exc:
            from agent_tools import error_code
            error=error_code(exc)
    citations=[by_id[i] for i in chosen]
    return dict(sessionId=s['sessionId'],flightId=flight_id,minute=minute,source=source,errorCode=error,
                answer='\n'.join(e['text'] for e in citations),citations=citations)
