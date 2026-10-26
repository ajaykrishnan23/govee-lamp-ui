# Govee Lamp Control — Design

Date: 2026-10-25
Status: approved by Ajay 2026-10-25

## Provider change (2026-10-25, decided by Ajay)

**The AI provider is OpenAI, not Claude.** Ajay supplied `OPENAI_API_KEY`. Wherever this doc says "Claude" or "Claude API", read it as OpenAI via the Responses API, with function tools and structured outputs. Default models: `gpt-6-luna` for both prompts and shows (Ajay: "use 6-luna"). `gpt-6.1-sol` is the configurable upgrade. All are configurable. The budget cap uses OpenAI prices. Secrets: `OPENAI_API_KEY` replaces `ANTHROPIC_API_KEY`.

## Intent

Ajay has a paper floor lamp in his room with two Govee H6006 smart bulbs inside it. The Govee app is clunky. He wants his own interface where he can:

1. Do the everyday stuff fast: on, off, brightness, a few moods.
2. **Prompt** the lights in plain language, typed or spoken, and have an AI (Claude) figure out what to do: "make it feel like a campfire", "fade to off over 20 minutes", "save this as reading mode". Claude should also be free to invent and save its own setups.
3. **Study a song (or any audio) first**, then play back a light show written for that specific track, synced to the music.

It's a personal toy for one room and one person. It should be fun and feel smart, not like an enterprise app.

## Hardware facts (verified)

- 2 × Govee **H6006** (A19 RGBWW, Wi‑Fi + BLE, Matter over Wi‑Fi). **No Zigbee.**
- Both bulbs are inside **one paper lamp shade**, so they blend into one glowing column. *Guess, unconfirmed:* they're stacked top/bottom, which allows two-tone gradients and "rising" effects. The design must still look good if they're side by side.
- Each bulb shows **one color at a time** (no per-segment control).
- The ceiling light is out of scope.
- **LAN control is enabled** by Ajay. H6006 is on Govee's official LAN API list and Home Assistant's `govee_light_local` list.
- Govee LAN API: UDP multicast scan to `239.255.255.250:4001`, replies on `:4002`; commands as JSON over UDP to `<bulb-ip>:4003`. Commands: `turn`, `brightness` (1–100), `colorwc` (RGB or Kelvin 2000–9000), `devStatus`. Docs: https://app-h5.govee.com/user-manual/wlan-guide
- Govee's cloud API is rate limited and slow, so it's **not used**. Everything goes over the LAN.

## Goals

- A web app that runs on Ajay's Mac and can be opened from the Mac or his phone on the home Wi‑Fi, with a password.
- **Presets / quick controls:** on, off, brightness, color, and a handful of built‑in moods. These never wait on the AI.
- **Prompt mode is a first-class feature, not just a song add-on.** Ajay's words: "it's not just song, I'd like to say or type that I need lights that make me feel like studying, or warm cozy cuddly lights." Mood and vibe requests are a core use, and Claude should interpret them creatively, using both bulbs, gentle motion where it fits, and saving good results.
- **Prompt mode:** a text box plus a mic button. Speech becomes text and goes to Claude, which controls the lights through tools. Simple commands ("off", "on", "brighter") are matched locally and run instantly, without the AI.
- **Saved setups:** Claude or Ajay can save named scenes and effects and recall them by name, by button, or by voice.
- **Song mode:**
  - Detect what's playing on Spotify (Mac or phone) through the Spotify Web API "currently playing" endpoint, which includes the playback position.
  - Get the audio. For Spotify tracks, fetch the matching audio from YouTube by artist + title (`yt-dlp`), analyze it, then **delete the audio**. Agreed by Ajay; personal use.
  - Analyze it: tempo, beat and downbeat times, an energy/loudness curve, section boundaries (intro / build / drop / breakdown), and onsets.
  - Claude writes a **timed light show** (a timeline of cues for the two bulbs) from the analysis plus title, artist and mood. It can be dramatic: blackout before a drop, strobes on hits, slow color drift in verses.
  - Play the show in sync with Spotify's playback position. Resync on seek, skip, or pause.
  - Cache shows per track, so replays start instantly. Prompts like "redo this one, more chill" rewrite the cached show.
  - First-time prep of about a minute per track is acceptable.

## Non-goals

