"""The build bar must move through the phase that actually takes the time.

Reported 2026-10-01: 「增加进度加载动画显示，加载推演的时候时间长，我需要看到它的
进度在动」. The counter existed but was only written inside the per-flight loop, so on
a virtual build it sat at 0 through the radar sweep and then swept 0 -> 100 in one
motion. At the stride the incursion fix needs, the sweep is 49 derivations of ~275 ms
-- about 13 s of the 40-odd second build -- and a bar that shows *that* phase as
instant, while showing the loop as everything, describes the build backwards.

Three things are pinned here, and the third is the one that matters:

  * ``progress_stage`` is one total mapping from a percentage to a sentence;
  * the bands are ordered, so no edit can make the report non-monotone;
  * the sweep reports **per sample and before the availability check**, so a radar
    source that returns nothing still moves the bar. That last one is the negative
    verification: without it, "the bar froze" would silently come back the moment
    the feed hiccuped, and the test would still pass on a healthy feed.
"""
import pytest

from traffic import radar_field, service, weather_control, weather_sim  # noqa: F401

from tests.test_radar_payload import INSIDE_CELLS, _frame

STRONG = (INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)


@pytest.fixture
def canned_radar(monkeypatch):
    """Pin the radar frame source so the sweep is cheap and seed-fixed.

    两个取帧入口都钉：实测通道经 ``weather_control.radar_frame``，虚拟通道直接调
    ``weather_sim.frame``。只钉前者时，虚拟通道的用例会静默地用上真生成器 —— 它总是返回
    可用帧，于是"源不可用也要让进度条动"这条负向判据会自己变成一条永真的断言。
    """
    def install(entries=(STRONG,), mode='virtual', available=True):
        base = _frame(list(entries))
        base.update({'mode': mode, 'available': available})
        # 生成器的帧带合成章：``_virtual_radar_sweep`` 的通道自检认的就是它。
        base['provenance'] = {**base['provenance'], 'synthetic': True,
                              'provider': 'SYNTHETIC_RADAR'}
        monkeypatch.setattr(weather_control, 'radar_frame', lambda **kwargs: base)
        monkeypatch.setattr(weather_sim, 'frame', lambda **kwargs: base)
        monkeypatch.setattr(weather_control, 'mode', lambda *a, **k: mode)
        monkeypatch.setattr(weather_control, 'seed', lambda *a, **k: 42)
        service._virtual_radar_derived.cache_clear()
        service._virtual_radar_samples.cache_clear()
        service._RADAR_WINDOW_CACHE.clear()
        service._RADAR_ERODED_CACHE.clear()
    return install


def test_progress_stage_is_one_total_mapping():
    """Every percentage in 0..100 maps to a sentence, and the boundaries are exact.

    The caption is derived server-side from the same number as the bar, so this is
    the only place the two could disagree. Below-range input clamps to the first
    stage rather than raising: a bar must not be able to take the payload down.
    """
    assert service.progress_stage(0) == service.PROGRESS_STAGES[0][1]
    assert service.progress_stage(-40) == service.PROGRESS_STAGES[0][1]
    assert service.progress_stage(100) == service.PROGRESS_STAGES[-1][1]
    assert service.progress_stage(999) == service.PROGRESS_STAGES[-1][1]
    for threshold, label in service.PROGRESS_STAGES:
        assert service.progress_stage(threshold) == label
        assert service.progress_stage(threshold + 0.4) == label
    # Total over the whole range: no value falls through to nothing.
    stages = {service.progress_stage(value) for value in range(0, 101)}
    assert len(stages) == len(service.PROGRESS_STAGES)


