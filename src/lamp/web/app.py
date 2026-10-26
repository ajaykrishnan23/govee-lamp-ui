"""HTTP routes: login, quick controls, prompts, live events, static UI."""
import asyncio
import functools
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import COOKIE, MAX_AGE_S

if TYPE_CHECKING:
    from ..runtime import Services

log = logging.getLogger(__name__)

MAX_VOICE_BYTES = 2 * 1024 * 1024


class Login(BaseModel):
    password: str


class Power(BaseModel):
    target: str = "all"
    on: bool


class Brightness(BaseModel):
    target: str = "all"
    value: int


class Color(BaseModel):
    target: str = "all"
    rgb: tuple[int, int, int] | None = None
    kelvin: int | None = None


class Prompt(BaseModel):
    text: str


class Rename(BaseModel):
    old: str
    new: str


def create_app(svc: "Services", lifespan=None) -> FastAPI:
    app = FastAPI(title="lamp", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    static = svc.settings.static_dir

    def authed(request: Request) -> bool:
        return svc.settings.dev_noauth or svc.signer.verify(request.cookies.get(COOKIE))

    def require(request: Request) -> None:
        if not authed(request):
            raise HTTPException(401, "login required")

    def bad_request(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **kw):
            try:
                return await fn(*a, **kw)
            except ValueError as e:
                raise HTTPException(400, str(e))
        return wrapper

    @app.post("/login")
    async def login(body: Login, response: Response):
        if not svc.signer.check_password(body.password):
            raise HTTPException(401, "wrong password")
        response.set_cookie(COOKIE, svc.signer.issue(), max_age=MAX_AGE_S, httponly=True,
                            secure=True, samesite="strict")
        return {"ok": True}

    @app.get("/login")
    async def login_page():
        return FileResponse(static / "login.html")

    @app.get("/")
    async def index(request: Request):
        if not authed(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(static / "index.html")

    api = Depends(require)

    @app.get("/api/state", dependencies=[api])
    async def state():
        return svc.snapshot()

    @app.post("/api/power", dependencies=[api])
    @bad_request
    async def power(body: Power):
        await svc.ctl.set(body.target, {"on": body.on})
        return {"ok": True}

    @app.post("/api/brightness", dependencies=[api])
    @bad_request
    async def brightness(body: Brightness):
        await svc.ctl.set(body.target, {"on": True, "brightness": max(1, min(100, body.value))})
        return {"ok": True}

    @app.post("/api/color", dependencies=[api])
    @bad_request
    async def color(body: Color):
        if body.rgb is not None:
            patch = {"rgb": tuple(max(0, min(255, c)) for c in body.rgb)}
        elif body.kelvin is not None:
            patch = {"kelvin": max(2000, min(9000, body.kelvin))}
        else:
            raise ValueError("give rgb or kelvin")
        await svc.ctl.set(body.target, {"on": True, **patch})
        return {"ok": True}

    @app.post("/api/preset/{name}", dependencies=[api])
    async def preset(name: str):
        p = svc.ctl.presets.get(name)
        if not p:
            raise HTTPException(404, f"no mood {name!r}")
        await svc.ctl.apply_preset(p)
        return {"ok": True}

    @app.delete("/api/preset/{name}", dependencies=[api])
    @bad_request
    async def delete_preset(name: str):
        svc.ctl.presets.delete(name)
        svc.publish_state()
        return {"ok": True}

    @app.post("/api/prompt", dependencies=[api])
    async def prompt(body: Prompt):
        return await svc.handle_prompt(body.text)

    @app.post("/api/voice", dependencies=[api])
    async def voice(audio: UploadFile = File(...)):
        data = await audio.read(MAX_VOICE_BYTES + 1)
        if len(data) > MAX_VOICE_BYTES:
            raise HTTPException(413, "clip too long")
        suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix) as f:
            f.write(data)
            f.flush()
            try:
                text = await asyncio.to_thread(svc.transcriber.transcribe, Path(f.name))
            except Exception as e:
                log.exception("transcription failed")
                return {"text": "", "reply": "Couldn't make out the audio.", "actions": [], "error": str(e), "via": "voice"}
        if not text.strip():
            return {"text": "", "reply": "Didn't catch that.", "actions": [], "error": "heard nothing", "via": "voice"}
        return {"text": text, **await svc.handle_prompt(text)}

    @app.post("/api/stop", dependencies=[api])
    async def stop():
        await svc.ctl.stop()
        return {"ok": True}

    @app.post("/api/bulbs/rename", dependencies=[api])
    @bad_request
    async def rename(body: Rename):
        svc.lamp.rename(body.old, body.new.strip().lower())
        return {"ok": True}

    @app.post("/api/bulbs/swap", dependencies=[api])
    @bad_request
    async def swap():
        svc.lamp.swap()
        return {"ok": True}

    @app.post("/api/bulbs/rediscover", dependencies=[api])
    async def rediscover():
        await svc.lamp.refresh()
        return {"bulbs": svc.lamp.names()}

    @app.get("/api/events", dependencies=[api])
    async def events():
        snap = svc.snapshot()
        return StreamingResponse(svc.bus.subscribe(initial=[("snapshot", snap)]), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    if static.exists():
        app.mount("/static", StaticFiles(directory=static), name="static")
    return app
