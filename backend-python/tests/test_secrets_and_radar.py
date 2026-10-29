"""Credential sealing and the 中国气象数据网 radar adapter.

These tests exist because both modules handle material that must not leak: the
store holds account passwords, and the radar adapter builds request URLs whose
query string carries those passwords in clear text. A regression here would be
silent, so each guarantee below is asserted directly rather than inferred.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from traffic import cma_radar
from traffic.secret_store import (
    SecretDecryptError,
    SecretNotFound,
    SecretStore,
    fingerprint,
    redact,
)

FAKE_USER = 'test-user-0001'
FAKE_SECRET = 'Zx9-plaintext-probe-4711'


@pytest.fixture()
def store(tmp_path):
    return SecretStore(path=tmp_path / 'secrets.db', key=b'k' * 32)


def test_values_are_sealed_before_they_reach_the_database(tmp_path):
    """The whole point of the store: the raw bytes on disk must not contain it."""
    path = tmp_path / 'secrets.db'
    store = SecretStore(path=path, key=b'q' * 32)
    store.put('cma.api_password', FAKE_SECRET)

    raw = path.read_bytes()
    assert FAKE_SECRET.encode('utf-8') not in raw, '明文出现在数据库文件里'
    # The column really is ciphertext rather than an empty placeholder.
    with sqlite3.connect(path) as connection:
        blob = connection.execute("SELECT ciphertext FROM secrets WHERE name='cma.api_password'").fetchone()[0]
    assert blob and len(blob) > len(FAKE_SECRET)
    assert store.get('cma.api_password') == FAKE_SECRET


def test_rotating_a_value_keeps_it_readable_and_records_the_change(store):
    store.put('huafeng.api_key', 'first-value')
    digest_one = store.fingerprint_of('huafeng.api_key')['fingerprint']
    store.put('huafeng.api_key', 'second-value')
    assert store.get('huafeng.api_key') == 'second-value'

    digest_two = store.fingerprint_of('huafeng.api_key')['fingerprint']
    assert digest_one != digest_two, '指纹必须随值变化，否则无法核对轮换是否生效'
    actions = [row['action'] for row in store.audit()]
    assert 'CREATE' in actions and 'ROTATE' in actions
    # The audit trail must be value-free: fingerprints only.
    assert all(FAKE_SECRET not in json.dumps(row, ensure_ascii=False) for row in store.audit())


def test_listing_never_exposes_a_value(store):
    store.put('cma.api_user_id', FAKE_USER)
    rows = store.names()
    assert rows and rows[0]['name'] == 'cma.api_user_id'
    assert FAKE_USER not in json.dumps(rows, ensure_ascii=False)


def test_a_different_key_cannot_open_the_database(tmp_path):
    path = tmp_path / 'secrets.db'
    SecretStore(path=path, key=b'a' * 32).put('cma.api_password', FAKE_SECRET)
    with pytest.raises(SecretDecryptError):
        SecretStore(path=path, key=b'b' * 32).get('cma.api_password')


def test_missing_and_empty_values_are_refused(store):
    with pytest.raises(SecretNotFound):
        store.get('cma.api_password')
    with pytest.raises(Exception):
        store.put('cma.api_password', '')
    assert store.get_optional('cma.api_password') is None


def test_redaction_masks_credentials_and_ignores_tiny_values():
    url = f'http://api.data.cma.cn:8090/api?userId={FAKE_USER}&pwd={FAKE_SECRET}&dataFormat=json'
    masked = redact(url, FAKE_USER, FAKE_SECRET)
    assert FAKE_SECRET not in masked and FAKE_USER not in masked
    assert masked.count('***REDACTED***') == 2
    # Short values are left alone; masking them would corrupt unrelated text.
    assert redact('abcd', 'ab') == 'abcd'


def test_fingerprint_is_stable_and_does_not_contain_the_value():
    digest = fingerprint(FAKE_SECRET)
    assert digest == fingerprint(FAKE_SECRET) and len(digest) == 12
    assert FAKE_SECRET not in digest


def test_key_material_is_normalised_before_it_reaches_fernet(tmp_path):
    """A raw 32-byte key must work, not just a ready-made 44-character Fernet key.

    Requiring an operator to hand-roll ``Fernet.generate_key()`` output before
    filling in ``ALC_SECRET_KEY`` is the kind of detail that gets a store
    abandoned, so both spellings are accepted and an unsupported length still
    fails loudly rather than silently writing under a wrong key.
    """
    from cryptography.fernet import Fernet

    from traffic.secret_store import SecretKeyUnavailable, normalise_key

    # A ready Fernet key passes through untouched.
    ready = Fernet.generate_key()
    assert normalise_key(ready) == ready and normalise_key(ready.decode()) == ready
    # A raw 32-byte key and its hex spelling both become the same usable key.
    assert normalise_key(b'k' * 32) == normalise_key((b'k' * 32).hex())
    Fernet(normalise_key(b'k' * 32))  # must be constructible, not merely non-empty
    for bad in (b'', b'short', b'x' * 31):
        with pytest.raises(SecretKeyUnavailable):
            normalise_key(bad)

    # The two spellings are interchangeable against one database.
    path = tmp_path / 'secrets.db'
    SecretStore(path=path, key=b'z' * 32).put('huafeng.api_key', FAKE_SECRET)
    assert SecretStore(path=path, key=normalise_key(b'z' * 32)).get('huafeng.api_key') == FAKE_SECRET


# --- radar adapter -------------------------------------------------------

def _recent_window(gap_hours=2, span_hours=2):
    """A time range that is inside the platform's published 7-day window.

    `validate_window()` checks the range against the clock, so a literal date in
    a test is a time bomb: `20260916100000` stopped being accepted seven days
    later, and the suite went red with a message that reads like a regression in
    the adapter when nothing about the adapter had changed. Derived from now.
    """
    fmt = '%Y%m%d%H%M%S'
    end = datetime.now(timezone.utc) - timedelta(hours=gap_hours)
    return (end - timedelta(hours=span_hours)).strftime(fmt), end.strftime(fmt)


def test_safe_url_masks_both_query_credentials():
    url = (f'{cma_radar.API_BASE}?userId={FAKE_USER}&pwd={FAKE_SECRET}'
           '&interfaceId=getRadaFileByTimeRange')
    masked = cma_radar.safe_url(url, FAKE_USER, FAKE_SECRET)
    assert FAKE_SECRET not in masked and FAKE_USER not in masked


def test_request_matches_the_documented_contract():
    start, end = _recent_window()
    params = cma_radar.build_params(FAKE_USER, FAKE_SECRET, start, end)
    assert params['interfaceId'] == 'getRadaFileByTimeRange'
    assert params['dataCode'] == 'RADA_L3_MST_V3_CREF_PNG'
    assert params['dataFormat'] == 'json'
    assert params['elements'] == 'Station_Id_C,DATETIME,FORMAT,FILE_NAME'
    assert params['timeRange'] == f'[{start},{end}]'
    # Adding a station filter must switch to the station-scoped interface.
    scoped = cma_radar.build_params(FAKE_USER, FAKE_SECRET, start, end, station_ids=['54342'])
    assert scoped['interfaceId'] == 'getRadaFileByTimeRangeAndStaId'
    assert scoped['staIDs'] == '54342'


def test_ranges_outside_the_published_window_are_refused():
    with pytest.raises(cma_radar.RadarUnavailable):
        cma_radar.validate_window('20260101000000', '20260120000000')
    with pytest.raises(cma_radar.RadarUnavailable):
        cma_radar.validate_window('20260916120000', '20260916100000')
    # A guessed-but-unverified resource code must fail rather than return nothing.
    # The window has to be valid here: with an expired literal date the call was
    # refused by the date check before it ever reached the code check, so the
    # assertion below was passing without testing the branch it names.
    start, end = _recent_window()
    with pytest.raises(cma_radar.RadarUnavailable):
        cma_radar.build_params(FAKE_USER, FAKE_SECRET, start, end, data_code='NOT_VERIFIED')


def test_response_envelopes_and_field_casing_are_both_accepted():
    rows = [{'Station_Id_C': None, 'DATETIME': '2026-09-16 10:00:00',
             'FORMAT': 'PNG', 'FILE_NAME': 'Z_RADA_C_BABJ_20260916100000_P_ACHN.CREF000.png'}]
    for payload in ({'returnCode': '0', 'DS': rows}, {'data': rows}, rows):
        assert cma_radar._records(payload) == rows
    with pytest.raises(cma_radar.RadarUnavailable):
        cma_radar._records({'returnCode': '401', 'returnMessage': '账号或密码错误'})

    item = cma_radar.normalise(rows[0])
    assert item['fileName'].endswith('.CREF000.png') and item['format'] == 'PNG'
    assert item['stationId'] is None


class _StubResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _StubClient:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if self.error:
            raise self.error
        return _StubResponse(self.payload)


def test_query_returns_files_with_provenance(store, monkeypatch):
    store.put('cma.api_user_id', FAKE_USER)
    store.put('cma.api_password', FAKE_SECRET)
    client = _StubClient({'returnCode': '0', 'DS': [
        {'Station_Id_C': None, 'DATETIME': '2026-09-16 10:00:00', 'FORMAT': 'PNG',
         'FILE_NAME': 'Z_RADA_C_BABJ_20260916100000_P_ACHN.CREF000.png'}]})
    # Same time bomb as above: the window is validated against the clock, so a
    # literal date makes this test fail seven days later for a reason that has
    # nothing to do with provenance.
    start, end = _recent_window()
    result = cma_radar.query_files(start, end, store=store, client=client)

    assert result['available'] and len(result['files']) == 1
    assert result['provenance']['provider'] == 'CMA_DATA_NET'
    assert result['provenance']['dataset'] == 'RADA_L3_MST_V3_CREF_PNG'
    assert result['provenance']['transport'] == 'HTTP_QUERY_CREDENTIALS'
    # The adapter must present the credentials it loaded from the sealed store.
    assert client.calls[0][1]['pwd'] == FAKE_SECRET


def test_missing_credentials_fail_closed_without_calling_the_network(store):
    client = _StubClient({'returnCode': '0', 'DS': []})
    result = cma_radar.query_files('20260916100000', '20260916120000', store=store, client=client)
    assert result['available'] is False and result['files'] == []
    assert '凭据' in result['error']
    assert client.calls == [], '凭据缺失时不应发起请求'


def test_network_and_platform_failures_never_leak_the_credential(store):
    import httpx

    store.put('cma.api_user_id', FAKE_USER)
    store.put('cma.api_password', FAKE_SECRET)

    failing = _StubClient(error=httpx.ConnectError(f'boom userId={FAKE_USER} pwd={FAKE_SECRET}'))
    result = cma_radar.query_files('20260916100000', '20260916120000', store=store, client=failing)
    assert result['available'] is False and result['files'] == []
    assert FAKE_SECRET not in json.dumps(result, ensure_ascii=False)
    assert FAKE_USER not in json.dumps(result, ensure_ascii=False)

    rejected = _StubClient({'returnCode': '401', 'returnMessage': f'密码错误 {FAKE_SECRET}'})
    result = cma_radar.query_files('20260916100000', '20260916120000', store=store, client=rejected)
    assert result['available'] is False and result['files'] == []


def test_status_reports_readiness_without_revealing_the_credential(store):
    report = cma_radar.status(store=store)
    assert report['ready'] is False and 'hint' in report
    store.put('cma.api_user_id', FAKE_USER)
    store.put('cma.api_password', FAKE_SECRET)
    report = cma_radar.status(store=store)
    assert report['ready'] is True
    assert FAKE_SECRET not in json.dumps(report, ensure_ascii=False)
    assert FAKE_USER not in json.dumps(report, ensure_ascii=False)
