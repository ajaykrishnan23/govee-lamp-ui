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


def test_env_file_found_from_any_directory(monkeypatch, tmp_path):
    from lamp.config import ENV_FILE
    assert ENV_FILE.name == ".env" and (ENV_FILE.parent / "pyproject.toml").exists()


def test_cli_missing_setting_message_hides_values(monkeypatch, tmp_path, capsys):
    import pytest

    from lamp import cli, config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-super-secret\n")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(SystemExit) as e:
        cli.load_settings()
    msg = str(e.value)
    assert "APP_PASSWORD" in msg and "sk-super-secret" not in msg
