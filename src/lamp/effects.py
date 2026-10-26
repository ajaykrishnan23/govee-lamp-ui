"""Timelines of light cues, and the single-activity runner that plays them."""
import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, Field

from .lamp import Lamp, LightState

log = logging.getLogger(__name__)

Channel = Field(ge=0, le=255)
Kind = Literal["idle", "effect"]


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
    if timeline.loop and t_ms >= timeline.duration_ms:
        # later passes continue from where the loop ended, not from the pre-effect look
        start = state_at(timeline.model_copy(update={"loop": False}), timeline.duration_ms, start)
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


@dataclass
class _Glide:
    """A bulb's smoothed output, kept in floats so tiny per-tick steps aren't rounded away."""
    on: bool
    rgb: list[float]
    brightness: float
    kelvin: float | None = None  # set only while gliding between two whites


def _toward(cur: float, target: float, max_step: float) -> float:
    return target if abs(target - cur) <= max_step else cur + max_step * (1 if target > cur else -1)


@dataclass
class Smoothing:
    """Anti-flicker guard for every animation: caps how fast brightness and color may change,
    so sudden jumps and strobes become gentle glides no matter how a timeline is written."""
    brightness_per_s: float = 20.0
    color_per_s: float = 60.0
    kelvin_per_s: float = 1000.0

    def start(self, s: LightState) -> _Glide:
        rgb = list(s.rgb) if s.rgb is not None else list(kelvin_to_rgb(s.kelvin or 2700))
        return _Glide(on=s.on, rgb=rgb, brightness=float(s.brightness) if s.on else 1.0, kelvin=s.kelvin)

    def step(self, g: _Glide, target: LightState, dt: float) -> _Glide:
        want_b = float(target.brightness) if target.on else 1.0
        if target.on and not g.on:
            g = _Glide(on=True, rgb=g.rgb, brightness=1.0, kelvin=g.kelvin)  # fade in from dark
        b = _toward(g.brightness, want_b, self.brightness_per_s * dt)
        if target.kelvin is not None and g.kelvin is not None:
            k = _toward(g.kelvin, target.kelvin, self.kelvin_per_s * dt)
            rgb = list(kelvin_to_rgb(round(k)))
        else:
            k = None
            want = target.rgb if target.rgb is not None else kelvin_to_rgb(target.kelvin or 2700)
            rgb = [_toward(c, w, self.color_per_s * dt) for c, w in zip(g.rgb, want)]
        on = target.on or b > 1.0  # glide down before switching off
        return _Glide(on=on, rgb=rgb, brightness=b, kelvin=k)

    @staticmethod
    def output(g: _Glide, target: LightState) -> LightState:
        if g.kelvin is not None:
            return LightState(on=g.on, kelvin=round(g.kelvin), brightness=round(g.brightness))
        rgb = tuple(round(c) for c in g.rgb)
        if target.kelvin is not None and target.rgb is None and rgb == kelvin_to_rgb(target.kelvin):
            return LightState(on=g.on, kelvin=target.kelvin, brightness=round(g.brightness))
        return LightState(on=g.on, rgb=rgb, brightness=round(g.brightness))

    @staticmethod
    def arrived(out: LightState, target: LightState) -> bool:
        return out == target or (not target.on and not out.on)


class Clock(Protocol):
    def now_ms(self) -> float: ...


class MonotonicClock:
    def now_ms(self) -> float:
        return time.monotonic() * 1000


class ActivityManager:
    def __init__(self, lamp: Lamp, clock: Clock, tick_hz: float, smoothing: Smoothing | None = Smoothing()):
        self.lamp = lamp
        self.clock = clock
        self.tick = 1.0 / tick_hz
        self.smoothing = smoothing
        self._glides: dict[str, _Glide] = {}
        self._last_step_ms: float | None = None
        self.kind: Kind = "idle"
        self._timeline: Timeline | None = None
        self._start: dict[str, LightState] = {}
        self._t0 = 0.0
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

    def skip(self, ms: float) -> None:
        """Move the playhead forward (used after the Mac wakes from sleep)."""
        self._t0 -= ms

    def position_ms(self) -> float:
        return self.clock.now_ms() - self._t0

    async def play(self, timeline: Timeline, kind: Kind = "effect", start_loop: bool = True) -> None:
        await self.stop()
        self._timeline = timeline
        self._start = self.lamp.state()
        self._t0 = self.clock.now_ms()
        self._glides = {}
        self._last_step_ms = None
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
        now = self.clock.now_ms()
        dt = 0.0 if self._last_step_ms is None else max(0.0, min(1.0, (now - self._last_step_ms) / 1000))
        self._last_step_ms = now
        # looping timelines wrap inside state_at; one-shot ones stop at their end
        t = pos if tl.loop else min(pos, tl.duration_ms)
        caught_up = True
        for name, s in state_at(tl, t, self._start).items():
            if self.smoothing:
                g = self._glides.get(name) or self.smoothing.start(self.lamp.state().get(name, s))
                g = self._glides[name] = self.smoothing.step(g, s, dt)
                out = self.smoothing.output(g, s)
                caught_up &= self.smoothing.arrived(out, s)
            else:
                out = s
            color = {"rgb": out.rgb} if out.rgb is not None else {"kelvin": out.kelvin}
            try:
                self.lamp.apply(name, {"on": out.on, "brightness": out.brightness, **color})
            except ValueError:
                pass  # bulb vanished mid-effect
        done = not tl.loop and pos >= tl.duration_ms and caught_up
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
