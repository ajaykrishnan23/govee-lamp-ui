# Govee Lamp Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A password-protected web app on Ajay's Mac that controls the two H6006 bulbs in his paper floor lamp over the Govee LAN API. It has instant quick controls, typed or spoken mood prompts handled by AI, and Spotify-synced light shows that are studied and written ahead of time.

**Architecture:** One Python process (FastAPI + asyncio) owns the bulbs. Layers:
- A UDP transport layer talks to the bulbs.
- An effect engine plays timelines, with one current activity at a time.
- Presets/commands provide the instant path.
- A AI tool-use agent handles prompts.
- A song pipeline does Spotify now-playing → yt-dlp audio → librosa analysis → AI-written show → compiled timeline synced to Spotify position.

A static Alpine/daisyUI page talks to it over REST + Server-Sent Events, served over HTTPS (mkcert) so the phone mic works.

**Tech Stack:** Python 3.12 via `uv`, FastAPI, uvicorn, pydantic / pydantic-settings, httpx, openai SDK (Responses API), librosa + numpy + soundfile, yt-dlp, ffmpeg (already installed), faster-whisper, pytest + pytest-asyncio + respx. Frontend: Tailwind CSS v4 CLI + daisyUI v5 (compiled locally) and Alpine.js (vendored). Playwright for the screenshot loop. mkcert (Homebrew).

**Spec:** `docs/superpowers/specs/2026-10-25-govee-lamp-control-design.md`. Read it before any task.

## Execution order

Ajay: "if you can't do song stuff it's fine, we can come to that later." Build Tasks 1–10, then Task 16 (core lamp + prompts + voice + resilience). Then check in with Ajay before Tasks 11–15 (song mode). Task 7's `SongControl` is a no-op stub until Task 15.

## Global Constraints

