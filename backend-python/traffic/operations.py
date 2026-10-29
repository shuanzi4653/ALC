import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx
from . import service
from .spatial import position
import workspace as workspace_ctx

JOURNAL=Path(__file__).resolve().parents[2]/'.run'/'traffic-operations.json'
LOCK=threading.Lock()
KINDS={'MANUAL':'人工干预', 'SYSTEM':'系统决策', 'SOURCE':'数据源变更', 'EXPORT':'导出',
       'DISPOSAL':'事件处置'}
ACTION_LABELS={
    'SUSPEND':'人工暂停', 'RESUME':'恢复原时隙',
    'PLAN_BUILT':'运行计划构建完成', 'WEATHER_MODE':'气象通道切换', 'EXPORT':'导出运行日志',
    'ACKNOWLEDGED':'确认事件', 'IN_PROGRESS':'开始处置', 'HANDLED':'标记已处置',
    'REVIEWED':'复核处置',
}
DISPOSAL_STATES={'ACKNOWLEDGED':'已确认', 'IN_PROGRESS':'处置中',
                 'HANDLED':'已处置', 'REVIEWED':'已复核'}
DISPOSAL_ACTIONS={
    'DELAY':{'label':'延迟起飞', 'supported':False, 'state':'IN_PROGRESS',
             'reason':'本系统的改时隙在计划构建时写定（班次字段 delayMinutes 与 '
                      'groundWaitMinutes），运行时不支持对已生成的一个事件重新排时隙。'
                      '请重新推演计划，或改用「停止放行」并在调度台账恢复原时隙。'},
    'DETOUR':{'label':'改航绕飞', 'supported':False, 'state':'IN_PROGRESS',
              'reason':'航路成因与绕行几何在计划构建时写定（班次字段 routeBasis 与 '
                       'points），运行时不支持对已生成的一个事件重算航路。'
                       '请重新推演计划，或改用「停止放行」并在调度台账恢复原时隙。'},
    'SUSPEND':{'label':'停止放行', 'supported':True, 'state':'IN_PROGRESS',
               'reason':'对事件样本班次下达 SUSPEND，写回运行操作与决策日志。'},
    'ACKNOWLEDGED':{'label':'确认', 'supported':True, 'state':'ACKNOWLEDGED',
                    'reason':'确认该事件，尚未给出处置动作。'},
    'HANDLED':{'label':'标记已处置', 'supported':True, 'state':'HANDLED',
               'reason':'处置动作完成，等待复核。'},
    'REVIEWED':{'label':'复核', 'supported':True, 'state':'REVIEWED',
                'reason':'交班或复盘时的复核留痕。'},
}
REASONS={
    'WEATHER_BLOCKED':'未来气象风险阻断路径', 'SEPARATION_RESOURCE_OR_TIME_LIMIT':'已声明高度层、起降与交叉资源或额外耗时均无法满足',
    'FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED':'最终气象或边界复核未通过', 'WEATHER_UNAVAILABLE':'气象不可用',
    'WEATHER_DETOUR':'已规划气象绕行', 'CLEAR':'按已声明高度层与时隙运行', 'NO_GEOMETRIC_PATH':'边界内无可用路线',
    'TURN_RADIUS_OR_BOUNDARY_LIMIT':'转弯半径或边界限制', 'ALTITUDE_PROFILE_LIMIT':'高度剖面超过机型限制',
    'BEYOND_PLANNING_HORIZON':'超出 8 小时规划视界，无法在视界内完成',
    'STATIC_AIRSPACE_BLOCKED':'起降点位于固定管制区（未获批准不得进入）内，无法规划离场或进场路径',
}
ACTIONS={
    'NONE':'未放行', 'LAYERED_CORRIDOR':'按已声明高度层走廊运行', 'SLOT_AND_LAYER':'错时与高度层协同',
    'ALTERNATE_LAYER':'改用备用已声明高度层', 'GROUND_HOLD_AND_LAYER':'地面等待并改用高度层',
}

def _kind(row):
    return row.get('kind') or 'MANUAL'

def _read():
    try: return json.loads(JOURNAL.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError): return []

def _write(data):
    JOURNAL.parent.mkdir(parents=True,exist_ok=True)
    temp=JOURNAL.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(JOURNAL)

def records(session_id):
    with LOCK:
        data=_read()
    return [r for r in data if r.get('sessionId')==session_id and _kind(r)=='MANUAL']

def ready_session(seed,scenario):
    s=service.session(seed,scenario)
    if s['status']!='READY': raise ValueError('运行计划尚未就绪')
    return s

