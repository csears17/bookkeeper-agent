# Bookkeeper Agent — WS-A Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tested core library for the bookkeeper-agent — config, encrypted token storage, SQLite models, a fixed client→inbox→company registry, a cost meter with a hard monthly spend cap, and an append-only audit log — with no live external calls.

**Architecture:** A small Python package (`src/bookkeeper_agent/`) with focused modules. Storage is local SQLite via SQLAlchemy 2.0. Secrets use Fernet/MultiFernet envelope encryption (ported pattern from Coast). The client map is loaded from a version-controlled TOML file — never the DB — so the model can never choose which book a bill lands in. The cost meter wraps every future Claude call: `check_cap()` before, `record()` after; `SpendCapExceeded` is raised at 100% of the monthly cap.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, cryptography (Fernet), python-dotenv, tomllib (stdlib), pytest.

This plan is WS-A of three (WS-B Connectors, WS-C Agent pipeline follow). Full design: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`.

---

## File structure (created by this plan)

```
bookkeeper-agent/
  pyproject.toml                       # package + deps + pytest config
  .gitignore
  .env.example                         # documents required env vars (no secrets)
  clients.example.toml                 # documents the client map shape
  src/bookkeeper_agent/
    __init__.py
    config.py                          # Settings.load() from env/.env
    security.py                        # TokenCipher (Fernet/MultiFernet)
    clients.py                         # ClientConfig + load_clients() from TOML
    costs.py                           # cost_usd(), CostMeter, SpendCapExceeded
    audit.py                           # record_event(), list_events()
    db/
      __init__.py
      base.py                          # Base, make_engine, init_db, session_scope
      models.py                        # OAuthToken, CostRecord, AuditEvent
  tests/
    __init__.py
    conftest.py                        # in-memory engine fixture
    test_config.py
    test_security.py
    test_clients.py
    test_db_models.py
    test_costs.py
    test_audit.py
```

Each module has one responsibility. `db/models.py` holds only WS-A tables (OAuthToken, CostRecord, AuditEvent); PendingBill and connector-specific tables are added in their own workstreams.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `clients.example.toml`
- Create: `src/bookkeeper_agent/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
def test_package_imports():
    import bookkeeper_agent

    assert bookkeeper_agent.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent'`

- [ ] **Step 3: Create the scaffold files**

`pyproject.toml`:
```toml
[project]
name = "bookkeeper-agent"
version = "0.1.0"
description = "Internal Claude-powered AP/bookkeeping agent (bills -> QBO, Slack-approved)"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.49",
    "SQLAlchemy>=2.0",
    "cryptography>=42",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
pythonpath = ["src"]
```

`.gitignore`:
```gitignore
__pycache__/
*.pyc
.venv/
.env
clients.toml
*.db
.pytest_cache/
build/
dist/
*.egg-info/
```

`.env.example`:
```dotenv
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-opus-4-8

# Token encryption: one or more Fernet keys, comma-separated.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# First key encrypts; all keys can decrypt (rotation).
TOKEN_ENC_KEYS=

# Spend cap (USD per calendar month). Warn at 75%, hard stop at 100%.
MONTHLY_USD_CAP=25

# Local paths
DB_PATH=bookkeeper.db
CLIENTS_PATH=clients.toml
```

`clients.example.toml`:
```toml
# Fixed client -> inbox -> QBO-company map. Copy to clients.toml (gitignored) and fill in.
# provider is "google" or "microsoft". mailbox must be unique across all clients.
# autonomy_level: 0 = Slack-approve before any write (default). 1/2 reserved for later.

[[client]]
key = "habit-pilates"
display_name = "Habit Pilates"
provider = "google"
mailbox = "habit@unionstreet.io"
qbo_realm_id = "1234567890"
autonomy_level = 0

[[client]]
key = "2expect"
display_name = "2Expect LLC"
provider = "microsoft"
mailbox = "2expect@unionstreet.io"
qbo_realm_id = "9876543210"
autonomy_level = 0
```

`src/bookkeeper_agent/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore .env.example clients.example.toml src/bookkeeper_agent/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore(ws-a): project scaffold + smoke test"
```