- Live mic–reactive "visualizer" mode (option 1, rejected by Ajay for now).
- Access from outside the home network.
- Multiple users or accounts.
- Controlling other Govee devices or the ceiling light. (Discovery may list them; they're simply not used.)
- Song shows for audio sources other than Spotify (YouTube links, files) — not asked for.
- A native phone app. The website works in the phone's browser.

## Anti-goals (failure even if it "works")

- On/off feels laggy because it goes through the AI or the cloud.
- The show drifts noticeably out of sync with the music.
- Flashing so aggressive it's unpleasant in a small room. Strobes should be deliberate, not constant.
- API keys leaking into the browser, the chat, or anything committed.

## Constraints and decisions

### Decided with Ajay
- Web interface on the home network, password-protected, usable from the Mac and phone.
- A promptable AI interface. Ajay provides API keys (Claude, Spotify).
- Song mode = "study first" (pre-analysis, then synced playback), not live mic.
- Audio for Spotify tracks comes from YouTube via yt-dlp and is deleted after analysis.
- Spotify developer app: Web API only, redirect URI `http://127.0.0.1:8888/callback`.

- **Budget: hard monthly cap on Claude spend.** The app tracks token usage and cost per call. When the month's cap is hit, song mode falls back to a rule-based (non-AI) show built from the analysis, and prompts fall back to local command matching and saved presets, with a visible "AI budget reached" notice. *My call:* the cap is a setting with a default of $10/month, and the UI shows month-to-date spend.
- **Mac:** a laptop that stays on most of the time. It should recover cleanly after sleep or a restart, through a login service. If the laptop is off, the lights simply aren't controllable, and that's fine.
- **Phone:** iPhone with Chrome. That's WebKit underneath, so the same speech recognition limits as Safari apply.

### Decisions after review (my calls)
- **Song mode is an explicit toggle**, not automatic. Playing Spotify doesn't take over the lamp unless song mode is on ("sync to my music" or the button). Any manual command or mood prompt turns song mode off.
- **Prep ahead, within budget:** while song mode is on, the app reads the Spotify queue (`GET /me/player/queue`) and preps the **next one track** in the background, so most songs are ready on time. It never preps ahead once the budget is spent. A track with no show yet plays the rule-based show until its AI show is ready, then switches over at the next section boundary.
- **Show cost control:** Claude gets a compressed analysis summary (sections, energy levels, key hits, tempo), not raw beat lists. The scheduler expands "on beat" style cues against the real beat grid, so the AI writes short structured shows, not thousands of cues.
- **Voice fallback:** use the browser's built-in recognition when it works. If it's unavailable or fails, the mic button records a short clip and sends it to the Mac, where **local Whisper** (e.g. faster-whisper or whisper.cpp, small English model) transcribes it. No extra API key or cost. The builder should verify early which path actually works on iPhone Chrome.
- **Sleep/wake:** runs as a macOS LaunchAgent so it starts on login. It rediscovers bulbs on wake or a network change. While an effect or song show is running, it holds a `caffeinate` assertion so the Mac doesn't idle-sleep mid-effect. That does nothing if the lid is closed, and that's accepted. Long timed effects resume, or get cleanly abandoned, after wake.

### My calls (Ajay hasn't objected; open to change)
- **Python backend** (FastAPI) on the Mac. The Mac is the hub and must be awake.
- **Frontend: follow a small personal UI-stack guide** (Ajay's request): Tailwind + daisyUI + Alpine, the woodshed palette, and a screenshot loop. Applied here:
  - Tailwind + daisyUI for styling and components; Alpine.js for client state (mic, sliders, prompt log, now-playing); htmx only if server-rendered fragments help. Nothing outside the skill's allowlist without asking.
  - The page is served by FastAPI as static files. *My call:* Tailwind/daisyUI/Alpine are vendored or compiled locally rather than loaded from a CDN, so the UI works even if the internet is flaky (the lights are LAN-only). If the skill's tier-1 (Vite + TS) build turns out to be warranted, the builder may graduate to it.
  - **Palette: woodshed** (`woodshed-theme.css`), the skill's default for personal tooling. Tokens only, no raw hex in markup.
  - **The screenshot loop is required:** render at desktop and phone widths with `shot.mjs` (Playwright), look at the result, fix, repeat. Up to about 3 rounds per screen.
  - Mobile-first: big buttons, the prompt box always reachable.
- **Voice:** the browser's built-in Web Speech API (`webkitSpeechRecognition`), so no extra key. Safari on iOS and Chrome both support it.
- **HTTPS on the LAN:** browsers only allow mic access on secure pages, so the server uses a locally trusted certificate (mkcert). Ajay trusts it once on his phone.
- **Password:** one shared password in the settings file. Login sets a long-lived cookie.
- **Secrets:** a `.env` file on the Mac (`ANTHROPIC_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `APP_PASSWORD`), git-ignored, never sent to the browser.
- **Spotify auth:** a one-time OAuth flow run from the Mac (because the redirect is `127.0.0.1`). The refresh token is stored locally. Scope: `user-read-currently-playing user-read-playback-state`.
- **Claude model:** the latest capable Claude model for show writing and prompt handling. A faster or cheaper model is fine for quick prompt commands if latency matters.
- **Audio analysis:** `librosa` (beats, onsets, RMS energy, structural segmentation). Possibly `madmom`-style downbeats if librosa isn't good enough; that's up to the builder.
- **Persistence:** local JSON files or SQLite for presets, cached shows, and bulb IPs/MACs.

## How the pieces fit

```
Phone / Mac browser ──HTTPS──► FastAPI on Mac ──UDP :4003──► 2 × H6006 (LAN API)
        │  (password cookie)        │
        │                           ├── Claude API (prompt → tool calls; song analysis → show)
        │                           ├── Spotify Web API (what's playing + position)
        │                           └── yt-dlp + librosa (fetch + analyze audio, then delete)
        └── Web Speech API (voice → text, in browser)
```

### Light engine (core)
- Discovers bulbs on startup through LAN scan and remembers them by MAC address. The two bulbs get stable names; *suggested:* "top" and "bottom", renameable in the UI.
- A primitive layer: `set(bulb|all, on/off, rgb|kelvin, brightness)`.
- An effect runner that plays timelines (lists of timed cues with optional fades). Fades are done by sending stepped updates. The builder must measure how fast H6006 actually accepts LAN updates and cap the send rate below it (*guess:* somewhere around 10–20 updates/sec per bulb; unverified).
- There's one "current activity" at a time (idle, effect, or song show). Any manual command or prompt pre-empts it.

### Prompt mode (Claude tools)
Claude gets tools roughly like:
- `set_lights(target, power?, color?, kelvin?, brightness?, fade_ms?)`
- `run_effect(timeline | effect_spec, loop?, duration?)`: for things like "breathe slowly in purple" or "sunrise over 10 min".
- `save_preset(name, definition)`, `load_preset(name)`, `list_presets()`
- `stop()`
- Song-related: `prepare_show(source)`, `revise_show(track, instruction)`

It also gets context: current light state, the saved presets, what's playing right now, and the lamp description (two bulbs in one paper shade). Its replies show in the UI as a short line of what it did.

### Song mode pipeline
1. Identify the track (Spotify now-playing, or the pasted link/file).
2. If a show is cached, use it. Otherwise fetch the audio, analyze it, send a compact analysis summary to Claude (beats/downbeats, section list with energy levels, notable hits), and ask for a show in a strict JSON timeline schema. Validate the result, then save it.
3. Sync: poll Spotify playback state (*guess:* every 1–2 s) and estimate the position locally between polls. The scheduler fires cues against that clock. Pause stops the show; seek or skip resyncs; a track change triggers prep for the new track (with an ambient "thinking" effect while it waits).
4. Audio files are deleted after analysis. Only the analysis and the show are kept.

### UI (rough)
- **Top:** big on/off, a brightness slider, and a color picker for each bulb or both.
- **Moods:** a row of preset chips (built-ins plus saved ones).
- **Prompt bar:** a text field, a mic button, and a running log of what Claude did.
- **Now playing:** the Spotify track, show status (ready / preparing / playing), and "redo show" with an optional instruction.
- **Settings:** bulb names and order (top/bottom), the Spotify connection, and the password.

## Left to the builder
- Exact JSON schema for shows and effects.
- The analysis tuning and how the summary given to Claude is compressed.
- Sync and latency compensation details, plus a per-setup offset slider if needed.
- Which built-in moods ship by default (*suggested:* warm white, reading, sunset, campfire, ocean, party, night-light).
- Project layout, tests, and how it's started (*suggested:* one command, optionally a macOS launch agent so it starts on login).