def command(seed,scenario,flight_id,minute,action,plan_revision=None,command_id=None):
    s=ready_session(seed,scenario)
    f=next((f for f in s['flights'] if f['id']==flight_id),None)
    if not f: raise ValueError('班次不存在')
    if plan_revision and plan_revision != s.get('planRevision'):
        raise ValueError('计划版本已过期（409），请刷新当前调度计划后重试')
    if f['status']!='SCHEDULED': raise ValueError('算法关闭的班次不能人工放行，请重新调度')
    if minute>=f['departureMinute']: raise ValueError('仅能操作尚未起飞的班次；已起飞或已过原时隙的班次请重新调度')
    if action not in ('SUSPEND','RESUME'): raise ValueError('未知操作')
    with LOCK:
        try: data=json.loads(JOURNAL.read_text(encoding='utf-8'))
        except FileNotFoundError: data=[]
        if command_id:
            duplicate=next((r for r in data if r.get('commandId')==command_id and r.get('sessionId')==s['sessionId']),None)
            if duplicate: return {**duplicate,'idempotent':True}
        relevant=[r for r in data
                  if r.get('sessionId')==s['sessionId'] and _kind(r)=='MANUAL'
                  and r.get('flightId')==flight_id]
        if relevant and minute<relevant[-1]['minute']: raise ValueError('请将时间轴移至该班次最近操作时刻之后，再执行操作')
        current=relevant[-1]['action'] if relevant else 'RESUME'
        if current==action: raise ValueError('该班次已经处于此状态')
        record=dict(id=uuid.uuid4().hex,kind='MANUAL',commandId=command_id or uuid.uuid4().hex,sessionId=s['sessionId'],flightId=flight_id,
                    action=action,minute=minute,at=datetime.now(timezone.utc).isoformat(),name=f['name'],
                    planRevision=s.get('planRevision'),plannedReleaseAt=f.get('plannedReleaseAt'))
        data.append(record);JOURNAL.parent.mkdir(parents=True,exist_ok=True)
        temp=JOURNAL.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(JOURNAL)
    return record

class EvidenceVeto(ValueError):
    pass

def _present(row):
    kind=_kind(row);action=row.get('action')
    disposal_action=row.get('disposalAction')
    return dict(id=row.get('id'),at=row.get('at'),kind=kind,kindLabel=KINDS.get(kind,kind),
                action=action,actionLabel=ACTION_LABELS.get(action,action),
                disposalAction=disposal_action,
                disposalActionLabel=DISPOSAL_ACTIONS.get(disposal_action,{}).get('label'),
                sessionId=row.get('sessionId'),minute=row.get('minute'),flightId=row.get('flightId'),
                name=row.get('name'),planRevision=row.get('planRevision'),
                eventKey=row.get('eventKey'),actor=row.get('actor'),
                detail=row.get('detail') or '')

def journal(session_id):
    ws = workspace_ctx.current()
    with LOCK:
        data=_read()
    rows=[r for r in data
          if r.get('sessionId')==session_id
          or (r.get('sessionId') is None and (r.get('workspace') or '')==ws)]
    rows.sort(key=lambda r:(r.get('at') or '',r.get('id') or ''))
    return [_present(r) for r in rows]

def note_build(session):
    if not session or session.get('status')!='READY': return None
    session_id=session.get('sessionId');revision=session.get('planRevision')
    stats=session.get('stats') or {};closed=stats.get('closedByReason') or {}
    with LOCK:
        data=_read()
        if any(_kind(r)=='SYSTEM' and r.get('action')=='PLAN_BUILT'
               and r.get('sessionId')==session_id and r.get('planRevision')==revision for r in data):
            return None
        record=dict(id=uuid.uuid4().hex,kind='SYSTEM',action='PLAN_BUILT',sessionId=session_id,
                    planRevision=revision,fingerprint=session.get('fingerprint'),
                    at=datetime.now(timezone.utc).isoformat(),
                    detail='全网 %s 班 · 算法受理 %s · 关闭 %s · 气象绕行 %s · 天气成因关闭 %s'%(
                        stats.get('flights','—'),stats.get('accepted','—'),stats.get('closed','—'),
                        closed.get('WEATHER_DETOUR',0),closed.get('WEATHER_BLOCKED',0)))
        data.append(record);_write(data)
    return record

def note_source(mode,previous=None,actor=None,reason=None,workspace=None):
    text='气象通道 %s → %s'%(previous or '—',mode)
    if reason: text+='；原因：%s'%reason
    if actor: text+='；操作者 %s'%actor
    record=dict(id=uuid.uuid4().hex,kind='SOURCE',action='WEATHER_MODE',sessionId=None,
                workspace=(workspace if workspace is not None else workspace_ctx.current()),
                at=datetime.now(timezone.utc).isoformat(),mode=mode,previous=previous,
                actor=actor,reason=reason,detail=text)
    with LOCK:
        data=_read();data.append(record);_write(data)
    return record

