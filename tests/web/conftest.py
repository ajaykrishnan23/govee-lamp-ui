import httpx
import pytest

from lamp.config import Settings
from lamp.runtime import build_app
from tests.ai.test_agent import FakeClient, resp
from tests.fakes import A, B, FakeTransport, fake_discover

SECRET_VALUES = ["sk-test-openai", "spotify-secret-xyz", "pw-123"]


@pytest.fixture
def settings(tmp_path):
    return Settings(app_password="pw-123", openai_api_key="sk-test-openai", spotify_client_secret="spotify-secret-xyz",
                    spotify_client_id="cid", data_dir=tmp_path / "data", max_updates_per_sec=1000)


@pytest.fixture
def ai():
    return FakeClient(resp(text="Cozy."), resp(text="Again."))


@pytest.fixture
async def app_env(settings, ai, transcriber):
    transport = FakeTransport()
    app, svc = build_app(settings, transport=transport, ai_client=ai, discover_fn=fake_discover(A, B),
                         transcriber=transcriber)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            yield client, svc, transport


@pytest.fixture
async def authed(app_env):
    client, svc, transport = app_env
    r = await client.post("/login", json={"password": "pw-123"})
    assert r.status_code == 200
    return client, svc, transport


class FakeTranscriber:
    def __init__(self, text="lights off"):
        self.text = text
        self.paths = []

    def transcribe(self, path):
        self.paths.append(path)
        assert path.exists()
        return self.text


@pytest.fixture
def transcriber():
    return FakeTranscriber()
