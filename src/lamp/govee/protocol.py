"""Pure builders/parsers for Govee LAN API messages.

See https://app-h5.govee.com/user-manual/wlan-guide
"""
import json
from dataclasses import dataclass

MULTICAST_GROUP = "239.255.255.250"
SCAN_PORT = 4001
LISTEN_PORT = 4002
CONTROL_PORT = 4003


@dataclass(frozen=True)
class BulbInfo:
    ip: str
    mac: str
    sku: str


@dataclass(frozen=True)
class BulbStatus:
    on: bool
    brightness: int
    rgb: tuple[int, int, int]
    kelvin: int


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _msg(cmd: str, data: dict) -> bytes:
    return json.dumps({"msg": {"cmd": cmd, "data": data}}, separators=(",", ":")).encode()


def scan_msg() -> bytes:
    return _msg("scan", {"account_topic": "reserve"})


def turn_msg(on: bool) -> bytes:
    return _msg("turn", {"value": 1 if on else 0})


def brightness_msg(pct: int) -> bytes:
    return _msg("brightness", {"value": _clamp(pct, 1, 100)})


def color_msg(r: int, g: int, b: int) -> bytes:
    color = {"r": _clamp(r, 0, 255), "g": _clamp(g, 0, 255), "b": _clamp(b, 0, 255)}
    return _msg("colorwc", {"color": color, "colorTemInKelvin": 0})


def kelvin_msg(k: int) -> bytes:
    return _msg("colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": _clamp(k, 2000, 9000)})


def status_msg() -> bytes:
    return _msg("devStatus", {})


def _parse(data: bytes, cmd: str) -> dict | None:
    try:
        msg = json.loads(data)["msg"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(msg, dict) or msg.get("cmd") != cmd or not isinstance(msg.get("data"), dict):
        return None
    return msg["data"]


def parse_scan(data: bytes) -> BulbInfo | None:
    d = _parse(data, "scan")
    if d is None or not all(k in d for k in ("ip", "device", "sku")):
        return None
    return BulbInfo(ip=d["ip"], mac=d["device"], sku=d["sku"])


def parse_status(data: bytes) -> BulbStatus | None:
    d = _parse(data, "devStatus")
    if d is None:
        return None
    try:
        c = d["color"]
        return BulbStatus(
            on=bool(d["onOff"]),
            brightness=int(d["brightness"]),
            rgb=(int(c["r"]), int(c["g"]), int(c["b"])),
            kelvin=int(d.get("colorTemInKelvin", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None
