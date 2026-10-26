"""Timelines of light cues, and the single-activity runner that plays them."""
import asyncio
import logging
import math
import time
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, Field

from .lamp import Lamp, LightState

log = logging.getLogger(__name__)

Channel = Field(ge=0, le=255)
Kind = Literal["idle", "effect", "song"]


class Cue(BaseModel):
    t_ms: int = Field(ge=0)
    target: str = "all"
    rgb: tuple[int, int, int] | None = None
    kelvin: int | None = Field(default=None, ge=2000, le=9000)
    brightness: int | None = Field(default=None, ge=1, le=100)
    on: bool | None = None
    fade_ms: int = Field(default=0, ge=0)

    def model_post_init(self, _):
        if self.rgb is not None and not all(0 <= c <= 255 for c in self.rgb):
            raise ValueError("rgb channels must be 0-255")


class Timeline(BaseModel):
    cues: list[Cue]
    duration_ms: int = Field(gt=0)
    loop: bool = False


def kelvin_to_rgb(k: int) -> tuple[int, int, int]:
    """Approximate blackbody color (Tanner Helland's fit)."""
    t = k / 100
    if t <= 66:
        r, g = 255, 99.47 * math.log(t) - 161.12
        b = 0 if t <= 19 else 138.52 * math.log(t - 10) - 305.04
    else:
        r, g, b = 329.70 * (t - 60) ** -0.1332, 288.12 * (t - 60) ** -0.0755, 255
    return tuple(max(0, min(255, round(c))) for c in (r, g, b))


def _lerp(a: float, b: float, f: float) -> int:
    return round(a + (b - a) * f)


def _blend(a: LightState, b: LightState, f: float) -> LightState:
    if a.kelvin is not None and b.kelvin is not None:
        color = {"kelvin": _lerp(a.kelvin, b.kelvin, f), "rgb": None}
    elif a.rgb is None and a.kelvin is None:
        color = {"rgb": b.rgb, "kelvin": b.kelvin}
    else:
        ca = a.rgb if a.rgb is not None else kelvin_to_rgb(a.kelvin)
        cb = b.rgb if b.rgb is not None else kelvin_to_rgb(b.kelvin)
        color = {"rgb": tuple(_lerp(x, y, f) for x, y in zip(ca, cb)), "kelvin": None}
    # turning on happens at the start of a fade, turning off at the end
    on = b.on if b.on else a.on
    return LightState(on=on, brightness=_lerp(a.brightness, b.brightness, f), **color)


def state_at(timeline: Timeline, t_ms: float, start: dict[str, LightState]) -> dict[str, LightState]:
    if timeline.loop:
        t_ms %= timeline.duration_ms
    cues = sorted(timeline.cues, key=lambda c: c.t_ms)
    out = {}
    for name, cur in start.items():
        for c in cues:
            if c.t_ms > t_ms:
                break
            if c.target not in ("all", name):
                continue
            target = cur.merged(c.model_dump(include={"rgb", "kelvin", "brightness", "on"}))
            if c.fade_ms and t_ms < c.t_ms + c.fade_ms:
                cur = _blend(cur, target, (t_ms - c.t_ms) / c.fade_ms)
            else:
                cur = target
        out[name] = cur
    return out


class Clock(Protocol):
    def now_ms(self) -> float: ...


class MonotonicClock:
    def now_ms(self) -> float:
        return time.monotonic() * 1000


class ActivityManager:
    def __init__(self, lamp: Lamp, clock: Clock, tick_hz: float):
        self.lamp = lamp
        self.clock = clock
        self.tick = 1.0 / tick_hz
        self.kind: Kind = "idle"
        self._timeline: Timeline | None = None
        self._start: dict[str, LightState] = {}
        self._t0 = 0.0
        self._position_fn: Callable[[], float] | None = None
        self._task: asyncio.Task | None = None
        self._listeners: list[Callable[[str], None]] = []

    def on_kind_change(self, cb: Callable[[str], None]) -> None:
        self._listeners.append(cb)

    def _set_kind(self, kind: Kind) -> None:
        if kind != self.kind:
            self.kind = kind
            for cb in self._listeners:
                try:
                    cb(kind)
                except Exception:
                    log.exception("activity listener failed")

    def position_ms(self) -> float:
        return self._position_fn() if self._position_fn else self.clock.now_ms() - self._t0

    async def play(self, timeline: Timeline, kind: Kind = "effect",
                   position_fn: Callable[[], float] | None = None, start_loop: bool = True) -> None:
        await self.stop()
        self._timeline = timeline
        self._start = self.lamp.state()
        self._t0 = self.clock.now_ms()
        self._position_fn = position_fn
        self._set_kind(kind)
        if start_loop:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._timeline = None
        self._set_kind("idle")

    def step(self) -> bool:
        """Apply the timeline at the current position. Returns False once finished."""
        tl = self._timeline
        if tl is None:
            return False
        pos = self.position_ms()
        done = not tl.loop and pos >= tl.duration_ms
        for name, s in state_at(tl, min(pos, tl.duration_ms), self._start).items():
            color = {"rgb": s.rgb} if s.rgb is not None else {"kelvin": s.kelvin}
            try:
                self.lamp.apply(name, {"on": s.on, "brightness": s.brightness, **color})
            except ValueError:
                pass  # bulb vanished mid-effect
        if done:
            self._timeline = None
            self._set_kind("idle")
        return not done

    async def _run(self) -> None:
        try:
            while self.step():
                await asyncio.sleep(self.tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("effect crashed")
            self._timeline = None
            self._set_kind("idle")
        finally:
            if self._task is asyncio.current_task():
                self._task = None
