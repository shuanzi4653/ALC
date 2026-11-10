# -*- coding: utf-8 -*-
"""边缘节点后端（`/api/edge/*`）的判据。

这些接口只做"记录与值守"，所以判据都是**不许假装**：
- 数据龄要服务端自己用 `frameTs` 算，不能采信节点自报的 `dataAgeMin`；
- 签名没配密钥就明说 `sigVerified=false`，不许默认通过；
- 帧不足 7 条要报 `shortfall`，不许补零；
- 没注册的节点上报要 403，不许静默落库。
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_service as edge  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(edge, 'DB', tmp_path / 'edge.sqlite3')
    monkeypatch.setenv('EDGE_ENABLED', '1')
    monkeypatch.delenv('EDGE_HMAC_SECRET', raising=False)
    return tmp_path / 'edge.sqlite3'


def _register(node='edge-sy-01', site='VP-1-01'):
    return edge.register({'node': node, 'siteId': site, 'fw': 'edge-1.0.1', 'hwRev': 'r3'})


def _report(node='edge-sy-01', seq=1, **overrides):
    payload = {
        'node': node, 'seq': seq, 'ts': edge._now(), 'mode': 'ONLINE',
        'frameTs': edge._now(), 'timeSource': 'SERVER_HTTP',
        'rulesFingerprint': edge.rules_fingerprint(),
        'p': {'vis': 0.1, 'gust': 0.05, 'unsafe': 0.15},
        'decision': {'tier': 'WATCH'}, 'latencyMs': 18, 'fw': 'edge-1.0.1',
    }
    payload.update(overrides)
    return payload


def test_edge_disabled_by_default(monkeypatch):
    monkeypatch.delenv('EDGE_ENABLED', raising=False)
    monkeypatch.setattr(edge, 'CONFIG_PATH', Path('/nonexistent/application.yml'))
    assert edge.enabled() is False
    monkeypatch.setenv('EDGE_ENABLED', 'true')
    assert edge.enabled() is True


def test_unregistered_node_is_rejected_before_writing(db):
    payload = edge.report(_report())
    assert payload['status'] == 'FORBIDDEN'
    assert payload['reason'] == 'NODE_NOT_REGISTERED'


def test_register_then_report_is_stored_once(db):
    registered = _register()
    assert registered['status'] == 'OK'
    assert registered['rulesFingerprint'] == edge.rules_fingerprint()

    first = edge.report(_report(seq=7))
    again = edge.report(_report(seq=7))
    assert first['ok'] is True and first['duplicate'] is False
    assert again['duplicate'] is True
    assert edge.health()['reports'] == 1


def test_data_age_comes_from_frame_ts_not_from_the_node(db):
    _register()
    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # 节点谎报 dataAgeMin=0，服务端必须按 frameTs 算成 45 min。
    payload = edge.report(_report(seq=1, frameTs=old, dataAgeMin=0))
    assert 44.0 <= payload['dataAgeMin'] <= 46.0
    assert payload['ageTier'] == 'FRESH'


def test_rules_fingerprint_mismatch_is_flagged(db):
    _register()
    payload = edge.report(_report(seq=1, rulesFingerprint='rules-v1:deadbeef0000'))
    assert payload['staleRules'] is True
    assert edge.health()['fingerprintMismatchNodes'] == 1


def test_signature_is_verified_when_secret_is_configured(db, monkeypatch):
    _register()
    body = _report(seq=1)
    body['sig'] = 'hmac-sha256:' + '0' * 64
    wrong = edge.report(dict(body))
    assert wrong['sigVerified'] is False

    monkeypatch.setenv('EDGE_HMAC_SECRET', 'test-secret')
    body = _report(seq=2)
    signed = dict(body)
    signed.pop('sig', None)
    body['sig'] = 'hmac-sha256:' + edge._signature('edge-sy-01', body['ts'], 2, signed)
    right = edge.report(body)
    assert right['sigVerified'] is True


def test_batch_splits_accepted_duplicate_and_rejected(db):
    _register()
    edge.report(_report(seq=1))
    payload = edge.report_batch({'node': 'edge-sy-01', 'items': [
        {'seq': 1, 'ts': edge._now(), 'mode': 'OFFLINE', 'frameTs': edge._now()},
        {'seq': 2, 'ts': edge._now(), 'mode': 'OFFLINE', 'frameTs': edge._now()},
        {'seq': 3, 'ts': edge._now(), 'mode': 'BROKEN', 'frameTs': edge._now()},
    ]})
    assert payload['duplicateSeqs'] == [1]
    assert payload['acceptedSeqs'] == [2]
    assert payload['rejected'] and payload['rejected'][0]['seq'] == 3


def test_heartbeat_reports_backfill_and_updates_last_seen(db):
    _register()
    payload = edge.heartbeat({'node': 'edge-sy-01', 'mode': 'DEGRADED',
                              'dataAgeMin': 12, 'queueDepth': 30})
    assert payload['ok'] is True
    assert payload['backfill'] is True
    row = edge.nodes()['nodes'][0]
    assert row['mode'] == 'DEGRADED'
    assert row['queueDepth'] == 30


def test_node_flips_to_offline_when_server_sees_no_success_for_10_minutes(db):
    _register()
    edge.heartbeat({'node': 'edge-sy-01', 'mode': 'ONLINE', 'dataAgeMin': 1, 'queueDepth': 0})
    stale = (datetime.now(timezone.utc) - timedelta(minutes=11)).strftime('%Y-%m-%dT%H:%M:%SZ')
    with edge._connect() as dbc:
        dbc.execute('UPDATE nodes SET last_seen=? WHERE node=?', (stale, 'edge-sy-01'))
    row = edge.nodes()['nodes'][0]
    assert row['mode'] == 'OFFLINE'
    assert edge.health()['countsClosed'] is True


def test_frames_mark_shortfall_and_never_claim_synthetic(db, monkeypatch):
    from weather import metar_history
    now = int(datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(metar_history, 'station_histories',
                        lambda hours=7, force=False: {code: [
                            {'station': code, 'epoch': now - 3600 * index,
                             'timeUtc': datetime.fromtimestamp(now - 3600 * index, tz=timezone.utc)
                             .strftime('%Y-%m-%dT%H:%M:%SZ'),
                             'visM': 3000.0, 'gustMs': 5.0, 'windMs': 3.0, 'tempC': -3.0,
                             'cloudBaseM': 800.0, 'rawOb': f'{code} TEST'}
                            for index in range(2)]  # 只有 2 条，必须报 shortfall
                            for code in metar_history.STATIONS})
    payload = edge.frames(limit=7)
    assert payload['shortfall'] is True
    assert all(frame['source'] == 'METAR' for frame in payload['frames'])
    assert {frame['station'] for frame in payload['frames']} == set(metar_history.STATIONS)


def test_sites_cover_three_stages(db):
    payload = edge.sites()
    assert len(payload['demo']) == 3
    assert {site['stationCode'] for site in payload['demo']} == {'ZYTX', 'ZYCC', 'ZYHB'}
    assert payload['planned']['count'] == 216
    assert all(site['stage'] == 'future' and site['enabled'] is False for site in payload['future'])


def test_params_keep_the_two_threshold_sets_apart(db):
    """端侧四档 0.8/0.5/0.2 与走廊判据是两套数，接口里必须分开给。"""
    from traffic import v2
    payload = edge.params()
    assert payload['thresholds'] == {'ban': 0.8, 'caution': 0.5, 'watch': 0.2}
    assert payload['corridorThresholds']['block'] == pytest.approx(v2.P_PROB_BLOCK)
    assert payload['corridorThresholds']['watch'] == pytest.approx(v2.P_PROB_WATCH)
    assert payload['stationCodes'] == ['ZYTX', 'ZYCC', 'ZYHB']
    assert payload['paramsVersion'].startswith('corridors:')