def note_disposal(session_id,event_key,state,note=None,actor=None,action=None):
    if state not in DISPOSAL_STATES: raise ValueError('未知处置状态：%s'%state)
    label=DISPOSAL_STATES[state]
    action_label=DISPOSAL_ACTIONS.get(action,{}).get('label')
    text='%s（事件 %s）'%(label,event_key)
    if action_label: text='%s · %s（事件 %s）'%(label,action_label,event_key)
    if note: text+='；说明：%s'%note
    if actor: text+='；操作者 %s'%actor
    record=dict(id=uuid.uuid4().hex,kind='DISPOSAL',action=state,sessionId=session_id,
                eventKey=event_key,actor=actor,note=note,disposalAction=action,
                at=datetime.now(timezone.utc).isoformat(),detail=text)
    with LOCK:
        data=_read();data.append(record);_write(data)
    return record

def dispose(seed,scenario,event_key,action,flight_id=None,minute=None,
            plan_revision=None,note=None,actor=None,command_id=None):
    spec=DISPOSAL_ACTIONS.get(str(action or ''))
    if not spec: raise ValueError('未知处置动作：%s'%action)
    if not spec['supported']:
        return {'applied':False,'supported':False,'action':action,
                'label':spec['label'],'state':None,'reason':spec['reason'],
                'detail':'本系统不支持对该事件执行「%s」：%s'%(spec['label'],spec['reason'])}
    if action=='SUSPEND':
        if not flight_id: raise ValueError('停止放行需要给出该事件的样本班次')
        command(seed,scenario,flight_id,minute,action='SUSPEND',
                plan_revision=plan_revision,command_id=command_id)
    record=note_disposal(event_key=event_key,session_id=_session_id(seed,scenario),
                         state=spec['state'],note=note,actor=actor,action=action)
    return {'applied':True,'supported':True,'action':action,'label':spec['label'],
            'state':spec['state'],'record':record,
            'detail':'已执行「%s」，事件状态推进到「%s」。'%(spec['label'],
                                                          DISPOSAL_STATES[spec['state']])}

def _session_id(seed,scenario):
    return ready_session(seed,scenario).get('sessionId')

def note_export(session_id,fmt,rows):
    """导出一次写一行 `EXPORT`。导出本身由前端在本地生成，这里只留痕。"""
    record=dict(id=uuid.uuid4().hex,kind='EXPORT',action='EXPORT',sessionId=session_id,
                at=datetime.now(timezone.utc).isoformat(),
                detail='导出运行日志 · %s · %s 条'%(fmt,rows))
    with LOCK:
        data=_read();data.append(record);_write(data)
    return record