---

## Task 2: Settings loader

**Files:**
- Create: `src/bookkeeper_agent/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.config'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/config.py`:
```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    token_enc_keys: list[str]
    monthly_usd_cap: float
    db_path: Path
    clients_path: Path
    model: str = "claude-opus-4-8"

    @classmethod
    def load(cls, env_file: str | None = ".env") -> "Settings":
        if env_file and Path(env_file).exists():
            load_dotenv(env_file)
        keys = [k.strip() for k in os.environ.get("TOKEN_ENC_KEYS", "").split(",") if k.strip()]
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            token_enc_keys=keys,
            monthly_usd_cap=float(os.environ.get("MONTHLY_USD_CAP", "25")),
            db_path=Path(os.environ.get("DB_PATH", "bookkeeper.db")),
            clients_path=Path(os.environ.get("CLIENTS_PATH", "clients.toml")),
            model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/config.py tests/test_config.py
git commit -m "feat(ws-a): Settings loader from env/.env"
```

---

## Task 3: TokenCipher (envelope encryption)

**Files:**
- Create: `src/bookkeeper_agent/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: Write the failing test**

`tests/test_security.py`:
```python
import pytest
from cryptography.fernet import Fernet

from bookkeeper_agent.security import TokenCipher


def test_round_trip():
    cipher = TokenCipher([Fernet.generate_key().decode()])
    token = cipher.encrypt("super-secret-refresh-token")
    assert token != b"super-secret-refresh-token"
    assert cipher.decrypt(token) == "super-secret-refresh-token"


def test_multifernet_decrypts_with_old_key_after_rotation():
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = TokenCipher([old_key])
    token = old_cipher.encrypt("value")

    # New cipher lists new key first, old key second: must still decrypt old token.
    rotated = TokenCipher([new_key, old_key])
    assert rotated.decrypt(token) == "value"


def test_requires_at_least_one_key():
    with pytest.raises(ValueError):
        TokenCipher([])


def test_repr_hides_keys():
    cipher = TokenCipher([Fernet.generate_key().decode()])
    assert "key" not in repr(cipher).lower() or "hidden" in repr(cipher).lower()
    assert "<hidden>" in repr(cipher)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.security'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/security.py`:
```python
from __future__ import annotations

from cryptography.fernet import Fernet, MultiFernet


class TokenCipher:
    """Fernet/MultiFernet envelope encryption for secrets at rest.

    Pass one or more Fernet keys. The first key encrypts; every key can
    decrypt, which enables key rotation (add the new key first, keep the
    old one until all tokens are re-encrypted via rotate()).
    """

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("TokenCipher requires at least one Fernet key")
        self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])

    @classmethod
    def from_keys(cls, keys: list[str]) -> "TokenCipher":
        return cls(keys)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode()

    def rotate(self, token: bytes) -> bytes:
        """Re-encrypt an existing token under the current primary key."""
        return self._fernet.rotate(token)

    def __repr__(self) -> str:
        return "TokenCipher(keys=<hidden>)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_security.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/security.py tests/test_security.py
git commit -m "feat(ws-a): TokenCipher Fernet/MultiFernet envelope encryption"
```

---

## Task 4: DB base + models

**Files:**
- Create: `src/bookkeeper_agent/db/__init__.py`
- Create: `src/bookkeeper_agent/db/base.py`
- Create: `src/bookkeeper_agent/db/models.py`
- Create: `tests/conftest.py`
- Test: `tests/test_db_models.py`

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`:
```python
import pytest
from sqlalchemy import create_engine

from bookkeeper_agent.db.base import Base


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    return eng
```

`tests/test_db_models.py`:
```python
from datetime import datetime, timezone

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent, CostRecord, OAuthToken


def test_oauth_token_round_trip(engine):
    with session_scope(engine) as s:
        s.add(OAuthToken(service="qbo", ref="1234567890", secret_ciphertext=b"abc"))
    with session_scope(engine) as s:
        row = s.query(OAuthToken).filter_by(service="qbo", ref="1234567890").one()
        assert row.secret_ciphertext == b"abc"


