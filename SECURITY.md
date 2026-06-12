# Security

## Preventing committed secrets

Real credentials must never land in tracked files. Two independent layers
enforce this; either one catches a leak on its own.

### 1. Pre-commit hook (local, fast)

Blocks a commit the moment a staged file contains a real-looking secret
(`sk-ant-` Anthropic keys, `xoxb-`/`xapp-` Slack tokens, `AIza` Google keys,
44-char Fernet keys on `TOKEN_ENC_KEYS`, or a non-placeholder value on any
`*_SECRET` / `*_TOKEN` / `ANTHROPIC_API_KEY` line in `.env.example`).

Enable it once per clone:

```sh
git config core.hooksPath .githooks
```

It then runs automatically on every `git commit`. To bypass it deliberately
(rare), use `git commit --no-verify`.

The detection logic lives in
[`src/bookkeeper_agent/secret_scan.py`](src/bookkeeper_agent/secret_scan.py)
so it is unit-tested rather than buried in shell. You can run it by hand:

```sh
PYTHONPATH=src python -m bookkeeper_agent.secret_scan --staged   # scan the index
PYTHONPATH=src python -m bookkeeper_agent.secret_scan FILE...    # scan files
```

### 2. CI test (catches a bypassed or uninstalled hook)

[`tests/test_no_committed_secrets.py`](tests/test_no_committed_secrets.py)
asserts the tracked `.env.example` only ever contains placeholders. It runs as
part of the normal suite (`./.venv/Scripts/python.exe -m pytest`), so even a
`--no-verify` commit or a clone without the hook configured is caught in CI.

### Placeholders are always allowed

Template values such as `sk-ant-...`, `xoxb-...`, empty assignments
(`TOKEN_ENC_KEYS=`), and `<your-secret>` are recognized as placeholders and
never block a commit.
