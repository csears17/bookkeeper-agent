from cryptography.fernet import Fernet

from bookkeeper_agent import secret_scan
from bookkeeper_agent.secret_scan import find_secrets, main, scan_blobs

# Real-looking fixtures are split so the contiguous secret pattern never appears
# literally in this tracked file -- otherwise the scanner would flag its own
# test suite and the pre-commit hook would block editing it. The strings are
# reassembled at runtime, so the regexes are still exercised against the full
# value.
ANTHROPIC_KEY = "sk-ant-" + "api03-AbCdEf0123456789AbCdEf0123456789AbCdEf"
SLACK_BOT = "xoxb-" + "2468013579-1357924680-AbCdEfGhIjKlMnOpQrStUvWx"
SLACK_APP = "xapp-" + "1-A02ABCDEF-1357924680-AbCdEfGhIjKlMnOp"
GOOGLE_KEY = "AIza" + "SyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"


def test_flags_real_anthropic_key():
    findings = find_secrets("notes.txt", f"key = {ANTHROPIC_KEY}")
    assert findings
    assert any("anthropic" in f.lower() for f in findings)


def test_allows_anthropic_placeholder():
    assert find_secrets(".env.example", "ANTHROPIC_API_KEY=sk-ant-...") == []


def test_flags_slack_bot_and_app_tokens():
    bot = find_secrets("a.py", f'TOKEN = "{SLACK_BOT}"')
    app = find_secrets("a.py", f'TOKEN = "{SLACK_APP}"')
    assert bot and any("slack" in f.lower() for f in bot)
    assert app and any("slack" in f.lower() for f in app)


def test_allows_slack_placeholders():
    assert find_secrets("a.txt", "SLACK_BOT_TOKEN=xoxb-...\nSLACK_APP_TOKEN=xapp-...") == []


def test_flags_google_api_key():
    findings = find_secrets("a.txt", f"GOOGLE_KEY={GOOGLE_KEY}")
    assert findings and any("google" in f.lower() for f in findings)


def test_flags_fernet_key_assigned_to_token_enc_keys():
    # A real 44-char urlsafe base64 Fernet key (matches how this repo generates them).
    fernet = Fernet.generate_key().decode()
    findings = find_secrets(".env.example", f"TOKEN_ENC_KEYS={fernet}")
    assert findings and any("fernet" in f.lower() or "token_enc" in f.lower() for f in findings)


def test_allows_empty_token_enc_keys():
    assert find_secrets(".env.example", "TOKEN_ENC_KEYS=") == []


def test_flags_real_value_on_secret_line_in_env_example():
    findings = find_secrets(".env.example", "QBO_CLIENT_SECRET=A1b2C3d4E5f6G7h8I9j0")
    assert findings and any("secret" in f.lower() for f in findings)


def test_flags_real_value_on_token_line_in_env_example():
    findings = find_secrets(".env.example", "SOME_TOKEN=A1b2C3d4E5f6G7h8I9j0K1l2")
    assert findings


def test_allows_placeholder_values_on_secret_and_token_lines():
    content = (
        "QBO_CLIENT_SECRET=<your-secret>\n"
        "SOME_TOKEN=\n"
        "OTHER_TOKEN=...\n"
        "THIRD_TOKEN=${THIRD_TOKEN}\n"
        "FOURTH_TOKEN=your-token-here\n"
    )
    assert find_secrets(".env.example", content) == []


def test_empty_secret_value_does_not_swallow_next_line():
    # Regression: an empty KEY= on a _SECRET/_TOKEN line must NOT capture the
    # following line as its value (the \\s-crosses-newline bug).
    content = "QBO_CLIENT_SECRET=\nQBO_ENV=sandbox\n"
    assert find_secrets(".env.example", content) == []


def test_secret_line_rule_only_applies_to_env_example():
    # A real-looking secret value on a *_SECRET line in a normal file is fine
    # unless it matches a known provider pattern.
    assert find_secrets("config.py", "QBO_CLIENT_SECRET=A1b2C3d4E5f6G7h8I9j0") == []


def test_scan_blobs_returns_only_files_with_findings():
    blobs = {"clean.txt": "nothing to see here", "dirty.txt": ANTHROPIC_KEY}
    result = scan_blobs(blobs)
    assert "clean.txt" not in result
    assert "dirty.txt" in result


def test_main_staged_returns_1_when_secret_present(monkeypatch):
    monkeypatch.setattr(
        secret_scan, "_staged_blobs", lambda: {".env.example": f"ANTHROPIC_API_KEY={ANTHROPIC_KEY}"}
    )
    assert main(["--staged"]) == 1


def test_main_staged_returns_0_when_clean(monkeypatch):
    monkeypatch.setattr(
        secret_scan, "_staged_blobs", lambda: {".env.example": "ANTHROPIC_API_KEY=sk-ant-..."}
    )
    assert main(["--staged"]) == 0


def test_main_scans_given_paths(tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("nothing here", encoding="utf-8")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text(SLACK_BOT, encoding="utf-8")

    assert main([str(clean)]) == 0
    assert main([str(dirty)]) == 1