def test_cost_record_and_audit_event_persist(engine):
    with session_scope(engine) as s:
        s.add(CostRecord(
            ym="2026-06", model="claude-opus-4-8", input_tokens=1000,
            output_tokens=500, cache_creation_input_tokens=0,
            cache_read_input_tokens=0, usd=0.0175, request_id="req_1",
            capability="bills",
        ))
        s.add(AuditEvent(kind="system", summary="started"))
    with session_scope(engine) as s:
        assert s.query(CostRecord).count() == 1
        ev = s.query(AuditEvent).one()
        assert ev.kind == "system"
        assert isinstance(ev.ts, datetime)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.db'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/db/__init__.py`:
```python
```

`src/bookkeeper_agent/db/base.py`:
```python
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_path: str | Path) -> Engine:
    return create_engine(f"sqlite:///{db_path}", future=True)


def init_db(engine: Engine) -> None:
    # Import models so they register on Base.metadata before create_all.
    from bookkeeper_agent.db import models  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine):
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

`src/bookkeeper_agent/db/models.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bookkeeper_agent.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OAuthToken(Base):
    """Encrypted secret for a service connection.

    service: "qbo" | "slack" | "google" | "microsoft"
    ref: discriminator within a service (e.g. QBO realm_id; "default" for app-level).
    secret_ciphertext: TokenCipher-encrypted bytes.
    """

    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("service", "ref", name="uq_service_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(128), default="default")
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class CostRecord(Base):
    """One row per Claude API call, used for spend tracking and usage audit."""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=_utcnow)
    ym: Mapped[str] = mapped_column(String(7))  # "YYYY-MM"
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0)
    usd: Mapped[float] = mapped_column(default=0.0)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditEvent(Base):
    """Append-only forensic record. Never updated or deleted in code."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=_utcnow)
    kind: Mapped[str] = mapped_column(String(32))  # read|proposal|approval|rejection|write|system
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    company_realm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(512))
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_db_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/db/ tests/conftest.py tests/test_db_models.py
git commit -m "feat(ws-a): SQLite base + OAuthToken/CostRecord/AuditEvent models"
```

---

## Task 5: Client registry (fixed config)

**Files:**
- Create: `src/bookkeeper_agent/clients.py`
- Test: `tests/test_clients.py`

- [ ] **Step 1: Write the failing test**

`tests/test_clients.py`:
```python
import pytest

from bookkeeper_agent.clients import ClientConfigError, load_clients

VALID = """
[[client]]
key = "habit-pilates"
display_name = "Habit Pilates"
provider = "google"
mailbox = "habit@unionstreet.io"
qbo_realm_id = "111"
autonomy_level = 0

[[client]]
key = "2expect"
display_name = "2Expect LLC"
provider = "microsoft"
mailbox = "2expect@unionstreet.io"
qbo_realm_id = "222"
"""


def _write(tmp_path, text):
    p = tmp_path / "clients.toml"
    p.write_text(text)
    return p


def test_loads_valid_clients(tmp_path):
    clients = load_clients(_write(tmp_path, VALID))
    assert set(clients) == {"habit-pilates", "2expect"}
    assert clients["habit-pilates"].mailbox == "habit@unionstreet.io"
    assert clients["2expect"].autonomy_level == 0  # default applied


def test_company_for_mailbox_lookup(tmp_path):
    clients = load_clients(_write(tmp_path, VALID))
    by_mailbox = {c.mailbox: c for c in clients.values()}
    assert by_mailbox["habit@unionstreet.io"].qbo_realm_id == "111"


def test_rejects_duplicate_mailbox(tmp_path):
    dupe = VALID + """
[[client]]
key = "third"
display_name = "Third"
provider = "google"
mailbox = "habit@unionstreet.io"
qbo_realm_id = "333"
"""
    with pytest.raises(ClientConfigError, match="duplicate mailbox"):
        load_clients(_write(tmp_path, dupe))


def test_rejects_bad_provider(tmp_path):
    bad = """
