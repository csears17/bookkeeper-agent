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
