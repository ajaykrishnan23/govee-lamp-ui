import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from lamp.ai.agent import PromptAgent
from lamp.ai.budget import Budget
from tests.fakes import FakeSong, make_controller


def usage(i=100, o=20):
    return NS(input_tokens=i, output_tokens=o, input_tokens_details=NS(cached_tokens=0))


def call(tool, call_id="c1", **args):
    return NS(type="function_call", name=tool, arguments=json.dumps(args), call_id=call_id)


def resp(*items, text=""):
    return NS(output=list(items), output_text=text, usage=usage())


class FakeClient:
    def __init__(self, *responses, error=None):
        self.responses_q = list(responses)
        self.calls: list[dict] = []
        self.error = error
        self.responses = self

    async def create(self, **kw):
        self.calls.append({**kw, "input": list(kw.get("input", []))})
        if self.error:
            raise self.error
        return self.responses_q.pop(0)


async def make_agent(tmp_path, client, cap=10.0, song=None):
    ctl, t, _ = await make_controller(tmp_path, song)
    budget = Budget(tmp_path / "usage.jsonl", cap)
    return PromptAgent(client, "gpt-6-luna", ctl, budget), ctl, t, budget


async def test_mood_prompt_calls_set_lights_and_replies(tmp_path):
    client = FakeClient(
        resp(call("set_lights", target="all", rgb=[255, 140, 60], brightness=35)),
        resp(text="Warm and low, cozy vibes."),
    )
    agent, ctl, _, budget = await make_agent(tmp_path, client)
    r = await agent.handle("warm cozy cuddly lights")
    assert r.reply == "Warm and low, cozy vibes."
    assert r.error is None and r.actions and "set_lights" in r.actions[0]
    assert ctl.lamp.state()["top"].rgb == (255, 140, 60)
    assert budget.month_to_date() > 0
    sent_output = client.calls[1]["input"][-1]
    assert sent_output["type"] == "function_call_output" and sent_output["call_id"] == "c1"


async def test_system_prompt_has_lamp_context(tmp_path):
    client = FakeClient(resp(text="ok"))
    agent, *_ = await make_agent(tmp_path, client)
    await agent.handle("hi")
    instructions = client.calls[0]["instructions"]
    assert "paper" in instructions and "campfire" in instructions and "top" in instructions
    assert client.calls[0]["model"] == "gpt-6-luna"


async def test_save_preset_tool_persists(tmp_path):
    client = FakeClient(
        resp(call("save_preset", name="deep focus", from_current=False,
                  static={"all": {"kelvin": 5000, "brightness": 85}})),
        resp(text="Saved."),
    )
    agent, ctl, *_ = await make_agent(tmp_path, client)
    await agent.handle("save a deep focus mode")
    assert ctl.presets.get("deep focus").static["all"]["kelvin"] == 5000


async def test_save_preset_from_current(tmp_path):
    client = FakeClient(resp(call("save_preset", name="mine", from_current=True)), resp(text="Saved."))
    agent, ctl, *_ = await make_agent(tmp_path, client)
    ctl.lamp.apply("all", {"rgb": (9, 8, 7)})
    await agent.handle("save this as mine")
    assert ctl.presets.get("mine").static["top"]["rgb"] == [9, 8, 7]


async def test_run_effect_tool(tmp_path):
    tl = {"cues": [{"t_ms": 0, "rgb": [10, 20, 30], "brightness": 50, "fade_ms": 1000}], "duration_ms": 2000, "loop": True}
    client = FakeClient(resp(call("run_effect", timeline=tl)), resp(text="Breathing."))
    agent, ctl, *_ = await make_agent(tmp_path, client)
    await agent.handle("breathe")
    assert ctl.activity.kind == "effect"
    await ctl.activity.stop()


async def test_light_tool_stops_song_mode(tmp_path):
    song = FakeSong(on=True)
    client = FakeClient(resp(call("set_lights", target="all", kelvin=3000)), resp(text="ok"))
    agent, *_ = await make_agent(tmp_path, client, song=song)
    await agent.handle("warm white please")
    assert song.on is False


async def test_budget_blocked_skips_api(tmp_path):
    client = FakeClient(resp(text="never"))
    agent, *_ = await make_agent(tmp_path, client, cap=0.0)
    r = await agent.handle("make it cozy")
    assert r.error == "budget" and "budget" in r.reply.lower()
    assert client.calls == []


async def test_agent_api_error_reports_and_leaves_lights(tmp_path):
    err = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    client = FakeClient(error=err)
    agent, ctl, t, _ = await make_agent(tmp_path, client)
    r = await agent.handle("make it cozy")
    assert r.error and t.sent == []


async def test_invalid_tool_args_return_tool_error_to_model(tmp_path):
    client = FakeClient(
        resp(call("set_lights", target="all", rgb=[300, 0, 0])),
        resp(call("set_lights", call_id="c2", target="all", rgb=[255, 0, 0])),
        resp(text="Red."),
    )
    agent, ctl, *_ = await make_agent(tmp_path, client)
    r = await agent.handle("red")
    first_out = client.calls[1]["input"][-1]
    assert first_out["type"] == "function_call_output" and "error" in first_out["output"].lower()
    assert ctl.lamp.state()["top"].rgb == (255, 0, 0)
    assert r.reply == "Red."


async def test_loop_capped(tmp_path):
    client = FakeClient(*[resp(call("list_presets", call_id=f"c{i}")) for i in range(10)])
    agent, *_ = await make_agent(tmp_path, client)
    r = await agent.handle("loop forever")
    assert len(client.calls) == 6
    assert r.reply
