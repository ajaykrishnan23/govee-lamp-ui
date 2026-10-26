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
    mgr = ActivityManager(lamp, clock, tick_hz=1000)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(9, 9, 9))], duration_ms=100), start_loop=False)
    assert mgr.kind == "effect"
    assert mgr.step() is True
    assert lamp.state()["top"].rgb == (9, 9, 9)
    clock.advance(150)
    assert mgr.step() is False
    assert mgr.kind == "idle"


async def test_play_preempts_previous(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000)
    kinds = []
    mgr.on_kind_change(kinds.append)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(1, 1, 1))], duration_ms=10_000), start_loop=False)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(2, 2, 2))], duration_ms=10_000), kind="song", start_loop=False)
    mgr.step()
    assert mgr.kind == "song"
    assert lamp.state()["top"].rgb == (2, 2, 2)
    assert kinds[-1] == "song"


async def test_stop_returns_idle_and_leaves_last_state(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(5, 5, 5))], duration_ms=10_000), start_loop=False)
    mgr.step()
    await mgr.stop()
    assert mgr.kind == "idle"
    assert lamp.state()["top"].rgb == (5, 5, 5)


async def test_runner_only_sends_diffs(tmp_path):
    lamp, t = await make_lamp(tmp_path)
    clock = FakeClock()
    mgr = ActivityManager(lamp, clock, tick_hz=1000)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(255, 0, 0), brightness=50)], duration_ms=2000), start_loop=False)
    for _ in range(20):
        mgr.step()
        clock.advance(100)
    keys = sorted((ip, k) for ip, k, _ in t.sent)
    assert keys == [("10.0.0.1", "brightness"), ("10.0.0.1", "color"), ("10.0.0.2", "brightness"), ("10.0.0.2", "color")]


async def test_position_fn_drives_playhead(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    pos = {"ms": 0}
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000)
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(1, 0, 0)), Cue(t_ms=5000, rgb=(0, 1, 0))], duration_ms=10_000)
    await mgr.play(tl, kind="song", position_fn=lambda: pos["ms"], start_loop=False)
    pos["ms"] = 6000
    mgr.step()
    assert lamp.state()["top"].rgb == (0, 1, 0)


async def test_background_loop_ticks(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    from lamp.effects import MonotonicClock
    import asyncio
    mgr = ActivityManager(lamp, MonotonicClock(), tick_hz=50)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(7, 7, 7))], duration_ms=60))
    await asyncio.sleep(0.2)
    assert lamp.state()["top"].rgb == (7, 7, 7)
    assert mgr.kind == "idle"


def test_later_cue_interrupts_running_fade():
    tl = Timeline(cues=[Cue(t_ms=0, rgb=(200, 0, 0), fade_ms=1000), Cue(t_ms=500, rgb=(0, 0, 9))], duration_ms=2000)
    assert state_at(tl, 600, START)["top"].rgb == (0, 0, 9)
