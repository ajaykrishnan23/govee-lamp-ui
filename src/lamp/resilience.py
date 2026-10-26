"""Living on a laptop: keep awake during effects, recover after sleep, start at login."""
import logging
import os
import plistlib
import subprocess
import time
from pathlib import Path
from typing import Callable

from .effects import ActivityManager
from .lamp import Lamp

log = logging.getLogger(__name__)

AGENT_LABEL = "com.ajay.lamp"


class KeepAwake:
    """Holds a `caffeinate -i` assertion while an effect is running."""

    def __init__(self, popen: Callable = subprocess.Popen, pid: int | None = None):
        self._popen = popen
        self._pid = pid or os.getpid()
        self._proc = None

    def on_kind(self, kind: str) -> None:
        if kind != "idle" and self._proc is None:
            self._proc = self._popen(["caffeinate", "-i", "-w", str(self._pid)])
        elif kind == "idle" and self._proc is not None:
            self._proc.terminate()
            self._proc = None


class WakeWatcher:
    """Spots sleep: wall-clock time jumps while monotonic time (paused in sleep on macOS) doesn't."""

    def __init__(self, jump_threshold_s: float = 20, wall=time.time, mono=time.monotonic):
        self.threshold = jump_threshold_s
        self._wall, self._mono = wall, mono
        self._last = (wall(), mono())

    def check(self) -> float | None:
        now = (self._wall(), self._mono())
        jump = (now[0] - self._last[0]) - (now[1] - self._last[1])
        self._last = now
        return jump if jump > self.threshold else None


async def handle_wake(lamp: Lamp, activity: ActivityManager, jump_s: float) -> None:
    log.info("woke up after ~%.0fs asleep; rediscovering bulbs", jump_s)
    try:
        await lamp.refresh()
    except Exception:
        log.exception("rediscovery after wake failed")
    if activity.kind == "effect":
        # timed effects (e.g. a 20-minute fade) should have kept going while we slept
        activity.skip(jump_s * 1000)
        activity.step()


def agent_plist(repo: Path, uv: str) -> bytes:
    return plistlib.dumps({
        "Label": AGENT_LABEL,
        "ProgramArguments": [uv, "run", "lamp", "serve"],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(repo / "data" / "lamp.log"),
        "StandardErrorPath": str(repo / "data" / "lamp.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
    })


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
