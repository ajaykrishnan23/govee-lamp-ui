import pytest

from lamp.effects import ActivityManager, Cue, Timeline, state_at
from lamp.lamp import LightState
from tests.fakes import FakeClock, make_lamp

START = {"top": LightState(rgb=(0, 0, 0), brightness=100), "bottom": LightState(rgb=(0, 0, 0), brightness=100)}


def test_state_at_holds_before_first_cue():
    tl = Timeline(cues=[Cue(t_ms=1000, rgb=(255, 0, 0))], duration_ms=2000)
    assert state_at(tl, 500, START) == START


def test_state_at_fade_midpoint():
    tl = Timeline(cues=[Cue(t_ms=0, target="top", rgb=(200, 100, 0), fade_ms=1000)], duration_ms=2000)
    s = state_at(tl, 500, START)
    assert s["top"].rgb == (100, 50, 0)
    assert s["bottom"].rgb == (0, 0, 0)


def test_state_at_after_fade_is_target():
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(200, 100, 0), fade_ms=1000)], duration_ms=2000)
    assert state_at(tl, 1500, START)["bottom"].rgb == (200, 100, 0)


def test_state_at_loops():
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(255, 0, 0)), Cue(t_ms=500, rgb=(0, 0, 255))], duration_ms=1000, loop=True)
    assert state_at(tl, 1200, START)["top"].rgb == (255, 0, 0)
    assert state_at(tl, 1700, START)["top"].rgb == (0, 0, 255)


def test_twenty_minute_fade_to_off():
    tl = Timeline(cues=[Cue(t_ms=0, brightness=1, on=False, fade_ms=1_200_000)], duration_ms=1_200_000)
    half = state_at(tl, 600_000, START)["top"]
    assert half.on and half.brightness in (50, 51)
    end = state_at(tl, 1_200_000, START)["top"]
    assert end.on is False


def test_cue_rejects_bad_rgb():
    with pytest.raises(ValueError):
        Cue(t_ms=0, rgb=(300, 0, 0))


async def test_play_runs_and_finishes(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    clock = FakeClock()
    mgr = ActivityManager(lamp, clock, tick_hz=1000, smoothing=None)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(9, 9, 9))], duration_ms=100), start_loop=False)
    assert mgr.kind == "effect"
    assert mgr.step() is True
    assert lamp.state()["top"].rgb == (9, 9, 9)
    clock.advance(150)
    assert mgr.step() is False
    assert mgr.kind == "idle"


async def test_play_preempts_previous(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000, smoothing=None)
    kinds = []
    mgr.on_kind_change(kinds.append)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(1, 1, 1))], duration_ms=10_000), start_loop=False)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(2, 2, 2))], duration_ms=10_000), start_loop=False)
    mgr.step()
    assert mgr.kind == "effect"
    assert lamp.state()["top"].rgb == (2, 2, 2)
    assert kinds[-1] == "effect"


async def test_stop_returns_idle_and_leaves_last_state(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000, smoothing=None)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(5, 5, 5))], duration_ms=10_000), start_loop=False)
    mgr.step()
    await mgr.stop()
    assert mgr.kind == "idle"
    assert lamp.state()["top"].rgb == (5, 5, 5)


async def test_runner_only_sends_diffs(tmp_path):
    lamp, t = await make_lamp(tmp_path)
    clock = FakeClock()
    mgr = ActivityManager(lamp, clock, tick_hz=1000, smoothing=None)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(255, 0, 0), brightness=50)], duration_ms=2000), start_loop=False)
    for _ in range(20):
        mgr.step()
        clock.advance(100)
    keys = sorted((ip, k) for ip, k, _ in t.sent)
    assert keys == [("10.0.0.1", "brightness"), ("10.0.0.1", "color"), ("10.0.0.2", "brightness"), ("10.0.0.2", "color")]


async def test_background_loop_ticks(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    from lamp.effects import MonotonicClock
    import asyncio
    mgr = ActivityManager(lamp, MonotonicClock(), tick_hz=50, smoothing=None)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(7, 7, 7))], duration_ms=60))
    await asyncio.sleep(0.2)
    assert lamp.state()["top"].rgb == (7, 7, 7)
    assert mgr.kind == "idle"


def test_later_cue_interrupts_running_fade():
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(200, 0, 0), fade_ms=1000), Cue(t_ms=500, rgb=(0, 0, 9))], duration_ms=2000)
    assert state_at(tl, 600, START)["top"].rgb == (0, 0, 9)


