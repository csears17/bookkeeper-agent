"""Scan text for real-looking secrets so they never get committed.

Shared by two layers of defense:

* ``.githooks/pre-commit`` runs ``python -m bookkeeper_agent.secret_scan --staged``
  to block a commit that introduces a secret into a staged file.
* ``tests/test_no_committed_secrets.py`` asserts the tracked ``.env.example``
  template only ever contains placeholders, catching leaks in CI even if the
  hook is bypassed (``git commit --no-verify``) or not installed.

Pure standard library: no detect-secrets / gitleaks dependency.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Provider patterns. These match the *real* credential shapes, not the
# placeholder forms (``sk-ant-...``, ``xoxb-...``, empty values), which lack the
# length / character class of a genuine secret.
_PROVIDER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic API key (sk-ant-)", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("Slack bot token (xoxb-)", re.compile(r"xoxb-[A-Za-z0-9-]{10,}")),
    ("Slack app token (xapp-)", re.compile(r"xapp-[A-Za-z0-9-]{10,}")),
    ("Google API key (AIza)", re.compile(r"AIza[A-Za-z0-9_-]{30,}")),
]

# A Fernet key is 32 random bytes urlsafe-base64-encoded: 43 chars + "=" padding.
_FERNET_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}=")
_TOKEN_ENC_KEYS_LINE = re.compile(r"(?mi)^\s*TOKEN_ENC_KEYS\s*=\s*(.+)$")

# Lines in a .env.example template whose value must stay a placeholder.
# Use horizontal whitespace ([ \t]) around '=' — NOT \s, which matches newlines
# and would let an empty value (KEY=) swallow the following line as its "value".
_SECRET_ASSIGNMENT = re.compile(
    r"(?mi)^[ \t]*([A-Z0-9_]*(?:_SECRET|_TOKEN)|ANTHROPIC_API_KEY)[ \t]*=[ \t]*(.*?)[ \t]*$"
)


def _is_placeholder(value: str) -> bool:
    """True if ``value`` is empty or an obvious template placeholder."""
    v = value.strip().strip("'\"").strip()
    if not v:
        return True
    if "..." in v or "<" in v or ">" in v or "${" in v:
        return True
    lowered = v.lower()
    return lowered.startswith(
        ("your", "example", "changeme", "change-me", "placeholder", "xxx", "todo")
    )


def find_secrets(path: str, content: str) -> list[str]:
    """Return human-readable descriptions of secrets found in ``content``.

    ``path`` selects file-specific rules (the ``.env.example`` placeholder
    rule only applies to that template).
    """
    findings: list[str] = []

    for label, pattern in _PROVIDER_PATTERNS:
        if pattern.search(content):
            findings.append(label)

    m = _TOKEN_ENC_KEYS_LINE.search(content)
    if m:
        for part in m.group(1).split(","):
            if _FERNET_TOKEN.fullmatch(part.strip()):
                findings.append("Fernet key assigned to TOKEN_ENC_KEYS")
                break

    if path.replace("\\", "/").split("/")[-1] == ".env.example":
        for key, value in _SECRET_ASSIGNMENT.findall(content):
            if not _is_placeholder(value):
                findings.append(f"Real value on {key} line in .env.example")

    return findings


def scan_blobs(blobs: dict[str, str]) -> dict[str, list[str]]:
    """Map each path with findings to its list of findings (clean files omitted)."""
    return {
        path: found
        for path, content in blobs.items()
        if (found := find_secrets(path, content))
    }


def _staged_blobs() -> dict[str, str]:
    """Read the staged (index) content of every added/modified tracked file."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    blobs: dict[str, str] = {}
    for path in (line.strip() for line in out.splitlines() if line.strip()):
        blob = subprocess.run(
            ["git", "show", f":{path}"],
            capture_output=True,
            text=True,
        )
        if blob.returncode == 0:
            blobs[path] = blob.stdout
    return blobs


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--staged" in argv:
        blobs = _staged_blobs()
    else:
        paths = [a for a in argv if not a.startswith("-")]
        blobs = {}
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    blobs[path] = fh.read()
            except OSError as exc:  # pragma: no cover - defensive
                print(f"secret-scan: could not read {path}: {exc}", file=sys.stderr)

    findings = scan_blobs(blobs)
    if findings:
        print("ERROR: refusing to proceed - possible secrets detected:\n", file=sys.stderr)
        for path, items in findings.items():
            for item in items:
                print(f"  {path}: {item}", file=sys.stderr)
        print(
            "\nRemove the secret (use a placeholder in templates). "
            "To bypass intentionally: git commit --no-verify",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
