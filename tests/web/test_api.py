import json

from tests.fakes import FakeSong
from tests.web.conftest import SECRET_VALUES


async def test_api_requires_login(app_env):
    client, _, _ = app_env
    assert (await client.get("/api/state")).status_code == 401
    r = await client.get("/")
    assert r.status_code in (302, 303, 307) and r.headers["location"].startswith("/login")


async def test_login_wrong_password_401(app_env):
    client, _, _ = app_env
    assert (await client.post("/login", json={"password": "nope"})).status_code == 401


async def test_login_sets_cookie(app_env):
    client, _, _ = app_env
    r = await client.post("/login", json={"password": "pw-123"})
    assert r.status_code == 200 and "lamp_session" in r.cookies
    assert (await client.get("/api/state")).status_code == 200


async def test_state_shape(authed):
    client, _, _ = authed
    s = (await client.get("/api/state")).json()
    assert set(s) >= {"bulbs", "activity", "presets", "budget", "song"}
    assert set(s["bulbs"]) == {"top", "bottom"}


async def test_state_never_contains_secrets(authed):
    client, _, _ = authed
    body = (await client.get("/api/state")).text
    assert not any(v in body for v in SECRET_VALUES)


async def test_power_brightness_color(authed):
    client, svc, _ = authed
    await client.post("/api/power", json={"target": "all", "on": False})
    assert not svc.lamp.state()["top"].on
    await client.post("/api/brightness", json={"target": "top", "value": 33})
    assert svc.lamp.state()["top"].brightness == 33
    await client.post("/api/color", json={"target": "bottom", "rgb": [1, 2, 3]})
    assert svc.lamp.state()["bottom"].rgb == (1, 2, 3)
    await client.post("/api/color", json={"target": "bottom", "kelvin": 3000})
    assert svc.lamp.state()["bottom"].kelvin == 3000


async def test_bad_target_is_400(authed):
    client, _, _ = authed
    assert (await client.post("/api/power", json={"target": "middle", "on": True})).status_code == 400


async def test_prompt_instant_off_does_not_call_ai(authed, ai):
    client, svc, _ = authed
    r = (await client.post("/api/prompt", json={"text": "lights off"})).json()
    assert r["via"] == "instant"
    assert ai.calls == []
    assert not svc.lamp.state()["top"].on


async def test_prompt_mood_goes_to_ai(authed, ai):
    client, _, _ = authed
    r = (await client.post("/api/prompt", json={"text": "warm cozy cuddly lights"})).json()
    assert r["via"] == "ai" and r["reply"] == "Cozy."
    assert len(ai.calls) == 1


async def test_preset_routes(authed):
    client, svc, _ = authed
    assert (await client.post("/api/preset/sunset")).status_code == 200
    assert svc.lamp.state()["top"].rgb == (200, 40, 120)
    assert (await client.post("/api/preset/nope")).status_code == 404
    assert (await client.delete("/api/preset/sunset")).status_code == 400


async def test_quick_control_stops_song_mode(authed):
    client, svc, _ = authed
    song = FakeSong(on=True)
    svc.ctl.song = song
    await client.post("/api/power", json={"target": "all", "on": True})
    assert song.on is False


async def test_bulb_rename_and_swap(authed):
    client, svc, _ = authed
    await client.post("/api/bulbs/rename", json={"old": "top", "new": "upper"})
    assert svc.lamp.names() == ["upper", "bottom"]
    assert (await client.post("/api/bulbs/swap")).status_code == 200


async def test_events_published_after_change(authed):
    client, svc, _ = authed
    q = svc.bus.listen()
    await client.post("/api/brightness", json={"target": "all", "value": 12})
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    states = [json.loads(e["data"]) for e in events if e["type"] == "state"]
    assert states and states[-1]["top"]["brightness"] == 12


async def test_event_stream_format(authed):
    _, svc, _ = authed
    gen = svc.bus.subscribe(initial=[("hello", {"a": 1})])
    first = await gen.__anext__()
    assert first == 'event: hello\ndata: {"a": 1}\n\n'
    await gen.aclose()


async def test_voice_endpoint_transcribes_then_prompts(authed, transcriber, ai):
    client, svc, _ = authed
    r = await client.post("/api/voice", files={"audio": ("clip.m4a", b"\x00" * 1000, "audio/mp4")})
    body = r.json()
    assert r.status_code == 200
    assert body["text"] == "lights off" and body["via"] == "instant"
    assert ai.calls == []
    assert not transcriber.paths[0].exists()  # temp clip cleaned up


async def test_voice_rejects_oversize(authed):
    client, _, _ = authed
    r = await client.post("/api/voice", files={"audio": ("clip.m4a", b"\x00" * (2 * 1024 * 1024 + 1), "audio/mp4")})
    assert r.status_code == 413


async def test_voice_empty_transcript(authed, transcriber):
    client, _, _ = authed
    transcriber.text = "  "
    r = await client.post("/api/voice", files={"audio": ("clip.webm", b"\x00" * 10, "audio/webm")})
    assert r.status_code == 200 and r.json()["error"] == "heard nothing"
