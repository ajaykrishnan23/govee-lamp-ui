"""Regression tests for findings from the whole-branch review."""
import asyncio
import json

import httpx
import pytest

from lamp.commands import Command
from lamp.config import Settings
from lamp.control import Controller
from lamp.effects import ActivityManager, MonotonicClock
from lamp.govee.protocol import BulbStatus
from lamp.govee.transport import GoveeTransport
from lamp.presets import Preset, PresetStore
from lamp.web.events import EventBus
from tests.ai.test_agent import FakeClient, call, make_agent, resp
from tests.fakes import A, B, FakeTransport, fake_discover, make_lamp
from tests.web.conftest import ai, app_env, authed, settings, transcriber  # noqa: F401 (fixtures)


# Important 2: a stalled SSE client must be disconnected so the browser reconnects
async def test_event_stream_ends_after_overflow():
    bus = EventBus()
    gen = bus.subscribe(initial=[("snapshot", {})])
    await gen.__anext__()
    for i in range(300):
        bus.publish("state", {"i": i})
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 1)


# Important 3: cached state must not hide a power-cycled bulb
async def test_refresh_rereads_status_for_known_bulbs(tmp_path):
    lamp, t = await make_lamp(tmp_path)
    lamp.apply("all", {"rgb": (255, 0, 0)})
    t.status = {"10.0.0.1": BulbStatus(True, 100, (0, 0, 0), 2700)}
    await lamp.refresh()
    assert lamp.state()["top"].kelvin == 2700


async def test_forced_apply_resends_unchanged_values(tmp_path):
    lamp, t = await make_lamp(tmp_path)
    lamp.apply("top", {"rgb": (255, 0, 0)})
    t.sent.clear()
    lamp.apply("top", {"rgb": (255, 0, 0), "on": True}, force=True)
    assert {k for _, k, _ in t.sent} >= {"color", "power"}


# Important 4: overlapping discoveries must not crash
async def test_concurrent_discover_does_not_crash():
    t = GoveeTransport(10)
    t.listen_port = 0
    await t.start()
    try:
        await asyncio.gather(t.discover(0.1), t.discover(0.1))
    finally:
        await t.close()


# Important 5: odd tool args / missing usage / unexpected errors stay inside the agent
async def test_non_object_tool_args_become_tool_error(tmp_path):
    client = FakeClient(resp(call("set_lights", **{})), resp(text="ok"))
    client.responses_q[0].output[0].arguments = "null"
    agent, *_ = await make_agent(tmp_path, client)
    r = await agent.handle("x")
    out = client.calls[1]["input"][-1]
    assert out["type"] == "function_call_output" and out["output"].startswith("error")
    assert r.reply == "ok"


async def test_missing_usage_does_not_crash(tmp_path):
    r0 = resp(text="fine")
    r0.usage = None
    agent, *_ = await make_agent(tmp_path, FakeClient(r0))
    assert (await agent.handle("x")).reply == "fine"


async def test_handle_prompt_catches_unexpected_agent_errors(authed):
    client, svc, _ = authed

    async def boom(text):
        raise OSError("disk full")

    svc.agent.handle = boom
    q = svc.bus.listen()
    r = await client.post("/api/prompt", json={"text": "something soft like a rainy afternoon"})
    assert r.status_code == 200 and "disk full" in r.json()["error"]
    types = []
    while not q.empty():
        types.append(q.get_nowait()["type"])
    assert "log" in types


# Important 6: saved static moods are validated
@pytest.mark.parametrize("patch", [{"kelvin": "warm"}, {"rgb": [999, 0, 0]}, {"brightness": 0}, {"colour": 1}])
def test_preset_rejects_bad_static(patch):
    with pytest.raises(ValueError):
        Preset(name="bad", static={"all": patch})


# Important 8: login works over plain HTTP too
async def test_login_over_http(settings, ai, transcriber):
    from lamp.runtime import build_app
    app, _ = build_app(settings, transport=FakeTransport(), ai_client=ai, discover_fn=fake_discover(A, B),
                       transcriber=transcriber)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/login", json={"password": "pw-123"})
            assert (await c.get("/api/state")).status_code == 200


# Important 9: rapid taps resolve in tap order
async def test_rapid_preset_taps_last_wins(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    store = PresetStore(tmp_path / "p.json")
    activity = ActivityManager(lamp, MonotonicClock(), tick_hz=50)
    ctl = Controller(lamp, activity, store)
    await ctl.apply_preset(store.get("campfire"))
    await asyncio.gather(ctl.apply_preset(store.get("ocean")), ctl.apply_preset(store.get("party")))
    assert activity._timeline == store.get("party").timeline
    await activity.stop()


async def test_static_set_not_overridden_by_concurrent_effect(tmp_path):
    lamp, _ = await make_lamp(tmp_path)
    store = PresetStore(tmp_path / "p.json")
    activity = ActivityManager(lamp, MonotonicClock(), tick_hz=50)
    ctl = Controller(lamp, activity, store)
    await ctl.apply_preset(store.get("campfire"))
    await asyncio.gather(ctl.run_timeline(store.get("ocean").timeline), ctl.set("all", {"on": False}))
    assert activity.kind == "idle" and not lamp.state()["top"].on


# re-graded: an empty APP_PASSWORD would let anyone log in with ""
def test_empty_password_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        Settings(app_password="  ")
