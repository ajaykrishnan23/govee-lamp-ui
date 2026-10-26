"""Turns free-form prompts ("warm cozy cuddly lights") into light changes via OpenAI tool calls."""
import json
import logging
from dataclasses import dataclass, field

import openai
from pydantic import ValidationError

from ..control import Controller
from ..effects import Cue, Timeline
from ..presets import Preset
from .budget import Budget

log = logging.getLogger(__name__)

MAX_TURNS = 6

_RGB = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255}, "minItems": 3, "maxItems": 3}
_STATE = {
    "on": {"type": "boolean"},
    "rgb": _RGB,
    "kelvin": {"type": "integer", "minimum": 2000, "maximum": 9000, "description": "white color temperature; use instead of rgb"},
    "brightness": {"type": "integer", "minimum": 1, "maximum": 100},
}
_TARGET = {"type": "string", "description": "'all' or a bulb name"}
_CUE = {"type": "object", "properties": {
    "t_ms": {"type": "integer", "minimum": 0}, "target": _TARGET, **_STATE,
    "fade_ms": {"type": "integer", "minimum": 0, "description": "fade from the previous value over this long"},
}, "required": ["t_ms"]}
_TIMELINE = {"type": "object", "properties": {
    "cues": {"type": "array", "items": _CUE},
    "duration_ms": {"type": "integer", "minimum": 1},
    "loop": {"type": "boolean"},
}, "required": ["cues", "duration_ms"]}


def _fn(name: str, description: str, properties: dict, required: list[str] = ()) -> dict:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required)}}


TOOLS = [
    _fn("set_lights", "Set bulbs to a static look, optionally fading there.",
        {"target": _TARGET, **_STATE, "fade_ms": {"type": "integer", "minimum": 0}}, ["target"]),
    _fn("run_effect", "Play a timeline of cues (looping ambience, slow sunrise, timed fade-out, etc).",
        {"timeline": _TIMELINE}, ["timeline"]),
    _fn("save_preset", "Save a named mood. Use from_current=true to save exactly what the lamp shows now.",
        {"name": {"type": "string"}, "description": {"type": "string"}, "from_current": {"type": "boolean"},
         "static": {"type": "object", "description": "bulb name or 'all' -> {on, rgb, kelvin, brightness}"},
         "timeline": _TIMELINE}, ["name"]),
    _fn("load_preset", "Apply a saved or built-in mood by name.", {"name": {"type": "string"}}, ["name"]),
    _fn("list_presets", "List moods with descriptions.", {}),
    _fn("stop", "Stop any running effect or music sync, leaving the current look.", {}),
    _fn("start_song_mode", "Start syncing the lamp to whatever is playing on Spotify.", {}),
    _fn("stop_song_mode", "Stop syncing to music.", {}),
    _fn("redo_song_show", "Rewrite the light show for the current song.", {"instruction": {"type": "string"}}, ["instruction"]),
]

SYSTEM = """You control Ajay's lamp: a tall paper floor lamp with two Govee color bulbs inside, \
probably stacked ({names}). Both shine through the same paper shade, so they blend into one glowing \
column; two-tone looks (e.g. warm bottom, cooler top) and slow movement between bulbs read beautifully. \
Each bulb shows one color at a time.

Be creative with mood requests ("feel like studying", "warm cozy cuddly"): choose colors, brightness \
and how the two bulbs relate, and add gentle slow motion (run_effect with long fades, looping) where it \
fits the vibe. Prefer kelvin for whites. Never flash, strobe or flicker: Ajay finds it hard on \
the eyes. Every change should fade over at least 2 seconds. For timed requests ("fade off over 20 minutes") use fades.
If a look lands well or Ajay asks, save it with save_preset. Act first, then reply in one short, \
friendly sentence saying what you did.

Current state: {state}
Activity: {activity}. Music sync: {song}.
Moods: {presets}"""


@dataclass
class AgentResult:
    reply: str
    actions: list[str] = field(default_factory=list)
    error: str | None = None


