import plistlib
from pathlib import Path

from lamp.effects import ActivityManager, Cue, Timeline
from lamp.resilience import KeepAwake, WakeWatcher, agent_plist, handle_wake
from tests.fakes import FakeClock, make_lamp


class FakeProc:
    def __init__(self, args):
        self.args = args
        self.terminated = False

    def terminate(self):
        self.terminated = True


def test_keepawake_starts_and_stops_with_activity():
    procs = []
    ka = KeepAwake(popen=lambda args: procs.append(FakeProc(args)) or procs[-1], pid=1234)
    ka.on_kind("effect")
    ka.on_kind("song")  # already held: no second process
    assert len(procs) == 1 and procs[0].args == ["caffeinate", "-i", "-w", "1234"]
    ka.on_kind("idle")
    assert procs[0].terminated
    ka.on_kind("effect")
    assert len(procs) == 2


def test_wall_clock_jump_triggers_wake_handler():
    t = {"wall": 1000.0, "mono": 50.0}
    w = WakeWatcher(jump_threshold_s=20, wall=lambda: t["wall"], mono=lambda: t["mono"])
    assert w.check() is None
    t["wall"] += 5
    t["mono"] += 5
    assert w.check() is None
    t["wall"] += 600  # slept for ~10 min: monotonic barely moved
    t["mono"] += 5
    assert abs(w.check() - 595) < 1e-6


async def test_wake_completes_expired_fade(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, brightness=1, on=False, fade_ms=60_000)], duration_ms=60_000),
                   start_loop=False)
    mgr.step()
    refreshed = []

    async def refresh():
        refreshed.append(True)

    lamp.refresh = refresh
    await handle_wake(lamp, mgr, jump_s=120)
    assert mgr.kind == "idle"
    assert lamp.state()["top"].on is False
    assert refreshed


async def test_wake_keeps_looping_effect(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    mgr = ActivityManager(lamp, FakeClock(), tick_hz=1000)
    await mgr.play(Timeline(cues=[Cue(t_ms=0, rgb=(1, 2, 3))], duration_ms=1000, loop=True), start_loop=False)

    async def refresh():
        pass

    lamp.refresh = refresh
    await handle_wake(lamp, mgr, jump_s=120)
    assert mgr.kind == "effect"


def test_agent_plist_contents(tmp_path):
    data = plistlib.loads(agent_plist(Path("/repo"), "/opt/homebrew/bin/uv"))
    assert data["Label"] == "com.ajay.lamp"
    assert data["RunAtLoad"] is True and data["KeepAlive"] is True
    assert data["WorkingDirectory"] == "/repo"
    assert data["ProgramArguments"] == ["/opt/homebrew/bin/uv", "run", "lamp", "serve"]
    assert data["StandardOutPath"] == "/repo/data/lamp.log"
