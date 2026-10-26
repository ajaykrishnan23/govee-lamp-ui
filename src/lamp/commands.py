"""Instant commands that never go to the AI."""
import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["on", "off", "brightness", "brighter", "dimmer", "preset", "stop", "song_on", "song_off"]


@dataclass(frozen=True)
class Command:
    kind: Kind
    value: int | str | None = None


_FILLER = r"(?:please |the |my |it |lights? |lamp |all )*"
_TAIL = r"(?: (?:the |my |all )*(?:lights?|lamp|it)(?: please)?| please)?"
_PATTERNS: list[tuple[str, Kind]] = [
    (rf"(?:turn |switch )?{_FILLER}off{_TAIL}", "off"),
    (rf"(?:turn |switch )?{_FILLER}on{_TAIL}", "on"),
    (r"(?:make it |a bit |little )*(?:brighter|more light|brighten(?: up)?)", "brighter"),
    (r"(?:make it |a bit |little )*(?:dim|dimmer|darker|dim it|dim down)", "dimmer"),
    (r"stop(?: it| that| the effect)?", "stop"),
    (r"(?:sync|match)(?: the lights)? (?:to|with) (?:my |the )?music|song mode|music mode|music on", "song_on"),
    (r"stop (?:the )?(?:music|song)(?: lights| mode| sync)?|song mode off|music off", "song_off"),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%\s]", "", text.lower())).strip()


def parse_command(text: str, preset_names: list[str]) -> Command | None:
    t = _norm(text)
    if not t:
        return None
    if m := re.fullmatch(r"(?:set )?(?:the )?(?:brightness|bright)(?: to)? (\d{1,3})%?|(\d{1,3})%", t):
        return Command("brightness", max(1, min(100, int(m.group(1) or m.group(2)))))
    for pattern, kind in _PATTERNS:
        if re.fullmatch(pattern, t):
            return Command(kind)
    stripped = re.sub(r"^(?:make it |set it to |set |switch to |go |put on |turn on )?(?:the |a )?|(?: mode| mood| vibes?| lights| please)$", "", t).strip()
    for name in preset_names:
        if _norm(name) in (t, stripped):
            return Command("preset", name)
    return None
