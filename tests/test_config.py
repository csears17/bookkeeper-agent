from pathlib import Path

from bookkeeper_agent.config import Settings


def test_load_reads_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("TOKEN_ENC_KEYS", "key-a, key-b")
    monkeypatch.setenv("MONTHLY_USD_CAP", "40")
    monkeypatch.setenv("DB_PATH", "/tmp/x.db")
    monkeypatch.setenv("CLIENTS_PATH", "/tmp/clients.toml")

    s = Settings.load(env_file=None)

    assert s.anthropic_api_key == "sk-ant-test"
    assert s.token_enc_keys == ["key-a", "key-b"]
    assert s.monthly_usd_cap == 40.0
    assert s.db_path == Path("/tmp/x.db")
    assert s.clients_path == Path("/tmp/clients.toml")
    assert s.model == "claude-opus-4-8"


def test_defaults(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "TOKEN_ENC_KEYS", "MONTHLY_USD_CAP", "DB_PATH", "CLIENTS_PATH", "CLAUDE_MODEL"):
        monkeypatch.delenv(var, raising=False)

    s = Settings.load(env_file=None)

    assert s.token_enc_keys == []
    assert s.monthly_usd_cap == 25.0
    assert s.db_path == Path("bookkeeper.db")
