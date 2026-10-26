"""The lamp: named bulbs (bound by MAC), cached light state, diffed sends."""
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .govee.protocol import BulbInfo, brightness_msg, color_msg, kelvin_msg, turn_msg

log = logging.getLogger(__name__)

SKU = "H6006"
DEFAULT_NAMES = ["top", "bottom"]
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class LightState:
    on: bool = True
    rgb: RGB | None = None
    kelvin: int | None = None
    brightness: int = 100

    def merged(self, patch: dict) -> "LightState":
        s = replace(self, **{k: v for k, v in patch.items() if k in ("on", "brightness") and v is not None})
        if patch.get("rgb") is not None:
            s = replace(s, rgb=tuple(patch["rgb"]), kelvin=None)
        elif patch.get("kelvin") is not None:
            s = replace(s, kelvin=int(patch["kelvin"]), rgb=None)
        return s

    def to_dict(self) -> dict:
        return {"on": self.on, "rgb": self.rgb, "kelvin": self.kelvin, "brightness": self.brightness}


class Lamp:
    def __init__(self, transport, registry_path: Path, discover_fn=None):
        self._t = transport
        self._path = registry_path
        self._discover = discover_fn or transport.discover
        self._names: dict[str, str] = self._load()  # name -> mac, in display order
        self._ips: dict[str, str] = {}  # mac -> ip
        self._state: dict[str, LightState] = {}
        self._listeners: list[Callable[[dict[str, LightState]], None]] = []

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._names, indent=2))

    async def refresh(self) -> None:
        found: list[BulbInfo] = [b for b in await self._discover() if b.sku == SKU]
        known = set(self._names.values())
        for b in sorted(found, key=lambda b: b.mac):
            if b.mac not in known:
                taken = set(self._names)
                name = next(n for n in DEFAULT_NAMES + [f"bulb{i}" for i in range(3, 99)] if n not in taken)
                self._names[name] = b.mac
            self._ips[b.mac] = b.ip
        self._save()
        # re-read every bulb: one may have been power-cycled since we last looked
        found_macs = {b.mac for b in found}
        for name, mac in self._names.items():
            if mac in found_macs:
                st = await self._t.query_status(self._ips[mac])
                if st:
                    self._state[name] = LightState(
                        on=st.on, brightness=st.brightness,
                        rgb=None if st.kelvin else st.rgb, kelvin=st.kelvin or None,
                    )
                else:
                    self._state.setdefault(name, LightState())
        self._emit()

    def names(self) -> list[str]:
        return [n for n, mac in self._names.items() if mac in self._ips]

    def rename(self, old: str, new: str) -> None:
        if old not in self._names or new in self._names:
            raise ValueError(f"cannot rename {old!r} to {new!r}")
        self._names = {(new if n == old else n): m for n, m in self._names.items()}
        if old in self._state:
            self._state[new] = self._state.pop(old)
        self._save()
        self._emit()

    def swap(self) -> None:
        a, b = list(self._names)[:2]
        self._names[a], self._names[b] = self._names[b], self._names[a]
        self._state[a], self._state[b] = self._state.get(b, LightState()), self._state.get(a, LightState())
        self._save()
        self._emit()

    def state(self) -> dict[str, LightState]:
        return {n: self._state.get(n, LightState()) for n in self.names()}

    def targets(self, target: str) -> list[str]:
        if target == "all":
            return self.names()
        if target not in self.names():
            raise ValueError(f"unknown bulb {target!r}; known: {self.names()}")
        return [target]

    def apply(self, target: str, patch: dict, force: bool = False) -> None:
        """Change bulbs. Only changed fields are sent, unless `force` (a user's explicit
        command) resends every field in the patch in case the cache is stale."""
        for name in self.targets(target):
            old = self._state.get(name, LightState())
            new = old.merged(patch)
            ip = self._ips[self._names[name]]
            if new.on != old.on or (force and "on" in patch):
                self._t.send_latest(ip, "power", turn_msg(new.on))
            if new.brightness != old.brightness or (force and "brightness" in patch):
                self._t.send_latest(ip, "brightness", brightness_msg(new.brightness))
            if (new.rgb, new.kelvin) != (old.rgb, old.kelvin) or (force and ("rgb" in patch or "kelvin" in patch)):
                if new.rgb is not None:
                    self._t.send_latest(ip, "color", color_msg(*new.rgb))
                elif new.kelvin is not None:
                    self._t.send_latest(ip, "color", kelvin_msg(new.kelvin))
            self._state[name] = new
        self._emit()

    def on_change(self, cb: Callable[[dict[str, LightState]], None]) -> None:
        self._listeners.append(cb)

    def _emit(self) -> None:
        snapshot = self.state()
        for cb in self._listeners:
            try:
                cb(snapshot)
            except Exception:
                log.exception("lamp listener failed")
