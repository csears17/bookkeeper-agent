from cryptography.fernet import Fernet

from bookkeeper_agent.app import App, build_app


def test_build_app_wires_everything(tmp_path, monkeypatch):
    clients = tmp_path / "clients.toml"
    clients.write_text(
        '[[client]]\nkey="habit-pilates"\ndisplay_name="Habit Pilates"\n'
        'provider="google"\nmailbox="habit@unionstreet.io"\nqbo_realm_id="111"\n'
    )
    monkeypatch.setenv("TOKEN_ENC_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("QBO_CLIENT_ID", "id")
    monkeypatch.setenv("QBO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("QBO_ENV", "sandbox")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-x")
    monkeypatch.setenv("SLACK_APPROVAL_CHANNEL", "C-APPROVALS")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("CLIENTS_PATH", str(clients))

    app = build_app(env_file=None)
    assert isinstance(app, App)
    assert "habit-pilates" in app.clients
    assert app.approval_channel == "C-APPROVALS"
    assert app.slack_app_token == "xapp-x"
    assert app.gate is not None and app.pipeline is not None


def test_build_app_errors_without_required_env(tmp_path, monkeypatch):
    import pytest
    for var in ("TOKEN_ENC_KEYS", "ANTHROPIC_API_KEY", "QBO_CLIENT_ID", "SLACK_BOT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        build_app(env_file=None)
