"""Probe how fast the bulbs accept LAN color updates.

For each rate, sends alternating colors for a few seconds, reading the color
back via devStatus to see whether the bulb kept up. Watch the lamp too:
read-back only proves the bulb accepted the command.
Usage: uv run python tools/measure_rate.py [seconds_per_rate]
"""
import asyncio
import sys

from lamp.govee.protocol import brightness_msg, color_msg, kelvin_msg
from lamp.govee.transport import GoveeTransport

COLORS = [(255, 0, 0), (0, 0, 255)]


async def main(seconds: float) -> None:
    t = GoveeTransport(max_updates_per_sec=1000)
    await t.start()
    bulbs = await t.discover(3)
    if not bulbs:
        print("no bulbs found")
        return
    before = {b.ip: await t.query_status(b.ip) for b in bulbs}
    for rate in (5, 10, 15, 20, 30):
        ok = total = 0
        for i in range(int(rate * seconds)):
            rgb = COLORS[i % 2]
            for b in bulbs:
                t.send(b.ip, color_msg(*rgb))
            await asyncio.sleep(1 / rate)
            if i % rate == rate - 1:  # sample once a second
                for b in bulbs:
                    s = await t.query_status(b.ip, timeout=0.5)
                    total += 1
                    ok += bool(s and s.rgb == rgb)
        print(f"{rate:>3}/s  read-back matched {ok}/{total}")
    for ip, s in before.items():  # restore
        if s:
            t.send(ip, color_msg(*s.rgb) if s.kelvin == 0 else kelvin_msg(s.kelvin))
            t.send(ip, brightness_msg(s.brightness))
    await t.close()


asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 3))
