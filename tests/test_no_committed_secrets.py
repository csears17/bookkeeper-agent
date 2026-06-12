"""CI guard: the tracked .env.example template must contain only placeholders.

This catches a leaked secret even if the pre-commit hook is bypassed
(`git commit --no-verify`) or was never installed (`git config core.hooksPath`).
"""

from pathlib import Path

from bookkeeper_agent.secret_scan import find_secrets

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _lines() -> list[str]:
    return ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file()


def test_anthropic_api_key_is_placeholder():
    lines = [ln.strip() for ln in _lines() if ln.strip().startswith("ANTHROPIC_API_KEY=")]
    assert lines == ["ANTHROPIC_API_KEY=sk-ant-..."]


def test_token_enc_keys_is_empty():
    lines = [ln.strip() for ln in _lines() if ln.strip().startswith("TOKEN_ENC_KEYS=")]
    assert lines == ["TOKEN_ENC_KEYS="]


def test_no_real_secret_substrings():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for needle in ("sk-ant-api", "xoxb-", "xapp-"):
        assert needle not in text, f"{needle} found in .env.example"


def test_scanner_reports_env_example_clean():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert find_secrets(".env.example", text) == []
