"""Run the agent:  python -m bookkeeper_agent"""
from __future__ import annotations

from bookkeeper_agent.app import build_app
from bookkeeper_agent.runner import run


def main() -> None:
    app = build_app()
    print(f"Bookkeeper agent ready. Approval channel: {app.approval_channel} "
          f"| {len(app.clients)} client(s) configured.")
    run(app)


if __name__ == "__main__":
    main()
