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
