# Lamp

A web app on your Mac for the two Govee H6006 bulbs in the paper floor lamp. It has quick controls, moods, and a prompt box (typed or spoken) where an AI does what you ask: "warm cozy cuddly lights", "make it feel like studying", "fade off over 20 minutes". Everything goes straight to the bulbs over your Wi‑Fi through the Govee LAN API.

## Setup (once)

```sh
uv sync                                   # Python deps
(cd web && npm install && npm run build)  # page styles + Alpine
cp .env.example .env                      # then fill in OPENAI_API_KEY and APP_PASSWORD
brew install mkcert
uv run lamp certs                         # HTTPS certs; asks for your Mac password once to trust them
```

In the Govee Home app, turn on **LAN Control** for each bulb. Check that the Mac sees them:

```sh
uv run lamp discover
```

### iPhone (needed for the mic)

1. AirDrop `$(mkcert -CAROOT)/rootCA.pem` to the phone and tap Allow.
2. Settings → General → VPN & Device Management → install the profile.
3. Settings → General → About → Certificate Trust Settings → turn on full trust for the mkcert root.
4. Open `https://<your-mac>.local:8443` in Chrome (`lamp serve` prints the address).

## Daily use

```sh
uv run lamp serve            # run it now
uv run lamp install-agent    # or: start automatically at login (logs in data/lamp.log)
uv run lamp uninstall-agent
```

- **Instant commands** never touch the AI: on, off, brighter, dimmer, "brightness 40", "stop", or a mood name ("campfire", "make it the ocean mood").
- **Anything else** goes to the AI (`gpt-6-luna` by default; set `PROMPT_MODEL` in `.env` to change it). It can set static looks, run looping effects, fade over time, and save moods ("save this as reading mode").
- **Budget:** AI spend is capped at $10/month (`MONTHLY_BUDGET_USD`). At the cap, instant commands and moods keep working.
- **Voice:** the mic uses the browser's speech recognition. If that isn't available, it records a clip and transcribes it on the Mac with Whisper, which is free and needs no key. The first clip downloads a model of about 500 MB.
- **Sleep:** while an effect runs, the Mac is kept from idle-sleeping (closing the lid still sleeps it). After a sleep, the app finds the bulbs again and timed effects catch up.

## Hardware notes

See [docs/hardware-notes.md](docs/hardware-notes.md).

## Troubleshooting

- **No bulbs found:** check that LAN Control is on in the Govee app and the Mac is on the same Wi‑Fi. The first scan after starting sometimes gets no answer (macOS may ask for Local Network permission). Use "Find bulbs again" in settings or run `lamp discover` again.
- **The page loads on the Mac but not on the phone:** the macOS firewall is blocking incoming connections. The first time `lamp serve` runs, click **Allow** when macOS asks about Python accepting incoming connections. If you missed that prompt, go to System Settings → Network → Firewall → Options and allow the `python3` inside `.venv`. Test in this order: `https://localhost:8443` on the Mac, then `https://<mac-ip>:8443` on the phone (`lamp serve` prints the IP), then `https://<name>.local:8443`. Some routers also block devices on the same Wi‑Fi from reaching each other ("client isolation" / guest networks).
- **The browser warns about the certificate:** run `uv run lamp certs` (it runs `mkcert -install`). On the phone, finish the trust steps above.
- **The mic does nothing on the phone:** the page must be on `https://`, and Chrome needs microphone permission for the site.
- **AI replies "budget reached":** raise `MONTHLY_BUDGET_USD` in `.env`, or wait for next month.

## Development

```sh
uv run pytest -q -m "not slow"     # fast suite
uv run pytest -q                   # includes the Whisper test
(cd web && npm run watch)          # rebuild CSS while editing
SHOT_PASSWORD=… node tools/shot.mjs / 390x844   # screenshot the running app into tmp/
```
