"""Wires the pieces together into a running app."""
import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

import openai

from .ai.agent import PromptAgent
from .ai.budget import Budget
from .commands import parse_command
from .config import Settings
from .control import Controller, NoSong
from .effects import ActivityManager, MonotonicClock
from .govee.transport import GoveeTransport
from .lamp import Lamp
from .presets import PresetStore
from .voice import Transcriber
from .web.app import create_app
from .web.auth import SessionSigner
from .web.events import EventBus

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    transport: object
    lamp: Lamp
    activity: ActivityManager
    ctl: Controller
    agent: PromptAgent
    budget: Budget
    bus: EventBus
    signer: SessionSigner
    transcriber: object

    def snapshot(self) -> dict:
        return {
            "bulbs": {n: s.to_dict() for n, s in self.lamp.state().items()},
            "activity": self.activity.kind,
            "presets": [{"name": p.name, "description": p.description, "builtin": p.builtin}
                        for p in self.ctl.presets.list()],
            "budget": self.budget.status(),
            "song": self.ctl.song.status(),
        }

    def publish_state(self) -> None:
        self.bus.publish("snapshot", self.snapshot())

    async def handle_prompt(self, text: str) -> dict:
        cmd = parse_command(text, self.ctl.presets.names())
        if cmd:
            reply = await self.ctl.run_command(cmd)
            out = {"reply": reply, "actions": [cmd.kind], "error": None, "via": "instant"}
        else:
            r = await self.agent.handle(text)
            out = {"reply": r.reply, "actions": r.actions, "error": r.error, "via": "ai"}
            self.bus.publish("budget", self.budget.status())
            self.publish_state()  # presets may have changed
        self.bus.publish("log", {"text": text, **out})
        return out


def build_services(settings: Settings, transport=None, ai_client=None, discover_fn=None,
                   transcriber=None) -> Services:
    d = settings.data_dir
    transport = transport or GoveeTransport(settings.max_updates_per_sec)
    lamp = Lamp(transport, d / "bulbs.json", discover_fn=discover_fn)
    activity = ActivityManager(lamp, MonotonicClock(), tick_hz=settings.max_updates_per_sec)
    ctl = Controller(lamp, activity, PresetStore(d / "presets.json"), NoSong())
    budget = Budget(d / "usage.jsonl", settings.monthly_budget_usd)
    client = ai_client or openai.AsyncOpenAI(api_key=settings.openai_api_key or "missing", timeout=60)
    agent = PromptAgent(client, settings.prompt_model, ctl, budget)
    bus = EventBus()
    svc = Services(settings, transport, lamp, activity, ctl, agent, budget, bus,
                   SessionSigner(d / "secret.key", settings.app_password), transcriber or Transcriber())
    lamp.on_change(lambda s: bus.publish("state", {n: v.to_dict() for n, v in s.items()}))
    activity.on_kind_change(lambda k: bus.publish("activity", {"kind": k}))
    return svc


def build_app(settings: Settings, **overrides):
    svc = build_services(settings, **overrides)

    @asynccontextmanager
    async def lifespan(app):
        if hasattr(svc.transport, "start"):
            await svc.transport.start()
        try:
            await svc.lamp.refresh()
        except Exception:
            log.exception("initial bulb discovery failed")
        if hasattr(svc.transcriber, "_load"):  # warm the fallback model so the first voice clip isn't slow
            asyncio.get_running_loop().run_in_executor(None, svc.transcriber._load)
        yield
        await svc.activity.stop()
        if hasattr(svc.transport, "close"):
            await svc.transport.close()

    return create_app(svc, lifespan=lifespan), svc
