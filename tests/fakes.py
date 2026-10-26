import json

from lamp.govee.protocol import BulbInfo
from lamp.lamp import Lamp

A = BulbInfo("10.0.0.1", "AA", "H6006")
B = BulbInfo("10.0.0.2", "BB", "H6006")


class FakeTransport:
    def __init__(self, status=None):
        self.sent: list[tuple[str, str, dict]] = []
        self.status = status or {}

    def send_latest(self, ip, key, msg):
        self.sent.append((ip, key, json.loads(msg)["msg"]))

    async def query_status(self, ip, timeout=1.0):
        return self.status.get(ip)


def fake_discover(*bulbs):
    async def discover(timeout=3.0):
        return list(bulbs)
    return discover


async def make_lamp(tmp_path, *bulbs):
    t = FakeTransport()
    lamp = Lamp(t, tmp_path / "bulbs.json", discover_fn=fake_discover(*(bulbs or (A, B))))
    await lamp.refresh()
    t.sent.clear()
    return lamp, t


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now_ms(self) -> float:
        return self.t

    def advance(self, ms: float) -> None:
        self.t += ms


class FakeSong:
    def __init__(self, on=False):
        self.on = on
        self.calls: list[str] = []

    async def start(self):
        self.calls.append("start")
        self.on = True

    async def stop(self):
        self.calls.append("stop")
        self.on = False

    async def redo(self, instruction: str):
        self.calls.append(f"redo:{instruction}")

    def status(self) -> dict:
        return {"on": self.on, "state": "idle"}


async def make_controller(tmp_path, song=None):
    from lamp.control import Controller
    from lamp.effects import ActivityManager
    from lamp.presets import PresetStore
    lamp, t = await make_lamp(tmp_path)
    clock = FakeClock()
    activity = ActivityManager(lamp, clock, tick_hz=1000)
    ctl = Controller(lamp, activity, PresetStore(tmp_path / "presets.json"), song or FakeSong())
    return ctl, t, clock
