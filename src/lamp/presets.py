"""Named light setups: built-in moods plus ones saved by Ajay or the AI."""
import builtins
import json
import re
from pathlib import Path

from pydantic import BaseModel

from .effects import Cue, Timeline


class Preset(BaseModel):
    name: str
    description: str = ""
    static: dict[str, dict] | None = None  # bulb name or "all" -> LightState patch
    timeline: Timeline | None = None
    builtin: bool = False

    def model_post_init(self, _):
        if (self.static is None) == (self.timeline is None):
            raise ValueError("a preset needs exactly one of static or timeline")


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _loop(duration_ms: int, cues: list[Cue]) -> Timeline:
    return Timeline(cues=cues, duration_ms=duration_ms, loop=True)


BUILTINS: list[Preset] = [
    Preset(name="warm white", description="Plain warm white.",
           static={"all": {"on": True, "kelvin": 2700, "brightness": 80}}),
    Preset(name="reading", description="Bright neutral white for reading.",
           static={"all": {"on": True, "kelvin": 4000, "brightness": 100}}),
    Preset(name="study", description="Steady cool-neutral light for focus.",
           static={"all": {"on": True, "kelvin": 4500, "brightness": 90}}),
    Preset(name="sunset", description="Amber at the bottom fading into magenta at the top.",
           static={"bottom": {"on": True, "rgb": (255, 110, 20), "brightness": 70},
                   "top": {"on": True, "rgb": (200, 40, 120), "brightness": 60}}),
    Preset(name="campfire", description="Warm orange flicker.", timeline=_loop(4000, [
        Cue(t_ms=0, on=True, rgb=(255, 90, 10), brightness=55, fade_ms=300),
        Cue(t_ms=400, target="top", rgb=(255, 70, 5), brightness=40, fade_ms=500),
        Cue(t_ms=700, target="bottom", rgb=(255, 120, 20), brightness=65, fade_ms=400),
        Cue(t_ms=1300, rgb=(255, 80, 8), brightness=48, fade_ms=600),
        Cue(t_ms=2100, target="top", rgb=(255, 100, 15), brightness=58, fade_ms=500),
        Cue(t_ms=2600, target="bottom", rgb=(240, 60, 5), brightness=45, fade_ms=700),
        Cue(t_ms=3400, rgb=(255, 90, 10), brightness=55, fade_ms=500),
    ])),
    Preset(name="ocean", description="Slow blue and teal drift.", timeline=_loop(20_000, [
        Cue(t_ms=0, on=True, target="top", rgb=(0, 90, 255), brightness=60, fade_ms=5000),
        Cue(t_ms=0, on=True, target="bottom", rgb=(0, 200, 170), brightness=60, fade_ms=5000),
        Cue(t_ms=10_000, target="top", rgb=(0, 200, 170), fade_ms=9000),
        Cue(t_ms=10_000, target="bottom", rgb=(0, 90, 255), fade_ms=9000),
    ])),
    Preset(name="cozy", description="Low warm amber with a slow breathe.", timeline=_loop(8000, [
        Cue(t_ms=0, on=True, rgb=(255, 120, 40), brightness=45, fade_ms=4000),
        Cue(t_ms=4000, rgb=(255, 100, 30), brightness=25, fade_ms=4000),
    ])),
    Preset(name="party", description="Fast color cycle, top and bottom offset.", timeline=_loop(4000, [
        Cue(t_ms=i * 500, on=True, target=bulb, rgb=rgb, brightness=100, fade_ms=400)
        for i, rgb in enumerate([(255, 0, 80), (255, 140, 0), (0, 220, 120), (0, 120, 255),
                                 (160, 0, 255), (255, 0, 160), (255, 220, 0), (0, 255, 220)])
        for bulb, rgb in (("top", rgb), ("bottom", rgb[::-1]))
    ])),
    Preset(name="night light", description="Very dim red-amber.",
           static={"all": {"on": True, "rgb": (255, 60, 0), "brightness": 5}}),
]
for _p in BUILTINS:
    _p.builtin = True
_BUILTIN_KEYS = {_key(p.name): p for p in BUILTINS}


class PresetStore:
    def __init__(self, path: Path):
        self._path = path
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            raw = []
        self._saved: dict[str, Preset] = {_key(p["name"]): Preset(**p) for p in raw}

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([p.model_dump(mode="json") for p in self._saved.values()], indent=2))

    def list(self) -> list[Preset]:
        return BUILTINS + list(self._saved.values())

    def names(self) -> "builtins.list[str]":
        return [p.name for p in self.list()]

    def get(self, name: str) -> Preset | None:
        k = _key(name)
        return _BUILTIN_KEYS.get(k) or self._saved.get(k)

    def save(self, p: Preset) -> None:
        if _key(p.name) in _BUILTIN_KEYS:
            raise ValueError(f"{p.name!r} is a built-in mood; pick another name")
        self._saved[_key(p.name)] = p.model_copy(update={"builtin": False})
        self._write()

    def delete(self, name: str) -> None:
        if _key(name) in _BUILTIN_KEYS:
            raise ValueError("built-in moods can't be deleted")
        self._saved.pop(_key(name), None)
        self._write()