def explain(seed,scenario,flight_id,minute,question,cfg):
    s=ready_session(seed,scenario)
    layers=s.get('layerUsage') or {}
    layer_text='；'.join(f"{key} {value} 架次" for key,value in sorted(layers.items())) or '本轮无已放行班次'
    delivery=s.get('deliveryPlan') or {}
    evidence=[dict(id='source',title='数据来源',text='城市道路与建筑底图来自 OpenFreeMap / OpenStreetMap；交通运行是模拟数据，天气来源及质量状态随当前计划快照显示。'),
              dict(id='network',title='全域运行计划',text=f"36 个地级行政区，{s['stats']['carRoutes']} 条汽车走廊、{s['stats']['deliveryRoutes']} 条城区配送走廊，{s['stats']['accepted']} 个班次通过算法评估，{s['stats']['closed']} 个关闭。"),
              dict(id='constraints',title='硬约束',text='跨省仅省会连接；配送限制在本城服务区。水平250米、垂直60米模拟分离；机型高度上限、转弯半径、起降与交叉资源及额外耗时超过60分钟均参与关闭判断。人工不能越过算法关闭结果。'),
              dict(id='layers',title='高度层分配',text=f"只使用机型已声明的高度层（{layer_text}），冲突以换层、时隙或地面等待解决，不叠加高度。地面等待班次 {s['stats'].get('groundHolds',0)} 个，改用备用层 {s['stats'].get('alternateLayers',0)} 个。"),
              dict(id='delivery',title='城区配送',text=f"订单 {delivery.get('orders','—')} 单，送达 {delivery.get('delivered','—')} 单，取消 {delivery.get('cancelled','—')} 单，平均地面等待 {delivery.get('averageGroundWaitMinutes','—')} 分钟。订单、商家与载具均为模拟数据，电量为模型估计。"),
              dict(id='weather',title='气象状态',text=f"场景 {scenario}，数据快照编号 {seed}，推演第 {minute:.1f} 分钟。天气快照：{s.get('weatherSnapshot',{}).get('provider','NONE')}；本系统不合成气象数据，绕行检查只使用真实来源的几何（公开观测/模式估算与实测雷达）。")]
    if flight_id:
        f=next((f for f in s['flights'] if f['id']==flight_id),None)
        if not f: raise ValueError('班次不存在')
        suspended=False
        for r in records(s['sessionId']):
            if r['flightId']==flight_id and r['minute']<=minute: suspended=r['action']=='SUSPEND'
        text=f"班次 {f['id']}，{f['name']}，{'人工暂停' if suspended else REASONS.get(f['reason'],f['reason'])}。申请起飞 {f.get('requestedDepartureAt','—')}，计划放行 {f.get('plannedReleaseAt','—')}，地面等待 {f['delayMinutes']} 分钟，绕行增时 {f['detourMinutes']} 分钟。"
        if f['points']: text+=f"预计到达 {f.get('estimatedArrivalAt','—')}，分配高度层 {f.get('assignedLayerAglM','—')} 米 AGL，最高 {f['maxAltitudeM']} 米。调度处理 {ACTIONS.get(f['separationAction'],f['separationAction'])}，净空状态 {f.get('clearanceStatus','—')}。"
        if f.get('orderId'): text+=f"订单 {f['orderId']}，载具 {f.get('vehicleId','—')}，交机剩余电量 {f.get('energyPercentRemainingAtHandover','—')}%。"
        evidence.append(dict(id='flight',title='当前班次证据',text=text))
    by_id={e['id']:e for e in evidence};chosen=list(by_id);source='rule';error='NOT_CONFIGURED';veto=None;ai_ids=set()
    if cfg.get('api_key'):
        try:
            with httpx.Client(timeout=httpx.Timeout(20,connect=5),trust_env=False) as client:
                response=client.post(cfg['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+cfg['api_key']},json={
                    'model':cfg.get('model','deepseek-chat'),'temperature':0,'max_tokens':300,'response_format':{'type':'json_object'},
                    'messages':[{'role':'system','content':'根据问题从证据中选取相关id，返回JSON {"evidenceIds":[...]}。不得生成新事实或修改放行结论。'},
                                {'role':'user','content':json.dumps(dict(question=question,evidence=evidence),ensure_ascii=False)}]})
                response.raise_for_status();ids=json.loads(response.json()['choices'][0]['message']['content'])['evidenceIds']
            if not isinstance(ids,list) or not ids: raise EvidenceVeto('外部模型没有返回任何证据引用')
            if len(ids)>5: raise EvidenceVeto('外部模型返回了 %d 条引用，超过 5 条上限'%len(ids))
            unknown=[str(i) for i in ids if not isinstance(i,str) or i not in by_id]
            if unknown: raise EvidenceVeto('外部模型引用了证据集合里不存在的编号：'+'、'.join(unknown))
            ai_ids=set(ids)
            chosen=list(dict.fromkeys((['flight'] if flight_id else ['network'])+ids+['constraints','source']));source='deepseek';error=None
        except EvidenceVeto as exc:
            veto=str(exc);error='EVIDENCE_VETO'
        except Exception as exc:
            from agent_tools import error_code
            error=error_code(exc)
    if source=='deepseek': outcome='ACCEPTED'
    elif veto: outcome='VETOED'
    elif error=='NOT_CONFIGURED': outcome='NOT_CONFIGURED'
    else: outcome='UNAVAILABLE'
    citations=[]
    for key in chosen:
        item=dict(by_id[key]);item['origin']='AI' if key in ai_ids else 'RULE'
        item['originLabel']='外部模型选取' if key in ai_ids else '规则默认证据'
        citations.append(item)
    return dict(sessionId=s['sessionId'],flightId=flight_id,minute=minute,source=source,errorCode=error,
                vetoed=veto,answer='\n'.join(e['text'] for e in citations),citations=citations,
                ai=dict(used=source=='deepseek',outcome=outcome,
                        model=(cfg.get('model') or 'deepseek-chat') if cfg.get('api_key') else None,
                        vetoed=veto,errorCode=error,selected=sorted(ai_ids),available=sorted(by_id),
                        note='外部模型只能从本计划已有的证据里挑选引用编号；越出该集合即整条回答降级为规则证据，不得生成新事实、不得修改放行结论。'))
