import json

import pytest

from lamp.govee.protocol import BulbInfo, BulbStatus
from lamp.lamp import Lamp, LightState

A = BulbInfo("10.0.0.1", "AA", "H6006")
B = BulbInfo("10.0.0.2", "BB", "H6006")
OTHER = BulbInfo("10.0.0.9", "ZZ", "H6199")


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


@pytest.fixture
def registry(tmp_path):
    return tmp_path / "bulbs.json"


async def make(registry, *bulbs, status=None):
    t = FakeTransport(status)
    lamp = Lamp(t, registry, discover_fn=fake_discover(*bulbs))
    await lamp.refresh()
    t.sent.clear()
    return lamp, t


async def test_first_discovery_names_top_bottom(registry):
    lamp, _ = await make(registry, A, B, OTHER)
    assert lamp.names() == ["top", "bottom"]


async def test_refresh_seeds_state_from_status(registry):
    lamp, _ = await make(registry, A, B, status={"10.0.0.1": BulbStatus(True, 40, (0, 0, 0), 2700)})
    assert lamp.state()["top"] == LightState(on=True, rgb=None, kelvin=2700, brightness=40)


async def test_apply_all_sends_to_both_only_changed_fields(registry):
    lamp, t = await make(registry, A, B)
    lamp.apply("all", {"brightness": 30})
    assert sorted((ip, key) for ip, key, _ in t.sent) == [("10.0.0.1", "brightness"), ("10.0.0.2", "brightness")]
    t.sent.clear()
    lamp.apply("all", {"brightness": 30})
    assert t.sent == []


async def test_rgb_patch_clears_kelvin(registry):
    lamp, t = await make(registry, A, B)
    lamp.apply("top", {"kelvin": 3000})
    lamp.apply("top", {"rgb": (255, 0, 0)})
    assert lamp.state()["top"].kelvin is None and lamp.state()["top"].rgb == (255, 0, 0)
    lamp.apply("top", {"kelvin": 4000})
    assert lamp.state()["top"].rgb is None and lamp.state()["top"].kelvin == 4000
    assert [k for _, k, _ in t.sent] == ["color", "color", "color"]


async def test_power_patch_sends_turn(registry):
    lamp, t = await make(registry, A, B)
    lamp.apply("bottom", {"on": False})
    assert t.sent == [("10.0.0.2", "power", {"cmd": "turn", "data": {"value": 0}})]


async def test_rename_and_swap_persist(registry):
    lamp, _ = await make(registry, A, B)
    lamp.rename("top", "upper")
    lamp.swap()
    lamp2, t2 = await make(registry, A, B)
    assert lamp2.names() == ["upper", "bottom"]
    lamp2.apply("upper", {"on": False})
    assert t2.sent[0][0] == "10.0.0.2"  # swapped: upper is now bulb B


async def test_rediscovery_rebinds_bulb_by_mac(registry):
    lamp, t = await make(registry, A, B)
    lamp._discover = fake_discover(BulbInfo("10.0.0.77", "AA", "H6006"), B)
    await lamp.refresh()
    t.sent.clear()
    lamp.apply("top", {"on": False})
    assert t.sent[0][0] == "10.0.0.77"


async def test_apply_unknown_target_raises_value_error(registry):
    lamp, _ = await make(registry, A, B)
    with pytest.raises(ValueError):
        lamp.apply("middle", {"on": True})


async def test_on_change_called_with_state(registry):
    lamp, _ = await make(registry, A, B)
    seen = []
    lamp.on_change(seen.append)
    lamp.apply("all", {"brightness": 10})
    assert seen and seen[-1]["top"].brightness == 10