def test_progress_bands_are_ordered_and_inside_the_range():
    """The bands must be monotone and must not collide.

    A single edit that swaps two constants -- exactly the edit this change invites
    -- would make the bar jump backwards. Cheap to state, and it is the invariant
    the frontend animation relies on.
    """
    bands = [service.PROGRESS_START_PERCENT, service.PROGRESS_SNAPSHOT_PERCENT,
             service.PROGRESS_SWEEP_PERCENT]
    assert bands == sorted(bands)
    assert 0 <= bands[0] and bands[-1] <= 100
    thresholds = [threshold for threshold, _label in service.PROGRESS_STAGES]
    assert thresholds == sorted(thresholds)
    assert thresholds[0] == 0
    # The sweep is the phase the report exists for, so it must own real width --
    # a band of zero would put the bar back to jumping the whole way in one step.
    assert service.PROGRESS_SWEEP_PERCENT - service.PROGRESS_SNAPSHOT_PERCENT >= 10


def test_the_sweep_reports_once_per_stride_step(canned_radar):
    """Nine samples at stride 60 must produce nine reports, not one."""
    canned_radar()
    seen = []
    steps = len(range(0, service.TIMELINE_MINUTES + 1, service.RADAR_SWEEP_STRIDE_MINUTES))
    samples = service._virtual_radar_sweep(seen.append)
    assert len(samples) == steps
    assert len(seen) == steps
    assert seen == sorted(seen)
    assert seen[0] == pytest.approx(1 / steps)
    assert seen[-1] == pytest.approx(1.0)


def test_a_dead_radar_source_still_moves_the_bar(canned_radar):
    """Negative verification: an unavailable frame must not freeze the sweep.

    The reporter is called before the availability check on purpose. If it were
    called after, a radar outage would produce zero progress calls and the bar
    would stop exactly when the operator most needs to know the build is alive --
    and every assertion in the healthy-source test above would still pass.
    """
    canned_radar(available=False)
    seen = []
    samples = service._virtual_radar_sweep(seen.append)
    assert samples == ()
    steps = len(range(0, service.TIMELINE_MINUTES + 1, service.RADAR_SWEEP_STRIDE_MINUTES))
    assert len(seen) == steps
    assert seen[-1] == pytest.approx(1.0)


def test_the_reporter_is_threaded_through_the_radar_branch(canned_radar):
    """``_radar_avoidance`` must hand the reporter down, not swallow it.

    This is the wiring point between the band arithmetic in ``simulate`` and the
    per-sample reporting in ``_virtual_radar_sweep``: if the parameter is dropped
    here, the sweep goes silent again and the bar returns to one long jump.
    """
    canned_radar()
    seen = []
    samples, info = service._radar_avoidance('live', weather_control.MODE_VIRTUAL,
                                             seen.append)
    assert info['included'] is True
    assert samples
    assert len(seen) == len(samples)
    assert seen[-1] == pytest.approx(1.0)


def test_the_measured_branch_never_reports(canned_radar):
    """One observation is one derivation -- there is no phase to watch.

    Asserted rather than left implicit because "the bar moved during a measured
    build" would be a fabricated phase: the measured channel has no sweep.
    """
    canned_radar(mode='measured')
    seen = []
    service._radar_avoidance('live', weather_control.MODE_MEASURED, seen.append)
    assert seen == []


def test_clear_scenario_progress_is_monotone_and_complete():
    """A plan with no weather still has to drive the bar from start to 100.

    ``clear`` never enters the radar branch, so the sweep band would stay empty.
    ``simulate`` states the boundary explicitly; this is the test that notices if
    that statement is removed and the bar stalls at the snapshot band.
    """
    seen = []
    service.simulate(seed=42, scenario='clear', progress=seen.append)
    assert seen[0] == service.PROGRESS_START_PERCENT
    assert seen[-1] == 100
    assert seen == sorted(seen)
    assert max(seen) <= 100
    # Both bands were exercised, so the mapping is not a single flat line.
    assert any(value == service.PROGRESS_SNAPSHOT_PERCENT for value in seen)
    assert any(value == service.PROGRESS_SWEEP_PERCENT for value in seen)
    assert any(value > service.PROGRESS_SWEEP_PERCENT for value in seen)