- Bulbs: 2 × Govee H6006, controlled **only** over the LAN API. Scan multicast `239.255.255.250:4001`, listen `:4002`, commands to `<ip>:4003`. Never use the Govee cloud API.
- LAN command values: `brightness` 1–100 integer. `colorwc` RGB 0–255, Kelvin 2000–9000. `colorTemInKelvin: 0` means "use RGB".
- Each bulb is one color at a time. Bulbs are identified by MAC (`device` field) and named `top` / `bottom` by default, renameable and swappable.
- Song mode is Spotify only, and an **explicit toggle**. Any manual command or mood prompt turns it off.
- Spotify redirect URI exactly `http://127.0.0.1:8888/callback`. Scopes exactly `user-read-currently-playing user-read-playback-state`.
- Audio fetched for analysis is deleted after analysis. Only the analysis + show are kept.
- Hard monthly AI budget, default **$10/month**, shown in the UI. At the cap: songs get the rule-based show, prompts get the local command parser + presets only, and the UI shows "AI budget reached".
- Simple commands (on, off, brighter, dimmer, brightness N, preset names, stop) never call AI.
- Secrets live only in `.env` (`OPENAI_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `APP_PASSWORD`). `.env`, `data/` and `certs/` are git-ignored, and secrets are never sent to the browser.
- Strobe/flash safety: never more than **4 flashes per second per bulb**. Strobes are only placed on detected hits or explicit moments, never as a constant pattern.
- Frontend follows a personal UI-stack guide for Tasks 9–10:
  - Use Tailwind + daisyUI + Alpine (htmx only if useful), and nothing outside its allowlist.
  - Use the woodshed palette tokens from `woodshed-theme.css`, with no raw hex in markup.
  - Mobile-first.
  - Run the screenshot loop (`tools/shot.mjs`) at 390x844 and 1280x800.
- Frontend libraries are vendored or compiled locally, with no runtime CDN.
- **AI provider is OpenAI (Ajay's decision), not Claude.** Use the `openai` Python SDK's **Responses API** with function tools and structured outputs. Use Exa (`mcp__exa__web_fetch_exa` on `https://developers.openai.com/api/docs/...`) for current SDK docs; don't use the `claude-api` skill. Default models: `prompt_model="gpt-6.1-sol"` (reasoning effort low) and `show_model="gpt-6.1-sol"` (reasoning effort medium); `gpt-6-luna` is the cheap alternative.
- Bash sandbox note for the executor: UDP multicast, binding `0.0.0.0`, and calls to the Spotify/OpenAI/YouTube hosts may need `allowed_domains` or a sandbox-off retry. Hardware steps need the real LAN.

## Review Focus

1. **A bulb goes away or changes IP** (unplugged, DHCP lease change, Mac wakes on a new network). Commands to it must not raise or block the other bulb, and the next rediscovery re-binds it by MAC. Test → Task 2 (`test_send_to_unreachable_ip_does_not_raise`) and Task 3 (`test_rediscovery_rebinds_bulb_by_mac`).
2. **Spotify has nothing usable playing**: 204 No Content, an ad, a podcast episode, a local file with no ID, or a private session. Song mode should idle with a clear status, not crash or loop. Test → Task 11 (`test_now_playing_handles_204_episode_and_local`) and Task 15 (`test_song_mode_idles_when_nothing_playing`).
3. **YouTube match is wrong or unavailable**: no network, a live version with a very different length, or a yt-dlp failure. Reject candidates whose duration is off by more than 10 s. If nothing is usable, fall back to a beat-less ambient show with status "couldn't find audio". Test → Task 12 (`test_pick_candidate_rejects_duration_mismatch`) and Task 15 (`test_fetch_failure_uses_ambient_show`).
4. **Playback jumps**: pause, seek, skip, or the Mac sleeps mid-show. The show must stop on pause, resync within one poll after a seek, and switch shows on a skip. A sleep/wake time jump stops timed effects cleanly. Test → Task 15 (`test_seek_resyncs`, `test_pause_stops_and_resume_continues`) and Task 16 (`test_wall_clock_jump_triggers_wake_handler`).
5. **AI returns garbage or fails**: invalid show JSON, an API error, a timeout, or the budget hit mid-request. The lamp keeps a valid show (rule-based) and the prompt log shows the error without the lights going weird. Test → Task 14 (`test_invalid_show_falls_back_to_rule_based`) and Task 7 (`test_agent_api_error_reports_and_leaves_lights`).

---

## File structure

```
pyproject.toml                 uv project, deps, `lamp` console script
.env.example  .gitignore  README.md
lamp/
  config.py                    Settings (pydantic-settings, .env)
  govee/protocol.py            pure LAN message builders/parsers
  govee/transport.py           asyncio UDP: discover, send, status, rate limiting
  lamp.py                      Bulb registry (MAC→name), LightState, Lamp.apply
  effects.py                   Cue/Timeline, interpolation, EffectRunner, ActivityManager
  presets.py                   built-in moods + saved presets store
  commands.py                  local instant-command parser
  ai/budget.py                 cost ledger, month-to-date, can_spend
  ai/agent.py                  AI tool-use loop for prompts
  song/spotify.py              OAuth login + now_playing + queue
  song/fetch.py                yt-dlp search/pick/download → wav
  song/analyze.py              librosa analysis + compact summary
  song/show.py                 Show schema, compile_show, rule_based_show, ambient_show
  song/cache.py                per-track analysis+show store
  song/writer.py               AI show writer with fallback
  song/mode.py                 SongMode: polling, clock, sync, prefetch, swap
  voice.py                     faster-whisper fallback transcription
  runtime.py                   wiring, caffeinate, wake detection, LaunchAgent
  web/events.py                SSE EventBus
  web/auth.py                  password login + signed cookie
  web/app.py                   FastAPI routes + static files
  cli.py                       `lamp serve|discover|spotify-login|certs|install-agent`
web/
  package.json                 tailwind cli, daisyui, alpinejs, playwright
  src/input.css                tailwind + daisyui + woodshed theme
  static/index.html  static/login.html  static/app.js  static/vendor/alpine.min.js
tools/shot.mjs                 copied from the ui-stack references
tools/measure_rate.py          hardware send-rate probe
tests/…                        mirrors lamp/
data/  certs/                  runtime, git-ignored
```

---

### Task 1: Project scaffold, settings, LAN protocol

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `lamp/__init__.py`, `lamp/config.py`, `lamp/govee/__init__.py`, `lamp/govee/protocol.py`
- Test: `tests/govee/test_protocol.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings` (pydantic-settings, `.env`) with fields:
    - `openai_api_key: str = ""`, `spotify_client_id: str = ""`, `spotify_client_secret: str = ""`, `app_password: str`
    - `monthly_budget_usd: float = 10.0`, `prompt_model = "gpt-6.1-sol"`, `show_model = "gpt-6.1-sol"`
    - `host = "0.0.0.0"`, `port = 8443`, `data_dir: Path = Path("data")`, `certs_dir: Path = Path("certs")`
    - `max_updates_per_sec: float = 10.0`, `sync_offset_ms: int = 0`
    - `get_settings() -> Settings`
  - In `protocol.py`:
    - `scan_msg() -> bytes`, `turn_msg(on: bool) -> bytes`, `brightness_msg(pct: int) -> bytes` (clamps 1–100), `color_msg(r: int, g: int, b: int) -> bytes` (clamps 0–255, `colorTemInKelvin: 0`), `kelvin_msg(k: int) -> bytes` (clamps 2000–9000), `status_msg() -> bytes`
    - `@dataclass BulbInfo(ip: str, mac: str, sku: str)`, `parse_scan(data: bytes) -> BulbInfo | None`
    - `@dataclass BulbStatus(on: bool, brightness: int, rgb: tuple[int,int,int], kelvin: int)`, `parse_status(data: bytes) -> BulbStatus | None`

- [ ] **Step 1:** `git init`. Use `uv init --package --python 3.12` (package `lamp`), and add the runtime deps listed in Tech Stack plus dev deps `pytest pytest-asyncio respx`. Set `asyncio_mode = "auto"` in pytest config. Add console script `lamp = "lamp.cli:main"`. `.gitignore`: `.env`, `data/`, `certs/`, `.venv/`, `web/node_modules/`, `web/static/app.css`, `tmp/`, `__pycache__/`. Write `.env.example` with the four secret keys blank.
- [ ] **Step 2: Write failing tests**
  - `test_turn_msg_shape`: `json.loads(turn_msg(True)) == {"msg":{"cmd":"turn","data":{"value":1}}}`
  - `test_brightness_clamps`: `brightness_msg(0)` → value 1, `brightness_msg(150)` → 100
  - `test_color_msg_uses_rgb`: data == `{"color":{"r":255,"g":0,"b":10},"colorTemInKelvin":0}`
  - `test_kelvin_clamps`: `kelvin_msg(1500)` → 2000
  - `test_parse_scan`: the doc's sample response → `BulbInfo("192.168.1.23","1F:80:C5:32:32:36:72:4E","Hxxxx")`
  - `test_parse_scan_garbage_returns_none`: `b"not json"` and wrong `cmd` → None
  - `test_parse_status`: the doc's sample → `BulbStatus(True,100,(255,0,0),7200)`
  - `test_settings_defaults`: with `APP_PASSWORD=x` in env, budget is 10.0 and port is 8443
- [ ] **Step 3:** Run `uv run pytest tests -v`. Expected: FAIL (import errors).
- [ ] **Step 4:** Implement `config.py` and `protocol.py` to the interfaces above. Use compact JSON (`separators=(",",":")`).
- [ ] **Step 5:** Run `uv run pytest tests -v`. Expected: all PASS.
- [ ] **Step 6:** Commit: `feat: project scaffold, settings, Govee LAN protocol`

### Task 2: UDP transport, discovery, rate-limited sending

**Files:**
- Create: `lamp/govee/transport.py`, `tools/measure_rate.py`
- Test: `tests/govee/test_transport.py`

**Interfaces:**
- Consumes: `protocol.*` (Task 1)
- Produces:
  - `async def discover(timeout: float = 3.0) -> list[BulbInfo]`: binds `:4002`, sends `scan_msg()` to the multicast group `:4001`, collects and dedupes by MAC.
  - `class GoveeTransport`: `__init__(max_updates_per_sec: float)`, `async start()`, `async close()`
    - `send(ip: str, msg: bytes) -> None`: fire-and-forget, never raises on OSError (logs it).
    - `send_latest(ip: str, key: str, msg: bytes) -> None`: coalescing. Per `(ip, key)` only the newest pending message is kept, and each IP is flushed at most `max_updates_per_sec` times per second.
    - `async query_status(ip: str, timeout: float = 1.0) -> BulbStatus | None`

- [ ] **Step 1: Write failing tests**, using a local UDP echo/capture socket on 127.0.0.1 instead of a bulb:
  - `test_send_delivers_bytes`
  - `test_send_latest_coalesces`: 50 rapid `send_latest(ip,"color",…)` calls with a 10/s limit → the capture gets ≤ 3 packets within 200 ms, and the last packet is the final message.
  - `test_send_to_unreachable_ip_does_not_raise`: send to `10.255.255.1` and to a closed port. No exception, and a following send to the capture socket still arrives.
  - `test_query_status_timeout_returns_none`
- [ ] **Step 2:** Run `uv run pytest tests/govee/test_transport.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement using `asyncio.DatagramProtocol`. Use one sender task per IP, draining a dict of latest messages per key at the rate limit. For `discover`, set `SO_REUSEADDR` and `SO_REUSEPORT` on the `:4002` listener.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Hardware check (real LAN).**
  - Write `tools/measure_rate.py`. It discovers the bulbs, then for each rate in 5, 10, 15, 20, 30/s it sends alternating red/blue `color_msg` for 5 s. It prints the rate and prompts the person to note whether the bulb kept up.
  - Run `uv run lamp discover` (this can be a temporary `python -m` call until Task 8 adds the CLI). Expected: two lines with `sku H6006`, IP and MAC.
  - Test whether `color_msg(0,0,0)` blacks out the bulb without turning it off. Record the result, the observed max smooth rate, and the visible latency in the README "Hardware notes".
  - If the bulbs keep up above 10/s, set `max_updates_per_sec` to about 80% of the observed max.
- [ ] **Step 6:** Commit: `feat: UDP transport with discovery and coalesced rate limiting`

### Task 3: Lamp model: bulb registry, names, state

**Files:**
- Create: `lamp/lamp.py`
- Test: `tests/test_lamp.py`

**Interfaces:**
- Consumes: `GoveeTransport`, `discover`, `protocol` messages
- Produces:
  - `@dataclass LightState(on: bool = True, rgb: tuple[int,int,int] | None = None, kelvin: int | None = None, brightness: int = 100)`. Exactly one of `rgb`/`kelvin` is set. `merged(patch: dict) -> LightState`.
  - `Target = Literal["all"] | str` (a bulb name).
  - `class Lamp`: `__init__(transport, registry_path: Path, discover_fn=discover)`.
    - `async refresh() -> None`: discovers bulbs and binds them by MAC to names stored in `data/bulbs.json`. New MACs get `top`, then `bottom`, then `bulb3`… Only `sku == "H6006"` is used.
    - `names() -> list[str]`, `rename(old: str, new: str)`, `swap()` (swaps the top/bottom MACs)
    - `state() -> dict[str, LightState]`
    - `apply(target: Target, patch: dict) -> None`: updates the cached state and sends only what changed via `send_latest` with keys `power` / `brightness` / `color`.
    - `on_change(cb: Callable[[dict[str, LightState]], None])`: used for SSE.

- [ ] **Step 1: Write failing tests**, with a fake transport recording `(ip,key,msg)` and a fake `discover_fn`:
  - `test_first_discovery_names_top_bottom`
  - `test_apply_all_sends_to_both_only_changed_fields`: applying a brightness patch sends only `brightness` messages.
  - `test_rgb_patch_clears_kelvin`: and vice versa.
  - `test_rename_and_swap_persist`: reloading from the registry file keeps the names.
  - `test_rediscovery_rebinds_bulb_by_mac`: the same MAC with a new IP keeps its name, and subsequent sends go to the new IP.
  - `test_apply_unknown_target_raises_value_error`
- [ ] **Step 2:** Run `uv run pytest tests/test_lamp.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `lamp.py` per the interfaces.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: lamp model with MAC-bound bulb names and state`

### Task 4: Effects: timelines, fades, single-activity runner

**Files:**
- Create: `lamp/effects.py`
- Test: `tests/test_effects.py`

**Interfaces:**
- Consumes: `Lamp.apply`, `LightState`
- Produces:
  - `class Cue(BaseModel)`: `t_ms: int`, `target: str = "all"`, `rgb: tuple[int,int,int] | None`, `kelvin: int | None`, `brightness: int | None`, `on: bool | None`, `fade_ms: int = 0`
  - `class Timeline(BaseModel)`: `cues: list[Cue]`, `duration_ms: int`, `loop: bool = False`
  - `def state_at(timeline: Timeline, t_ms: int, start: dict[str, LightState]) -> dict[str, LightState]`: the pure function the runner uses. During a cue's fade it linearly interpolates RGB/Kelvin/brightness from the previous resolved value.
  - `class Clock(Protocol)`: `def now_ms() -> float`. `MonotonicClock`.
  - `class ActivityManager`: `__init__(lamp, clock, tick_hz: float)`
    - `kind: Literal["idle","effect","song"]`
    - `async play(timeline: Timeline, kind: str = "effect", position_fn: Callable[[], float] | None = None)`: stops the current activity first. The `position_fn` override lets song mode drive the playhead.
    - `async stop()`
    - `on_kind_change(cb)`
    - Tick loop at `tick_hz` (default = `settings.max_updates_per_sec`) computes `state_at` and calls `lamp.apply` only on diffs.

- [ ] **Step 1: Write failing tests**, with a fake clock and a fake lamp:
  - `test_state_at_holds_before_first_cue`
  - `test_state_at_fade_midpoint`: from (0,0,0) to (200,100,0) with a 1000 ms fade, at t=500 → (100,50,0).
  - `test_state_at_loops`
  - `test_play_preempts_previous`
  - `test_stop_returns_idle_and_leaves_last_state`
  - `test_runner_only_sends_diffs`: a static timeline over 2 s produces exactly one apply per field.
  - `test_twenty_minute_fade_to_off`: the timeline from the spec example ("fade to off over 20 minutes") has brightness at 50% halfway and power off at the end.
- [ ] **Step 2:** Run `uv run pytest tests/test_effects.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement per the interfaces.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: timeline effects and single-activity manager`

### Task 5: Presets, built-in moods, instant command parser

**Files:**
- Create: `lamp/presets.py`, `lamp/commands.py`
- Test: `tests/test_presets.py`, `tests/test_commands.py`

**Interfaces:**
- Consumes: `LightState`, `Timeline`
- Produces:
  - `class Preset(BaseModel)`: `name: str`, `description: str = ""`, `static: dict[str, dict] | None` (bulb name or `"all"` → LightState patch), `timeline: Timeline | None`, `builtin: bool = False`
  - `class PresetStore`: `__init__(path: Path)`, `list() -> list[Preset]`, `get(name) -> Preset | None` (case-insensitive, ignores spaces), `save(p: Preset)` (overwrites non-builtins only; saving over a builtin name raises), `delete(name)`
  - `BUILTINS`: `warm white`, `reading`, `study` (cool-neutral steady, about 4500K at 90%), `sunset` (amber bottom → magenta top), `campfire` (warm flicker timeline), `ocean` (slow blue/teal drift), `cozy` (low warm amber with a slow breathe), `party` (fast hue cycle within the strobe limit), `night light` (dim red-amber at 5%)
  - `@dataclass Command(kind: Literal["on","off","brightness","brighter","dimmer","preset","stop","song_on","song_off"], value: int | str | None = None)`
  - `parse_command(text: str, preset_names: list[str]) -> Command | None`: returns None for anything not obviously simple, which then goes to AI.

- [ ] **Step 1: Write failing tests**
  - `parse_command` table test:
    - `"off"`, `"lights off"`, `"turn it off"` → off
    - `"on"` → on
    - `"brightness 40"`, `"40%"` → brightness 40
    - `"brighter"` → brighter
    - `"dim"` → dimmer
    - `"stop"` → stop
    - `"sync to my music"`, `"song mode"` → song_on
    - `"stop the music lights"` → song_off
    - `"campfire"`, `"Campfire mode"` → preset campfire
    - `"make it feel like studying in a library at night"` → None
    - `"warm cozy cuddly lights"` → None (fuzzy moods go to AI, not to the `cozy` preset)
  - `test_builtins_are_valid`: every builtin has exactly one of static/timeline, and the party timeline flashes ≤ 4 Hz per bulb.
  - `test_save_get_roundtrip_case_insensitive`
  - `test_cannot_overwrite_builtin`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. The parser uses anchored regexes plus an exact or near-exact (whole-text) preset-name match.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: presets, built-in moods, instant command parser`

### Task 6: Budget ledger

**Files:**
- Create: `lamp/ai/__init__.py`, `lamp/ai/budget.py`
- Test: `tests/ai/test_budget.py`

**Interfaces:**
- Produces:
  - `PRICES: dict[str, tuple[float, float, float]]`: USD per million (input, cached input, output) tokens, from developers.openai.com/api/docs/pricing as of 2026-10-25: `gpt-6.1-sol` (2.00, 0.10, 10.00), `gpt-6-luna` (0.10, 0.01, 0.50), `gpt-6-astra` (10.00, 1.00, 50.00). Reasoning tokens bill as output.
  - `class Budget`: `__init__(path: Path, monthly_cap_usd: float, today: Callable[[], date] = date.today)`
    - `record(model: str, usage) -> float`: returns the call cost and appends to `data/usage.jsonl`.
    - `month_to_date() -> float`, `remaining() -> float`, `can_spend(estimate_usd: float = 0.0) -> bool`
    - `status() -> dict`: `{"spent": float, "cap": float, "blocked": bool}`

- [ ] **Step 1: Write failing tests**
  - `test_record_computes_cost`
  - `test_month_rollover_resets`: entries from last month are excluded.
  - `test_can_spend_false_at_cap`
  - `test_unknown_model_uses_most_expensive_price`: overestimating is the safe direction.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: monthly AI budget ledger`

### Task 7: AI prompt agent

**Files:**
- Create: `lamp/ai/agent.py`
- Test: `tests/ai/test_agent.py`

**Interfaces:**
- Consumes: `Lamp`, `ActivityManager`, `PresetStore`, `Budget`, `Timeline`. Also a `SongControl` protocol: `async start()`, `async stop()`, `async redo(instruction: str)`, `status() -> dict`. Task 15 implements it; the tests use a fake.
- Produces:
  - `class PromptAgent`: `__init__(client: openai.AsyncOpenAI, model: str, lamp, activity, presets, budget, song: SongControl)`
    - `async handle(text: str) -> AgentResult`
  - `@dataclass AgentResult(reply: str, actions: list[str], error: str | None = None)`
  - Tools, with JSON schemas built from the pydantic models:
    - `set_lights(target, on?, rgb?, kelvin?, brightness?, fade_ms?)`
    - `run_effect(timeline: Timeline)`
    - `save_preset(preset: Preset)`
    - `load_preset(name)`
    - `list_presets()`
    - `stop()`
    - `start_song_mode()`, `stop_song_mode()`, `redo_song_show(instruction)`
  - The system prompt describes:
    - the lamp: two H6006 bulbs in one paper shade, probably stacked top/bottom
    - the current state, the preset names, the song status
    - the flash limit (≤ 4 Hz per bulb)
    - the rule: mood requests ("feel like studying", "warm cozy cuddly") deserve creative two-bulb answers with gentle motion where it fits
    - the rule: offer to save setups that work, and save when asked
  - Any light-changing tool stops song mode first (except the song tools).
  - The tool loop is capped at 6 iterations. Usage is recorded on `Budget`. If `not budget.can_spend()`, it returns `AgentResult(reply="AI budget reached — quick commands and presets still work.", actions=[], error="budget")` without calling the API.

- [ ] **Step 1: Write failing tests**, with a fake OpenAI client returning scripted `function_call` / final-message responses:
  - `test_mood_prompt_calls_set_lights_and_replies`
  - `test_save_preset_tool_persists`
  - `test_light_tool_stops_song_mode`
  - `test_budget_blocked_skips_api`: the fake client is never called.
  - `test_agent_api_error_reports_and_leaves_lights`: the client raises `openai.APIError`. The result has `error` set and the lamp received no apply calls.
  - `test_invalid_tool_args_return_tool_error_to_model`: rgb `[300,0,0]` comes back to the model as a `function_call_output` containing the error, and the loop continues.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with `AsyncOpenAI().responses.create(..., tools=[function tools], reasoning={"effort": "low"})`, and a manual loop feeding `function_call_output` items back.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: AI prompt agent with light tools`

### Task 8: Web backend: auth, REST, SSE, HTTPS, CLI

**Files:**
- Create: `lamp/web/__init__.py`, `lamp/web/events.py`, `lamp/web/auth.py`, `lamp/web/app.py`, `lamp/runtime.py` (wiring only for now), `lamp/cli.py`
- Test: `tests/web/test_auth.py`, `tests/web/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7
- Produces:
  - `class EventBus`: `publish(type: str, data: dict)`, `async subscribe() -> AsyncIterator[str]` (SSE-formatted lines)
  - `auth.py`: HMAC-signed cookie `lamp_session`, valid for 90 days. The key is a random secret stored in `data/secret.key`. `check_password(pw) -> bool` uses `hmac.compare_digest`.
  - `class App` in `runtime.py`: `build_app(settings) -> FastAPI` builds the `Lamp`, `ActivityManager`, `PresetStore`, `Budget`, `PromptAgent`, `EventBus`, and starts `lamp.refresh()` on startup.
  - Routes. Everything except `/login` and the static login page requires the cookie: the API returns 401 and HTML redirects to `/login`.
    - `POST /login {password}`
    - `GET /api/state` → `{bulbs, activity, presets, budget, song}`
    - `POST /api/power {target,on}`, `POST /api/brightness {target,value}`, `POST /api/color {target,rgb?|kelvin?}`
    - `POST /api/preset/{name}`, `DELETE /api/preset/{name}`
    - `POST /api/prompt {text}` → runs `parse_command` first, then `PromptAgent`. Returns `{reply, actions, error, via: "instant"|"ai"}`.
    - `POST /api/stop`
    - `POST /api/bulbs/rename {old,new}`, `POST /api/bulbs/swap`, `POST /api/bulbs/rediscover`
    - `GET /api/events` (SSE: `state`, `activity`, `log`, `budget`, `song`)
    - Static `web/static` at `/`
    - Manual quick-control routes stop song mode.
  - `cli.py` commands:
    - `serve`: uvicorn on `settings.host:port` with `certs/lamp.pem` + `certs/lamp-key.pem`, falling back to HTTP with a loud warning if the certs are missing.
    - `discover`
    - `certs`: runs `mkcert -install`, then `mkcert -cert-file certs/lamp.pem -key-file certs/lamp-key.pem <hostname>.local <LAN IP> localhost 127.0.0.1`, and prints the iPhone trust steps.
    - `spotify-login` (Task 11) and `install-agent` (Task 16) are stubs for now.

- [ ] **Step 1: Write failing tests** with `httpx.AsyncClient(transport=ASGITransport(app))` and fakes injected for the transport and the OpenAI client:
  - `test_api_requires_login`: 401 without the cookie.
  - `test_login_wrong_password_401`, `test_login_sets_cookie`
  - `test_prompt_instant_off_does_not_call_ai`: `via == "instant"`, and the fake AI is never called.
  - `test_prompt_mood_goes_to_ai`
  - `test_quick_control_stops_song_mode`
  - `test_events_stream_emits_state_after_change`
  - `test_state_never_contains_secrets`: the serialized `/api/state` contains none of the `.env` values.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** `brew install mkcert`, then `uv run lamp certs`, then `uv run lamp serve`. Run `curl -k https://localhost:8443/api/state`. Expected: 401.
- [ ] **Step 6:** Commit: `feat: FastAPI backend with auth, SSE, HTTPS`

### Task 9: Frontend: control page and login (ui-stack)

**Files:**
- Create: `web/package.json`, `web/src/input.css`, `web/static/index.html`, `web/static/login.html`, `web/static/app.js`, `web/static/vendor/alpine.min.js` (copied from `node_modules/alpinejs/dist/cdn.min.js` by a script), `tools/shot.mjs` (copied from the ui-stack references)

**Interfaces:**
- Consumes: the Task 8 routes and SSE event types
- Produces: the UI that Tasks 10 and 15 extend. It's an Alpine root component `lampApp()` in `app.js` with fields `bulbs`, `activity`, `presets`, `budget`, `song`, `log[]`, `listening`, `busy`, and methods `send(text)`, `power(target,on)`, `setBrightness(target,v)`, `setColor(target,hex)`, `applyPreset(name)`, `stop()`.

- [ ] **Step 1:** `npm init` in `web/`, then add `tailwindcss @tailwindcss/cli daisyui alpinejs playwright`. Scripts:
  - `build`: Tailwind CLI `src/input.css` → `static/app.css`, then copy Alpine into `static/vendor/`
  - `watch`
  - `shot`: `node ../tools/shot.mjs`

  `input.css` imports Tailwind and the daisyUI plugin, and defines the `woodshed` daisyUI theme from section (B) of `woodshed-theme.css`, as default and dark.
- [ ] **Step 2:** Build `index.html`, mobile-first, top to bottom:
  - **Header:** a big on/off toggle and the activity badge (`idle` / `effect` / `song`).
  - **Lamp preview:** two stacked swatches showing the live `top`/`bottom` colors from SSE.
  - **Brightness slider** and a **color picker**, each with a target segmented control (`both` / `top` / `bottom`).
  - **Moods:** chips for the presets, with builtins first.
  - **Prompt bar:** pinned to the bottom on mobile. Text field, mic button (wired in Task 10), send.
  - **Log:** the latest replies and actions, marked `instant` or `ai`.
  - **Footer:** budget status ("$2.10 of $10 this month", or "AI budget reached").
  - **Settings drawer:** rename bulbs, swap top/bottom, rediscover.

  Add `login.html` with a single password field. Use tokens only, with no raw hex.
- [ ] **Step 3:** Run the screenshot loop. With the server running, use `SHOT_BASE=https://localhost:8443` (set `ignoreHTTPSErrors` in the copied `shot.mjs`, or serve HTTP locally for the shots), plus a cookie or a dev-only `LAMP_DEV_NOAUTH=1` setting.
  - Shoot `/` at 390x844 and 1280x800, then shoot `/login.html`.
  - Read each PNG, state in words what's wrong, fix it, and re-shoot. Up to 3 rounds. There must be zero console errors.
- [ ] **Step 4:** Manual check on the real lamp from the Mac browser: on/off, brightness, color for `top` only, the `campfire` preset, and the `stop` prompt all work, and the preview swatches update.
- [ ] **Step 5:** Commit: `feat: woodshed control UI (Tailwind, daisyUI, Alpine)`

### Task 10: Voice input with Whisper fallback

**Files:**
- Create: `lamp/voice.py`
- Modify: `lamp/web/app.py` (add `POST /api/voice`), `web/static/app.js`, `web/static/index.html`
- Test: `tests/test_voice.py`, `tests/web/test_api.py`

**Interfaces:**
- Produces:
  - `class Transcriber`: `__init__(model_size: str = "small.en")` (lazy-loads faster-whisper, `compute_type="int8"`), `transcribe(path: Path) -> str`
  - `POST /api/voice` (multipart `audio`, ≤ 2 MB / 30 s) → `{text}`. It then calls the same handler as `/api/prompt` and returns `{text, reply, actions, error, via}`.
  - Frontend `startListening()`:
    - If `window.SpeechRecognition || window.webkitSpeechRecognition` exists, use it (`lang: "en-US"`, one shot, final result → `send(text)`).
    - On missing support or an `error` event, fall back to `MediaRecorder` (audio/mp4 on iOS, webm elsewhere): record until a second tap or 15 s, then upload.

- [ ] **Step 1: Write failing tests**
  - `test_voice_endpoint_transcribes_then_prompts`: with a fake Transcriber returning `"lights off"`, `via == "instant"`.
  - `test_voice_rejects_oversize`: 413.
  - `test_transcriber_decodes_m4a`: a real 1 s generated tone via ffmpeg runs without error (marked `slow`).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the backend and the frontend.
- [ ] **Step 4:** Run. Expected: PASS. Re-run the screenshot loop with the mic in the listening state.
- [ ] **Step 5: Manual iPhone check.**
  - AirDrop `$(mkcert -CAROOT)/rootCA.pem` to the phone, install the profile, then enable it under Settings → General → About → Certificate Trust Settings.
  - Open `https://<hostname>.local:8443` in Chrome and say "warm cozy cuddly lights".
  - Record in the README which path worked: built-in recognition or the Whisper fallback.
- [ ] **Step 6:** Commit: `feat: voice prompts with on-device Whisper fallback`

### Task 11: Spotify login and playback client

**Files:**
- Create: `lamp/song/__init__.py`, `lamp/song/spotify.py`
- Modify: `lamp/cli.py` (implement `spotify-login`)
- Test: `tests/song/test_spotify.py` (respx)

**Interfaces:**
- Produces:
  - `@dataclass Track(id: str, title: str, artists: list[str], duration_ms: int)`
  - `@dataclass Playback(track: Track | None, progress_ms: int, is_playing: bool, fetched_at_ms: float, reason: Literal["ok","nothing","episode","ad","local","unavailable"])`
  - `class SpotifyClient`: `__init__(client_id, client_secret, token_path: Path, http: httpx.AsyncClient)`
    - `async now_playing() -> Playback`: uses `GET /v1/me/player/currently-playing?additional_types=episode`.
    - `async queue() -> list[Track]`: uses `GET /v1/me/player/queue` and drops non-tracks.
    - Refreshes the access token automatically on 401 or expiry.
  - `lamp spotify-login`:
    - Runs a temporary HTTP server on `127.0.0.1:8888`.
    - Opens the authorize URL with the exact scopes.
    - Exchanges the code and writes `data/spotify_token.json` with the refresh token.

- [ ] **Step 1: Write failing tests**
  - `test_now_playing_track`
  - `test_now_playing_handles_204_episode_and_local`: 204 → `reason="nothing"`, an episode → `"episode"`, `is_local` → `"local"`, `currently_playing_type=="ad"` → `"ad"`.
  - `test_refreshes_on_401_then_retries_once`
  - `test_network_error_returns_unavailable`
  - `test_queue_filters_episodes`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Manual check.**
  - Ajay puts the Client ID and Secret in `.env` himself. The executor never handles the secret in chat.
  - Run `uv run lamp spotify-login` and log in, then play a song.
  - A small debug command, `uv run python -m lamp.song.spotify`, should print the track and progress.
  - If Spotify returns 403 because of developer-mode or Premium restrictions, stop and report to Ajay.
- [ ] **Step 6:** Commit: `feat: Spotify login and now-playing/queue client`

### Task 12: Audio fetch and analysis

**Files:**
- Create: `lamp/song/fetch.py`, `lamp/song/analyze.py`
- Test: `tests/song/test_fetch.py`, `tests/song/test_analyze.py`

**Interfaces:**
- Consumes: `Track`
- Produces:
  - `pick_candidate(track: Track, candidates: list[dict]) -> dict | None`. Candidates are yt-dlp info dicts. Reject entries with `|duration*1000 − track.duration_ms| > 10_000`, and penalize titles containing `live`, `remix`, `sped up`, `slowed`, `cover` or `karaoke` unless the Spotify title contains them. Among the rest, prefer the "official audio"/"topic" channel, then the smallest duration delta.
  - `async fetch_audio(track: Track, workdir: Path) -> Path | None`: runs `ytsearch5:{artists[0]} - {title} audio` without downloading, picks a candidate, downloads bestaudio, and converts it with ffmpeg to mono 22050 Hz wav. Returns None on any failure. Runs blocking work in a thread.
  - `@dataclass Analysis(duration_ms: int, tempo: float, beats_ms: list[int], downbeats_ms: list[int], hits_ms: list[int], energy: list[float], energy_hop_ms: int, sections: list[Section])` with `@dataclass Section(start_ms: int, end_ms: int, energy: float, label: str)`. Labels are `intro|verse|build|drop|break|outro`, assigned heuristically from relative energy and slope.
  - `analyze(path: Path) -> Analysis`:
    - beats: `librosa.beat.beat_track`
    - downbeats: every 4th beat, phase chosen by max onset strength
    - hits: onsets with strength > the 95th percentile, at least 250 ms apart
    - energy: RMS over 500 ms hops, normalized 0–1
    - sections: agglomerative segmentation on chroma+MFCC, 6–12 segments, merged when shorter than 8 s
  - `summarize(a: Analysis) -> dict`: compact, at most about 3 KB of JSON. It includes tempo, sections with energy and label, the first and last downbeats, and the hit times (capped at 64).
  - `Analysis.to_json()` / `Analysis.from_json()`

- [ ] **Step 1: Write failing tests**
  - `test_pick_candidate_rejects_duration_mismatch`
  - `test_pick_candidate_prefers_official_over_live`
  - `test_fetch_returns_none_when_ytdlp_raises` (yt-dlp is mocked)
  - `test_analyze_click_track`: a synthesized 120 BPM click track (numpy → soundfile) for 30 s, with a loud second half. Tempo is within 2 BPM of 120, the beat count is about 60 ± 3, and the last section's energy is greater than the first's.
  - `test_summarize_size_bound`
  - `test_analysis_json_roundtrip`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Manual check: fetch and analyze the currently playing Spotify track, and print the summary. The labels should look plausible against the song, and the wav should be deleted afterward (the caller does this; verify with `ls`).
- [ ] **Step 6:** Commit: `feat: YouTube audio fetch and librosa analysis`

### Task 13: Show schema, compiler, rule-based and ambient shows, cache

**Files:**
- Create: `lamp/song/show.py`, `lamp/song/cache.py`
- Test: `tests/song/test_show.py`, `tests/song/test_cache.py`

**Interfaces:**
- Consumes: `Analysis`, `Timeline`, `Cue`
- Produces:
  - `Pattern = Literal["hold","breathe","pulse_beat","pulse_downbeat","alternate_beat","rise","strobe_hits","blackout","drift"]`
  - `class ShowSection(BaseModel)`: `start_ms`, `end_ms`, `palette: list[tuple[int,int,int]]` (1–4 colors), `brightness: int` (1–100), `pattern: Pattern`, `intensity: float` (0–1)
  - `class Moment(BaseModel)`: `t_ms`, `action: Literal["blackout","flash","color"]`, `rgb: tuple[int,int,int] | None`, `duration_ms: int = 300`
  - `class Show(BaseModel)`: `version: Literal[1]`, `track_id`, `source: Literal["ai","rule","ambient"]`, `notes: str = ""`, `sections`, `moments`
  - `compile_show(show: Show, analysis: Analysis | None) -> Timeline`:
    - `alternate_beat` and `rise` use the `top`/`bottom` names.
    - `rise` lights bottom then top on each downbeat.
    - Flashes from `strobe_hits` and moments are thinned to ≤ 4 Hz per bulb.
    - Total cue density is kept within `max_updates_per_sec`.
    - When `analysis` is None (ambient), beat-based patterns degrade to `drift`/`breathe`.
  - `rule_based_show(track_id: str, analysis: Analysis) -> Show`: maps section labels to patterns, energy to brightness, a hue family from tempo/energy, a blackout 1 beat before each `drop`, and `strobe_hits` only in `drop` sections.
  - `ambient_show(track_id: str, duration_ms: int) -> Show`
  - `section_boundary_after(show: Show, t_ms: int) -> int`
  - `class ShowCache`: `__init__(dir: Path)`, `get(track_id) -> CachedTrack | None`, `put(track_id, analysis: Analysis | None, show: Show)`. Revising a show keeps the previous versions in `history`.

- [ ] **Step 1: Write failing tests**
  - `test_compile_pulse_beat_places_cues_on_beats`
  - `test_compile_respects_4hz_flash_limit`: `strobe_hits` with hits 100 ms apart → ≤ 4 flashes/s per bulb.
  - `test_compile_respects_update_budget`
  - `test_rule_based_blackout_before_drop`
  - `test_ambient_compiles_without_analysis`
  - `test_show_validation_rejects_bad_palette`: rgb 300 or an empty palette fails.
  - `test_cache_roundtrip_and_history`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: show schema, beat-grid compiler, rule-based and ambient shows`

### Task 14: AI show writer

**Files:**
- Create: `lamp/song/writer.py`
- Test: `tests/song/test_writer.py`

**Interfaces:**
- Consumes: `Budget`, `summarize`, `Show`, `rule_based_show`, `ambient_show`, OpenAI Responses API docs (via Exa)
- Produces:
  - `class ShowWriter`: `__init__(client, model: str, budget: Budget)`
    - `async write(track: Track, analysis: Analysis | None, instruction: str | None = None, previous: Show | None = None) -> Show`
    - It asks for a `Show` via Responses API structured output (`text.format` = JSON schema from `Show`, strict).
    - The prompt includes:
      - the title and artists
      - `summarize(analysis)`, or "no audio analysis available" for ambient
      - the lamp description
      - the pattern vocabulary and what each pattern does
      - the flash limit
      - guidance: be dramatic but tasteful; contrast between sections; the drop deserves an entrance; quiet sections stay calm
      - `instruction` and `previous` for redo requests ("redo this one, more chill")
    - It validates and clamps sections to the track duration. On a pydantic error it retries once with the error text. After that, or on an API error, timeout (60 s) or budget block, it returns `rule_based_show` (or `ambient_show` when there's no analysis), with `notes` saying why.

- [ ] **Step 1: Write failing tests** with a fake client:
  - `test_writer_returns_ai_show`
  - `test_invalid_show_falls_back_to_rule_based`: invalid twice → `source=="rule"` and the notes mention the validation failure.
  - `test_budget_block_returns_rule_without_calling_api`
  - `test_redo_includes_instruction_and_previous_in_prompt`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: AI show writer with validation and fallback`

### Task 15: Song mode: sync, prefetch, swap; API and UI

**Files:**
- Create: `lamp/song/mode.py`
- Modify: `lamp/runtime.py`, `lamp/web/app.py`, `web/static/index.html`, `web/static/app.js`
- Test: `tests/song/test_mode.py`, `tests/web/test_api.py`

**Interfaces:**
- Consumes: `SpotifyClient`, `fetch_audio`, `analyze`, `ShowCache`, `ShowWriter`, `compile_show`, `rule_based_show`, `ambient_show`, `ActivityManager.play(..., position_fn=…)`, `EventBus`, `Clock`
- Produces:
  - `class SongMode` implements `SongControl` from Task 7: `async start()`, `async stop()`, `async redo(instruction: str)`, `status() -> dict`
    - Status fields: `{on, track, state: "idle"|"preparing"|"ready"|"playing"|"paused"|"no_audio", source, reason}`
  - Loop while on, polling `now_playing()` every 1.5 s:
    - **Position clock:** `progress_ms + (now − fetched_at_ms) + settings.sync_offset_ms` while playing, frozen while paused. The poll result replaces the estimate when they differ by more than 250 ms; that's how seeks resync.
    - **Track change:** look in the cache. If a show is there, play it. If not, play `rule_based_show` once analysis exists (or a gentle "thinking" breathe while fetching), and start an AI write in the background. When it finishes, swap to the AI show at `section_boundary_after(current_position)`.
    - **Fetch failure:** play `ambient_show`, set `state="no_audio"`, and still write an AI ambient show if the budget allows.
    - **Prefetch:** after the current track is ready, take the first item of `queue()`. If it isn't cached and `budget.can_spend()`, fetch, analyze, write, and cache it in the background. There's at most one prefetch at a time.
    - **Pause** → `activity.stop()`, keeping the last state dimmed to 30%. **Resume** → replay from the position.
    - **`reason != "ok"`** → idle with the status reason. The lamp keeps its previous look.
  - Routes:
    - `POST /api/song/start`, `POST /api/song/stop`
    - `POST /api/song/redo {instruction?}`: rewrites and re-caches, then swaps immediately.
    - `GET /api/song/status`
    - SSE `song` events
  - UI "Now playing" card:
    - the track and artist, a state badge, and the source (`ai` / `rule` / `ambient`)
    - the start/stop toggle
    - "Redo show", with an optional instruction field
    - a sync offset slider (−300…+300 ms) in settings, saved to `data/settings.json` and overriding the `.env` default

- [ ] **Step 1: Write failing tests**, with a fake Spotify, fake fetch/analyze/writer, fake clock and fake activity:
  - `test_song_mode_idles_when_nothing_playing`
  - `test_cached_track_plays_immediately`
  - `test_uncached_plays_rule_then_swaps_to_ai_at_section_boundary`
  - `test_seek_resyncs`: the progress jumps by 60 s → `position_fn` reflects it within one poll.
  - `test_pause_stops_and_resume_continues`
  - `test_skip_switches_show`
  - `test_fetch_failure_uses_ambient_show`
  - `test_prefetch_next_in_queue_once_and_respects_budget`
  - `test_stop_song_mode_stops_activity`
  - `test_audio_file_deleted_after_analysis`: the workdir is empty after preparing a track, on both the success path and when analysis raises.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `mode.py`, wire it into `runtime.py`, and pass it to `PromptAgent` as `song`. Add the routes and UI, then run the screenshot loop for the now-playing card (preparing and playing states).
- [ ] **Step 4:** Run `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Manual end-to-end.**
  - Play a song on the phone's Spotify and say "sync to my music".
  - Confirm it plays the thinking breathe → rule show → AI show swap, and that the lights hit beats audibly in sync. Tune `sync_offset_ms`.
  - Seek to the middle and confirm it resyncs within about 2 s. Skip, and the next track (prefetched) starts with its show immediately.
  - Say "redo this one, more chill" and confirm the show changes.
  - Say "off" and confirm song mode stops.
- [ ] **Step 6:** Commit: `feat: Spotify-synced song mode with prefetch and live swap`

### Task 16: Runtime resilience: LaunchAgent, caffeinate, wake recovery, README

**Files:**
- Modify: `lamp/runtime.py`, `lamp/cli.py`
- Create: `README.md`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Produces:
  - `class KeepAwake`: holds `caffeinate -i -w <pid>` while `activity.kind != "idle"` and releases it at idle. `subprocess` is injected for tests.
  - `class WakeWatcher`: `__init__(on_wake: Callable[[], Awaitable[None]], interval_s=5, jump_threshold_s=20, wall=time.time, mono=time.monotonic)`. If wall-clock elapsed minus monotonic elapsed exceeds the threshold, it calls `on_wake`.
    - The `on_wake` handler: `lamp.refresh()`; abandon effects that are timed but not looped (for example, a 20-minute fade that should have finished is set to its end state); song mode resyncs.
  - `lamp install-agent`: writes `~/Library/LaunchAgents/com.ajay.lamp.plist` (RunAtLoad, KeepAlive, WorkingDirectory = repo, `uv run lamp serve`, logs to `data/lamp.log`) and runs `launchctl bootstrap gui/$UID …`. Add `lamp uninstall-agent`.
  - Also rediscover every 10 minutes, and immediately when a send target hasn't answered a `devStatus` query for 3 attempts.
- [ ] **Step 1: Write failing tests**
  - `test_keepawake_starts_and_stops_with_activity`
  - `test_wall_clock_jump_triggers_wake_handler`
  - `test_wake_completes_expired_fade`
  - `test_agent_plist_contents`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Write `README.md`:
  - **Setup:** `uv sync`, `cd web && npm i && npm run build`, `brew install mkcert`, `lamp certs`, the iPhone trust steps, filling in `.env`, `lamp spotify-login`, `lamp install-agent`.
  - **Daily use**, and the hardware notes from Task 2.
  - **Troubleshooting:** LAN switch off, bulbs not found, Spotify 403, certificate not trusted.
- [ ] **Step 6: Manual check.** Install the agent and reboot or log out and back in. The page is reachable from the phone. Close the lid for about 1 min, then open it: bulbs are rediscovered and controls work within about 10 s.
- [ ] **Step 7:** Commit: `feat: login agent, keep-awake, wake recovery, README`
