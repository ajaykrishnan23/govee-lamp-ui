from lamp.commands import Command
from tests.fakes import make_controller


async def test_off_and_on(tmp_path):
    ctl, _, _ = await make_controller(tmp_path)
    await ctl.run_command(Command("off"))
    assert all(not s.on for s in ctl.lamp.state().values())
    await ctl.run_command(Command("on"))
    assert all(s.on for s in ctl.lamp.state().values())


async def test_brighter_and_dimmer_step_20_and_clamp(tmp_path):
    ctl, _, _ = await make_controller(tmp_path)
    await ctl.run_command(Command("brightness", 90))
    await ctl.run_command(Command("brighter"))
    assert ctl.lamp.state()["top"].brightness == 100
    await ctl.run_command(Command("dimmer"))
    assert ctl.lamp.state()["top"].brightness == 80


async def test_static_preset_applies_per_bulb(tmp_path):
    ctl, _, _ = await make_controller(tmp_path)
    await ctl.run_command(Command("preset", "sunset"))
    s = ctl.lamp.state()
    assert s["bottom"].rgb == (255, 110, 20) and s["top"].rgb == (200, 40, 120)


async def test_timeline_preset_starts_effect(tmp_path):
    ctl, _, _ = await make_controller(tmp_path)
    await ctl.run_command(Command("preset", "campfire"))
    assert ctl.activity.kind == "effect"
    await ctl.activity.stop()


async def test_manual_set_stops_effect(tmp_path):
    ctl, _, _ = await make_controller(tmp_path)
    await ctl.run_command(Command("preset", "campfire"))
    await ctl.set("all", {"rgb": (1, 2, 3)})
    assert ctl.activity.kind == "idle"
    assert ctl.lamp.state()["top"].rgb == (1, 2, 3)


async def test_set_with_fade_plays_timeline(tmp_path):
    ctl, _, clock = await make_controller(tmp_path)
    await ctl.set("all", {"brightness": 1, "on": False}, fade_ms=1000)
    assert ctl.activity.kind == "effect"
    await ctl.activity.stop()


async def test_unknown_preset_message(tmp_path):
    ctl, _, _ = await make_controller(tmp_path)
    reply = await ctl.run_command(Command("preset", "nope"))
    assert "nope" in reply
