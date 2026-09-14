import pytest
from traffic import operations


@pytest.fixture
def plan(monkeypatch, tmp_path):
    flight = dict(id='f1', name='local flight', status='SCHEDULED', departureMinute=30,
                  scheduledMinute=25, delayMinutes=5, detourMinutes=0, points=[], reason='CLEAR')
    data = dict(status='READY', sessionId='a'*24, flights=[flight],
                stats=dict(carRoutes=53, deliveryRoutes=108, accepted=1, closed=0))
    monkeypatch.setattr(operations.service, 'session', lambda *_: data)
    monkeypatch.setattr(operations, 'JOURNAL', tmp_path/'journal.json')
    return data


def test_suspend_resume_persist_without_mutating_frozen_plan(plan):
    operations.command(42, 'clear', 'f1', 10, 'SUSPEND')
    operations.command(42, 'clear', 'f1', 20, 'RESUME')
    assert [r['action'] for r in operations.records(plan['sessionId'])] == ['SUSPEND', 'RESUME']
    assert operations.records('b'*24) == []
    assert plan['flights'][0]['status'] == 'SCHEDULED'


def test_commands_fail_closed_and_reject_time_travel(plan):
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 30, 'SUSPEND')
    operations.command(42, 'clear', 'f1', 20, 'SUSPEND')
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 21, 'SUSPEND')
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 19, 'RESUME')
    plan['flights'][0]['status'] = 'CLOSED'
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 25, 'RESUME')


def test_evidence_uses_operation_time_and_exact_session(plan):
    operations.command(42, 'clear', 'f1', 20, 'SUSPEND')
    before = operations.explain(42, 'clear', 'f1', 19, 'why', {})
    after = operations.explain(42, 'clear', 'f1', 21, 'why', {})
    assert '人工暂停' not in before['answer']
    assert '人工暂停' in after['answer']
    assert after['sessionId'] == plan['sessionId']
    assert after['source'] == 'rule'
    assert after['minute'] == 21
