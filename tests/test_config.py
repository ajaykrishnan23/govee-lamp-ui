from lamp.config import Settings


def test_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("APP_PASSWORD", "x")
    s = Settings()
    assert s.app_password == "x"
    assert s.monthly_budget_usd == 10.0
    assert s.port == 8443
    assert s.prompt_model == "gpt-6-luna"
    assert s.show_model == "gpt-6-luna"