[[client]]
key = "x"
display_name = "X"
provider = "yahoo"
mailbox = "x@unionstreet.io"
qbo_realm_id = "1"
"""
    with pytest.raises(ClientConfigError, match="provider"):
        load_clients(_write(tmp_path, bad))


def test_rejects_bad_autonomy_level(tmp_path):
    bad = """
[[client]]
key = "x"
display_name = "X"
provider = "google"
mailbox = "x@unionstreet.io"
qbo_realm_id = "1"
autonomy_level = 5
"""
    with pytest.raises(ClientConfigError, match="autonomy_level"):
        load_clients(_write(tmp_path, bad))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_clients.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.clients'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/clients.py`:
```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_VALID_PROVIDERS = {"google", "microsoft"}


class ClientConfigError(ValueError):
    """Raised when the client map is invalid."""


@dataclass(frozen=True)
class ClientConfig:
    key: str
    display_name: str
    provider: str
    mailbox: str
    qbo_realm_id: str
    autonomy_level: int = 0


def load_clients(path: str | Path) -> dict[str, ClientConfig]:
    """Load and validate the fixed client->inbox->company map.

    Returns a dict keyed by client key. Raises ClientConfigError on any
    structural problem (missing field, bad provider, duplicate key/mailbox,
    out-of-range autonomy level).
    """
    data = tomllib.loads(Path(path).read_text())
    entries = data.get("client", [])
    if not entries:
        raise ClientConfigError("no [[client]] entries found")

    clients: dict[str, ClientConfig] = {}
    seen_mailboxes: set[str] = set()
    required = ("key", "display_name", "provider", "mailbox", "qbo_realm_id")

    for entry in entries:
        for field in required:
            if not entry.get(field):
                raise ClientConfigError(f"client entry missing required field: {field}")
        key = entry["key"]
        provider = entry["provider"]
        mailbox = entry["mailbox"]
        autonomy = int(entry.get("autonomy_level", 0))

        if provider not in _VALID_PROVIDERS:
            raise ClientConfigError(
                f"client {key!r}: provider must be one of {sorted(_VALID_PROVIDERS)}, got {provider!r}"
            )
        if key in clients:
            raise ClientConfigError(f"duplicate client key: {key!r}")
        if mailbox in seen_mailboxes:
            raise ClientConfigError(f"duplicate mailbox: {mailbox!r}")
        if autonomy not in (0, 1, 2):
            raise ClientConfigError(f"client {key!r}: autonomy_level must be 0, 1, or 2, got {autonomy}")

        seen_mailboxes.add(mailbox)
        clients[key] = ClientConfig(
            key=key,
            display_name=entry["display_name"],
            provider=provider,
            mailbox=mailbox,
            qbo_realm_id=str(entry["qbo_realm_id"]),
            autonomy_level=autonomy,
        )

    return clients
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_clients.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/clients.py tests/test_clients.py
git commit -m "feat(ws-a): fixed client->inbox->company registry from TOML"
```

---

## Task 6: Cost meter + spend-cap gate

**Files:**
- Create: `src/bookkeeper_agent/costs.py`
- Test: `tests/test_costs.py`

- [ ] **Step 1: Write the failing test**

`tests/test_costs.py`:
```python
import pytest

from bookkeeper_agent.costs import CostMeter, SpendCapExceeded, cost_usd


def test_cost_usd_opus_rates():
    # Opus 4.8: $5/1M input, $25/1M output.
    usd = cost_usd("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0)
    assert usd == pytest.approx(5.0)
    usd = cost_usd("claude-opus-4-8", input_tokens=0, output_tokens=1_000_000)
    assert usd == pytest.approx(25.0)


def test_cost_usd_cache_tiers():
    # cache write = 1.25x input; cache read = 0.1x input.
    usd = cost_usd(
        "claude-opus-4-8",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert usd == pytest.approx(6.25 + 0.5)


def test_record_accumulates_month_total(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, ym="2026-06")  # $5
    meter.record("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, ym="2026-06")  # $5
    assert meter.month_total("2026-06") == pytest.approx(10.0)
    assert meter.month_total("2026-07") == pytest.approx(0.0)


def test_check_cap_raises_at_cap(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=2_000_000, output_tokens=0, ym="2026-06")  # $10
    with pytest.raises(SpendCapExceeded):
        meter.check_cap(ym="2026-06")


def test_check_cap_ok_below_cap(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, ym="2026-06")  # $5
    meter.check_cap(ym="2026-06")  # no raise


def test_status_warn_flag_at_75pct(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=1_500_000, output_tokens=0, ym="2026-06")  # $7.50
    status = meter.status(ym="2026-06")
    assert status["warn"] is True
    assert status["ratio"] == pytest.approx(0.75)
    assert status["total"] == pytest.approx(7.5)
    assert status["cap"] == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_costs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.costs'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/costs.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import CostRecord

# USD per token. cache_write = 1.25x input, cache_read = 0.1x input.
_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {
        "input": 5.0 / 1_000_000,
        "output": 25.0 / 1_000_000,
        "cache_write": 6.25 / 1_000_000,
        "cache_read": 0.5 / 1_000_000,
    },
}


class SpendCapExceeded(Exception):
    """Raised when the month's Claude spend has reached the configured cap."""


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    if model not in _PRICES:
        raise KeyError(f"no price table for model {model!r}")
    p = _PRICES[model]
    return (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_creation_input_tokens * p["cache_write"]
        + cache_read_input_tokens * p["cache_read"]
    )


