"""The traffic session cache must not grow without bound.

``_fingerprint()`` hashes every ``traffic/*.py`` file, so a single source edit
invalidates every cached plan at once. In-memory ``JOBS`` eviction never touched
the disk, and one measured machine had accumulated 73 files / 1.4 GB across 22
fingerprint generations while only 25 files belonged to the live revision. These
tests pin the pruning contract so that regression cannot come back silently.

The test drives ``_prune_stale_store`` directly against a temporary ``STORE``
rather than going through ``session()``, because the point is the disk policy,
not the cache-hit path -- and building a real session costs ~20 MB / several
seconds each.
"""
import json

import pytest

from traffic import service


def _write_cache(directory, name, fingerprint, body=None):
    """Minimal stand-in for a cached session: only the header matters here."""
    path = directory / name
    payload = {'fingerprint': fingerprint, 'planRevision': service.PLAN_REVISION}
    payload.update(body or {})
    path.write_text(json.dumps(payload, ensure_ascii=False) + '\n' + 'x' * 200, encoding='utf-8')
    return path


@pytest.fixture()
def store(tmp_path, monkeypatch):
    target = tmp_path / 'traffic'
    target.mkdir()
    monkeypatch.setattr(service, 'STORE', target)
    return target


def test_stale_generations_are_dropped_and_the_live_one_is_kept(store):
    live = service.FINGERPRINT
    keep = [_write_cache(store, f'keep{i}.json', live) for i in range(3)]
    drop = [_write_cache(store, f'drop{i}.json', 'deadbeefdeadbeef') for i in range(5)]

    service._prune_stale_store()

    assert all(p.exists() for p in keep), '当前指纹的缓存必须保留'
    assert not any(p.exists() for p in drop), '失效指纹的缓存必须清除'
    assert sorted(p.name for p in store.glob('*.json')) == sorted(p.name for p in keep)


def test_a_file_without_a_readable_fingerprint_is_treated_as_stale(store):
    """Unattributable cache is not evidence; dropping it only costs a recompute."""
    unreadable = store / 'torn.json'
    unreadable.write_text('{"status": "READY"', encoding='utf-8')   # truncated, no fingerprint
    good = _write_cache(store, 'good.json', service.FINGERPRINT)

    service._prune_stale_store()

    assert not unreadable.exists()
    assert good.exists()


def test_interrupted_writes_are_swept_even_when_fingerprints_all_match(store):
    """A crash between write and rename leaves a .tmp that nothing else reclaims."""
    good = _write_cache(store, 'good.json', service.FINGERPRINT)
    leftover = store / 'halfway.json.tmp'
    leftover.write_text('partial', encoding='utf-8')

    service._prune_stale_store()

    assert not leftover.exists()
    assert good.exists()


def test_pruning_is_idempotent(store):
    _write_cache(store, 'a.json', service.FINGERPRINT)
    _write_cache(store, 'b.json', 'nope')
    service._prune_stale_store()
    first = sorted(p.name for p in store.glob('*.json'))
    service._prune_stale_store()
    assert sorted(p.name for p in store.glob('*.json')) == first


def test_a_missing_store_directory_is_not_an_error(store):
    """Housekeeping runs after a build; it must never raise into that request."""
    for path in store.iterdir():
        path.unlink()
    store.rmdir()
    service._prune_stale_store()          # must not raise
    assert not store.exists()


def test_pruning_only_touches_json_and_tmp_not_foreign_files(store):
    """The store directory is ours, but an operator may drop a note in it."""
    note = store / 'README.txt'
    note.write_text('手动放置的说明', encoding='utf-8')
    _write_cache(store, 'stale.json', 'old')

    service._prune_stale_store()

    assert note.exists(), '非缓存文件不得被清理'
    assert not (store / 'stale.json').exists()