class PromptAgent:
    def __init__(self, client, model: str, ctl: Controller, budget: Budget):
        self.client = client
        self.model = model
        self.ctl = ctl
        self.budget = budget

    def _instructions(self) -> str:
        c = self.ctl
        return SYSTEM.format(
            names=" and ".join(c.lamp.names()) or "no bulbs found",
            state=json.dumps({n: s.to_dict() for n, s in c.lamp.state().items()}),
            activity=c.activity.kind, song=c.song.status(),
            presets=", ".join(c.presets.names()),
        )

    async def handle(self, text: str) -> AgentResult:
        if not self.budget.can_spend():
            return AgentResult("AI budget reached — quick commands and moods still work.", error="budget")
        items: list = [{"role": "user", "content": text}]
        actions: list[str] = []
        for _ in range(MAX_TURNS):
            try:
                r = await self.client.responses.create(
                    model=self.model, instructions=self._instructions(), tools=TOOLS,
                    input=items, reasoning={"effort": "low"},
                )
            except openai.OpenAIError as e:
                log.warning("AI call failed: %s", e)
                return AgentResult(f"Couldn't reach the AI ({type(e).__name__}).", actions, error=str(e) or type(e).__name__)
            self._record_usage(getattr(r, "usage", None))
            calls = [it for it in r.output if it.type == "function_call"]
            if not calls:
                return AgentResult(r.output_text.strip() or "Done.", actions)
            items += [it.model_dump(exclude_none=True) if hasattr(it, "model_dump") else vars(it) for it in r.output]
            for c in calls:
                out = await self._run_tool(c.name, c.arguments)
                if not out.startswith("error"):
                    actions.append(f"{c.name} {c.arguments}")
                items.append({"type": "function_call_output", "call_id": c.call_id, "output": out})
        return AgentResult("Done." if actions else "I got stuck — try rephrasing?", actions)

    def _record_usage(self, u) -> None:
        if u is None:
            return
        details = getattr(u, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        self.budget.record(self.model, u.input_tokens or 0, cached, u.output_tokens or 0)

    async def _run_tool(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                return "error: arguments must be a JSON object"
            return await self._dispatch(name, args)
        except (ValidationError, ValueError, KeyError, TypeError, RuntimeError) as e:
            return f"error: {e}"
        except Exception as e:  # never let one tool take down the request
            log.exception("tool %s failed", name)
            return f"error: {type(e).__name__}: {e}"

    async def _dispatch(self, name: str, a: dict) -> str:
        c = self.ctl
        match name:
            case "set_lights":
                patch = {k: a[k] for k in ("on", "rgb", "kelvin", "brightness") if a.get(k) is not None}
                Cue(t_ms=0, target=a["target"], **patch)  # validates ranges
                await c.set(a["target"], patch, fade_ms=int(a.get("fade_ms") or 0))
                return "ok"
            case "run_effect":
                await c.run_timeline(Timeline.model_validate(a["timeline"]))
                return "playing"
            case "save_preset":
                if a.get("from_current"):
                    static = {n: s.to_dict() | {"rgb": list(s.rgb) if s.rgb else None}
                              for n, s in c.lamp.state().items()}
                    static = {n: {k: v for k, v in d.items() if v is not None} for n, d in static.items()}
                    p = Preset(name=a["name"], description=a.get("description", ""), static=static)
                else:
                    p = Preset.model_validate({k: a[k] for k in ("name", "description", "static", "timeline") if k in a})
                c.presets.save(p)
                return f"saved {p.name!r}"
            case "load_preset":
                p = c.presets.get(a["name"])
                if not p:
                    return f"error: no mood {a['name']!r}"
                await c.apply_preset(p)
                return "ok"
            case "list_presets":
                return json.dumps([{"name": p.name, "description": p.description} for p in c.presets.list()])
            case "stop":
                await c.stop()
                return "stopped"
            case "start_song_mode":
                return await c.start_song()
            case "stop_song_mode":
                await c.song.stop()
                return "stopped"
            case "redo_song_show":
                await c.song.redo(a["instruction"])
                return "rewriting"
        return f"error: unknown tool {name}"