def _current_ym() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class CostMeter:
    """Tracks monthly Claude spend in the DB and enforces a hard cap.

    Usage in the agentic loop:
        meter.check_cap()          # before a model call; raises SpendCapExceeded at 100%
        resp = client.messages.create(...)
        meter.record(model, **resp.usage_as_kwargs, request_id=resp._request_id)
    """

    def __init__(self, engine: Engine, monthly_cap: float, warn_ratio: float = 0.75):
        self._engine = engine
        self.monthly_cap = monthly_cap
        self.warn_ratio = warn_ratio

    def month_total(self, ym: str | None = None) -> float:
        ym = ym or _current_ym()
        with session_scope(self._engine) as s:
            total = s.execute(
                select(func.coalesce(func.sum(CostRecord.usd), 0.0)).where(CostRecord.ym == ym)
            ).scalar_one()
        return float(total)

    def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        request_id: str | None = None,
        capability: str | None = None,
        ym: str | None = None,
    ) -> float:
        ym = ym or _current_ym()
        usd = cost_usd(
            model,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
        )
        with session_scope(self._engine) as s:
            s.add(CostRecord(
                ym=ym,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                usd=usd,
                request_id=request_id,
                capability=capability,
            ))
        return usd

    def check_cap(self, ym: str | None = None) -> None:
        ym = ym or _current_ym()
        total = self.month_total(ym)
        if total >= self.monthly_cap:
            raise SpendCapExceeded(
                f"month {ym} spend ${total:.2f} has reached cap ${self.monthly_cap:.2f}"
            )

    def status(self, ym: str | None = None) -> dict:
        ym = ym or _current_ym()
        total = self.month_total(ym)
        ratio = (total / self.monthly_cap) if self.monthly_cap else 0.0
        return {
            "ym": ym,
            "total": total,
            "cap": self.monthly_cap,
            "ratio": ratio,
            "warn": ratio >= self.warn_ratio,
            "exceeded": total >= self.monthly_cap,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_costs.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/costs.py tests/test_costs.py
git commit -m "feat(ws-a): cost meter with 75%/100% monthly spend cap"
```

---

## Task 7: Audit log

**Files:**
- Create: `src/bookkeeper_agent/audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

`tests/test_audit.py`:
```python
import json

from bookkeeper_agent.audit import list_events, record_event
from bookkeeper_agent.db.base import session_scope


def test_record_and_list(engine):
    with session_scope(engine) as s:
        record_event(s, kind="proposal", summary="Proposed bill for ACME",
                     client_key="habit-pilates", company_realm="111",
                     request_id="req_1", detail={"amount": 250.0})
        record_event(s, kind="write", summary="Created bill 42",
                     client_key="habit-pilates", company_realm="111")

    events = list_events(engine)
    assert len(events) == 2
    kinds = {e.kind for e in events}
    assert kinds == {"proposal", "write"}
    proposal = next(e for e in events if e.kind == "proposal")
    assert json.loads(proposal.detail_json)["amount"] == 250.0


def test_list_filter_by_client(engine):
    with session_scope(engine) as s:
        record_event(s, kind="write", summary="a", client_key="habit-pilates", company_realm="111")
        record_event(s, kind="write", summary="b", client_key="2expect", company_realm="222")

    only = list_events(engine, client_key="2expect")
    assert len(only) == 1
    assert only[0].company_realm == "222"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.audit'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/audit.py`:
```python
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent


def record_event(
    session: Session,
    kind: str,
    summary: str,
    client_key: str | None = None,
    company_realm: str | None = None,
    request_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit event. Append-only: there is no update/delete API."""
    session.add(AuditEvent(
        kind=kind,
        summary=summary,
        client_key=client_key,
        company_realm=company_realm,
        request_id=request_id,
        detail_json=json.dumps(detail) if detail is not None else None,
    ))


def list_events(
    engine: Engine,
    client_key: str | None = None,
    kind: str | None = None,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.id)
    if client_key is not None:
        stmt = stmt.where(AuditEvent.client_key == client_key)
    if kind is not None:
        stmt = stmt.where(AuditEvent.kind == kind)
    with session_scope(engine) as s:
        rows = list(s.execute(stmt).scalars().all())
        # Detach so callers can read attributes after the session closes.
        for r in rows:
            s.expunge(r)
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_audit.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/audit.py tests/test_audit.py
git commit -m "feat(ws-a): append-only audit log"
```

---

## Task 8: Full-suite green + WS-A wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS — all tests across test_smoke, test_config, test_security, test_db_models, test_clients, test_costs, test_audit (21 tests).

- [ ] **Step 2: Confirm secrets are gitignored**

Run: `git status --porcelain`
Expected: clean (no `.env`, no `clients.toml`, no `*.db` showing as untracked-and-about-to-be-committed). If any appear, verify `.gitignore` from Task 1.

- [ ] **Step 3: Tag the workstream**

```bash
git tag ws-a-foundations
```

---

## Self-review against the spec

- **§3 storage (SQLite) / TokenCipher reuse** → Tasks 3 (TokenCipher), 4 (SQLite base + models). ✓
- **§5 secrets & encryption** → Task 3; tokens stored encrypted via `OAuthToken.secret_ciphertext` (Task 4). ✓
- **§5 multi-book isolation (fixed config map)** → Task 5 loads the client map from TOML, not the DB, and rejects duplicate mailboxes so inbox→company stays unambiguous. ✓
- **§5 spend cap (warn 75% / hard stop 100%)** → Task 6 (`status()["warn"]` at 0.75, `check_cap()` raises `SpendCapExceeded` at 1.0). ✓
- **§5 audit log (append-only, stamped with request_id + company)** → Tasks 4 (model) + 7 (record/list; no update/delete API). ✓
- **§3 engine model default `claude-opus-4-8`, changeable** → Task 2 (`Settings.model` from `CLAUDE_MODEL`, default Opus). ✓

**Deferred to later workstreams (correctly out of scope here):** Gmail/Graph/QBO/Slack connectors (WS-B); pre-screen, Claude classify/extract/categorize, the manual tool-use loop + write-gate, the poller, PendingBill model (WS-C). The cost meter and audit log are built now so WS-C wires straight into them.

**Placeholder scan:** none — every code step shows complete, runnable code.

**Type consistency:** `OAuthToken(service, ref, secret_ciphertext)`, `CostRecord(ym, model, *_tokens, usd, request_id, capability)`, `AuditEvent(kind, summary, client_key, company_realm, request_id, detail_json)`, `CostMeter(engine, monthly_cap, warn_ratio)`, `cost_usd(model, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens)`, `record_event(session, kind, summary, ...)`, `list_events(engine, client_key, kind)` — names are consistent across tasks and tests.