def test_loop_restarts_from_its_own_end_state_not_pre_effect_state():
    # ocean-style: fade in from whatever was on, then drift; the 2nd pass must not snap back to the old color
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(0, 90, 255), fade_ms=5000),
                        Cue(t_ms=10_000, rgb=(0, 200, 170), fade_ms=9000)], duration_ms=20_000, loop=True)
    warm = {"top": LightState(kelvin=2700, brightness=80)}
    first_end = state_at(tl, 19_999, warm)["top"]
    just_after_wrap = state_at(tl, 20_010, warm)["top"]
    assert first_end.rgb == (0, 200, 170)
    assert just_after_wrap.kelvin is None
    assert just_after_wrap.rgb == (0, 200, 170)  # starts fading toward blue from teal, not from warm white


async def test_runner_keeps_looping_past_first_pass(tmp_path):
    # the runner must not clamp the playhead to the timeline length for looping effects
    lamp, _ = await make_lamp(tmp_path)
    clock = FakeClock()
    mgr = ActivityManager(lamp, clock, tick_hz=1000, smoothing=None)
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(255, 0, 0)), Cue(t_ms=500, rgb=(0, 0, 255))], duration_ms=1000, loop=True)
    await mgr.play(tl, start_loop=False)
    seen = []
    for _ in range(12):  # 3 full passes, sampled every 250 ms
        assert mgr.step() is True
        seen.append(lamp.state()["top"].rgb)
        clock.advance(250)
    assert seen[4:8] == [(255, 0, 0), (255, 0, 0), (0, 0, 255), (0, 0, 255)]  # second pass repeats the first
    assert mgr.kind == "effect"


# ---- anti-flicker guard: on by default for every animation ----

async def _smoothed(tmp_path, tl):
    from lamp.effects import Smoothing
    lamp, _ = await make_lamp(tmp_path)
    lamp.apply("all", {"rgb": (0, 0, 0), "brightness": 1})
    clock = FakeClock()
    mgr = ActivityManager(lamp, clock, tick_hz=10)
    assert isinstance(mgr.smoothing, Smoothing)  # default is on
    await mgr.play(tl, start_loop=False)
    return lamp, clock, mgr


async def test_guard_slows_sudden_brightness_jump(tmp_path):
    lamp, clock, mgr = await _smoothed(tmp_path, Timeline(cues=[Cue(t_ms=0, brightness=100)], duration_ms=60_000))
    for _ in range(10):  # one second
        clock.advance(100)
        mgr.step()
    assert 15 <= lamp.state()["top"].brightness <= 22  # ~20%/s, not an instant jump


async def test_guard_slows_sudden_color_jump(tmp_path):
    lamp, clock, mgr = await _smoothed(tmp_path, Timeline(cues=[Cue(t_ms=0, rgb=(255, 0, 0))], duration_ms=60_000))
    for _ in range(10):
        clock.advance(100)
        mgr.step()
    assert 50 <= lamp.state()["top"].rgb[0] <= 62


async def test_guard_turns_a_strobe_into_a_gentle_wave(tmp_path):
    strobe = Timeline(cues=[Cue(t_ms=0, rgb=(255, 255, 255), brightness=100),
                            Cue(t_ms=100, rgb=(0, 0, 0), brightness=1)], duration_ms=200, loop=True)
    lamp, clock, mgr = await _smoothed(tmp_path, strobe)
    prev = lamp.state()["top"]
    for _ in range(40):
        clock.advance(100)
        mgr.step()
        cur = lamp.state()["top"]
        assert abs(cur.brightness - prev.brightness) <= 2
        assert all(abs(a - b) <= 6 for a, b in zip(cur.rgb, prev.rgb))
        prev = cur


async def test_guarded_oneshot_finishes_only_after_catching_up(tmp_path):
    lamp, clock, mgr = await _smoothed(tmp_path, Timeline(cues=[Cue(t_ms=0, brightness=100)], duration_ms=100))
    clock.advance(200)
    assert mgr.step() is True  # timeline is over but the light is still gliding
    for _ in range(60):
        clock.advance(100)
        if not mgr.step():
            break
    assert mgr.kind == "idle" and lamp.state()["top"].brightness == 100


async def test_guard_leaves_slow_moods_unchanged(tmp_path):
    from lamp.presets import BUILTINS
    for p in BUILTINS:
        if not p.timeline:
            continue
        start = {"top": LightState(rgb=(255, 90, 10), brightness=50), "bottom": LightState(rgb=(255, 90, 10), brightness=50)}
        tl = p.timeline
        for t in range(0, tl.duration_ms * 2, 100):
            a, b = state_at(tl, t, start), state_at(tl, t + 100, start)
            for n in a:
                assert abs(a[n].brightness - b[n].brightness) <= 2.5, (p.name, t)
                if a[n].rgb and b[n].rgb:
                    assert max(abs(x - y) for x, y in zip(a[n].rgb, b[n].rgb)) <= 7, (p.name, t)
