"""One place that turns user intents into lamp changes (used by the API and the AI)."""
import asyncio
from typing import Protocol

from .commands import Command
from .effects import ActivityManager, Cue, Timeline
from .lamp import Lamp
from .presets import Preset, PresetStore

STEP = 20


class SongControl(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def redo(self, instruction: str) -> None: ...
    def status(self) -> dict: ...


class NoSong:
    """Placeholder until song mode exists."""

    async def start(self) -> None:
        raise RuntimeError("song mode isn't set up yet")

    async def stop(self) -> None:
        pass

    async def redo(self, instruction: str) -> None:
        raise RuntimeError("song mode isn't set up yet")

    def status(self) -> dict:
        return {"on": False, "state": "unavailable"}


class Controller:
    def __init__(self, lamp: Lamp, activity: ActivityManager, presets: PresetStore, song: SongControl):
        self.lamp = lamp
        self.activity = activity
        self.presets = presets
        self.song = song
        # one change at a time, in arrival order, so rapid taps resolve "last tap wins"
        self._lock = asyncio.Lock()

    async def _take_over(self) -> None:
        if self.song.status().get("on"):
            await self.song.stop()
        await self.activity.stop()

    async def set(self, target: str, patch: dict, fade_ms: int = 0) -> None:
        self.lamp.targets(target)  # validate before stopping anything
        async with self._lock:
            await self._take_over()
            if fade_ms > 0:
                await self.activity.play(Timeline(cues=[Cue(t_ms=0, target=target, fade_ms=fade_ms, **patch)],
                                                  duration_ms=fade_ms))
            else:
                self.lamp.apply(target, patch, force=True)

    async def run_timeline(self, timeline: Timeline) -> None:
        async with self._lock:
            await self._take_over()
            await self.activity.play(timeline)

    async def apply_preset(self, p: Preset) -> None:
        if p.timeline:
            await self.run_timeline(p.timeline)
            return
        async with self._lock:
            await self._take_over()
            for target, patch in p.static.items():
                if target == "all" or target in self.lamp.names():
                    self.lamp.apply(target, patch, force=True)

    async def stop(self) -> None:
        async with self._lock:
            await self._take_over()

    async def start_song(self) -> str:
        if self.song.status().get("state") == "unavailable":
            return "Music sync isn't set up yet."
        async with self._lock:
            await self.activity.stop()
            await self.song.start()
        return "Syncing to your music."

    async def run_command(self, cmd: Command) -> str:
        match cmd.kind:
            case "on" | "off":
                await self.set("all", {"on": cmd.kind == "on"})
                return f"Lights {cmd.kind}."
            case "brightness":
                await self.set("all", {"on": True, "brightness": int(cmd.value)})
                return f"Brightness {cmd.value}%."
            case "brighter" | "dimmer":
                cur = max((s.brightness for s in self.lamp.state().values()), default=50)
                new = max(1, min(100, cur + (STEP if cmd.kind == "brighter" else -STEP)))
                await self.set("all", {"on": True, "brightness": new})
                return f"Brightness {new}%."
            case "preset":
                p = self.presets.get(str(cmd.value))
                if not p:
                    return f"No mood called {cmd.value!r}."
                await self.apply_preset(p)
                return f"{p.name.capitalize()}."
            case "stop":
                await self.stop()
                return "Stopped."
            case "song_on":
                return await self.start_song()
            case "song_off":
                await self.song.stop()
                return "Music sync off."
        return "?"
