# Hardware notes (measured 2026-10-25)

- Bulbs: 2 × H6006, firmware wifi/ble hard 1.07.02, ble soft 1.01.25.
  - `XX:XX:…` (bulb MAC, IP from DHCP)
  - `XX:XX:…` (bulb MAC, IP from DHCP)
- Discovery: multicast scan to 239.255.255.250:4001 works; broadcast to 255.255.255.255:4001 also works.
  The very first scan from a new process got no replies (probably macOS Local Network permission or bulb Wi-Fi power-save); later scans were reliable. Scans are sent twice, to both destinations.
- Rate: `devStatus` read-back matched the last color sent at 5, 10, 15, 20 and 30 updates/s (sampled once a second). That proves the bulbs accepted the commands, not that the change looked smooth. The default `max_updates_per_sec=10` stays until someone watches the lamp at higher rates.
- Blackout: `colorwc` rgb(0,0,0) while on is accepted (status reads on, rgb 0,0,0). Whether that looks fully dark is not yet confirmed by eye.
- `devStatus` reports `colorTemInKelvin` > 0 when the bulb is in white mode; rgb then reads (0,0,0).
