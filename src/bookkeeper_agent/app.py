"""Build the running agent from .env: real connectors + pipeline + write-gate."""
from __future__ import annotations

import os
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

from bookkeeper_agent.clients import ClientConfig, load_clients
from bookkeeper_agent.connectors.qbo_http import HttpxQboConnector
from bookkeeper_agent.connectors.qbo_oauth import QboOAuth, QboOAuthConfig
from bookkeeper_agent.connectors.qbo_tokens import QboTokenManager
from bookkeeper_agent.connectors.slack_http import HttpxSlackConnector
from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.costs import CostMeter
from bookkeeper_agent.db.base import init_db, make_engine
from bookkeeper_agent.llm.anthropic_client import AnthropicLlmClient
from bookkeeper_agent.pipeline.process import BillsPipeline
from bookkeeper_agent.pipeline.store import PendingBillRepo
from bookkeeper_agent.pipeline.writegate import ApprovalGate
from bookkeeper_agent.qbo_connect import REDIRECT_URI, _base_url
from bookkeeper_agent.security import TokenCipher


@dataclass
class App:
    clients: dict[str, ClientConfig]
    slack: HttpxSlackConnector
    pipeline: BillsPipeline
    gate: ApprovalGate
    approval_channel: str
    slack_app_token: str
    slack_bot_token: str


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} in .env first.")
    return value


def build_app(env_file: str | None = ".env") -> App:
    if env_file:
        load_dotenv(env_file)

    keys = [k.strip() for k in os.environ.get("TOKEN_ENC_KEYS", "").split(",") if k.strip()]
    if not keys:
        raise SystemExit("Set TOKEN_ENC_KEYS in .env first.")

    engine = make_engine(os.environ.get("DB_PATH", "bookkeeper.db"))
    init_db(engine)
    store = TokenStore(engine, TokenCipher(keys))
    repo = PendingBillRepo(engine)
    clients = load_clients(os.environ.get("CLIENTS_PATH", "clients.toml"))

    meter = CostMeter(engine, monthly_cap=float(os.environ.get("MONTHLY_USD_CAP", "25")))
    model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    llm = AnthropicLlmClient(
        anthropic.Anthropic(api_key=_require("ANTHROPIC_API_KEY")), model, meter)

    qbo_env = os.environ.get("QBO_ENV", "sandbox")
    oauth = QboOAuth(QboOAuthConfig(
        _require("QBO_CLIENT_ID"), _require("QBO_CLIENT_SECRET"), REDIRECT_URI, qbo_env))
    qbo = HttpxQboConnector(QboTokenManager(store, oauth).access_token,
                            base_url=_base_url(qbo_env))

    bot_token = _require("SLACK_BOT_TOKEN")
    slack = HttpxSlackConnector(bot_token)
    channel = _require("SLACK_APPROVAL_CHANNEL")

    pipeline = BillsPipeline(llm=llm, qbo=qbo, slack=slack, pending_repo=repo,
                             engine=engine, approval_channel=channel)
    gate = ApprovalGate(qbo=qbo, slack=slack, pending_repo=repo, engine=engine)

    return App(clients=clients, slack=slack, pipeline=pipeline, gate=gate,
               approval_channel=channel, slack_app_token=_require("SLACK_APP_TOKEN"),
               slack_bot_token=bot_token)
